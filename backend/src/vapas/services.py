from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from vapas.auth.service import AuthService
from vapas.config import Settings
from vapas.db.session import Database
from vapas.health import Dependencies
from vapas.mail.sender import EmailSender, create_email_sender
from vapas.security.ratelimit import RateLimiter
from vapas.storage.object_store import create_presign_client

if TYPE_CHECKING:
    from mypy_boto3_s3 import S3Client


@dataclass(frozen=True)
class Services:
    settings: Settings
    dependencies: Dependencies
    db: Database
    limiter: RateLimiter
    mailer: EmailSender
    auth: AuthService
    presign_client: S3Client

    @classmethod
    def from_settings(cls, settings: Settings) -> Services:
        dependencies = Dependencies.from_settings(settings)
        db = Database(dependencies.engine)
        limiter = RateLimiter(dependencies.redis)
        mailer = create_email_sender(settings)
        auth = AuthService(settings, db, settings.key_ring(), limiter, mailer)
        return cls(settings, dependencies, db, limiter, mailer, auth, create_presign_client(settings))

    async def close(self) -> None:
        await self.dependencies.close()
        self.presign_client.close()
