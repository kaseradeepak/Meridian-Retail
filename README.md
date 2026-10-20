# Meridian Retail Support-Draft Review Tool

A minimal command-line tool for a **fictional** classroom demo. For one support case it prints the supplied facts, the supplied policy, and a model-drafted reply **for human review only**.

The tool never sends a message, approves a refund, or changes a record. It only reads `cases.json`, `policy.md`, and `demo_outputs.json`, and prints to the terminal.

## Files

| File | Purpose |
| --- | --- |
| `app.py` | The tool |
| `policy.md` | Drafting policy P1–P4 (input) |
| `cases.json` | Cases C1, C2, C3 (input) |
| `demo_outputs.json` | Hand-written synthetic results for `--offline-demo` |
| `setup_env.py` | Writes a project-only `.env` |
| `.env.example` | Placeholder settings |
| `test_app.py`, `test_setup_env.py` | Tests (no external API calls) |

## Setup

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python setup_env.py
```

`setup_env.py` asks for the app API key with hidden input, asks for the model (default `claude-haiku-4-5-20251001`), and writes `.env` in this folder with owner-only permissions. It never prints the key. `.env` is excluded by `.gitignore`.

The app reads only `APP_ANTHROPIC_API_KEY` and `APP_ANTHROPIC_MODEL`. It does not read or set the global `ANTHROPIC_API_KEY`.

## Usage

```bash
python app.py --case C1                     # live model call
python app.py --case C2 --offline-demo      # no API call; prerecorded synthetic result
python app.py --case C3 --simulate-timeout  # no API call; shows the unavailable fallback
```

Output has three sections: **SUPPLIED FACTS**, **SUPPLIED POLICY**, and **DRAFT RESULT FOR HUMAN REVIEW**.

The model must return only JSON with exactly:

- `draft_reply` – text
- `evidence_refs` – list of policy IDs (P1–P4)
- `missing_information` – list of case field names
- `review_status` – `READY_FOR_HUMAN_REVIEW`, `NEEDS_INFORMATION`, or `BLOCKED`

The app checks these keys and types before showing anything. **Passing these checks does not mean the content is correct**; a human must review every draft.

## Failure behaviour

If the provider fails, times out (20 seconds, no retries), the key is missing, or the response is not valid, the app shows a safe unavailable state: an empty draft, `review_status: UNAVAILABLE`, and a manual fallback message. It never shows a traceback or an older draft. `--simulate-timeout` shows the same state without making a call.

## Tests

```bash
python -m pytest
```

The tests use fake model functions and a temporary folder. They make no external API calls and do not touch your real `.env`.

## Known limitation

`cases.json` does not record when damage was reported. For C1, the two-day rule (P1) can only be applied from the customer's own words ("arrived yesterday"), not by comparing two recorded dates.
