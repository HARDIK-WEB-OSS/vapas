from dataclasses import astuple

import pytest

from vapas.classify.channel_rules import Channel, Kind, channel_of, classify, kind_of, reference_of
from vapas.ingest.model import Direction
from vapas.synthetic.narrations import TEMPLATES, corpus

D, C = Direction.DEBIT, Direction.CREDIT


def test_synthetic_corpus_is_fully_consistent() -> None:
    items = corpus(seed=7, per_template=15)
    assert len(items) == 15 * len(TEMPLATES)
    wrong = [
        i.narration for i in items if astuple(classify(i.narration, i.direction)) != (i.channel, i.kind, i.reference)
    ]
    assert wrong == []


@pytest.mark.parametrize(
    ("text", "channel"),
    [
        ("RELIANCE RETAIL STORE PAYMENT", Channel.UNCLASSIFIED),
        ("POSTAGE STAMP PURCHASE", Channel.UNCLASSIFIED),
        ("ATMOSPHERE CAFE", Channel.UNCLASSIFIED),
        ("PREVIOUS MONTH SETTLEMENT", Channel.UNCLASSIFIED),
        ("UPI/DR/123456789012/RAJ/ELECTRICITY CHARGES", Channel.UPI),
        ("UPI AUTOPAY MANDATE NETFLIX", Channel.UPI),
        ("ATM WDL CHGS INCL GST", Channel.CHARGES),
        ("ACH D- HDFC LIFE MANDATE", Channel.NACH),
        ("NACH-DR-TATA CAPITAL-EMI", Channel.NACH),
        ("CASH DEPOSIT CDM PUNE", Channel.CASH),
        ("NFS/CASH WDL/123456789012/PUNE", Channel.ATM),
        ("AEPS/123456789012/CASH WITHDRAWAL", Channel.AEPS),
        ("upi/cr/123456789012/lowercase", Channel.UPI),
    ],
)
def test_channels(text: str, channel: Channel) -> None:
    assert channel_of(text) is channel


@pytest.mark.parametrize(
    ("text", "direction", "kind"),
    [
        ("UPI/REV/123456789012/SWIGGY", C, Kind.REVERSAL),
        ("UPI/REV/123456789012/SWIGGY", D, Kind.PAYMENT),
        ("UPI/REFUND/123456789012/AMAZON", C, Kind.MERCHANT_REFUND),
        ("UPI REFUND REVERSAL 123456789012", C, Kind.MERCHANT_REFUND),
        ("REVENUE DEPT PAYMENT", C, Kind.RECEIPT),
        ("RETAIL SALARY CREDIT", C, Kind.RECEIPT),
        ("NEFT RETURN SBIN123456789012 R", C, Kind.REVERSAL),
        ("ECOM CHARGEBACK 123456789012", C, Kind.CHARGEBACK),
        ("TAT COMP FAILED TXN", C, Kind.COMPENSATION),
        ("COMPENSATION FOR DELAYED REVERSAL", C, Kind.COMPENSATION),
        ("SMS ALERT CHGS", D, Kind.CHARGE),
        ("UPI/DR/123456789012/RAJ/ELECTRICITY CHARGES", D, Kind.PAYMENT),
        ("INT.PD:01-04-2025 TO 30-06-2025", C, Kind.INTEREST),
    ],
)
def test_kinds(text: str, direction: Direction, kind: Kind) -> None:
    assert kind_of(text, direction, channel_of(text)) is kind


def test_merchant_refund_is_never_a_reversal() -> None:
    for text in ("REFUND", "UPI/REFUND/REV", "RFND ORDER OD1234567890 FAILED"):
        assert classify(text, C).kind is Kind.MERCHANT_REFUND


@pytest.mark.parametrize(
    ("text", "channel", "reference"),
    [
        ("UPI/DR/412345678901/RAVI/okicici", Channel.UPI, "412345678901"),
        ("UPI-RAVI-ravi@okhdfc-HDFC0001234-412345678901-PAY", Channel.UPI, "412345678901"),
        ("POS 4321XXXXXXXX1234 AMAZON", Channel.POS, None),
        ("IMPS/P2A/9876543210/RAVI", Channel.IMPS, None),
        ("NEFT CR-HDFC0001234-RAVI-HDFCN52025041234", Channel.NEFT, "HDFCN52025041234"),
        ("NEFT CR-HDFC0001234-RAVI KUMAR SALARY", Channel.NEFT, None),
        ("RTGS CR-SBIN0001234-ACME-SBINR52025040112345678", Channel.RTGS, "SBINR52025040112345678"),
        ("ACH D- 412345678901 MANDATE", Channel.NACH, None),
    ],
)
def test_reference_extraction(text: str, channel: Channel, reference: str | None) -> None:
    assert reference_of(text, channel_of(text)) == reference
    assert channel_of(text) is channel
