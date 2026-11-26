from pathlib import Path

import pytest

from vapas.config import Settings
from vapas.security.private_path_guard import find_code_root

BASE_ENV = {
    "APP_ENV": "test",
    "DATABASE_URL": "postgresql+asyncpg://user:secret-db-password@127.0.0.1:55433/vapas",
    "REDIS_URL": "redis://127.0.0.1:6379/0",
    "S3_ENDPOINT_URL": "http://127.0.0.1:8333",
    "S3_ACCESS_KEY_ID": "test-key",
    "S3_SECRET_ACCESS_KEY": "secret-s3-password",
    "S3_BUCKET_RAW": "vapas-raw",
    "JWT_SECRET": "test-jwt-secret-0123456789abcdef0123456789",
    "KEK_KEYS": '{"1": "dmFwYXMtdGVzdC1rZXktZW5jcnlwdGlvbi12MS0wMDA="}',
    "KEK_ACTIVE_VERSION": "1",
}


@pytest.fixture
def repo_root() -> Path:
    return find_code_root(Path(__file__).parent)


@pytest.fixture
def base_env(monkeypatch: pytest.MonkeyPatch) -> dict[str, str]:
    for key, value in BASE_ENV.items():
        monkeypatch.setenv(key, value)
    for field in Settings.model_fields:
        if field.upper() not in BASE_ENV:
            monkeypatch.delenv(field.upper(), raising=False)
    return dict(BASE_ENV)
