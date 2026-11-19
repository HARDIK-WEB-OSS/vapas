import hashlib
from dataclasses import dataclass
from typing import Any

from redis.asyncio import Redis
from redis.exceptions import RedisError

TOKEN_BUCKET_LUA = """
local key = KEYS[1]
local capacity = tonumber(ARGV[1])
local rate = tonumber(ARGV[2])
local cost = tonumber(ARGV[3])
local clock = redis.call('TIME')
local now = tonumber(clock[1]) + tonumber(clock[2]) / 1000000
local state = redis.call('HMGET', key, 'tokens', 'ts')
local tokens = tonumber(state[1]) or capacity
local ts = tonumber(state[2]) or now
tokens = math.min(capacity, tokens + math.max(0, now - ts) * rate)
local needed = math.max(cost, 1)
local allowed = 0
if tokens >= needed then
  allowed = 1
  tokens = tokens - cost
end
redis.call('HSET', key, 'tokens', tostring(tokens), 'ts', tostring(now))
redis.call('PEXPIRE', key, math.ceil(capacity / rate * 1000) + 1000)
local retry = 0
if allowed == 0 then retry = (needed - tokens) / rate end
return {allowed, tostring(retry)}
"""


@dataclass(frozen=True)
class Limit:
    name: str
    capacity: int
    per_seconds: float

    @property
    def refill_per_second(self) -> float:
        return self.capacity / self.per_seconds


LOGIN_PER_IP = Limit("login_ip", 20, 600)
LOGIN_FAILURES_PER_ACCOUNT = Limit("login_fail", 5, 900)
SIGNUP_PER_IP = Limit("signup_ip", 20, 600)
EMAIL_PER_ACCOUNT = Limit("email_account", 3, 3600)
EMAIL_PER_IP = Limit("email_ip", 20, 600)
REFRESH_PER_IP = Limit("refresh_ip", 60, 60)


@dataclass(frozen=True)
class Decision:
    allowed: bool
    retry_after_seconds: float


class RateLimiterUnavailableError(Exception):
    pass


class RateLimiter:
    def __init__(self, redis: Redis, prefix: str = "rl") -> None:
        self._script = redis.register_script(TOKEN_BUCKET_LUA)
        self._prefix = prefix

    def _key(self, limit: Limit, subject: str) -> str:
        digest = hashlib.sha256(subject.encode()).hexdigest()[:32]
        return f"{self._prefix}:{limit.name}:{digest}"

    async def _run(self, limit: Limit, subject: str, cost: int) -> Decision:
        try:
            raw: Any = await self._script(
                keys=[self._key(limit, subject)], args=[limit.capacity, limit.refill_per_second, cost]
            )
        except RedisError as error:
            raise RateLimiterUnavailableError("rate limiter unavailable") from error
        return Decision(allowed=int(raw[0]) == 1, retry_after_seconds=float(raw[1]))

    async def hit(self, limit: Limit, subject: str) -> Decision:
        return await self._run(limit, subject, 1)

    async def peek(self, limit: Limit, subject: str) -> Decision:
        return await self._run(limit, subject, 0)
