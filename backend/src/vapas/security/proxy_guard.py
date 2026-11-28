import hmac
import json

from starlette.types import ASGIApp, Receive, Scope, Send

PROXY_SECRET_HEADER = "X-Vapas-Proxy-Secret"
PLATFORM_CHECK_PATHS = frozenset({"/health", "/ready"})
_HEADER_KEY = PROXY_SECRET_HEADER.lower().encode()


def _presented_secret(scope: Scope) -> bytes:
    return next((value for name, value in scope.get("headers", []) if name == _HEADER_KEY), b"")


async def _forbid(send: Send) -> None:
    body = json.dumps({"error": "forbidden", "message": "Use the VAPAS app."}).encode()
    headers = [(b"content-type", b"application/json"), (b"content-length", str(len(body)).encode())]
    await send({"type": "http.response.start", "status": 403, "headers": headers})
    await send({"type": "http.response.body", "body": body})


class ProxySecretMiddleware:
    def __init__(self, app: ASGIApp, secret: str | None) -> None:
        self.app = app
        self.secret = secret.encode() if secret else None

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        guarded = scope["type"] == "http" and self.secret is not None and scope["path"] not in PLATFORM_CHECK_PATHS
        if guarded and not hmac.compare_digest(_presented_secret(scope), self.secret or b""):
            await _forbid(send)
            return
        await self.app(scope, receive, send)
