import logging
import math
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Protocol

from fastapi import Request, Response
from fastapi.responses import JSONResponse

from vapas.auth.tokens import InvalidAccessTokenError, decode_access_token
from vapas.security.client_ip import resolve_client_ip
from vapas.security.ratelimit import Decision, Limit, RateLimiterUnavailableError

log = logging.getLogger(__name__)

API_PER_USER = Limit("api_user", 120, 120)
API_PER_IP = Limit("api_ip", 600, 120)
EXEMPT_PATHS = frozenset({"/health", "/ready"})
LOCAL_BUCKETS_MAX = 20_000
FALLBACK_LOG_EVERY_SECONDS = 60.0

Clock = Callable[[], float]
CallNext = Callable[[Request], Awaitable[Response]]


class SharedLimiter(Protocol):
    async def hit(self, limit: Limit, subject: str) -> Decision: ...


@dataclass
class _Bucket:
    tokens: float
    stamp: float


@dataclass
class InProcessLimiter:
    clock: Clock = time.monotonic
    buckets: dict[tuple[str, str], _Bucket] = field(default_factory=dict)

    def hit(self, limit: Limit, subject: str) -> Decision:
        now = self.clock()
        key = (limit.name, subject)
        bucket = self.buckets.get(key)
        if bucket is None:
            if len(self.buckets) >= LOCAL_BUCKETS_MAX:
                self.buckets.clear()
            bucket = _Bucket(float(limit.capacity), now)
            self.buckets[key] = bucket
        bucket.tokens = min(limit.capacity, bucket.tokens + (now - bucket.stamp) * limit.refill_per_second)
        bucket.stamp = now
        if bucket.tokens >= 1:
            bucket.tokens -= 1
            return Decision(True, 0.0)
        return Decision(False, (1 - bucket.tokens) / limit.refill_per_second)


@dataclass
class ApiLimiter:
    shared: SharedLimiter
    local: InProcessLimiter = field(default_factory=InProcessLimiter)
    last_fallback_log: float = -math.inf

    async def hit(self, limit: Limit, subject: str) -> Decision:
        try:
            return await self.shared.hit(limit, subject)
        except RateLimiterUnavailableError:
            now = time.monotonic()
            if now - self.last_fallback_log >= FALLBACK_LOG_EVERY_SECONDS:
                self.last_fallback_log = now
                log.warning("shared rate limiter unavailable, using in-process limits")
            return self.local.hit(limit, subject)


def _user_subject(request: Request, jwt_secret: str) -> str | None:
    header = request.headers.get("authorization", "")
    scheme, _, token = header.partition(" ")
    if scheme.lower() != "bearer" or not token:
        return None
    try:
        return str(decode_access_token(jwt_secret, token).user_id)
    except InvalidAccessTokenError:
        return None


def _too_many(decision: Decision) -> JSONResponse:
    retry = str(max(math.ceil(decision.retry_after_seconds), 1))
    body = {"error": "rate_limited", "message": "Too many requests. Try again later."}
    return JSONResponse(body, status_code=429, headers={"Retry-After": retry})


def api_limits_middleware(
    limiter_of: Callable[[Request], ApiLimiter], jwt_secret: str, ip_header: str | None = None
) -> Callable[..., object]:
    async def middleware(request: Request, call_next: CallNext) -> Response:
        if request.method == "OPTIONS" or request.url.path in EXEMPT_PATHS:
            return await call_next(request)
        limiter = limiter_of(request)
        ip = resolve_client_ip(request, ip_header)
        decision = await limiter.hit(API_PER_IP, ip)
        if not decision.allowed:
            return _too_many(decision)
        user = _user_subject(request, jwt_secret)
        if user is not None:
            decision = await limiter.hit(API_PER_USER, user)
            if not decision.allowed:
                return _too_many(decision)
        return await call_next(request)

    return middleware
