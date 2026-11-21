import re
from dataclasses import dataclass
from enum import StrEnum

from vapas.classify.channel_rules import Channel


class PayeeType(StrEnum):
    MERCHANT = "merchant"
    PERSON = "person"
    UNKNOWN = "unknown"


@dataclass(frozen=True)
class PayeeClassification:
    payee: PayeeType
    signal: str | None


def _rx(pattern: str) -> re.Pattern[str]:
    return re.compile(pattern, re.IGNORECASE)


UPI_MERCHANT_SIGNALS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("p2m_marker", _rx(r"\bP2M\b")),
    ("phonepe_merchant_qr_vpa", _rx(r"\bQ[0-9A-Z]{6,}@YBL\b")),
    ("paytm_merchant_qr_vpa", _rx(r"\bPAYTMQR[0-9A-Z]+@PAYTM\b")),
    ("bharatpe_merchant_vpa", _rx(r"\bBHARATPE[.0-9A-Z]*@")),
    ("pos_or_ecom_code", _rx(r"\b(POS|ECOM|E-COM)\b")),
)
UPI_PERSON_SIGNALS: tuple[tuple[str, re.Pattern[str]], ...] = (("p2p_marker", _rx(r"\bP2[PA]\b")),)
AEPS_MERCHANT_SIGNALS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("aadhaar_pay", _rx(r"\bAADHAAR\s*PAY\b|\bADHR\s*PAY\b")),
    ("aeps_purchase", _rx(r"\bPURCHASE\b|\bPRCH\b")),
)
AEPS_PERSON_SIGNALS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("aeps_fund_transfer", _rx(r"\bFUND\s+TRANSFER\b|\bFT\b")),
)
SIGNALS = {
    Channel.UPI: (UPI_MERCHANT_SIGNALS, UPI_PERSON_SIGNALS),
    Channel.AEPS: (AEPS_MERCHANT_SIGNALS, AEPS_PERSON_SIGNALS),
}
PATTERNS_VERIFIED_AGAINST_REAL_STATEMENTS = False


def _first(signals: tuple[tuple[str, re.Pattern[str]], ...], text: str) -> str | None:
    return next((name for name, pattern in signals if pattern.search(text)), None)


def classify_payee(narration: str, channel: Channel) -> PayeeClassification:
    if channel not in SIGNALS:
        return PayeeClassification(PayeeType.UNKNOWN, None)
    merchant_signals, person_signals = SIGNALS[channel]
    merchant = _first(merchant_signals, narration)
    person = _first(person_signals, narration)
    if merchant and not person:
        return PayeeClassification(PayeeType.MERCHANT, merchant)
    if person and not merchant:
        return PayeeClassification(PayeeType.PERSON, person)
    return PayeeClassification(PayeeType.UNKNOWN, None)
