from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date

from fpdf import FPDF

from vapas.letters.facts import LetterFacts, LetterItem
from vapas.letters.render import day, money, total_claim
from vapas.letters.templates import CHANNELS, FOOTER
from vapas.security.redact import redact

LINE = 5.5


@dataclass(frozen=True)
class EvidenceRow:
    item: LetterItem
    narration: str


def _latin(text: str) -> str:
    return text.replace("₹", "Rs ").encode("latin-1", "replace").decode("latin-1")


def masked_narration(narration: str) -> str:
    return redact(narration)[:90]


def _write(pdf: FPDF, text: str, bold: bool = False, size: int = 10) -> None:
    pdf.set_font("Helvetica", "B" if bold else "", size)
    pdf.multi_cell(0, LINE, _latin(text), new_x="LMARGIN", new_y="NEXT")


def _calculation(item: LetterItem) -> str:
    if not item.claim:
        return "No compensation is claimed for this transaction; the letter asks the bank to check and reverse it."
    ending = f"reversed on {day(item.reversal_date)}" if item.reversal_date else "not reversed as of the letter date"
    return (
        f"T = {day(item.txn_date)}. Deadline = {day(item.due_date) if item.due_date else '-'}. Amount {ending}. "
        f"Delay = {item.delay_days} days. Compensation = Rs {item.per_day_inr} x {item.delay_days} days = "
        f"{money(item.compensation_paise or 0)}"
        + (f", less {money(item.already_paid_paise)} already credited." if item.already_paid_paise else ".")
    )


def build(facts: LetterFacts, rows: Sequence[EvidenceRow], rule_quotes: Mapping[str, str], generated_on: date) -> bytes:
    pdf = FPDF(format="A4")
    pdf.set_auto_page_break(auto=True, margin=15)
    pdf.add_page()
    _write(pdf, "Evidence pack: failed transaction complaint", bold=True, size=14)
    _write(pdf, f"Bank: {facts.bank_name or facts.bank_code}. Prepared on {day(generated_on)}.")
    if facts.has_claim:
        _write(pdf, f"Total compensation claimed: {money(total_claim(facts))}.")
    pdf.ln(2)
    for number, row in enumerate(rows, 1):
        item = row.item
        channel = CHANNELS["en"].get(item.channel, "payment")
        reference = f", reference ending {item.reference_last4}" if item.reference_last4 else ""
        _write(pdf, f"{number}. {day(item.txn_date)} - {money(item.amount_paise)} - {channel}{reference}", bold=True)
        _write(pdf, f"Statement description (personal details masked): {masked_narration(row.narration)}")
        _write(pdf, _calculation(item))
        if item.claim and item.clause:
            _write(pdf, f"Rule: {item.clause} of RBI circular {item.instrument_ref}.")
            quote = rule_quotes.get(item.rule_id or "")
            if quote:
                _write(pdf, f'Source text: "{quote}"', size=9)
        pdf.ln(2)
    _write(pdf, FOOTER["en"], size=9)
    return bytes(pdf.output())
