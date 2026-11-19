from datetime import timedelta
from functools import lru_cache
from pathlib import Path
from typing import Literal, Self

from pydantic import Field, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from vapas.security.crypto import CryptoError, KeyRing, decode_key
from vapas.security.private_path_guard import ensure_outside_code_root

AppEnv = Literal["local", "test", "staging", "production"]
LOCAL_ENVS = frozenset({"local", "test"})
LOCAL_ONLY_MARKERS = ("local-only", "change-me")


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=(".env", "../.env"), env_file_encoding="utf-8", extra="ignore", frozen=True
    )

    app_env: AppEnv = "local"
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR"] = "INFO"
    public_app_url: str = "http://127.0.0.1:3000"
    database_url: SecretStr
    migration_database_url: SecretStr | None = None
    redis_url: SecretStr
    s3_endpoint_url: str | None = None
    s3_region: str = "auto"
    s3_access_key_id: SecretStr
    s3_secret_access_key: SecretStr
    s3_bucket_raw: str = Field(min_length=3, max_length=63)
    jwt_secret: SecretStr = Field(min_length=32)
    kek_keys: dict[int, SecretStr] = Field(min_length=1)
    kek_active_version: int = 1
    access_token_minutes: int = Field(default=15, ge=1, le=60)
    refresh_token_days: int = Field(default=30, ge=1, le=90)
    claim_lookback_months: int = Field(default=12, ge=1, le=120)
    private_fixtures_dir: Path | None = None
    worker_heartbeat_seconds: float = Field(default=30.0, gt=0)

    @field_validator("s3_endpoint_url", "migration_database_url", mode="before")
    @classmethod
    def blank_is_none(cls, value: object) -> object:
        return None if value == "" else value

    @field_validator("private_fixtures_dir", mode="before")
    @classmethod
    def blank_private_dir_is_none(cls, value: object) -> object:
        return None if value == "" else value

    @field_validator("private_fixtures_dir")
    @classmethod
    def private_dir_outside_repo(cls, value: Path | None) -> Path | None:
        return None if value is None else ensure_outside_code_root(value)

    @model_validator(mode="after")
    def keys_are_usable(self) -> Self:
        try:
            self.key_ring()
        except (CryptoError, ValueError) as error:
            raise ValueError(f"KEK_KEYS / KEK_ACTIVE_VERSION are not usable: {error}") from error
        return self

    @model_validator(mode="after")
    def no_local_secrets_outside_local(self) -> Self:
        if self.app_env in LOCAL_ENVS:
            return self
        secrets = [self.database_url, self.redis_url, self.s3_secret_access_key, self.jwt_secret]
        values = [s.get_secret_value() for s in secrets]
        values += [decode_key(k.get_secret_value()).decode(errors="ignore") for k in self.kek_keys.values()]
        if any(marker in value.lower() for value in values for marker in LOCAL_ONLY_MARKERS):
            raise ValueError(f"local-only example secrets are not allowed when APP_ENV={self.app_env}")
        return self

    def key_ring(self) -> KeyRing:
        keys = {version: decode_key(key.get_secret_value()) for version, key in self.kek_keys.items()}
        return KeyRing(keys, self.kek_active_version)

    @property
    def access_token_lifetime(self) -> timedelta:
        return timedelta(minutes=self.access_token_minutes)

    @property
    def refresh_token_lifetime(self) -> timedelta:
        return timedelta(days=self.refresh_token_days)

    @property
    def secure_cookies(self) -> bool:
        return self.app_env not in LOCAL_ENVS


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
