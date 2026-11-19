from pathlib import Path

import pytest
from pydantic import ValidationError

from vapas.config import Settings


def load() -> Settings:
    return Settings(_env_file=None)


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
