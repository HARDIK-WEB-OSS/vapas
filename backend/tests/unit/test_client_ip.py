import pytest
from starlette.requests import Request

from vapas.security.client_ip import resolve_client_ip


def request_with(headers: dict[str, str], peer: str = "10.0.0.9") -> Request:
    raw = [(name.lower().encode(), value.encode()) for name, value in headers.items()]
    return Request({"type": "http", "headers": raw, "client": (peer, 5000)})


def test_without_trusted_header_uses_the_socket_peer() -> None:
    assert resolve_client_ip(request_with({"X-Forwarded-For": "1.2.3.4"}), None) == "10.0.0.9"


def test_trusted_proxy_header_wins() -> None:
    request = request_with({"Fly-Client-IP": "49.36.1.2", "X-Forwarded-For": "1.2.3.4, 49.36.1.2"})
    assert resolve_client_ip(request, "fly-client-ip") == "49.36.1.2"


@pytest.mark.parametrize("value", ["", "1.2.3.4, 5.6.7.8", "x" * 65])
def test_malformed_trusted_header_falls_back_to_peer(value: str) -> None:
    assert resolve_client_ip(request_with({"Fly-Client-IP": value}), "fly-client-ip") == "10.0.0.9"
