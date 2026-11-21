import pytest

from vapas.classify.channel_rules import Channel
from vapas.classify.payee import PATTERNS_VERIFIED_AGAINST_REAL_STATEMENTS, PayeeType, classify_payee


@pytest.mark.parametrize(
    ("text", "channel", "payee", "signal"),
    [
        ("UPI/P2M/412345678901/SWIGGY", Channel.UPI, PayeeType.MERCHANT, "p2m_marker"),
        ("UPI/412345678901/Q12345678@ybl/PAY", Channel.UPI, PayeeType.MERCHANT, "phonepe_merchant_qr_vpa"),
        ("UPI/412345678901/paytmqr281005050101@paytm", Channel.UPI, PayeeType.MERCHANT, "paytm_merchant_qr_vpa"),
        ("UPI/412345678901/BHARATPE.90123@fbpe", Channel.UPI, PayeeType.MERCHANT, "bharatpe_merchant_vpa"),
        ("UPI/POS/412345678901/RELIANCE", Channel.UPI, PayeeType.MERCHANT, "pos_or_ecom_code"),
        ("UPI/P2P/412345678901/RAVI KUMAR", Channel.UPI, PayeeType.PERSON, "p2p_marker"),
        ("UPI/P2A/412345678901/RAVI KUMAR", Channel.UPI, PayeeType.PERSON, "p2p_marker"),
        ("AEPS/412345678901/AADHAAR PAY/KIRANA", Channel.AEPS, PayeeType.MERCHANT, "aadhaar_pay"),
        ("AEPS/412345678901/FUND TRANSFER", Channel.AEPS, PayeeType.PERSON, "aeps_fund_transfer"),
    ],
)
def test_clear_signals(text: str, channel: Channel, payee: PayeeType, signal: str) -> None:
    result = classify_payee(text, channel)
    assert (result.payee, result.signal) == (payee, signal)


@pytest.mark.parametrize(
    ("text", "channel"),
    [
        ("UPI/DR/412345678901/SWIGGY/swiggy@okaxis", Channel.UPI),
        ("UPI/DR/412345678901/RAVI KUMAR/ravi@okhdfc", Channel.UPI),
        ("UPI/P2M/412345678901/P2P REFUND", Channel.UPI),
        ("UPI/412345678901/QUEEN@ybl", Channel.UPI),
        ("AEPS/412345678901", Channel.AEPS),
        ("POS 4321XXXX1234 SHOP", Channel.POS),
    ],
)
def test_ambiguous_or_unrelated_stays_unknown(text: str, channel: Channel) -> None:
    assert classify_payee(text, channel).payee is PayeeType.UNKNOWN


def test_patterns_are_not_yet_verified_on_real_statements() -> None:
    assert PATTERNS_VERIFIED_AGAINST_REAL_STATEMENTS is False
