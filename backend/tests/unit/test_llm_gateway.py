import json
from typing import Any

import httpx
import pytest

from vapas.ingest.llm_fallback import FallbackRejectedError, LayoutMapping, build_prompt, layout_from_mapping
from vapas.ingest.model import FileKind, UnknownLayoutError
from vapas.ingest.parse import parse_document
from vapas.ingest.reconcile import reconcile
from vapas.jobs.queue import backoff
from vapas.llm_gateway.circuit_breaker import CircuitBreaker
from vapas.llm_gateway.gateway import LlmGateway, LlmUnavailableError, SensitiveDataBlockedError
from vapas.security.redact import find_sensitive

UNKNOWN_CSV = (
    b"Mystery Bank\n"
    b"Customer RAVI KUMAR ravi.kumar@example.in +91 9876543210 PAN ABCDE1234F\n"
    b"When,What,Out,In,Left\n"
    b"01/04/2025,UPI/DR/412345678901/RAVI KUMAR/ravik@okicici,250.00,,750.00\n"
    b"02/04/2025,NEFT CR HDFC0001234 PRIYA SHARMA A/C 123456789012,,1000.00,1750.00\n"
    b"03/04/2025,ATM WDL 4321 5678 9012 3456,500.00,,1250.00\n"
)

GOOD_MAPPING: dict[str, Any] = {
    "columns": [
        {"label": "When", "field": "date"},
        {"label": "What", "field": "narration"},
        {"label": "Out", "field": "debit"},
        {"label": "In", "field": "credit"},
        {"label": "Left", "field": "balance"},
    ],
    "date_format": "%d/%m/%Y",
}


class Recording:
    name = "recording"

    def __init__(self, answer: str | Exception) -> None:
        self.answer = answer
        self.prompts: list[str] = []

    async def complete_json(self, prompt: str) -> str:
        self.prompts.append(prompt)
        if isinstance(self.answer, Exception):
            raise self.answer
        return self.answer


async def free() -> None:
    return None


def sketch_of_unknown() -> tuple[str, ...]:
    with pytest.raises(UnknownLayoutError) as caught:
        parse_document(UNKNOWN_CSV, FileKind.CSV)
    return caught.value.sketch


async def test_nothing_identifying_reaches_the_model() -> None:
    provider = Recording(json.dumps(GOOD_MAPPING))
    gateway = LlmGateway(provider, daily_limit=5)
    await gateway.complete_json(build_prompt(sketch_of_unknown()), free)
    sent = provider.prompts[0]
    assert find_sensitive(sent) == []
    for secret in (
        "RAVI",
        "KUMAR",
        "PRIYA",
        "ravik",
        "9876543210",
        "ABCDE1234F",
        "412345678901",
        "HDFC0001234",
        "4321 5678",
    ):
        assert secret not in sent
    assert "When,What,Out,In,Left" in sent or "When What Out In Left" in sent


async def test_gateway_blocks_a_prompt_that_cannot_be_cleaned() -> None:
    provider = Recording("{}")
    gateway = LlmGateway(provider, daily_limit=5)
    sneaky = "account 1234567890123 belongs to user"
    await gateway.complete_json(sneaky, free)
    assert "1234567890123" not in provider.prompts[0]


async def test_gateway_without_provider_is_unavailable() -> None:
    with pytest.raises(LlmUnavailableError):
        await LlmGateway(None, daily_limit=5).complete_json("hello", free)


async def test_failures_open_the_circuit() -> None:
    now = [0.0]
    breaker = CircuitBreaker(failure_threshold=2, cooldown_seconds=30, clock=lambda: now[0])
    provider = Recording(httpx.ConnectError("down"))
    gateway = LlmGateway(provider, daily_limit=50, breaker=breaker)
    for _ in range(2):
        with pytest.raises(LlmUnavailableError):
            await gateway.complete_json("x", free)
    assert not gateway.available
    with pytest.raises(LlmUnavailableError):
        await gateway.complete_json("x", free)
    assert len(provider.prompts) == 2
    now[0] = 31.0
    assert gateway.available


def test_mapping_builds_a_layout_that_parses_and_reconciles() -> None:
    layout = layout_from_mapping(LayoutMapping.model_validate(GOOD_MAPPING))
    parsed = parse_document(UNKNOWN_CSV, FileKind.CSV, extra_layouts=(layout,))
    assert parsed.layout_code == "llm_mapping_v1"
    assert len(parsed.rows) == 3
    assert reconcile(parsed.rows, None).reconciled


@pytest.mark.parametrize(
    "bad",
    [
        {"columns": [{"label": "When", "field": "date"}], "date_format": "%d/%m/%Y"},
        {**GOOD_MAPPING, "date_format": "%m/%d/%Y"},
        {**GOOD_MAPPING, "columns": [{"label": "When", "field": "sql injection"}] * 3},
        {**GOOD_MAPPING, "extra": 1},
    ],
)
def test_bad_mappings_are_rejected(bad: dict[str, Any]) -> None:
    with pytest.raises((FallbackRejectedError, ValueError)):
        layout_from_mapping(LayoutMapping.model_validate(bad))


def test_mapping_without_balance_is_rejected() -> None:
    columns = [c for c in GOOD_MAPPING["columns"] if c["field"] != "balance"]
    with pytest.raises(FallbackRejectedError):
        layout_from_mapping(LayoutMapping.model_validate({**GOOD_MAPPING, "columns": columns}))


def test_backoff_grows() -> None:
    assert [backoff(n).total_seconds() for n in (1, 2, 3)] == [15, 30, 60]


def test_sensitive_block_error_has_a_code() -> None:
    assert SensitiveDataBlockedError.code == "llm_blocked_sensitive_data"
