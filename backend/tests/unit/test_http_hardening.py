import asyncio
from collections.abc import Iterator

import pytest
from fastapi import FastAPI, Request
from fastapi.testclient import TestClient
from pydantic import BaseModel

from vapas.security.api_limits import API_PER_IP, ApiLimiter, InProcessLimiter, api_limits_middleware
from vapas.security.http_guards import MAX_BODY_BYTES, BodySizeLimitMiddleware, SecurityHeadersMiddleware
from vapas.security.ratelimit import Decision, Limit, RateLimiterUnavailableError

SECRET = "x" * 40


class Echo(BaseModel):
    text: str


class Clock:
    def __init__(self) -> None:
        self.now = 0.0

    def __call__(self) -> float:
        return self.now


class BrokenShared:
    async def hit(self, limit: Limit, subject: str) -> Decision:
        raise RateLimiterUnavailableError("down")


def guarded_app(https_only: bool, limiter: ApiLimiter | None = None) -> FastAPI:
    app = FastAPI()
    if limiter is not None:
        app.middleware("http")(api_limits_middleware(lambda _: limiter, SECRET))
    app.add_middleware(BodySizeLimitMiddleware)
    app.add_middleware(SecurityHeadersMiddleware, https_only=https_only)

    @app.post("/echo")
    async def echo(body: Echo) -> Echo:
        return body

    @app.get("/health")
    async def health(request: Request) -> dict[str, str]:
        return {"ip": request.client.host if request.client else ""}

    return app


@pytest.fixture
def client() -> Iterator[TestClient]:
    with TestClient(guarded_app(https_only=True)) as test_client:
        yield test_client


def test_in_process_bucket_refills_over_time() -> None:
    clock = Clock()
    limiter = InProcessLimiter(clock=clock)
    limit = Limit("t", 2, 10)
    assert [limiter.hit(limit, "a").allowed for _ in range(3)] == [True, True, False]
    assert limiter.hit(limit, "b").allowed
    clock.now = 5.0
    assert limiter.hit(limit, "a").allowed
    assert not limiter.hit(limit, "a").allowed


def test_falls_back_to_in_process_limits_when_redis_is_down() -> None:
    clock = Clock()
    limiter = ApiLimiter(BrokenShared(), InProcessLimiter(clock=clock))
    limit = Limit("t", 1, 60)

    async def run() -> list[bool]:
        return [(await limiter.hit(limit, "ip")).allowed for _ in range(2)]

    assert asyncio.run(run()) == [True, False]


def test_api_limit_returns_429_with_retry_after() -> None:
    clock = Clock()
    limiter = ApiLimiter(BrokenShared(), InProcessLimiter(clock=clock))
    with TestClient(guarded_app(https_only=False, limiter=limiter)) as client:
        for _ in range(API_PER_IP.capacity):
            assert client.post("/echo", json={"text": "hi"}).status_code == 200
        blocked = client.post("/echo", json={"text": "hi"})
        assert blocked.status_code == 429
        assert blocked.json()["error"] == "rate_limited"
        assert int(blocked.headers["Retry-After"]) >= 1
        assert client.get("/health").status_code == 200
        assert blocked.headers["x-content-type-options"] == "nosniff"


def test_security_headers_on_every_response(client: TestClient) -> None:
    response = client.get("/health")
    assert response.headers["x-frame-options"] == "DENY"
    assert response.headers["referrer-policy"] == "no-referrer"
    assert "default-src 'none'" in response.headers["content-security-policy"]
    assert response.headers["strict-transport-security"].startswith("max-age=31536000")
    assert client.post("/echo", json={}).headers["x-content-type-options"] == "nosniff"


def test_no_hsts_on_plain_http_locally() -> None:
    with TestClient(guarded_app(https_only=False)) as client:
        assert "strict-transport-security" not in client.get("/health").headers


def test_oversized_body_is_refused_before_parsing(client: TestClient) -> None:
    assert client.post("/echo", json={"text": "a" * 1000}).status_code == 200
    big = client.post("/echo", json={"text": "a" * (MAX_BODY_BYTES + 1)})
    assert (big.status_code, big.json()["error"]) == (413, "body_too_large")


def test_oversized_chunked_body_is_refused(client: TestClient) -> None:
    payload = b'{"text": "' + b"a" * (MAX_BODY_BYTES + 1) + b'"}'

    def chunks() -> Iterator[bytes]:
        for start in range(0, len(payload), 8192):
            yield payload[start : start + 8192]

    response = client.post("/echo", content=chunks(), headers={"content-type": "application/json"})
    assert response.status_code == 413
