"""Meridian Retail support-draft review tool (fictional classroom demo).

Drafts a customer reply for HUMAN REVIEW ONLY. This tool never sends
messages, approves refunds, or changes records. It only reads policy.md,
cases.json, and demo_outputs.json, and prints to the terminal.
"""

import argparse
import json
import os
import sys
import urllib.request
from datetime import date
from pathlib import Path

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent
CASES_PATH = BASE_DIR / "cases.json"
POLICY_PATH = BASE_DIR / "policy.md"
DEMO_OUTPUTS_PATH = BASE_DIR / "demo_outputs.json"
ENV_PATH = BASE_DIR / ".env"

DEFAULT_MODEL = "qwen:1.8b"
DEFAULT_OLLAMA_HOST = "http://localhost:11434"
OLLAMA_TIMEOUT = 120.0
CASE_IDS = ("C1", "C2", "C3")
POLICY_IDS = ("P1", "P2", "P3", "P4")
CASE_FIELDS = (
    "case_id",
    "order_id",
    "product",
    "customer_question",
    "delivery_date",
    "issue_status",
    "issue_details",
)
RESULT_FIELDS = ("draft_reply", "evidence_refs", "missing_information", "review_status")
REVIEW_STATUSES = ("READY_FOR_HUMAN_REVIEW", "NEEDS_INFORMATION", "BLOCKED")
UNAVAILABLE_STATUS = "UNAVAILABLE"

FALLBACK_MESSAGE = (
    "MANUAL FALLBACK: No draft is available. A human agent must handle this "
    "case manually using policy.md."
)
SAFETY_NOTE = (
    "Nothing has been sent, no refund has been approved, and no record has been changed."
)
STRUCTURE_NOTE = (
    "Note: the result passed structure checks only. Correct structure does not "
    "prove correct content; a human must review it before any use."
)

SYSTEM_PROMPT = """You draft customer-support replies for Meridian Retail for HUMAN REVIEW ONLY.
Use ONLY the supplied case facts and supplied policy. Do not invent facts, dates, or policies.
You cannot approve refunds, send messages, or change records, and the draft must not claim otherwise.
The case facts include a "delivery_date" field. If it has a value, use that date from the case itself:
do not ask the customer for it and do not list it in "missing_information".
List a field in "missing_information" only if its value in the supplied facts is empty or null.
The supplied REPORTED DATE is the date the customer reported the issue. Do not infer the report date
from the customer's wording (for example "yesterday"). Apply the two-day rule in P1 by comparing the
REPORTED DATE with the case "delivery_date". If more than two days have passed, the draft must not say
the case can be referred for return review under P1.

Return ONLY a JSON object, with no other text, containing exactly these keys:
- "draft_reply": string, the proposed reply to the customer
- "evidence_refs": list of policy IDs you relied on, chosen from ["P1", "P2", "P3", "P4"]
- "missing_information": list of case field names whose values are needed but missing (empty list if none)
- "review_status": one of "READY_FOR_HUMAN_REVIEW", "NEEDS_INFORMATION", "BLOCKED"
"""


class InvalidResultError(ValueError):
    """Raised when a model or demo result fails validation."""


def load_case(case_id):
    if case_id not in CASE_IDS:
        raise ValueError(f"Unknown case: {case_id}")
    with CASES_PATH.open(encoding="utf-8") as f:
        cases = json.load(f)
    return cases[case_id]


def load_policy():
    return POLICY_PATH.read_text(encoding="utf-8")


def load_demo_outputs():
    with DEMO_OUTPUTS_PATH.open(encoding="utf-8") as f:
        return json.load(f)

def load_settings():
    """Read app settings from the project .env and APP_* variables only."""
    load_dotenv(ENV_PATH)
    host = os.environ.get("APP_OLLAMA_HOST", "").strip() or DEFAULT_OLLAMA_HOST
    model = os.environ.get("APP_OLLAMA_MODEL", "").strip() or DEFAULT_MODEL
    return host, model


def reported_date():
    """The issue reported date: today's date."""
    return date.today().isoformat()


def build_prompt(case, policy):
    return (
        "SUPPLIED FACTS (JSON):\n"
        f"{json.dumps(case, indent=2)}\n\n"
        f"REPORTED DATE: {reported_date()}\n\n"
        "SUPPLIED POLICY:\n"
        f"{policy}\n\n"
        "Return only the JSON object described in your instructions."
    )


def call_model(case, policy, host, model):
    """Make one local Ollama chat call and return the response text."""
    body = {
        "model": model,
        "stream": False,
        "format": "json",
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": build_prompt(case, policy)},
        ],
    }
    request = urllib.request.Request(
        f"{host.rstrip('/')}/api/chat",
        data=json.dumps(body).encode("utf-8"),
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(request, timeout=OLLAMA_TIMEOUT) as response:
        data = json.load(response)
    return data["message"]["content"]


def live_model_fn(case, policy):
    host, model = load_settings()
    return call_model(case, policy, host, model)


def parse_model_text(text):
    """Parse model text as JSON, tolerating a surrounding ```json fence."""
    stripped = text.strip()
    if stripped.startswith("```"):
        stripped = stripped.strip("`")
        if stripped.startswith("json"):
            stripped = stripped[len("json"):]
    try:
        return json.loads(stripped)
    except json.JSONDecodeError as exc:
        raise InvalidResultError("model output is not valid JSON") from exc


def validate_result(data):
    """Check the result's keys and types. This does not check content."""
    if not isinstance(data, dict):
        raise InvalidResultError("result is not a JSON object")
    if set(data) != set(RESULT_FIELDS):
        raise InvalidResultError("result does not have exactly the required keys")
    if not isinstance(data["draft_reply"], str):
        raise InvalidResultError("draft_reply must be text")
    refs = data["evidence_refs"]
    if not isinstance(refs, list) or not all(r in POLICY_IDS for r in refs):
        raise InvalidResultError("evidence_refs must be a list of policy IDs")
    missing = data["missing_information"]
    if not isinstance(missing, list) or not all(m in CASE_FIELDS for m in missing):
        raise InvalidResultError("missing_information must be a list of case field names")
    if data["review_status"] not in REVIEW_STATUSES:
        raise InvalidResultError("review_status is not an allowed value")
    return {key: data[key] for key in RESULT_FIELDS}


def unavailable(reason):
    return {
        "source": "unavailable",
        "reason": reason,
        "result": {
            "draft_reply": "",
            "evidence_refs": [],
            "missing_information": [],
            "review_status": UNAVAILABLE_STATUS,
        },
    }


def run_case(case_id, mode="live", model_fn=None):
    """Produce an outcome dict for one case. Never raises for model failures.

    mode is "live", "offline", or "timeout".
    """
    case = load_case(case_id)
    policy = load_policy()

    if mode == "timeout":
        return unavailable("simulated timeout (no API call made)")

    if mode == "offline":
        entry = load_demo_outputs().get(case_id)
        try:
            if entry is None or entry.get("case_id") != case_id:
                raise InvalidResultError("no demo output for this case")
            result = validate_result(entry["result"])
        except (InvalidResultError, KeyError, AttributeError):
            return unavailable("offline demo output is invalid")
        return {"source": "offline", "label": entry.get("label", ""), "result": result}

    model_fn = model_fn or live_model_fn
    try:
        result = validate_result(parse_model_text(model_fn(case, policy)))
    except InvalidResultError as exc:
        return unavailable(f"invalid model output: {exc}")
    except Exception as exc:  # provider, network, timeout, or config failure
        return unavailable(f"model provider unavailable ({type(exc).__name__})")
    return {"source": "model", "result": result}


def render(case, policy, outcome):
    result = outcome["result"]
    lines = [
        "=" * 60,
        "SUPPLIED FACTS",
        "=" * 60,
        json.dumps(case, indent=2),
        f"Reported date (today): {reported_date()}",
        "",
        "=" * 60,
        "SUPPLIED POLICY",
        "=" * 60,
        policy.strip(),
        "",
        "=" * 60,
        "DRAFT RESULT FOR HUMAN REVIEW",
        "=" * 60,
    ]
    if outcome["source"] == "offline":
        lines.append("OFFLINE DEMO: no model API was called.")
        lines.append(f"Source: {outcome['label']}")
    elif outcome["source"] == "unavailable":
        lines.append(f"Reason: {outcome['reason']}")
    lines += [
        f"review_status: {result['review_status']}",
        f"evidence_refs: {', '.join(result['evidence_refs']) or '(none)'}",
        f"missing_information: {', '.join(result['missing_information']) or '(none)'}",
        "draft_reply:",
        result["draft_reply"] or "(empty)",
        "",
    ]
    if outcome["source"] == "unavailable":
        lines.append(FALLBACK_MESSAGE)
    else:
        lines.append(STRUCTURE_NOTE)
    lines.append(SAFETY_NOTE)
    return "\n".join(lines)


def main(argv=None):
    parser = argparse.ArgumentParser(
        description="Draft a Meridian Retail support reply for human review."
    )
    parser.add_argument("--case", required=True, choices=CASE_IDS)
    group = parser.add_mutually_exclusive_group()
    group.add_argument(
        "--simulate-timeout", action="store_true",
        help="Make no API call and show the unavailable fallback.",
    )
    group.add_argument(
        "--offline-demo", action="store_true",
        help="Make no API call and show a prerecorded synthetic result.",
    )
    args = parser.parse_args(argv)

    if args.simulate_timeout:
        mode = "timeout"
    elif args.offline_demo:
        mode = "offline"
    else:
        mode = "live"

    outcome = run_case(args.case, mode=mode)
    print(render(load_case(args.case), load_policy(), outcome))
    return 0


if __name__ == "__main__":
    sys.exit(main())
