from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from vapas.security.private_path_guard import ensure_outside_code_root

AppEnv = Literal["local", "test", "staging", "production"]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=(".env", "../.env"), env_file_encoding="utf-8", extra="ignore", frozen=True
    )

    app_env: AppEnv = "local"
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR"] = "INFO"
    database_url: SecretStr
    redis_url: SecretStr
    s3_endpoint_url: str | None = None
    s3_region: str = "auto"
    s3_access_key_id: SecretStr
    s3_secret_access_key: SecretStr
    s3_bucket_raw: str = Field(min_length=3, max_length=63)
    claim_lookback_months: int = Field(default=12, ge=1, le=120)
    private_fixtures_dir: Path | None = None
    worker_heartbeat_seconds: float = Field(default=30.0, gt=0)

    @field_validator("s3_endpoint_url", mode="before")
    @classmethod
    def blank_endpoint_is_none(cls, value: object) -> object:
        return None if value == "" else value

    @field_validator("private_fixtures_dir", mode="before")
    @classmethod
    def blank_private_dir_is_none(cls, value: object) -> object:
        return None if value == "" else value

    @field_validator("private_fixtures_dir")
    @classmethod
    def private_dir_outside_repo(cls, value: Path | None) -> Path | None:
        return None if value is None else ensure_outside_code_root(value)


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
