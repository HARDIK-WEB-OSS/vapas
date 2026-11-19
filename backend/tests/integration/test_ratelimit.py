import asyncio

import pytest
from redis.asyncio import Redis

from vapas.config import Settings
from vapas.security.ratelimit import Limit, RateLimiter, RateLimiterUnavailableError

pytestmark = pytest.mark.integration


async def test_bucket_allows_capacity_then_blocks(live_settings: Settings) -> None:
    redis = Redis.from_url(live_settings.redis_url.get_secret_value())
    limiter = RateLimiter(redis, prefix="rltest")
    limit = Limit("burst", capacity=3, per_seconds=60)
    try:
        decisions = [await limiter.hit(limit, "subject") for _ in range(4)]
        assert [d.allowed for d in decisions] == [True, True, True, False]
        assert 0 < decisions[-1].retry_after_seconds <= 20
        assert (await limiter.hit(limit, "other-subject")).allowed
    finally:
        await redis.aclose()


async def test_peek_does_not_consume(live_settings: Settings) -> None:
    redis = Redis.from_url(live_settings.redis_url.get_secret_value())
    limiter = RateLimiter(redis, prefix="rltest")
    limit = Limit("peek", capacity=1, per_seconds=60)
    try:
        assert (await limiter.peek(limit, "s")).allowed
        assert (await limiter.peek(limit, "s")).allowed
        assert (await limiter.hit(limit, "s")).allowed
        assert not (await limiter.peek(limit, "s")).allowed
    finally:
        await redis.aclose()


async def test_tokens_refill_over_time(live_settings: Settings) -> None:
    redis = Redis.from_url(live_settings.redis_url.get_secret_value())
    limiter = RateLimiter(redis, prefix="rltest")
    limit = Limit("refill", capacity=2, per_seconds=0.4)
    try:
        assert (await limiter.hit(limit, "s")).allowed
        assert (await limiter.hit(limit, "s")).allowed
        assert not (await limiter.hit(limit, "s")).allowed
        await asyncio.sleep(0.3)
        assert (await limiter.hit(limit, "s")).allowed
    finally:
        await redis.aclose()


async def test_subjects_are_hashed_in_redis(live_settings: Settings) -> None:
    redis = Redis.from_url(live_settings.redis_url.get_secret_value())
    limiter = RateLimiter(redis, prefix="rltest")
    try:
        await limiter.hit(Limit("privacy", 5, 60), "asha@example.in")
        keys = [k.decode() if isinstance(k, bytes) else k for k in await redis.keys("rltest:privacy:*")]
        assert len(keys) == 1
        assert "asha" not in keys[0]
    finally:
        await redis.aclose()


async def test_redis_down_fails_closed() -> None:
    redis = Redis.from_url("redis://127.0.0.1:1/0", socket_connect_timeout=0.2)
    limiter = RateLimiter(redis)
    try:
        with pytest.raises(RateLimiterUnavailableError):
            await limiter.hit(Limit("down", 5, 60), "s")
    finally:
        await redis.aclose()
