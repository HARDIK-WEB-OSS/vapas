import hashlib
from dataclasses import dataclass, field
from datetime import date
from enum import StrEnum
from typing import Any

from vapas.classify.channel_rules import Channel, Kind
from vapas.ingest.model import Direction

DETECTOR_VERSION = 1


class Level(StrEnum):
    CLAIM = "claim"
    WORTH_CHECKING = "worth_checking"
    NEEDS_USER_INPUT = "needs_user_input"
    NEEDS_REVIEW = "needs_review"
    HISTORICAL = "historical"
    INFORMATIONAL = "informational"


class Detector(StrEnum):
    LATE_REVERSAL = "late_reversal"
    PARTIAL_REVERSAL = "partial_reversal"
    UNREVERSED_FAILED = "unreversed_failed"
    DUPLICATE = "duplicate"
    DUPLICATE_CHARGE = "duplicate_charge"
    NACH_AFTER_REVOCATION = "nach_after_revocation"


class Confidence(StrEnum):
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


class Question(StrEnum):
    PAYEE_WAS_MERCHANT = "payee_was_merchant"
    PAYMENT_FAILED = "payment_failed"
    MANDATE_REVOKED = "mandate_revoked"


@dataclass(frozen=True)
class TxnKey:
    id: int
    txn_date: date


@dataclass(frozen=True)
class Txn:
    key: TxnKey
    statement_id: str
    row_index: int
    txn_date: date
    value_date: date | None
    direction: Direction
    amount_paise: int
    balance_paise: int | None
    channel: Channel
    kind: Kind
    narration: str
    references: frozenset[bytes] = frozenset()
    bank_code: str = "UNKNOWN"

    @property
    def is_debit(self) -> bool:
        return self.direction is Direction.DEBIT

    @property
    def is_credit(self) -> bool:
        return self.direction is Direction.CREDIT


@dataclass(frozen=True)
class UserAnswers:
    payee_was_merchant: dict[TxnKey, bool] = field(default_factory=dict)
    payment_failed: dict[TxnKey, bool] = field(default_factory=dict)
    mandate_revoked_on: dict[str, date] = field(default_factory=dict)
    mandate_proof: dict[str, bool] = field(default_factory=dict)


@dataclass(frozen=True)
class Finding:
    detector: Detector
    level: Level
    confidence: Confidence
    rule_id: str | None
    finding_policy: str | None
    letter_scope: str | None
    debit: TxnKey | None
    reversals: tuple[TxnKey, ...]
    t_date: date | None
    r_date: date | None
    delay_days: int | None
    amount_owed_paise: int | None
    already_paid_paise: int
    why: str
    question: Question | None = None
    group_key: str | None = None
    accruing: bool = False
    facts: dict[str, Any] = field(default_factory=dict)

    def key(self, rules_sha: bytes, policy_sha: bytes) -> bytes:
        parts = [
            self.detector.value,
            self.rule_id or "",
            rules_sha.hex(),
            policy_sha.hex(),
            f"{self.debit.id}:{self.debit.txn_date}" if self.debit else "",
            ",".join(f"{k.id}:{k.txn_date}" for k in self.reversals),
            self.group_key or "",
        ]
        return hashlib.sha256("|".join(parts).encode()).digest()
