import asyncio
import logging
import smtplib
import ssl
from typing import Any, ClassVar

import pytest

from vapas.config import Settings
from vapas.mail.sender import EmailMessage, EmailSendError, SmtpEmailSender, create_email_sender

PASSWORD = "abcd efgh ijkl mnop"
MESSAGE = EmailMessage(to="asha@example.in", subject="Verify", body="link #token=abc", kind="verify_email")


class FakeSmtp:
    instances: ClassVar[list["FakeSmtp"]] = []
    starttls_supported = True
    reject_login = False

    def __init__(self, host: str, port: int, timeout: float) -> None:
        self.host, self.port, self.timeout = host, port, timeout
        self.calls: list[str] = []
        self.sent: list[Any] = []
        FakeSmtp.instances.append(self)

    def __enter__(self) -> "FakeSmtp":
        return self

    def __exit__(self, *_: object) -> None:
        self.calls.append("quit")

    def ehlo(self) -> None:
        self.calls.append("ehlo")

    def starttls(self, context: ssl.SSLContext) -> None:
        if not FakeSmtp.starttls_supported:
            raise smtplib.SMTPNotSupportedError("STARTTLS extension not supported by server.")
        assert context.verify_mode == ssl.CERT_REQUIRED
        self.calls.append("starttls")

    def login(self, user: str, password: str) -> None:
        if FakeSmtp.reject_login:
            raise smtplib.SMTPAuthenticationError(535, b"Username and Password not accepted")
        self.calls.append(f"login:{user}:{password == PASSWORD}")

    def send_message(self, message: Any) -> None:
        self.calls.append("send")
        self.sent.append(message)


@pytest.fixture(autouse=True)
def fake_smtp(monkeypatch: pytest.MonkeyPatch) -> None:
    FakeSmtp.instances = []
    FakeSmtp.starttls_supported = True
    FakeSmtp.reject_login = False
    monkeypatch.setattr(smtplib, "SMTP", FakeSmtp)


def gmail() -> SmtpEmailSender:
    return SmtpEmailSender("smtp.gmail.com", 587, "me@gmail.com", PASSWORD, "VAPAS <me@gmail.com>")


def test_starttls_before_login_then_send() -> None:
    asyncio.run(gmail().send(MESSAGE))
    smtp = FakeSmtp.instances[0]
    assert (smtp.host, smtp.port) == ("smtp.gmail.com", 587)
    assert smtp.calls == ["ehlo", "starttls", "ehlo", "login:me@gmail.com:True", "send", "quit"]
    mime = smtp.sent[0]
    assert (mime["To"], mime["From"], mime["Subject"]) == ("asha@example.in", "VAPAS <me@gmail.com>", "Verify")
    assert "link #token=abc" in mime.get_content()


def test_never_sends_without_tls() -> None:
    FakeSmtp.starttls_supported = False
    with pytest.raises(EmailSendError, match="SMTPNotSupportedError"):
        asyncio.run(gmail().send(MESSAGE))
    assert "send" not in FakeSmtp.instances[0].calls


def test_password_never_appears_in_errors_or_logs(caplog: pytest.LogCaptureFixture) -> None:
    FakeSmtp.reject_login = True
    with caplog.at_level(logging.DEBUG), pytest.raises(EmailSendError) as raised:
        asyncio.run(gmail().send(MESSAGE))
    assert raised.value.__cause__ is None
    assert raised.value.__suppress_context__
    assert PASSWORD not in str(raised.value)
    assert PASSWORD not in caplog.text


def test_smtp_selected_by_env_and_password_is_secret(base_env: dict[str, str], monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MAIL_BACKEND", "smtp")
    monkeypatch.setenv("SMTP_USERNAME", "me@gmail.com")
    monkeypatch.setenv("SMTP_PASSWORD", PASSWORD)
    monkeypatch.setenv("EMAIL_FROM", "VAPAS <me@gmail.com>")
    settings = Settings(_env_file=None)
    assert PASSWORD not in repr(settings)
    assert PASSWORD not in str(settings.model_dump())
    assert isinstance(create_email_sender(settings), SmtpEmailSender)
