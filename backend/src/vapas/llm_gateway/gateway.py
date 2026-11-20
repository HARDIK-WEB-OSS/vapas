import logging
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from typing import Protocol
from uuid import UUID

import httpx
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncConnection

from vapas.db.models import llm_usage
from vapas.llm_gateway.circuit_breaker import CircuitBreaker
from vapas.security.redact import find_sensitive, redact

log = logging.getLogger(__name__)
Charge = Callable[[], Awaitable[None]]
OLLAMA_TIMEOUT_SECONDS = 120.0


class LlmUnavailableError(Exception):
    code = "llm_unavailable"


class BudgetExceededError(Exception):
    code = "llm_budget_exceeded"


class SensitiveDataBlockedError(Exception):
    code = "llm_blocked_sensitive_data"


class Provider(Protocol):
    name: str

    async def complete_json(self, prompt: str) -> str: ...


class OllamaProvider:
    name = "ollama"

    def __init__(self, base_url: str, model: str, timeout_seconds: float = OLLAMA_TIMEOUT_SECONDS) -> None:
        self._url = base_url.rstrip("/") + "/api/generate"
        self._model = model
        self._timeout = timeout_seconds

    async def complete_json(self, prompt: str) -> str:
        body = {
            "model": self._model,
            "prompt": prompt,
            "format": "json",
            "stream": False,
            "options": {"temperature": 0},
        }
        async with httpx.AsyncClient(timeout=self._timeout) as client:
            response = await client.post(self._url, json=body)
            response.raise_for_status()
            return str(response.json()["response"])


async def consume_budget(conn: AsyncConnection, user_id: UUID, daily_limit: int) -> None:
    today = datetime.now(UTC).date()
    statement = (
        insert(llm_usage)
        .values(user_id=user_id, day=today, calls=1)
        .on_conflict_do_update(index_elements=["user_id", "day"], set_={"calls": llm_usage.c.calls + 1})
        .returning(llm_usage.c.calls)
    )
    calls = int((await conn.execute(statement)).scalar_one())
    if calls > daily_limit:
        raise BudgetExceededError(f"daily LLM budget of {daily_limit} calls used")


class LlmGateway:
    def __init__(self, provider: Provider | None, daily_limit: int, breaker: CircuitBreaker | None = None) -> None:
        self._provider = provider
        self._daily_limit = daily_limit
        self._breaker = breaker or CircuitBreaker()

    @property
    def available(self) -> bool:
        return self._provider is not None and self._breaker.allow()

    @property
    def daily_limit(self) -> int:
        return self._daily_limit

    async def complete_json(self, prompt: str, charge: Charge) -> str:
        cleaned = redact(prompt)
        if find_sensitive(cleaned):
            raise SensitiveDataBlockedError("prompt still contains identifiers after redaction")
        if self._provider is None or not self._breaker.allow():
            raise LlmUnavailableError("no model available")
        await charge()
        try:
            answer = await self._provider.complete_json(cleaned)
        except (httpx.HTTPError, KeyError, ValueError) as error:
            self._breaker.record_failure()
            log.warning(
                "model call failed", extra={"provider": self._provider.name, "error_type": type(error).__name__}
            )
            raise LlmUnavailableError("model call failed") from error
        self._breaker.record_success()
        return answer
