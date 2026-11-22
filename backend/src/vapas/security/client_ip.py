from starlette.requests import Request

UNKNOWN = "unknown"


def resolve_client_ip(request: Request, trusted_header: str | None) -> str:
    if trusted_header:
        value = request.headers.get(trusted_header, "").strip()
        if value and "," not in value and len(value) <= 64:
            return value
    return request.client.host if request.client else UNKNOWN
