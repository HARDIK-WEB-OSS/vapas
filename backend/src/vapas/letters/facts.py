from dataclasses import dataclass
from datetime import date

BANK_NAMES = {
    "SBI": "State Bank of India",
    "HDFC": "HDFC Bank",
    "ICICI": "ICICI Bank",
    "AXIS": "Axis Bank",
    "KOTAK": "Kotak Mahindra Bank",
}


@dataclass(frozen=True)
class LetterItem:
    finding_id: str
    claim: bool
    rule_id: str | None
    clause: str | None
    instrument_ref: str | None
    channel: str
    txn_date: date
    amount_paise: int
    reference_last4: str | None
    reversal_date: date | None
    due_date: date | None
    delay_days: int | None
    per_day_inr: int | None
    compensation_paise: int | None
    already_paid_paise: int
    accruing: bool
    merchant_source: str | None
    rule_disclosure: str | None


@dataclass(frozen=True)
class LetterFacts:
    bank_code: str
    language: str
    letter_date: date
    items: tuple[LetterItem, ...]
    sent_on: date | None = None
    received_on: date | None = None
    last_communication_on: date | None = None

    @property
    def bank_name(self) -> str | None:
        return BANK_NAMES.get(self.bank_code)

    @property
    def has_claim(self) -> bool:
        return any(item.claim for item in self.items)
