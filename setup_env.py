"""Write a project-only .env file for app.py.

The API key is read with hidden input and is never printed.
"""

import getpass
import os
import sys
from pathlib import Path

ENV_PATH = Path(__file__).resolve().parent / ".env"
DEFAULT_MODEL = "claude-haiku-4-5-20251001"


def main(env_path=ENV_PATH, input_fn=input, getpass_fn=getpass.getpass):
    env_path = Path(env_path)
    if env_path.exists():
        answer = input_fn(f"{env_path.name} already exists. Overwrite? [y/N]: ")
        if answer.strip().lower() != "y":
            print("No changes made.")
            return 1

    api_key = getpass_fn("App Anthropic API key (input hidden): ").strip()
    if not api_key:
        print("No API key entered. No changes made.")
        return 1

    model = input_fn(f"Model [{DEFAULT_MODEL}]: ").strip() or DEFAULT_MODEL

    content = f"APP_ANTHROPIC_API_KEY={api_key}\nAPP_ANTHROPIC_MODEL={model}\n"
    fd = os.open(env_path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        f.write(content)
    os.chmod(env_path, 0o600)

    print(f"Wrote {env_path.name} (API key saved, not shown). Model: {model}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
