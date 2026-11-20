import re
from dataclasses import dataclass
from enum import StrEnum

from vapas.ingest.model import Direction

CLASSIFIER_VERSION = 1


class Channel(StrEnum):
    UPI = "upi"
    IMPS = "imps"
    NEFT = "neft"
    RTGS = "rtgs"
    ATM = "atm"
    POS = "pos"
    ECOM = "ecom"
    NACH = "nach"
    AEPS = "aeps"
    CHARGES = "charges"
    CHEQUE = "cheque"
    CASH = "cash"
    INTEREST = "interest"
    UNCLASSIFIED = "unclassified"


class Kind(StrEnum):
    PAYMENT = "payment"
    RECEIPT = "receipt"
    REVERSAL = "reversal"
    MERCHANT_REFUND = "merchant_refund"
    CHARGEBACK = "chargeback"
    COMPENSATION = "compensation"
    CHARGE = "charge"
    INTEREST = "interest"


def _rx(pattern: str) -> re.Pattern[str]:
    return re.compile(pattern, re.IGNORECASE)


CHANNEL_RULES: tuple[tuple[Channel, re.Pattern[str]], ...] = (
    (Channel.AEPS, _rx(r"\bAEPS\b|\bAADHAAR\s+PAY\b")),
    (Channel.UPI, _rx(r"\bUPI\b")),
    (Channel.NACH, _rx(r"\bN?ACH\b|\bECS\b")),
    (Channel.IMPS, _rx(r"\bIMPS\b|\bMMT\b")),
    (Channel.RTGS, _rx(r"\bRTGS\b")),
    (Channel.NEFT, _rx(r"\bNEFT\b")),
    (Channel.CHARGES, _rx(r"\bCHGS?\b|\bCHRGS?\b|\bCHARGES\b|\bSMS\s+ALERT\b|\bAMC\b|\bMIN(?:IMUM)?\s+BAL")),
    (Channel.ATM, _rx(r"\bATM\b|\bATW\b|\bNFS\b|\bCASH\s+WDL\b")),
    (Channel.POS, _rx(r"\bPOS\b")),
    (Channel.ECOM, _rx(r"\bE-?COMM?\b")),
    (Channel.CHEQUE, _rx(r"\bCHQ\b|\bCHEQUE\b|\bCLG\b|\bCLEARING\b")),
    (Channel.CASH, _rx(r"\bCASH\s+DEP(?:OSIT)?\b|\bBY\s+CASH\b")),
    (Channel.INTEREST, _rx(r"\bINT\.?\s*(?:PD|PAID|CR)\b|\bINTEREST\b")),
)

REVERSAL = _rx(
    r"\bREV\b|\bREVERSAL\b|\bREVERSED\b|\bRVSL\b|\bRVRSL\b|\bREVSL\b|\bRET\b|\bRETURN(?:ED)?\b|\bFAILED\b|\bFAIL\b"
)
REFUND = _rx(r"\bREFUND\b|\bRFND\b")
CHARGEBACK = _rx(r"\bCHARGE\s?BACK\b|\bCHBK\b")
COMPENSATION = _rx(r"\bCOMPENSATION\b|\bTAT\s+COMP\b")

TWELVE_DIGITS = re.compile(r"(?<!\d)\d{12}(?!\d)")
NEFT_UTR = re.compile(r"(?<![A-Z0-9])[A-Z]{4}[A-Z0-9]{12}(?![A-Z0-9])")
RTGS_UTR = re.compile(r"(?<![A-Z0-9])[A-Z]{4}R[A-Z0-9]{17}(?![A-Z0-9])")
RRN_CHANNELS = frozenset({Channel.UPI, Channel.IMPS, Channel.ATM, Channel.POS, Channel.ECOM, Channel.AEPS})
MIN_UTR_DIGITS = 8


@dataclass(frozen=True)
class Classification:
    channel: Channel
    kind: Kind
    reference: str | None


def channel_of(text: str) -> Channel:
    return next((channel for channel, pattern in CHANNEL_RULES if pattern.search(text)), Channel.UNCLASSIFIED)


def kind_of(text: str, direction: Direction, channel: Channel) -> Kind:
    if direction is Direction.DEBIT:
        return Kind.CHARGE if channel is Channel.CHARGES else Kind.PAYMENT
    if CHARGEBACK.search(text):
        return Kind.CHARGEBACK
    if COMPENSATION.search(text):
        return Kind.COMPENSATION
    if REFUND.search(text):
        return Kind.MERCHANT_REFUND
    if REVERSAL.search(text):
        return Kind.REVERSAL
    if channel is Channel.INTEREST:
        return Kind.INTEREST
    return Kind.RECEIPT


def _utr(pattern: re.Pattern[str], text: str) -> str | None:
    for match in pattern.finditer(text.upper()):
        if sum(ch.isdigit() for ch in match.group(0)) >= MIN_UTR_DIGITS:
            return match.group(0)
    return None


def reference_of(text: str, channel: Channel) -> str | None:
    if channel in RRN_CHANNELS:
        match = TWELVE_DIGITS.search(text)
        return match.group(0) if match else None
    if channel is Channel.NEFT:
        return _utr(NEFT_UTR, text)
    if channel is Channel.RTGS:
        return _utr(RTGS_UTR, text)
    return None


def classify(narration: str, direction: Direction) -> Classification:
    channel = channel_of(narration)
    return Classification(channel, kind_of(narration, direction, channel), reference_of(narration, channel))
