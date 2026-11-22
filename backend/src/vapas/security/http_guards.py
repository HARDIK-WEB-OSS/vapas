import json
from collections.abc import Iterable

from starlette.types import ASGIApp, Message, Receive, Scope, Send

MAX_BODY_BYTES = 64 * 1024
DOCS_PATHS = frozenset({"/docs", "/docs/oauth2-redirect", "/redoc", "/openapi.json"})
BASE_HEADERS: tuple[tuple[bytes, bytes], ...] = (
    (b"x-content-type-options", b"nosniff"),
    (b"x-frame-options", b"DENY"),
    (b"referrer-policy", b"no-referrer"),
    (b"cross-origin-opener-policy", b"same-origin"),
    (b"cross-origin-resource-policy", b"same-site"),
    (b"permissions-policy", b"camera=(), microphone=(), geolocation=(), payment=()"),
)
API_CSP = (b"content-security-policy", b"default-src 'none'; frame-ancestors 'none'; base-uri 'none'")
HSTS = (b"strict-transport-security", b"max-age=31536000; includeSubDomains")


def security_headers(path: str, https_only: bool) -> list[tuple[bytes, bytes]]:
    headers = list(BASE_HEADERS)
    if path not in DOCS_PATHS:
        headers.append(API_CSP)
    if https_only:
        headers.append(HSTS)
    return headers


def _merge(existing: Iterable[tuple[bytes, bytes]], extra: list[tuple[bytes, bytes]]) -> list[tuple[bytes, bytes]]:
    present = {name.lower() for name, _ in existing}
    return [*existing, *(pair for pair in extra if pair[0] not in present)]


class SecurityHeadersMiddleware:
    def __init__(self, app: ASGIApp, https_only: bool) -> None:
        self.app = app
        self.https_only = https_only

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        extra = security_headers(scope["path"], self.https_only)

        async def send_with_headers(message: Message) -> None:
            if message["type"] == "http.response.start":
                message = {**message, "headers": _merge(message.get("headers", []), extra)}
            await send(message)

        await self.app(scope, receive, send_with_headers)


async def _reject(send: Send) -> None:
    body = json.dumps({"error": "body_too_large", "message": "Request body is too large."}).encode()
    headers = [(b"content-type", b"application/json"), (b"content-length", str(len(body)).encode())]
    await send({"type": "http.response.start", "status": 413, "headers": headers})
    await send({"type": "http.response.body", "body": body})


class BodySizeLimitMiddleware:
    def __init__(self, app: ASGIApp, max_bytes: int = MAX_BODY_BYTES) -> None:
        self.app = app
        self.max_bytes = max_bytes

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        declared = dict(scope["headers"]).get(b"content-length")
        if declared is not None and declared.isdigit() and int(declared) > self.max_bytes:
            await _reject(send)
            return
        if declared is not None:
            await self.app(scope, receive, send)
            return
        buffered = await _read_capped(receive, self.max_bytes)
        if buffered is None:
            await _reject(send)
            return
        replayed = False

        async def replay() -> Message:
            nonlocal replayed
            if replayed:
                return await receive()
            replayed = True
            return {"type": "http.request", "body": buffered, "more_body": False}

        await self.app(scope, replay, send)


async def _read_capped(receive: Receive, max_bytes: int) -> bytes | None:
    parts: list[bytes] = []
    size = 0
    while True:
        message = await receive()
        if message["type"] != "http.request":
            return b"".join(parts)
        chunk = message.get("body", b"")
        size += len(chunk)
        if size > max_bytes:
            return None
        parts.append(chunk)
        if not message.get("more_body", False):
            return b"".join(parts)
