from pathlib import Path

import pytest
from pydantic import ValidationError

from vapas.config import Settings


def load() -> Settings:
    return Settings(_env_file=None)


def use_production(monkeypatch: pytest.MonkeyPatch, env: str = "production") -> None:
    monkeypatch.setenv("APP_ENV", env)
    monkeypatch.setenv("MAIL_BACKEND", "resend")
    monkeypatch.setenv("RESEND_API_KEY", "re_live_key")
    monkeypatch.setenv("EMAIL_FROM", "VAPAS <no-reply@example.in>")


def test_defaults(base_env: dict[str, str]) -> None:
    settings = load()
    assert settings.claim_lookback_months == 12
    assert settings.private_fixtures_dir is None
    assert settings.s3_bucket_raw == "vapas-raw"


def test_private_dir_inside_repo_fails_startup(
    base_env: dict[str, str], repo_root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("PRIVATE_FIXTURES_DIR", str(repo_root / "private"))
    with pytest.raises(ValidationError, match="must be outside the repository"):
        load()


def test_private_dir_outside_repo_is_accepted(
    base_env: dict[str, str], tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("PRIVATE_FIXTURES_DIR", str(tmp_path))
    assert load().private_fixtures_dir == tmp_path.resolve()


def test_blank_private_dir_means_not_set(base_env: dict[str, str], monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PRIVATE_FIXTURES_DIR", "")
    assert load().private_fixtures_dir is None


@pytest.mark.parametrize("months", ["0", "-1", "121"])
def test_claim_lookback_bounds(base_env: dict[str, str], monkeypatch: pytest.MonkeyPatch, months: str) -> None:
    monkeypatch.setenv("CLAIM_LOOKBACK_MONTHS", months)
    with pytest.raises(ValidationError):
        load()


def test_missing_database_url_fails(base_env: dict[str, str], monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("DATABASE_URL")
    with pytest.raises(ValidationError):
        load()


def test_secrets_never_appear_in_repr(base_env: dict[str, str]) -> None:
    rendered = repr(load()) + str(load().model_dump())
    assert "secret-db-password" not in rendered
    assert "secret-s3-password" not in rendered


@pytest.mark.parametrize("env", ["staging", "production"])
def test_example_secrets_are_refused_outside_local(
    base_env: dict[str, str], monkeypatch: pytest.MonkeyPatch, env: str
) -> None:
    use_production(monkeypatch, env)
    monkeypatch.setenv("JWT_SECRET", "local-only-jwt-secret-change-me-0123456789abcdef")
    with pytest.raises(ValidationError, match="local-only example secrets"):
        load()


def test_example_kek_is_refused_in_production(base_env: dict[str, str], monkeypatch: pytest.MonkeyPatch) -> None:
    use_production(monkeypatch)
    monkeypatch.setenv("KEK_KEYS", '{"1": "dmFwYXMtbG9jYWwtb25seS1rZWstdjEtMDAwMDAwMDA="}')
    with pytest.raises(ValidationError, match="local-only example secrets"):
        load()


def test_real_looking_secrets_pass_in_production(base_env: dict[str, str], monkeypatch: pytest.MonkeyPatch) -> None:
    use_production(monkeypatch)
    assert load().secure_cookies is True


def test_kek_active_version_must_be_configured(base_env: dict[str, str], monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("KEK_ACTIVE_VERSION", "2")
    with pytest.raises(ValidationError):
        load()


def test_short_jwt_secret_is_refused(base_env: dict[str, str], monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("JWT_SECRET", "too-short")
    with pytest.raises(ValidationError):
        load()


@pytest.mark.parametrize("env", ["staging", "production"])
def test_capture_sender_is_refused_outside_local_and_test(
    base_env: dict[str, str], monkeypatch: pytest.MonkeyPatch, env: str
) -> None:
    monkeypatch.setenv("APP_ENV", env)
    monkeypatch.setenv("MAIL_BACKEND", "capture")
    with pytest.raises(ValidationError, match="MAIL_BACKEND=capture"):
        load()


def test_capture_factory_refuses_production_even_if_validation_is_skipped(base_env: dict[str, str]) -> None:
    from vapas.mail.sender import EmailProviderNotConfiguredError, create_email_sender

    unchecked = Settings.model_construct(**{**load().__dict__, "app_env": "production", "mail_backend": "capture"})
    with pytest.raises(EmailProviderNotConfiguredError):
        create_email_sender(unchecked)


@pytest.mark.parametrize(
    ("backend", "missing"),
    [("smtp", "SMTP_PASSWORD"), ("resend", "RESEND_API_KEY")],
)
def test_real_senders_need_their_credentials(
    base_env: dict[str, str], monkeypatch: pytest.MonkeyPatch, backend: str, missing: str
) -> None:
    monkeypatch.setenv("MAIL_BACKEND", backend)
    monkeypatch.setenv("SMTP_USERNAME", "me@gmail.com")
    monkeypatch.setenv("EMAIL_FROM", "VAPAS <me@gmail.com>")
    with pytest.raises(ValidationError, match=missing):
        load()


def test_api_docs_are_hidden_outside_local(base_env: dict[str, str], monkeypatch: pytest.MonkeyPatch) -> None:
    from vapas.main import create_app

    use_production(monkeypatch)
    app = create_app(load())
    assert (app.docs_url, app.redoc_url, app.openapi_url) == (None, None, None)
    monkeypatch.setenv("APP_ENV", "local")
    assert create_app(load()).docs_url == "/docs"


def test_llm_features_and_kill_switch_are_off_by_default(base_env: dict[str, str]) -> None:
    settings = load()
    assert (settings.llm_fallback_enabled, settings.letter_polish_enabled, settings.kill_switch) == (
        False,
        False,
        False,
    )


@pytest.mark.parametrize("env", ["staging", "production"])
def test_llm_fallback_is_refused_outside_local(
    base_env: dict[str, str], monkeypatch: pytest.MonkeyPatch, env: str
) -> None:
    use_production(monkeypatch, env)
    monkeypatch.setenv("LLM_FALLBACK_ENABLED", "true")
    with pytest.raises(ValidationError, match="LLM_FALLBACK_ENABLED"):
        load()


def test_kill_switch_can_be_turned_on_in_production(base_env: dict[str, str], monkeypatch: pytest.MonkeyPatch) -> None:
    use_production(monkeypatch)
    monkeypatch.setenv("KILL_SWITCH", "true")
    assert load().kill_switch is True


def test_custom_client_ip_header_outside_local_needs_the_proxy_secret(
    base_env: dict[str, str], monkeypatch: pytest.MonkeyPatch
) -> None:
    use_production(monkeypatch)
    monkeypatch.setenv("CLIENT_IP_HEADER", "X-Vapas-Client-IP")
    with pytest.raises(ValidationError, match="PROXY_SHARED_SECRET"):
        load()
    monkeypatch.setenv("PROXY_SHARED_SECRET", "p" * 40)
    assert load().client_ip_header == "X-Vapas-Client-IP"


def test_fly_client_ip_needs_no_proxy_secret(base_env: dict[str, str], monkeypatch: pytest.MonkeyPatch) -> None:
    use_production(monkeypatch)
    monkeypatch.setenv("CLIENT_IP_HEADER", "Fly-Client-IP")
    assert load().proxy_shared_secret is None


def test_short_proxy_secret_is_refused(base_env: dict[str, str], monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PROXY_SHARED_SECRET", "short")
    with pytest.raises(ValidationError):
        load()


@pytest.mark.parametrize(("path", "valid"), [("/auth", True), ("/api/auth", True), ("auth", False), ("/a b", False)])
def test_refresh_cookie_path(base_env: dict[str, str], monkeypatch: pytest.MonkeyPatch, path: str, valid: bool) -> None:
    monkeypatch.setenv("REFRESH_COOKIE_PATH", path)
    if valid:
        assert load().refresh_cookie_path == path
    else:
        with pytest.raises(ValidationError):
            load()
