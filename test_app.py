"""Tests for app.py. No test calls an external API."""

import json

import pytest

import app

VALID_C1 = {
    "draft_reply": "Thanks for reporting the broken zip. We have referred your case for return review; this is not a refund approval.",
    "evidence_refs": ["P1", "P3", "P4"],
    "missing_information": [],
    "review_status": "READY_FOR_HUMAN_REVIEW",
}


def fake_model(payload):
    def model_fn(case, policy):
        return payload if isinstance(payload, str) else json.dumps(payload)
    return model_fn


def must_not_call(*args, **kwargs):
    raise AssertionError("the model API must not be called")


@pytest.fixture
def no_live_calls(monkeypatch):
    monkeypatch.setattr(app, "call_model", must_not_call)
    monkeypatch.setattr(app.urllib.request, "urlopen", must_not_call)


# --- input files -----------------------------------------------------------

@pytest.mark.parametrize("case_id", app.CASE_IDS)
def test_cases_load_with_expected_fields(case_id):
    case = app.load_case(case_id)
    assert tuple(case) == app.CASE_FIELDS
    assert case["case_id"] == case_id


def test_cases_json_has_exactly_three_cases():
    data = json.loads(app.CASES_PATH.read_text(encoding="utf-8"))
    assert sorted(data) == ["C1", "C2", "C3"]
    assert data["C2"]["delivery_date"] is None


def test_policy_contains_all_policy_ids():
    policy = app.load_policy()
    for policy_id in app.POLICY_IDS:
        assert f"{policy_id}." in policy


def test_unknown_case_is_rejected():
    with pytest.raises(ValueError):
        app.load_case("C9")


# --- successful result -----------------------------------------------------

def test_successful_c1_result():
    outcome = app.run_case("C1", model_fn=fake_model(VALID_C1))
    assert outcome["source"] == "model"
    assert outcome["result"] == VALID_C1


def test_fenced_json_is_accepted():
    text = "```json\n" + json.dumps(VALID_C1) + "\n```"
    outcome = app.run_case("C1", model_fn=fake_model(text))
    assert outcome["result"] == VALID_C1


def test_model_receives_supplied_case_and_policy():
    seen = {}

    def model_fn(case, policy):
        seen["case"], seen["policy"] = case, policy
        return json.dumps(VALID_C1)

    app.run_case("C1", model_fn=model_fn)
    assert seen["case"]["order_id"] == "MR-1042"
    assert "P4." in seen["policy"]


def test_prompt_includes_todays_date_as_reported_date(monkeypatch):
    monkeypatch.setattr(app, "reported_date", lambda: "2026-09-13")
    prompt = app.build_prompt(app.load_case("C1"), app.load_policy())
    assert "REPORTED DATE: 2026-09-13" in prompt


def test_rendered_output_has_three_sections_and_safety_note():
    outcome = app.run_case("C1", model_fn=fake_model(VALID_C1))
    text = app.render(app.load_case("C1"), app.load_policy(), outcome)
    for heading in ("SUPPLIED FACTS", "SUPPLIED POLICY", "DRAFT RESULT FOR HUMAN REVIEW"):
        assert heading in text
    assert app.STRUCTURE_NOTE in text
    assert app.SAFETY_NOTE in text


# --- invalid model output --------------------------------------------------

def with_changes(**changes):
    data = dict(VALID_C1)
    data.update(changes)
    return data


def without(key):
    data = dict(VALID_C1)
    del data[key]
    return data


@pytest.mark.parametrize(
    "payload",
    [
        "not json at all",
        "[]",
        without("review_status"),
        with_changes(extra_field="x"),
        with_changes(draft_reply=123),
        with_changes(evidence_refs="P1"),
        with_changes(evidence_refs=["P9"]),
        with_changes(missing_information="delivery_date"),
        with_changes(missing_information=["shoe_size"]),
        with_changes(review_status="APPROVED"),
        with_changes(review_status="UNAVAILABLE"),
    ],
)
def test_invalid_model_output_is_unavailable(payload):
    outcome = app.run_case("C1", model_fn=fake_model(payload))
    assert outcome["source"] == "unavailable"
    assert outcome["result"]["review_status"] == "UNAVAILABLE"
    assert outcome["result"]["draft_reply"] == ""


# --- timeout and provider failures -----------------------------------------

def test_simulate_timeout_makes_no_call_and_is_unavailable():
    outcome = app.run_case("C1", mode="timeout", model_fn=must_not_call)
    assert outcome["source"] == "unavailable"
    assert outcome["result"]["review_status"] == "UNAVAILABLE"
    assert outcome["result"]["draft_reply"] == ""


def test_simulate_timeout_cli_shows_fallback(no_live_calls, capsys):
    assert app.main(["--case", "C1", "--simulate-timeout"]) == 0
    out = capsys.readouterr().out
    assert "review_status: UNAVAILABLE" in out
    assert app.FALLBACK_MESSAGE in out
    assert "DRAFT RESULT FOR HUMAN REVIEW" in out


def test_provider_timeout_is_unavailable_without_traceback(capsys):
    def raising_model(case, policy):
        raise TimeoutError("request timed out")

    outcome = app.run_case("C1", model_fn=raising_model)
    assert outcome["result"]["review_status"] == "UNAVAILABLE"
    assert outcome["result"]["draft_reply"] == ""
    text = app.render(app.load_case("C1"), app.load_policy(), outcome)
    assert "Traceback" not in text
    assert app.FALLBACK_MESSAGE in text


def test_ollama_unreachable_is_unavailable(monkeypatch):
    def refused(*args, **kwargs):
        raise ConnectionRefusedError("connection refused")

    monkeypatch.setattr(app, "load_settings", lambda: (app.DEFAULT_OLLAMA_HOST, app.DEFAULT_MODEL))
    monkeypatch.setattr(app.urllib.request, "urlopen", refused)
    outcome = app.run_case("C1")
    assert outcome["result"]["review_status"] == "UNAVAILABLE"


def test_ollama_request_uses_host_model_json_format_and_timeout(monkeypatch):
    captured = {}

    class FakeResponse:
        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

        def read(self):
            return json.dumps({"message": {"content": json.dumps(VALID_C1)}}).encode("utf-8")

    def fake_urlopen(request, timeout):
        captured["url"] = request.full_url
        captured["body"] = json.loads(request.data)
        captured["timeout"] = timeout
        return FakeResponse()

    monkeypatch.setattr(app.urllib.request, "urlopen", fake_urlopen)
    monkeypatch.setattr(app, "load_settings", lambda: ("http://ollama.test:11434/", "test-model"))

    outcome = app.run_case("C1")
    assert outcome["result"] == VALID_C1
    assert captured["url"] == "http://ollama.test:11434/api/chat"
    assert captured["body"]["model"] == "test-model"
    assert captured["body"]["format"] == "json"
    assert captured["body"]["stream"] is False
    assert captured["body"]["messages"][0] == {"role": "system", "content": app.SYSTEM_PROMPT}
    assert captured["timeout"] == app.OLLAMA_TIMEOUT


def test_load_settings_reads_app_variables_only(monkeypatch):
    monkeypatch.setattr(app, "load_dotenv", lambda *a, **k: None)
    monkeypatch.setenv("OLLAMA_HOST", "http://global:1234")
    monkeypatch.delenv("APP_OLLAMA_HOST", raising=False)
    monkeypatch.delenv("APP_OLLAMA_MODEL", raising=False)
    assert app.load_settings() == ("http://localhost:11434", "qwen:1.8b")

    monkeypatch.setenv("APP_OLLAMA_HOST", "http://other:11434")
    monkeypatch.setenv("APP_OLLAMA_MODEL", "other-model")
    assert app.load_settings() == ("http://other:11434", "other-model")


# --- offline demo outputs --------------------------------------------------

@pytest.mark.parametrize("case_id", app.CASE_IDS)
def test_offline_outputs_are_valid_and_labelled(case_id):
    entry = app.load_demo_outputs()[case_id]
    assert entry["case_id"] == case_id
    assert "SYNTHETIC" in entry["label"]
    assert app.validate_result(entry["result"]) == entry["result"]


def test_offline_c2_needs_delivery_date():
    result = app.load_demo_outputs()["C2"]["result"]
    assert result["review_status"] == "NEEDS_INFORMATION"
    assert result["missing_information"] == ["delivery_date"]


@pytest.mark.parametrize("case_id", app.CASE_IDS)
def test_offline_demo_cli_makes_no_call(case_id, no_live_calls, capsys):
    assert app.main(["--case", case_id, "--offline-demo"]) == 0
    out = capsys.readouterr().out
    assert "OFFLINE DEMO: no model API was called." in out
    assert "SYNTHETIC PRERECORDED DEMO OUTPUT" in out
    assert "UNAVAILABLE" not in out


def test_cli_rejects_unknown_case():
    with pytest.raises(SystemExit):
        app.main(["--case", "C4", "--offline-demo"])


def test_cli_rejects_both_modes():
    with pytest.raises(SystemExit):
        app.main(["--case", "C1", "--offline-demo", "--simulate-timeout"])
