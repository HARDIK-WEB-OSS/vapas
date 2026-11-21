import json
from dataclasses import replace
from datetime import date

import pytest

from vapas.letters.facts import LetterFacts, LetterItem
from vapas.letters.guardrails import BANK, CMS, check
from vapas.letters.polish import polish
from vapas.letters.render import fill, render_bank_letter, render_cms_complaint
from vapas.llm_gateway.gateway import LlmGateway

ATM = LetterItem(
    finding_id="f1",
    claim=True,
    rule_id="rbi.tat.atm_cash_not_dispensed",
    clause="Annex Sl. 1(a)",
    instrument_ref="DPSS.CO.PD No.629/02.01.014/2019-20",
    channel="atm",
    txn_date=date(2026, 3, 1),
    amount_paise=200_000,
    reference_last4="8901",
    reversal_date=date(2026, 3, 12),
    due_date=date(2026, 3, 6),
    delay_days=6,
    per_day_inr=100,
    compensation_paise=60_000,
    already_paid_paise=0,
    accruing=False,
    merchant_source=None,
    rule_disclosure=None,
)
UPI = replace(
    ATM,
    finding_id="f2",
    rule_id="rbi.tat.upi_merchant",
    clause="Annex Sl. 4(b)",
    channel="upi",
    txn_date=date(2026, 6, 1),
    amount_paise=45_000,
    reversal_date=date(2026, 6, 10),
    due_date=date(2026, 6, 6),
    delay_days=4,
    compensation_paise=40_000,
    merchant_source="customer",
)
DUPLICATE = replace(
    ATM,
    finding_id="f3",
    claim=False,
    rule_id=None,
    clause=None,
    channel="pos",
    amount_paise=45_000,
    txn_date=date(2026, 9, 3),
    compensation_paise=None,
    delay_days=None,
)
FIELDS = {"customer_name": "Asha Rao", "account_hint": "1234", "contact": "asha@example.in"}


def facts(*items: LetterItem, language: str = "en", bank: str = "SBI") -> LetterFacts:
    return LetterFacts(bank, language, date(2026, 11, 21), tuple(items), date(2026, 11, 21), date(2026, 11, 22))


@pytest.mark.parametrize("language", ["en", "hi"])
def test_template_letters_pass_their_own_guardrails(language: str) -> None:
    letter_facts = facts(ATM, UPI, DUPLICATE, language=language)
    text = render_bank_letter(letter_facts)
    assert check(text, letter_facts, BANK, final=False).ok, check(text, letter_facts, BANK, final=False).problems
    cms = render_cms_complaint(letter_facts)
    assert check(cms, letter_facts, CMS, final=False).ok


def test_bank_letter_states_the_engine_facts() -> None:
    text = render_bank_letter(facts(ATM, UPI))
    for expected in (
        "State Bank of India",
        "01/03/2026",
        "Rs 2,000",
        "reference ending 8901",
        "12/03/2026",
        "6 days after the deadline of 06/03/2026",
        "Annex Sl. 1(a) of RBI circular DPSS.CO.PD No.629/02.01.014/2019-20",
        "comes to Rs 600",
        "I confirm that this payment was made to a merchant.",
        "a total of Rs 1,000",
        "It is not legal advice.",
    ):
        assert expected in text


def test_unknown_bank_gets_a_placeholder() -> None:
    assert "[YOUR BANK'S NAME]" in render_bank_letter(facts(ATM, bank="UNKNOWN"))


def test_wrong_amount_is_blocked() -> None:
    letter_facts = facts(ATM)
    text = render_bank_letter(letter_facts).replace("comes to Rs 600", "comes to Rs 6,000")
    problems = check(text, letter_facts, BANK, final=False).problems
    assert any("Rs 6,000" in p for p in problems)


def test_unknown_rule_is_blocked() -> None:
    letter_facts = facts(ATM)
    text = render_bank_letter(letter_facts) + "\nSee also Annex Sl. 3(a) and rule rbi.tat.imps_not_credited."
    problems = check(text, letter_facts, BANK, final=False).problems
    assert any("Annex Sl. 3(a)" in p for p in problems)
    assert any("rbi.tat.imps_not_credited" in p for p in problems)


def test_reversal_only_letter_with_compensation_is_blocked() -> None:
    letter_facts = facts(DUPLICATE)
    text = render_bank_letter(letter_facts)
    assert "compensation" not in text.lower()
    tampered = text.replace("Please check this", "Please pay compensation and check this")
    assert not check(tampered, letter_facts, BANK, final=False).ok
    with_amount = text + "\nPlease also pay Rs 600."
    assert not check(with_amount, letter_facts, BANK, final=False).ok


def test_bank_letter_never_copies_rbi() -> None:
    letter_facts = facts(ATM)
    text = render_bank_letter(letter_facts) + "\ncc: Reserve Bank of India"
    assert any("must not copy RBI" in p for p in check(text, letter_facts, BANK, final=False).problems)


def test_nach_disclosure_and_merchant_note_are_required() -> None:
    nach = replace(
        ATM,
        channel="nach",
        rule_id="rbi.tat.nach_debit_after_revocation",
        clause="Annex Sl. 7(b)",
        rule_disclosure=(
            "The mandate revocation date stated here was provided by the customer and is not shown on the bank "
            "statement."
        ),
    )
    letter_facts = facts(nach, UPI)
    text = render_bank_letter(letter_facts)
    assert check(text, letter_facts, BANK, final=False).ok
    for removed in ("The mandate revocation date stated here", "I confirm that this payment"):
        start = text.index(removed)
        stripped = text[:start] + text[text.index(".", start) + 1 :]
        assert not check(stripped, letter_facts, BANK, final=False).ok


def test_placeholders_must_be_filled_before_approval() -> None:
    letter_facts = facts(ATM)
    text = render_bank_letter(letter_facts)
    assert any("fill in" in p for p in check(text, letter_facts, BANK, final=True).problems)
    filled = fill(text, "en", FIELDS)
    assert check(filled, letter_facts, BANK, final=True).ok
    assert "Asha Rao" in filled


def test_accruing_claim_says_it_keeps_growing() -> None:
    open_claim = replace(ATM, accruing=True, reversal_date=None, delay_days=20, compensation_paise=200_000)
    text = render_bank_letter(facts(open_claim))
    assert "has not been reversed as of 21/11/2026" in text
    assert "continues until the amount is reversed" in text


class FakeModel:
    name = "fake"

    def __init__(self, transform: object) -> None:
        self.transform = transform

    async def complete_json(self, prompt: str) -> str:
        letter = prompt.split("Letter:\n", 1)[1]
        assert callable(self.transform)
        return json.dumps({"text": self.transform(letter)})


async def free() -> None:
    return None


async def test_good_polish_is_used_and_bad_polish_falls_back_to_the_template() -> None:
    letter_facts = facts(ATM)
    template = render_bank_letter(letter_facts)
    good = await polish(
        template,
        letter_facts,
        BANK,
        LlmGateway(FakeModel(lambda t: t.replace("Dear Sir or Madam", "Respected Sir or Madam")), 5),
        free,
    )
    assert (good.polished, "Respected Sir or Madam" in good.text) == (True, True)
    bad = await polish(
        template, letter_facts, BANK, LlmGateway(FakeModel(lambda t: t.replace("Rs 600", "Rs 900")), 5), free
    )
    assert (bad.polished, bad.text) == (False, template)
    assert "polish rejected" in bad.note
    offline = await polish(template, letter_facts, BANK, LlmGateway(None, 5), free)
    assert (offline.polished, offline.text) == (False, template)


def test_evidence_pack_contains_calculation_rule_text_and_masks_details() -> None:
    import io

    from pypdf import PdfReader

    from vapas.cases.evidence_pack import EvidenceRow, build

    letter_facts = facts(ATM, DUPLICATE)
    rows = [
        EvidenceRow(ATM, "ATM WDL/412345678901/PUNE ravi@okicici 9876543210"),
        EvidenceRow(DUPLICATE, "POS 4321XXXXXXXX1234 BIGBASKET"),
    ]
    quotes = {
        "rbi.tat.atm_cash_not_dispensed": (
            "Pro-active reversal (R) of failed transaction within a maximum of T + 5 days."
        )
    }
    data = build(letter_facts, rows, quotes, date(2026, 11, 21))
    text = " ".join((page.extract_text() or "") for page in PdfReader(io.BytesIO(data)).pages)
    flat = " ".join(text.split())
    assert "Compensation = Rs 100 x 6 days = Rs 600" in flat
    assert "Annex Sl. 1(a) of RBI circular DPSS.CO.PD No.629/02.01.014/2019-20" in flat
    assert "within a maximum of T + 5 days" in flat
    assert "No compensation is claimed for this transaction" in flat
    for secret in ("412345678901", "ravi@okicici", "9876543210"):
        assert secret not in flat
    assert "not legal advice" in flat
