import random
from collections.abc import Callable
from dataclasses import dataclass

from vapas.classify.channel_rules import Channel, Kind
from vapas.ingest.model import Direction

NAMES = ("RAVI KUMAR", "PRIYA SHARMA", "ANIL MEHTA", "SUNITA DEVI", "ARJUN NAIR", "FATIMA KHAN", "J SINGH")
MERCHANTS = ("AMAZON PAY", "SWIGGY", "BIGBASKET", "IRCTC", "FLIPKART", "APOLLO PHARMACY", "RELIANCE RETAIL")
CITIES = ("MUMBAI", "PUNE", "DELHI", "BENGALURU", "KOCHI")
BANKS = ("SBIN", "HDFC", "ICIC", "UTIB", "KKBK")


@dataclass(frozen=True)
class Labelled:
    narration: str
    direction: Direction
    channel: Channel
    kind: Kind
    reference: str | None


@dataclass(frozen=True)
class Parts:
    rrn: str
    utr16: str
    utr22: str
    name: str
    merchant: str
    vpa: str
    ifsc: str
    card: str
    city: str
    order: str


Template = tuple[Direction, Channel, Kind, str, Callable[[Parts], str | None]]


def _rrn(p: Parts) -> str | None:
    return p.rrn


def _utr16(p: Parts) -> str | None:
    return p.utr16


def _utr22(p: Parts) -> str | None:
    return p.utr22


def _none(_: Parts) -> str | None:
    return None


D, C = Direction.DEBIT, Direction.CREDIT
TEMPLATES: tuple[Template, ...] = (
    (D, Channel.UPI, Kind.PAYMENT, "UPI/DR/{rrn}/{name}/{bank}/{vpa}/Payment", _rrn),
    (D, Channel.UPI, Kind.PAYMENT, "UPI-{name}-{vpa}-{ifsc}-{rrn}-PAY", _rrn),
    (D, Channel.UPI, Kind.PAYMENT, "UPI/P2M/{rrn}/{merchant}/ELECTRICITY CHARGES", _rrn),
    (D, Channel.UPI, Kind.PAYMENT, "UPI/{rrn}/COLLEGE FEE/{vpa}", _rrn),
    (C, Channel.UPI, Kind.RECEIPT, "UPI/CR/{rrn}/{name}/{vpa}/Payment", _rrn),
    (C, Channel.UPI, Kind.REVERSAL, "UPI/REV/{rrn}/{merchant}", _rrn),
    (C, Channel.UPI, Kind.REVERSAL, "REV-UPI-{rrn}-TXN FAILED", _rrn),
    (C, Channel.UPI, Kind.REVERSAL, "UPI RVSL {rrn} {merchant}", _rrn),
    (C, Channel.UPI, Kind.MERCHANT_REFUND, "UPI/REFUND/{rrn}/{merchant}", _rrn),
    (C, Channel.UPI, Kind.MERCHANT_REFUND, "UPI/{rrn}/{merchant}/REFUND REV ORDER {order}", _rrn),
    (D, Channel.IMPS, Kind.PAYMENT, "IMPS/P2A/{rrn}/{name}", _rrn),
    (D, Channel.IMPS, Kind.PAYMENT, "MMT/IMPS/{rrn}/{name}/{bank}", _rrn),
    (C, Channel.IMPS, Kind.RECEIPT, "IMPS-{rrn}-{name}-{bank}", _rrn),
    (C, Channel.IMPS, Kind.REVERSAL, "IMPS RET {rrn} {name}", _rrn),
    (D, Channel.NEFT, Kind.PAYMENT, "NEFT DR-{utr16}-{name}", _utr16),
    (C, Channel.NEFT, Kind.RECEIPT, "NEFT CR-{ifsc}-{name}-{utr16}", _utr16),
    (C, Channel.NEFT, Kind.REVERSAL, "NEFT RETURN {utr16} {name}", _utr16),
    (C, Channel.RTGS, Kind.RECEIPT, "RTGS CR-{ifsc}-{name}-{utr22}", _utr22),
    (D, Channel.ATM, Kind.PAYMENT, "ATM WDL/{rrn}/{city}", _rrn),
    (D, Channel.ATM, Kind.PAYMENT, "NFS/CASH WDL/{rrn}/{city}", _rrn),
    (D, Channel.ATM, Kind.PAYMENT, "ATW-{card}-{city}", _none),
    (C, Channel.ATM, Kind.REVERSAL, "ATM WDL REV {rrn} {city}", _rrn),
    (C, Channel.ATM, Kind.REVERSAL, "REV NFS {rrn} CASH NOT DISPENSED", _rrn),
    (D, Channel.POS, Kind.PAYMENT, "POS {card} {merchant}", _none),
    (D, Channel.POS, Kind.PAYMENT, "POS PRCH {rrn} {merchant}", _rrn),
    (C, Channel.POS, Kind.REVERSAL, "POS REV {rrn} {merchant}", _rrn),
    (D, Channel.ECOM, Kind.PAYMENT, "ECOM {card} {merchant} {rrn}", _rrn),
    (C, Channel.ECOM, Kind.REVERSAL, "E-COM REV {rrn} {merchant}", _rrn),
    (C, Channel.ECOM, Kind.CHARGEBACK, "ECOM CHARGEBACK {rrn} {merchant}", _rrn),
    (D, Channel.NACH, Kind.PAYMENT, "ACH D- {merchant} MANDATE", _none),
    (D, Channel.NACH, Kind.PAYMENT, "NACH DR {merchant} LOAN EMI", _none),
    (D, Channel.NACH, Kind.PAYMENT, "ECS {merchant} INSURANCE", _none),
    (D, Channel.AEPS, Kind.PAYMENT, "AEPS/{rrn}/CASH WITHDRAWAL", _rrn),
    (C, Channel.AEPS, Kind.REVERSAL, "AEPS REV {rrn}", _rrn),
    (D, Channel.CHARGES, Kind.CHARGE, "SMS ALERT CHGS QTR", _none),
    (D, Channel.CHARGES, Kind.CHARGE, "ATM WDL CHGS INCL GST", _none),
    (D, Channel.CHARGES, Kind.CHARGE, "MIN BAL CHARGES", _none),
    (D, Channel.CHARGES, Kind.CHARGE, "AMC FOR DEBIT CARD", _none),
    (C, Channel.CHARGES, Kind.REVERSAL, "REV SMS ALERT CHGS", _none),
    (D, Channel.CHEQUE, Kind.PAYMENT, "CHQ PAID {name}", _none),
    (C, Channel.CHEQUE, Kind.RECEIPT, "CLG {name} {bank}", _none),
    (C, Channel.CASH, Kind.RECEIPT, "CASH DEPOSIT {city}", _none),
    (C, Channel.INTEREST, Kind.INTEREST, "INT.PD:01-04-2025 TO 30-06-2025", _none),
    (C, Channel.UNCLASSIFIED, Kind.COMPENSATION, "TAT COMP FAILED TXN {rrn}", _none),
    (C, Channel.UNCLASSIFIED, Kind.RECEIPT, "SALARY {merchant} APR", _none),
    (D, Channel.UNCLASSIFIED, Kind.PAYMENT, "TRANSFER TO {name} RETAIL SAVINGS", _none),
)


def _parts(rng: random.Random) -> Parts:
    bank = rng.choice(BANKS)
    name = rng.choice(NAMES)
    return Parts(
        rrn=str(rng.randrange(10**11, 10**12)),
        utr16=f"{bank}{rng.choice('NH')}{rng.randrange(10**9, 10**10)}X",
        utr22=f"{bank}R{rng.randrange(10**16, 10**17)}",
        name=name,
        merchant=rng.choice(MERCHANTS),
        vpa=name.split()[-1].lower() + "@ok" + bank.lower(),
        ifsc=f"{bank}0{rng.randrange(100000, 999999)}",
        card=f"4321XXXXXXXX{rng.randrange(1000, 9999)}",
        city=rng.choice(CITIES),
        order=f"OD{rng.randrange(10**9, 10**10)}",
    )


def corpus(seed: int, per_template: int) -> list[Labelled]:
    rng = random.Random(seed)
    items: list[Labelled] = []
    for direction, channel, kind, template, reference in TEMPLATES:
        for _ in range(per_template):
            parts = _parts(rng)
            text = template.format(bank=parts.ifsc[:4], **{k: v for k, v in vars(parts).items()})
            items.append(Labelled(text, direction, channel, kind, reference(parts)))
    return items
