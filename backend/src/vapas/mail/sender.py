import asyncio
import json
import logging
import smtplib
import ssl
import time
from collections import deque
from dataclasses import dataclass
from email.message import EmailMessage as MimeMessage
from pathlib import Path
from typing import Protocol
from uuid import uuid4

import httpx

from vapas.config import LOCAL_ENVS, Settings

log = logging.getLogger(__name__)
CAPTURED_LIMIT = 200
RESEND_URL = "https://api.resend.com/emails"
SEND_TIMEOUT_SECONDS = 10.0


@dataclass(frozen=True)
class EmailMessage:
    to: str
    subject: str
    body: str
    kind: str


class EmailSender(Protocol):
    async def send(self, message: EmailMessage) -> None: ...


class EmailProviderNotConfiguredError(RuntimeError):
    pass


class EmailSendError(RuntimeError):
    pass


class CapturingEmailSender:
    def __init__(self, show_body_in_logs: bool, outbox: Path | None = None) -> None:
        self.messages: deque[EmailMessage] = deque(maxlen=CAPTURED_LIMIT)
        self._show_body = show_body_in_logs
        self._outbox = outbox

    async def send(self, message: EmailMessage) -> None:
        self.messages.append(message)
        extra = {"kind": message.kind, "body": message.body} if self._show_body else {"kind": message.kind}
        log.info("email captured", extra=extra)
        if self._outbox is not None:
            self._outbox.mkdir(parents=True, exist_ok=True)
            record = {"to": message.to, "subject": message.subject, "body": message.body, "kind": message.kind}
            path = self._outbox / f"{time.time_ns()}-{uuid4().hex[:8]}.json"
            path.write_text(json.dumps(record), encoding="utf-8")


class ResendEmailSender:
    def __init__(self, api_key: str, sender: str, client: httpx.AsyncClient | None = None) -> None:
        self._api_key = api_key
        self._sender = sender
        self._client = client or httpx.AsyncClient(timeout=SEND_TIMEOUT_SECONDS)

    async def send(self, message: EmailMessage) -> None:
        payload = {"from": self._sender, "to": [message.to], "subject": message.subject, "text": message.body}
        headers = {"Authorization": f"Bearer {self._api_key}", "Idempotency-Key": uuid4().hex}
        try:
            response = await self._client.post(RESEND_URL, json=payload, headers=headers)
        except httpx.HTTPError as error:
            raise EmailSendError(f"email provider unreachable: {type(error).__name__}") from error
        if response.status_code >= 300:
            raise EmailSendError(f"email provider answered {response.status_code}")
        log.info("email sent", extra={"kind": message.kind})


class SmtpEmailSender:
    def __init__(self, host: str, port: int, username: str, password: str, sender: str) -> None:
        self._host = host
        self._port = port
        self._username = username
        self._password = password
        self._sender = sender

    def _mime(self, message: EmailMessage) -> MimeMessage:
        mime = MimeMessage()
        mime["From"] = self._sender
        mime["To"] = message.to
        mime["Subject"] = message.subject
        mime.set_content(message.body)
        return mime

    def _deliver(self, mime: MimeMessage) -> None:
        with smtplib.SMTP(self._host, self._port, timeout=SEND_TIMEOUT_SECONDS) as smtp:
            smtp.ehlo()
            smtp.starttls(context=ssl.create_default_context())
            smtp.ehlo()
            smtp.login(self._username, self._password)
            smtp.send_message(mime)

    async def send(self, message: EmailMessage) -> None:
        try:
            await asyncio.to_thread(self._deliver, self._mime(message))
        except (smtplib.SMTPException, OSError) as error:
            raise EmailSendError(f"smtp delivery failed: {type(error).__name__}") from None
        log.info("email sent", extra={"kind": message.kind})


def create_email_sender(settings: Settings) -> EmailSender:
    if settings.mail_backend == "capture":
        if settings.app_env not in LOCAL_ENVS:
            raise EmailProviderNotConfiguredError("the capture sender is only allowed when APP_ENV is local or test")
        return CapturingEmailSender(settings.app_env == "local", settings.mail_outbox_dir)
    if settings.mail_backend == "smtp" and settings.smtp_username and settings.smtp_password and settings.email_from:
        password = settings.smtp_password.get_secret_value()
        return SmtpEmailSender(
            settings.smtp_host, settings.smtp_port, settings.smtp_username, password, settings.email_from
        )
    if settings.mail_backend == "resend" and settings.resend_api_key is not None and settings.email_from:
        return ResendEmailSender(settings.resend_api_key.get_secret_value(), settings.email_from)
    raise EmailProviderNotConfiguredError(f"no email provider is configured for APP_ENV={settings.app_env}")
