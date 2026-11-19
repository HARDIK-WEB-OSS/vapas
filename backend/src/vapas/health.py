from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass
from functools import partial
from typing import TYPE_CHECKING

from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncEngine

from vapas.config import Settings
from vapas.db.session import create_engine, ping_database
from vapas.storage.object_store import create_s3_client, ping_bucket

if TYPE_CHECKING:
    from mypy_boto3_s3 import S3Client

Probe = Callable[[], Awaitable[bool]]
PROBE_TIMEOUT_SECONDS = 3.0

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class Dependencies:
    engine: AsyncEngine
    redis: Redis
    s3: S3Client
    bucket: str

    @classmethod
    def from_settings(cls, settings: Settings) -> Dependencies:
        return cls(
            engine=create_engine(settings),
            redis=Redis.from_url(settings.redis_url.get_secret_value(), socket_timeout=2, socket_connect_timeout=2),
            s3=create_s3_client(settings),
            bucket=settings.s3_bucket_raw,
        )

    def probes(self) -> dict[str, Probe]:
        return {
            "postgres": partial(ping_database, self.engine),
            "redis": self._ping_redis,
            "object_store": partial(ping_bucket, self.s3, self.bucket),
        }

    async def _ping_redis(self) -> bool:
        return bool(await self.redis.ping())

    async def close(self) -> None:
        await self.engine.dispose()
        await self.redis.aclose()
        self.s3.close()


async def _run_probe(name: str, probe: Probe) -> bool:
    try:
        return await asyncio.wait_for(probe(), timeout=PROBE_TIMEOUT_SECONDS)
    except Exception as error:
        log.warning("dependency check failed", extra={"dependency": name, "error_type": type(error).__name__})
        return False


async def run_probes(probes: Mapping[str, Probe]) -> dict[str, bool]:
    results = await asyncio.gather(*(_run_probe(name, probe) for name, probe in probes.items()))
    return dict(zip(probes.keys(), results, strict=True))
