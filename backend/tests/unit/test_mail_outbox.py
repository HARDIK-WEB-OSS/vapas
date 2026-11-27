import asyncio
import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from vapas.config import Settings
from vapas.mail.sender import CapturingEmailSender, EmailMessage


def test_outbox_writes_one_file_per_message(tmp_path: Path) -> None:
    sender = CapturingEmailSender(show_body_in_logs=False, outbox=tmp_path / "outbox")
    asyncio.run(sender.send(EmailMessage(to="a@example.in", subject="Hi", body="link #token=abc", kind="verify")))
    files = list((tmp_path / "outbox").glob("*.json"))
    assert len(files) == 1
    assert json.loads(files[0].read_text(encoding="utf-8"))["body"] == "link #token=abc"


def test_outbox_is_refused_outside_local(base_env: dict[str, str], tmp_path: Path) -> None:
    with pytest.raises(ValidationError, match="MAIL_OUTBOX_DIR"):
        Settings(_env_file=None, app_env="production", mail_outbox_dir=tmp_path)
