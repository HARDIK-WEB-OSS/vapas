from __future__ import annotations

import os
import socket
from dataclasses import dataclass

from vapas.config import Settings
from vapas.db.session import Database
from vapas.health import Dependencies
from vapas.llm_gateway.gateway import LlmGateway, OllamaProvider
from vapas.security.crypto import KeyRing


@dataclass(frozen=True)
class WorkerContext:
    settings: Settings
    dependencies: Dependencies
    db: Database
    keys: KeyRing
    gateway: LlmGateway
    worker_id: str

    @classmethod
    def from_settings(cls, settings: Settings, gateway: LlmGateway | None = None) -> WorkerContext:
        dependencies = Dependencies.from_settings(settings)
        if gateway is None:
            provider = OllamaProvider(settings.ollama_url, settings.ollama_model) if settings.ollama_url else None
            gateway = LlmGateway(provider, settings.llm_daily_call_budget)
        return cls(
            settings=settings,
            dependencies=dependencies,
            db=Database(dependencies.engine),
            keys=settings.key_ring(),
            gateway=gateway,
            worker_id=f"{socket.gethostname()}:{os.getpid()}",
        )

    async def close(self) -> None:
        await self.dependencies.close()
