from __future__ import annotations

from dataclasses import dataclass

from vapas.auth.service import AuthService
from vapas.config import Settings
from vapas.db.session import Database
from vapas.health import Dependencies
from vapas.mail.sender import EmailSender, create_email_sender
from vapas.security.ratelimit import RateLimiter


@dataclass(frozen=True)
class Services:
    settings: Settings
    dependencies: Dependencies
    db: Database
    limiter: RateLimiter
    mailer: EmailSender
    auth: AuthService

    @classmethod
    def from_settings(cls, settings: Settings) -> Services:
        dependencies = Dependencies.from_settings(settings)
        db = Database(dependencies.engine)
        limiter = RateLimiter(dependencies.redis)
        mailer = create_email_sender(settings)
        auth = AuthService(settings, db, settings.key_ring(), limiter, mailer)
        return cls(settings, dependencies, db, limiter, mailer, auth)

    async def close(self) -> None:
        await self.dependencies.close()
