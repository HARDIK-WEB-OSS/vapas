import re
from dataclasses import dataclass
from decimal import Decimal

from vapas.letters.facts import LetterFacts
from vapas.letters.render import day, money, notes, total_claim
from vapas.letters.templates import FOOTER, PLACEHOLDERS

AMOUNT = re.compile(r"(?:Rs\.?|₹|INR)\s?([\d,]+(?:\.\d{1,2})?)")
CLAUSE = re.compile(r"Annex(?:ure)?\s+Sl\.\s?\d+\s?\([a-z]\)|Clause\s+\d+(?:\(\d+\))?(?:\([a-z]+\))*(?:-\([a-z]\))?")
INSTRUMENT_REF = re.compile(r"DPSS\.CO\.PD\s*No\.\s*[\w./-]*\w")
RULE_ID = re.compile(r"\brbi\.[a-z0-9_]+(?:\.[a-z0-9_]+)+")
COMPENSATION_WORDS = re.compile(r"(?i)compensation|penalty|मुआवज़|मुआवज")
COPIES_RBI = re.compile(r"(?i)\b(cc|c\.c\.|copy to|copied to|endorsed to|marked to)\b[^\n]{0,80}(rbi|reserve bank)")
BANK = "bank"
CMS = "cms"


@dataclass(frozen=True)
class GuardResult:
    problems: tuple[str, ...]

    @property
    def ok(self) -> bool:
        return not self.problems


def _paise(text: str) -> int:
    return int(Decimal(text.replace(",", "")) * 100)


def allowed_amounts(facts: LetterFacts) -> set[int]:
    allowed = {item.amount_paise for item in facts.items}
    for item in facts.items:
        if item.claim:
            allowed |= {item.compensation_paise or 0, item.already_paid_paise, (item.per_day_inr or 0) * 100}
    if facts.has_claim:
        allowed.add(total_claim(facts))
    return allowed


def check(text: str, facts: LetterFacts, kind: str, final: bool) -> GuardResult:
    problems: list[str] = []
    allowed = allowed_amounts(facts)
    for found in AMOUNT.findall(text):
        if _paise(found) not in allowed:
            problems.append(f"amount Rs {found} is not one of the engine's amounts")
    clauses = {item.clause for item in facts.items if item.claim and item.clause}
    for found in CLAUSE.findall(text):
        if " ".join(found.split()) not in clauses:
            problems.append(f"citation '{found}' is not a verified rule of this case")
    references = {item.instrument_ref for item in facts.items if item.claim and item.instrument_ref}
    for found in INSTRUMENT_REF.findall(text):
        if found not in references:
            problems.append(f"instrument reference '{found}' is not a verified rule of this case")
    rule_ids = {item.rule_id for item in facts.items if item.claim and item.rule_id}
    for found in RULE_ID.findall(text):
        if found not in rule_ids:
            problems.append(f"rule id '{found}' is not a verified rule of this case")
    if not facts.has_claim and COMPENSATION_WORDS.search(text):
        problems.append("a reversal-only letter must not mention compensation")
    for item in facts.items:
        if day(item.txn_date) not in text or money(item.amount_paise) not in text:
            problems.append(f"transaction of {day(item.txn_date)} is missing or changed")
        if item.claim and money(item.compensation_paise or 0) not in text:
            problems.append(f"compensation for the transaction of {day(item.txn_date)} is missing or changed")
        if item.claim and item.clause and item.clause not in text:
            problems.append(f"citation {item.clause} is missing")
        disclosure = notes(item, facts.language).strip()
        if disclosure and disclosure not in text:
            problems.append(f"a required statement for the transaction of {day(item.txn_date)} is missing")
    if FOOTER[facts.language] not in text:
        problems.append("the 'not legal advice' notice is missing")
    if kind == BANK and COPIES_RBI.search(text):
        problems.append("a bank letter must not copy RBI (RB-IOS 2026 Clause 10(1)(a)); escalate only through CMS")
    if final:
        unfilled = [p for name, p in PLACEHOLDERS[facts.language].items() if p in text]
        if unfilled:
            problems.append("fill in: " + ", ".join(unfilled))
    return GuardResult(tuple(problems))
