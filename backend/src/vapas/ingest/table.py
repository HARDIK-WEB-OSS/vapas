import re
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field

from vapas.ingest.layouts import Layout, is_complete
from vapas.ingest.model import Direction, Field, ParsedRow
from vapas.ingest.values import InvalidAmountError, parse_amount, parse_date

Grid = list[list[str]]
OPENING = re.compile(r"(?i)opening\s+balance|balance\s+b/?f|brought\s+forward")
DEBIT_WORDS = frozenset({"dr", "d", "debit", "withdrawal"})
CREDIT_WORDS = frozenset({"cr", "c", "credit", "deposit"})


@dataclass(frozen=True)
class ColumnMap:
    columns: dict[Field, int]

    def cell(self, cells: Sequence[str], name: Field) -> str:
        index = self.columns.get(name)
        if index is None or index >= len(cells):
            return ""
        return cells[index].strip()


def match_header(cells: Sequence[str], layout: Layout) -> ColumnMap | None:
    columns: dict[Field, int] = {}
    for index, cell in enumerate(cells):
        name = layout.field_for(cell)
        if name is not None and name not in columns:
            columns[name] = index
    return ColumnMap(columns) if is_complete(set(columns)) else None


@dataclass
class _Pending:
    cells: list[str]
    narration: list[str] = field(default_factory=list)
    refs: list[str] = field(default_factory=list)


@dataclass
class Assembly:
    rows: list[ParsedRow] = field(default_factory=list)
    opening_balance_paise: int | None = None
    skipped_lines: int = 0
    rejected_rows: int = 0


def _direction_of(text: str) -> Direction | None:
    word = text.strip().lower().rstrip(".")
    if word in DEBIT_WORDS:
        return Direction.DEBIT
    if word in CREDIT_WORDS:
        return Direction.CREDIT
    return None


def _amounts(cells: Sequence[str], cmap: ColumnMap) -> tuple[Direction, int] | None:
    if Field.AMOUNT in cmap.columns:
        amount = parse_amount(cmap.cell(cells, Field.AMOUNT))
        direction = _direction_of(cmap.cell(cells, Field.DIRECTION))
        if amount is None or amount == 0:
            return None
        if direction is None:
            raise InvalidAmountError("amount without a debit/credit marker")
        return direction, abs(amount)
    debit = parse_amount(cmap.cell(cells, Field.DEBIT)) or 0
    credit = parse_amount(cmap.cell(cells, Field.CREDIT)) or 0
    if debit and credit:
        raise InvalidAmountError("row has both a debit and a credit")
    if debit:
        return Direction.DEBIT, abs(debit)
    if credit:
        return Direction.CREDIT, abs(credit)
    return None


def _only_text(cells: Sequence[str], cmap: ColumnMap) -> bool:
    text_fields = {Field.NARRATION, Field.REF}
    numeric = [i for name, i in cmap.columns.items() if name not in text_fields]
    return all(i >= len(cells) or not cells[i].strip() for i in numeric)


class _Assembler:
    def __init__(self, layout: Layout) -> None:
        self.layout = layout
        self.out = Assembly()
        self.pending: _Pending | None = None
        self.cmap: ColumnMap | None = None

    def feed(self, cells: list[str]) -> None:
        cmap = self.cmap
        if cmap is None:
            return
        txn_date = parse_date(cmap.cell(cells, Field.DATE), self.layout.date_formats)
        if txn_date is not None:
            self.flush()
            self.pending = _Pending(cells=cells)
            self._add_text(self.pending, cells, cmap)
            return
        narration = cmap.cell(cells, Field.NARRATION)
        if OPENING.search(narration) and self.pending is None:
            self._opening(cells, cmap)
            return
        if self.pending is not None and _only_text(cells, cmap) and any(c.strip() for c in cells):
            self._add_text(self.pending, cells, cmap)
            return
        if any(c.strip() for c in cells):
            self.flush()
            self.out.skipped_lines += 1

    def _opening(self, cells: Sequence[str], cmap: ColumnMap) -> None:
        try:
            self.out.opening_balance_paise = parse_amount(cmap.cell(cells, Field.BALANCE))
        except InvalidAmountError:
            self.out.skipped_lines += 1

    @staticmethod
    def _add_text(pending: _Pending, cells: Sequence[str], cmap: ColumnMap) -> None:
        if narration := cmap.cell(cells, Field.NARRATION):
            pending.narration.append(narration)
        if ref := cmap.cell(cells, Field.REF):
            pending.refs.append(ref)

    def flush(self) -> None:
        pending, cmap = self.pending, self.cmap
        self.pending = None
        if pending is None or cmap is None:
            return
        cells = pending.cells
        narration = " ".join(" ".join(pending.narration).split())
        try:
            amounts = _amounts(cells, cmap)
            balance = parse_amount(cmap.cell(cells, Field.BALANCE))
        except InvalidAmountError:
            self.out.rejected_rows += 1
            return
        if amounts is None:
            if OPENING.search(narration) and balance is not None and not self.out.rows:
                self.out.opening_balance_paise = balance
            else:
                self.out.skipped_lines += 1
            return
        txn_date = parse_date(cmap.cell(cells, Field.DATE), self.layout.date_formats)
        if txn_date is None:
            self.out.rejected_rows += 1
            return
        direction, amount = amounts
        self.out.rows.append(
            ParsedRow(
                row_index=len(self.out.rows),
                txn_date=txn_date,
                value_date=parse_date(cmap.cell(cells, Field.VALUE_DATE), self.layout.date_formats),
                narration=narration,
                ref_no="".join(pending.refs) or None,
                direction=direction,
                amount_paise=amount,
                balance_paise=balance,
            )
        )


def assemble(grids: Iterable[Grid], layout: Layout) -> Assembly | None:
    assembler = _Assembler(layout)
    found_header = False
    for grid in grids:
        for cells in grid:
            header = match_header(cells, layout)
            if header is not None:
                if header != assembler.cmap:
                    assembler.flush()
                assembler.cmap = header
                found_header = True
                continue
            assembler.feed(cells)
    assembler.flush()
    return assembler.out if found_header else None
