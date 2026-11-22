import asyncio
import json

import httpx
import pytest

from vapas.config import Settings
from vapas.mail.sender import RESEND_URL, EmailMessage, EmailSendError, ResendEmailSender, create_email_sender

MESSAGE = EmailMessage(to="asha@example.in", subject="Reminder", body="File by 20 Dec", kind="case_d7")


def sender_with(handler: httpx.MockTransport) -> ResendEmailSender:
    return ResendEmailSender("re_test_key", "VAPAS <no-reply@example.in>", httpx.AsyncClient(transport=handler))


def test_resend_request_carries_the_message_and_key() -> None:
    seen: list[httpx.Request] = []

    def handle(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, json={"id": "abc"})

    asyncio.run(sender_with(httpx.MockTransport(handle)).send(MESSAGE))
    request = seen[0]
    assert str(request.url) == RESEND_URL
    assert request.headers["Authorization"] == "Bearer re_test_key"
    assert request.headers["Idempotency-Key"]
    body = json.loads(request.content)
    assert body == {
        "from": "VAPAS <no-reply@example.in>",
        "to": ["asha@example.in"],
        "subject": "Reminder",
        "text": "File by 20 Dec",
    }


@pytest.mark.parametrize("status", [401, 429, 500, 503])
def test_provider_errors_raise(status: int) -> None:
    sender = sender_with(httpx.MockTransport(lambda _: httpx.Response(status)))
    with pytest.raises(EmailSendError, match=str(status)):
        asyncio.run(sender.send(MESSAGE))


def test_unreachable_provider_raises() -> None:
    def handle(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("down", request=request)

    with pytest.raises(EmailSendError, match="unreachable"):
        asyncio.run(sender_with(httpx.MockTransport(handle)).send(MESSAGE))


def test_production_uses_resend_when_configured(base_env: dict[str, str], monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.setenv("MAIL_BACKEND", "resend")
    monkeypatch.setenv("RESEND_API_KEY", "re_live_key")
    monkeypatch.setenv("EMAIL_FROM", "VAPAS <no-reply@example.in>")
    assert isinstance(create_email_sender(Settings(_env_file=None)), ResendEmailSender)
