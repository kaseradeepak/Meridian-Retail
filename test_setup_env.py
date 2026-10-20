"""Tests for setup_env.py. Uses a temporary folder, never the real .env."""

import stat

import setup_env

SECRET = "sk-test-secret-do-not-print"


def make_input(answers):
    answers = iter(answers)
    return lambda prompt="": next(answers)


def test_writes_key_without_printing_it(tmp_path, capsys):
    env_path = tmp_path / ".env"
    code = setup_env.main(
        env_path=env_path,
        input_fn=make_input([""]),
        getpass_fn=lambda prompt="": SECRET,
    )
    assert code == 0
    content = env_path.read_text(encoding="utf-8")
    assert f"APP_ANTHROPIC_API_KEY={SECRET}" in content
    assert "APP_ANTHROPIC_MODEL=claude-haiku-4-5-20251001" in content
    assert "ANTHROPIC_API_KEY=" not in content.replace("APP_ANTHROPIC_API_KEY=", "")
    out = capsys.readouterr()
    assert SECRET not in out.out
    assert SECRET not in out.err
    assert stat.S_IMODE(env_path.stat().st_mode) == 0o600


def test_custom_model_is_saved(tmp_path):
    env_path = tmp_path / ".env"
    setup_env.main(
        env_path=env_path,
        input_fn=make_input(["claude-haiku-5-5"]),
        getpass_fn=lambda prompt="": SECRET,
    )
    assert "APP_ANTHROPIC_MODEL=claude-haiku-5-5" in env_path.read_text(encoding="utf-8")


def test_key_is_read_with_hidden_input(tmp_path):
    calls = []

    def fake_getpass(prompt=""):
        calls.append(prompt)
        return SECRET

    def fake_input(prompt=""):
        assert "key" not in prompt.lower(), "the key must not be asked with visible input"
        return ""

    setup_env.main(env_path=tmp_path / ".env", input_fn=fake_input, getpass_fn=fake_getpass)
    assert len(calls) == 1


def test_empty_key_writes_nothing(tmp_path):
    env_path = tmp_path / ".env"
    code = setup_env.main(
        env_path=env_path,
        input_fn=make_input([""]),
        getpass_fn=lambda prompt="": "",
    )
    assert code == 1
    assert not env_path.exists()


def test_existing_env_is_kept_unless_confirmed(tmp_path):
    env_path = tmp_path / ".env"
    env_path.write_text("APP_ANTHROPIC_API_KEY=old\n", encoding="utf-8")
    code = setup_env.main(
        env_path=env_path,
        input_fn=make_input(["n"]),
        getpass_fn=lambda prompt="": SECRET,
    )
    assert code == 1
    assert env_path.read_text(encoding="utf-8") == "APP_ANTHROPIC_API_KEY=old\n"
