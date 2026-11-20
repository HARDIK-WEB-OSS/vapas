import io
from collections.abc import Callable, Sequence
from typing import Any

import pdfplumber
from pypdf import PdfReader
from pypdf.errors import PdfReadError

from vapas.ingest.layouts import COMMON_DATE_FORMATS, PARSER_VERSION, Layout, candidate_layouts
from vapas.ingest.model import (
    FileKind,
    NeedsPasswordError,
    ParsedStatement,
    ParseError,
    UnknownLayoutError,
    WrongPasswordError,
)
from vapas.ingest.pdf_reader import page_text_lines, pdf_grids
from vapas.ingest.table import Assembly, Grid, assemble
from vapas.ingest.tabular import csv_grid, xls_grid, xlsx_grid
from vapas.ingest.values import parse_date
from vapas.security.redact import sketch
from vapas.security.upload_guard import check_pdf_document

SIGNATURE_SCAN_ROWS = 40


def _starts_with_date(line: str) -> bool:
    words = line.split()
    return any(parse_date(" ".join(words[:n]), COMMON_DATE_FORMATS) for n in (1, 3))


def _best(results: Sequence[tuple[Layout, Assembly, int]]) -> tuple[Layout, Assembly, int] | None:
    usable = [r for r in results if r[1].rows]
    return max(usable, key=lambda r: len(r[1].rows), default=None)


def _statement(layout: Layout, assembly: Assembly, pages: int) -> ParsedStatement:
    return ParsedStatement(
        bank_code=layout.bank_code,
        layout_code=layout.code,
        parser_version=PARSER_VERSION,
        rows=tuple(assembly.rows),
        opening_balance_paise=assembly.opening_balance_paise,
        skipped_lines=assembly.skipped_lines,
        rejected_rows=assembly.rejected_rows,
        pages=pages,
    )


def _open_pdf(data: bytes, password: str | None) -> None:
    try:
        reader = PdfReader(io.BytesIO(data))
        if reader.is_encrypted:
            if not password:
                raise NeedsPasswordError("statement is password protected")
            if not reader.decrypt(password):
                raise WrongPasswordError("password is wrong")
    except PdfReadError as error:
        raise ParseError("pdf could not be read") from error
    check_pdf_document(reader)


def parse_pdf(data: bytes, password: str | None, extra_layouts: Sequence[Layout] = ()) -> ParsedStatement:
    _open_pdf(data, password)
    with pdfplumber.open(io.BytesIO(data), password=password or "") as pdf:
        pages: list[Any] = list(pdf.pages)
        first_lines = page_text_lines(pages[0]) if pages else []
        layouts = [*extra_layouts, *candidate_layouts(" ".join(first_lines))]
        results = []
        for layout in layouts:
            assembly = assemble(pdf_grids(pages, layout), layout)
            if assembly is not None:
                results.append((layout, assembly, len(pages)))
        best = _best(results)
        if best is None:
            raise UnknownLayoutError(sketch(first_lines, _starts_with_date))
        return _statement(*best)


def _signature_text(grid: Grid) -> str:
    return " ".join(" ".join(row) for row in grid[:SIGNATURE_SCAN_ROWS])


def parse_grid(grid: Grid, extra_layouts: Sequence[Layout] = ()) -> ParsedStatement:
    layouts = [*extra_layouts, *candidate_layouts(_signature_text(grid))]
    results = [(layout, a, 1) for layout in layouts if (a := assemble([grid], layout)) is not None]
    best = _best(results)
    if best is None:
        lines = [" ".join(c for c in row if c.strip()) for row in grid[:SIGNATURE_SCAN_ROWS]]
        raise UnknownLayoutError(sketch(lines, _starts_with_date))
    return _statement(*best)


GRID_READERS: dict[FileKind, Callable[[bytes], Grid]] = {
    FileKind.CSV: csv_grid,
    FileKind.XLS: xls_grid,
    FileKind.XLSX: xlsx_grid,
}


def parse_document(
    data: bytes, kind: FileKind, password: str | None = None, extra_layouts: Sequence[Layout] = ()
) -> ParsedStatement:
    if kind is FileKind.PDF:
        return parse_pdf(data, password, extra_layouts)
    try:
        grid = GRID_READERS[kind](data)
    except Exception as error:
        raise ParseError(f"{kind.value} file could not be read") from error
    return parse_grid(grid, extra_layouts)
