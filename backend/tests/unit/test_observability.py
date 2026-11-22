from typing import Any, cast

import pytest
from sentry_sdk.types import Event

from vapas.config import Settings
from vapas.observability import init_error_tracking, scrub


def test_scrub_keeps_only_method_and_path() -> None:
    event: dict[str, Any] = {
        "request": {
            "method": "POST",
            "url": "https://api.example.in/auth/verify-email?token=secret",
            "data": {"password": "hunter2"},
            "cookies": {"vapas_refresh": "abc"},
            "headers": {"Authorization": "Bearer xyz"},
            "query_string": "token=secret",
        },
        "user": {"email": "asha@example.in", "ip_address": "1.2.3.4"},
        "server_name": "machine-1",
        "exception": {"values": [{"stacktrace": {"frames": [{"function": "f", "vars": {"narration": "UPI/RAMESH"}}]}}]},
        "breadcrumbs": {"values": [{"message": "query", "data": {"sql_params": ["asha"]}}]},
    }
    cleaned = cast(dict[str, Any], scrub(cast(Event, event)))
    assert cleaned["request"] == {"method": "POST", "url": "https://api.example.in/auth/verify-email"}
    assert "user" not in cleaned
    assert "server_name" not in cleaned
    assert "vars" not in cleaned["exception"]["values"][0]["stacktrace"]["frames"][0]
    assert "data" not in cleaned["breadcrumbs"]["values"][0]
    for secret in ("hunter2", "Bearer", "asha", "RAMESH", "token=secret"):
        assert secret not in repr(cleaned)


def test_error_tracking_is_off_without_dsn(base_env: dict[str, str], monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SENTRY_DSN", "")
    assert init_error_tracking(Settings(_env_file=None), "api") is False
