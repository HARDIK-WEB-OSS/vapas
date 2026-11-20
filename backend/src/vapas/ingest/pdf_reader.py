import re
from bisect import bisect_right
from collections.abc import Sequence
from dataclasses import dataclass
from itertools import pairwise
from statistics import median
from typing import Any

from vapas.ingest.layouts import Layout, is_complete
from vapas.ingest.model import Field
from vapas.ingest.table import Grid
from vapas.ingest.values import parse_date

LINE_TOLERANCE = 3.0
EDGE_TOLERANCE = 1.0
FOOTER_GAP_FACTOR = 2.0
AMOUNT_TOKEN = re.compile(r"[-+(]?[\d,]+\.\d{2}\)?(\(?(?i:cr|dr)\.?\)?)?")


@dataclass(frozen=True)
class Word:
    text: str
    x0: float
    x1: float
    top: float

    @property
    def center(self) -> float:
        return (self.x0 + self.x1) / 2


@dataclass(frozen=True)
class Span:
    name: Field | None
    label: str
    x0: float
    x1: float


def page_lines(page: Any) -> list[list[Word]]:
    raw = page.extract_words(x_tolerance=1.5, y_tolerance=2, keep_blank_chars=False)
    words = sorted((Word(w["text"], w["x0"], w["x1"], w["top"]) for w in raw), key=lambda w: (w.top, w.x0))
    lines: list[list[Word]] = []
    for word in words:
        if lines and abs(word.top - lines[-1][0].top) <= LINE_TOLERANCE:
            lines[-1].append(word)
        else:
            lines.append([word])
    return [sorted(line, key=lambda w: w.x0) for line in lines]


def header_spans(line: Sequence[Word], layout: Layout) -> list[Span] | None:
    spans: list[Span] = []
    index = 0
    widest = layout.longest_alias_words + 1
    while index < len(line):
        for size in range(min(widest, len(line) - index), 0, -1):
            chunk = line[index : index + size]
            label = " ".join(w.text for w in chunk)
            name = layout.field_for(label)
            if name is not None:
                spans.append(Span(name, label, chunk[0].x0, chunk[-1].x1))
                index += size
                break
        else:
            word = line[index]
            spans.append(Span(None, word.text, word.x0, word.x1))
            index += 1
    found = {s.name for s in spans if s.name is not None}
    return spans if is_complete(found) else None


def _gaps(lo: float, hi: float, intervals: Sequence[tuple[float, float]]) -> list[tuple[float, float]]:
    covered = sorted((max(a, lo), min(b, hi)) for a, b in intervals if b > lo and a < hi)
    gaps: list[tuple[float, float]] = []
    cursor = lo
    for start, end in covered:
        if start > cursor:
            gaps.append((cursor, start))
        cursor = max(cursor, end)
    if cursor < hi:
        gaps.append((cursor, hi))
    return gaps


def text_cuts(spans: Sequence[Span], lines: Sequence[Sequence[Word]]) -> list[float]:
    intervals = [(w.x0, w.x1) for line in lines for w in line]
    cuts: list[float] = []
    for left, right in pairwise(spans):
        lo, hi = min(left.x1, right.x0), max(left.x1, right.x0)
        middle = (lo + hi) / 2
        gaps = _gaps(lo, hi, intervals)
        if not gaps:
            cuts.append(middle)
            continue
        widest = max(gaps, key=lambda g: g[1] - g[0])
        cuts.append((widest[0] + widest[1]) / 2)
    return cuts


def to_cells(line: Sequence[Word], spans: Sequence[Span], cuts: Sequence[float]) -> list[str]:
    starts = [s.x0 for s in spans[1:]]
    cells: list[list[str]] = [[] for _ in spans]
    for word in line:
        if AMOUNT_TOKEN.fullmatch(word.text):
            cells[bisect_right(starts, word.x1 - EDGE_TOLERANCE)].append(word.text)
        else:
            cells[bisect_right(cuts, word.center)].append(word.text)
    return [" ".join(parts) for parts in cells]


def _starts_with_date(line: Sequence[Word], layout: Layout) -> bool:
    words = [w.text for w in line]
    return any(parse_date(" ".join(words[:n]), layout.date_formats) for n in (1, 3))


def without_footer(lines: list[list[Word]], layout: Layout) -> list[list[Word]]:
    if len(lines) < 3:
        return lines
    spacing = median(b[0].top - a[0].top for a, b in pairwise(lines))
    last_dated = max((i for i, line in enumerate(lines) if _starts_with_date(line, layout)), default=-1)
    for index in range(max(last_dated, 0) + 1, len(lines)):
        if lines[index][0].top - lines[index - 1][0].top > FOOTER_GAP_FACTOR * spacing:
            return lines[:index]
    return lines


def pdf_grids(pages: Sequence[Any], layout: Layout) -> list[Grid]:
    grids: list[Grid] = []
    spans: list[Span] | None = None
    for page in pages:
        lines = page_lines(page)
        header_at = next((i for i, line in enumerate(lines) if header_spans(line, layout)), None)
        if header_at is not None:
            spans = header_spans(lines[header_at], layout)
        if spans is None:
            grids.append([])
            continue
        body = without_footer(lines[header_at + 1 :] if header_at is not None else lines, layout)
        cuts = text_cuts(spans, body)
        grid: Grid = [[s.label for s in spans]] if header_at is not None else []
        grid.extend(to_cells(line, spans, cuts) for line in body)
        grids.append(grid)
    return grids


def page_text_lines(page: Any) -> list[str]:
    return [" ".join(w.text for w in line) for line in page_lines(page)]
