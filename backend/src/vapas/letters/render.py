from datetime import date

from vapas.letters.facts import LetterFacts, LetterItem
from vapas.letters.templates import (
    ACCRUING_ITEM,
    ALREADY_PAID,
    BANK_LETTER,
    CHANNELS,
    CHECK_ITEM,
    CHECK_REQUEST,
    CLAIM_ITEM,
    CLAIM_REQUEST,
    CMS_CHECK_REQUEST,
    CMS_CLAIM_REQUEST,
    CMS_COMPLAINT,
    CMS_NO_REPLY,
    FOOTER,
    MERCHANT_NOTES,
    OTHER_CHANNEL,
    PLACEHOLDERS,
    REFERENCE,
    SUBJECTS,
)

FIELDS = ("customer_name", "account_hint", "contact", "bank_name")


def money(paise: int) -> str:
    rupees, fraction = divmod(paise, 100)
    digits = str(rupees)
    if len(digits) > 3:
        head, tail = digits[:-3], digits[-3:]
        groups = [head[max(0, i - 2) : i] for i in range(len(head), 0, -2)][::-1]
        digits = ",".join([*groups, tail])
    return f"Rs {digits}" + (f".{fraction:02d}" if fraction else "")


def day(value: date) -> str:
    return value.strftime("%d/%m/%Y")


def citation(item: LetterItem, language: str) -> str:
    if language == "hi":
        return f"RBI परिपत्र {item.instrument_ref} के {item.clause}"
    return f"{item.clause} of RBI circular {item.instrument_ref}"


def notes(item: LetterItem, language: str) -> str:
    parts: list[str] = []
    if item.merchant_source:
        kind = "customer" if item.merchant_source == "customer" else "statement"
        parts.append(MERCHANT_NOTES[language][kind])
    if item.rule_disclosure:
        parts.append(item.rule_disclosure)
    return "".join(f" {p}" for p in parts)


def item_text(number: int, item: LetterItem, language: str, as_of: date) -> str:
    reference = REFERENCE[language].substitute(last4=item.reference_last4) if item.reference_last4 else ""
    common = {
        "number": number,
        "txn_date": day(item.txn_date),
        "amount": money(item.amount_paise),
        "channel": CHANNELS[language].get(item.channel, OTHER_CHANNEL[language]),
        "reference": reference,
        "notes": notes(item, language),
    }
    if not item.claim:
        return CHECK_ITEM[language].substitute(common)
    claim = {
        **common,
        "citation": citation(item, language),
        "due_date": day(item.due_date) if item.due_date else "",
        "delay": item.delay_days,
        "per_day": item.per_day_inr,
        "compensation": money(item.compensation_paise or 0),
    }
    if item.accruing:
        return ACCRUING_ITEM[language].substitute(claim, as_of=day(as_of))
    paid = ALREADY_PAID[language].substitute(paid=money(item.already_paid_paise)) if item.already_paid_paise else ""
    return CLAIM_ITEM[language].substitute(
        claim, reversal_date=day(item.reversal_date) if item.reversal_date else "", paid=paid
    )


def total_claim(facts: LetterFacts) -> int:
    return sum(item.compensation_paise or 0 for item in facts.items if item.claim)


def _common(facts: LetterFacts) -> dict[str, str]:
    language = facts.language
    placeholders = PLACEHOLDERS[language]
    items = "\n\n".join(item_text(n, item, language, facts.letter_date) for n, item in enumerate(facts.items, 1))
    return {
        "bank_name": facts.bank_name or placeholders["bank_name"],
        "customer_name": placeholders["customer_name"],
        "account_hint": placeholders["account_hint"],
        "contact": placeholders["contact"],
        "letter_date": day(facts.letter_date),
        "items": items,
        "footer": FOOTER[language],
    }


def render_bank_letter(facts: LetterFacts) -> str:
    total = money(total_claim(facts))
    request = (
        CLAIM_REQUEST[facts.language].replace("$total", total) if facts.has_claim else CHECK_REQUEST[facts.language]
    )
    subject = SUBJECTS[facts.language]["claim" if facts.has_claim else "check"]
    return BANK_LETTER[facts.language].substitute(_common(facts), request=request, subject=subject)


def render_cms_complaint(facts: LetterFacts) -> str:
    total = money(total_claim(facts))
    request = (
        CMS_CLAIM_REQUEST[facts.language].replace("$total", total)
        if facts.has_claim
        else CMS_CHECK_REQUEST[facts.language]
    )
    return CMS_COMPLAINT[facts.language].substitute(
        _common(facts),
        sent_on=day(facts.sent_on) if facts.sent_on else "",
        received_on=day(facts.received_on) if facts.received_on else "",
        reply=CMS_NO_REPLY[facts.language],
        request=request,
    )


def fill(text: str, language: str, fields: dict[str, str]) -> str:
    for name, placeholder in PLACEHOLDERS[language].items():
        if fields.get(name):
            text = text.replace(placeholder, fields[name].strip())
    return text
