import re
from collections.abc import Mapping
from dataclasses import dataclass, field

from vapas.ingest.model import Field

PARSER_VERSION = 1
NON_ALNUM = re.compile(r"[^a-z0-9]")

COMMON_DATE_FORMATS = (
    "%d/%m/%Y",
    "%d/%m/%y",
    "%d-%m-%Y",
    "%d-%m-%y",
    "%d %b %Y",
    "%d-%b-%Y",
    "%d-%b-%y",
    "%d %b %y",
    "%d.%m.%Y",
    "%Y-%m-%d",
)


def normalize_label(label: str) -> str:
    return NON_ALNUM.sub("", label.lower())


@dataclass(frozen=True)
class Layout:
    code: str
    bank_code: str
    signatures: tuple[str, ...]
    aliases: Mapping[Field, tuple[str, ...]]
    date_formats: tuple[str, ...] = COMMON_DATE_FORMATS
    verified_against_real_statement: bool = False
    lookup: dict[str, Field] = field(init=False, repr=False, compare=False)

    def __post_init__(self) -> None:
        table = {normalize_label(alias): name for name, aliases in self.aliases.items() for alias in aliases}
        object.__setattr__(self, "lookup", table)

    @property
    def longest_alias_words(self) -> int:
        return max(len(alias.split()) for aliases in self.aliases.values() for alias in aliases)

    def field_for(self, label: str) -> Field | None:
        return self.lookup.get(normalize_label(label))


def is_complete(fields: set[Field]) -> bool:
    has_amounts = {Field.DEBIT, Field.CREDIT} <= fields or {Field.AMOUNT, Field.DIRECTION} <= fields
    return {Field.DATE, Field.NARRATION, Field.BALANCE} <= fields and has_amounts


SBI = Layout(
    code="sbi_v1",
    bank_code="SBI",
    signatures=("state bank of india",),
    aliases={
        Field.DATE: ("Txn Date",),
        Field.VALUE_DATE: ("Value Date",),
        Field.NARRATION: ("Description",),
        Field.REF: ("Ref No./Cheque No.", "Ref No. /Cheque No."),
        Field.DEBIT: ("Debit",),
        Field.CREDIT: ("Credit",),
        Field.BALANCE: ("Balance",),
    },
    date_formats=("%d %b %Y", "%d-%m-%Y", "%d/%m/%Y", "%d-%b-%Y"),
)

HDFC = Layout(
    code="hdfc_v1",
    bank_code="HDFC",
    signatures=("hdfc bank",),
    aliases={
        Field.DATE: ("Date",),
        Field.NARRATION: ("Narration",),
        Field.REF: ("Chq./Ref.No.", "Chq / Ref No."),
        Field.VALUE_DATE: ("Value Dt", "Value Date"),
        Field.DEBIT: ("Withdrawal Amt.", "Withdrawal Amount"),
        Field.CREDIT: ("Deposit Amt.", "Deposit Amount"),
        Field.BALANCE: ("Closing Balance",),
    },
    date_formats=("%d/%m/%y", "%d/%m/%Y"),
)

ICICI = Layout(
    code="icici_v1",
    bank_code="ICICI",
    signatures=("icici bank",),
    aliases={
        Field.VALUE_DATE: ("Value Date",),
        Field.DATE: ("Transaction Date",),
        Field.REF: ("Cheque Number",),
        Field.NARRATION: ("Transaction Remarks",),
        Field.DEBIT: ("Withdrawal Amount (INR )", "Withdrawal Amount (INR)", "Withdrawal Amount"),
        Field.CREDIT: ("Deposit Amount (INR )", "Deposit Amount (INR)", "Deposit Amount"),
        Field.BALANCE: ("Balance (INR )", "Balance (INR)", "Balance"),
    },
    date_formats=("%d/%m/%Y", "%d-%m-%Y", "%d/%m/%y"),
)

AXIS = Layout(
    code="axis_v1",
    bank_code="AXIS",
    signatures=("axis bank",),
    aliases={
        Field.DATE: ("Tran Date", "Transaction Date"),
        Field.REF: ("CHQNO", "Chq No"),
        Field.NARRATION: ("PARTICULARS",),
        Field.DEBIT: ("DR", "Debit"),
        Field.CREDIT: ("CR", "Credit"),
        Field.BALANCE: ("BAL", "Balance"),
    },
    date_formats=("%d-%m-%Y", "%d/%m/%Y"),
)

KOTAK = Layout(
    code="kotak_v1",
    bank_code="KOTAK",
    signatures=("kotak mahindra bank",),
    aliases={
        Field.DATE: ("Date", "Transaction Date"),
        Field.NARRATION: ("Narration", "Description"),
        Field.REF: ("Chq/Ref No", "Chq/Ref No."),
        Field.DEBIT: ("Withdrawal (Dr)", "Debit"),
        Field.CREDIT: ("Deposit (Cr)", "Credit"),
        Field.BALANCE: ("Balance",),
    },
    date_formats=("%d-%m-%Y", "%d/%m/%Y", "%d %b %Y"),
)

BANK_LAYOUTS = (SBI, HDFC, ICICI, AXIS, KOTAK)


def _union(field_name: Field, *extra: str) -> tuple[str, ...]:
    seen = dict.fromkeys(alias for layout in BANK_LAYOUTS for alias in layout.aliases.get(field_name, ()))
    seen.update(dict.fromkeys(extra))
    return tuple(seen)


GENERIC = Layout(
    code="generic_v1",
    bank_code="UNKNOWN",
    signatures=(),
    aliases={
        Field.DATE: _union(Field.DATE, "Txn Date", "Post Date", "Transaction Date", "Tran Date", "Date"),
        Field.VALUE_DATE: _union(Field.VALUE_DATE),
        Field.NARRATION: _union(Field.NARRATION, "Particulars", "Remarks", "Transaction Details", "Details"),
        Field.REF: _union(Field.REF, "Ref No", "Reference No", "Cheque No.", "Chq No.", "UTR"),
        Field.DEBIT: _union(Field.DEBIT, "Withdrawals", "Debit Amount", "Debits"),
        Field.CREDIT: _union(Field.CREDIT, "Deposits", "Credit Amount", "Credits"),
        Field.AMOUNT: ("Amount", "Transaction Amount", "Amount (INR)"),
        Field.DIRECTION: ("Dr/Cr", "Cr/Dr", "Type", "Debit/Credit"),
        Field.BALANCE: _union(Field.BALANCE, "Available Balance", "Running Balance"),
    },
)


def candidate_layouts(text: str) -> list[Layout]:
    lowered = text.lower()
    matches = [layout for layout in BANK_LAYOUTS if any(s in lowered for s in layout.signatures)]
    return [*matches, GENERIC]
