import logging
from collections import deque
from dataclasses import dataclass
from typing import Protocol

from vapas.config import LOCAL_ENVS, Settings

log = logging.getLogger(__name__)
CAPTURED_LIMIT = 200


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


class CapturingEmailSender:
    def __init__(self, show_body_in_logs: bool) -> None:
        self.messages: deque[EmailMessage] = deque(maxlen=CAPTURED_LIMIT)
        self._show_body = show_body_in_logs

    async def send(self, message: EmailMessage) -> None:
        self.messages.append(message)
        extra = {"kind": message.kind, "body": message.body} if self._show_body else {"kind": message.kind}
        log.info("email captured", extra=extra)


def create_email_sender(settings: Settings) -> EmailSender:
    if settings.app_env in LOCAL_ENVS:
        return CapturingEmailSender(show_body_in_logs=settings.app_env == "local")
    raise EmailProviderNotConfiguredError(f"no email provider is configured for APP_ENV={settings.app_env}")
