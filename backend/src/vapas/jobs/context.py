from __future__ import annotations

import os
import socket
from dataclasses import dataclass

from vapas.config import Settings
from vapas.db.session import Database
from vapas.health import Dependencies
from vapas.llm_gateway.gateway import LlmGateway, gateway_for
from vapas.mail.sender import EmailSender, create_email_sender
from vapas.security.crypto import KeyRing


@dataclass(frozen=True)
class WorkerContext:
    settings: Settings
    dependencies: Dependencies
    db: Database
    keys: KeyRing
    gateway: LlmGateway
    worker_id: str
    mailer: EmailSender

    @classmethod
    def from_settings(cls, settings: Settings, gateway: LlmGateway | None = None) -> WorkerContext:
        dependencies = Dependencies.from_settings(settings)
        if gateway is None:
            gateway = gateway_for(settings, settings.llm_fallback_enabled)
        return cls(
            settings=settings,
            dependencies=dependencies,
            db=Database(dependencies.engine),
            keys=settings.key_ring(),
            gateway=gateway,
            worker_id=f"{socket.gethostname()}:{os.getpid()}",
            mailer=create_email_sender(settings),
        )

    async def close(self) -> None:
        await self.dependencies.close()
