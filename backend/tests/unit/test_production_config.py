import tomllib
from pathlib import Path
from typing import Any

import pytest


@pytest.fixture
def fly_env(repo_root: Path) -> dict[str, Any]:
    config = tomllib.loads((repo_root / "fly.toml").read_text(encoding="utf-8"))
    env: dict[str, Any] = config["env"]
    return env


def test_production_pins_the_pilot_safety_settings(fly_env: dict[str, Any]) -> None:
    assert fly_env["APP_ENV"] == "production"
    assert fly_env["INVITE_ONLY"] == "true"
    assert fly_env["LLM_FALLBACK_ENABLED"] == "false"
    assert fly_env["LETTER_POLISH_ENABLED"] == "false"
    assert fly_env["CLIENT_IP_HEADER"] == "X-Vapas-Client-IP"
    assert fly_env["REFRESH_COOKIE_PATH"] == "/api/auth"
    assert fly_env["MAIL_BACKEND"] == "smtp"
    assert fly_env["MAIL_OUTBOX_DIR"] == ""
    assert fly_env["OLLAMA_URL"] == ""


def test_secrets_and_switches_are_not_baked_into_the_image_config(fly_env: dict[str, Any]) -> None:
    assert {"KILL_SWITCH", "PROXY_SHARED_SECRET", "SMTP_PASSWORD"}.isdisjoint(fly_env)


def test_two_small_machines(repo_root: Path) -> None:
    config = tomllib.loads((repo_root / "fly.toml").read_text(encoding="utf-8"))
    sizes = {vm["processes"][0]: (vm["size"], vm["memory"]) for vm in config["vm"]}
    assert sizes == {"api": ("shared-cpu-1x", "512mb"), "worker": ("shared-cpu-1x", "1gb")}
