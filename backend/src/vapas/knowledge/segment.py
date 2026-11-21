import re
from collections.abc import Sequence
from dataclasses import dataclass

TOP = re.compile(r"^\s*(\d{1,2})\.\s+(\S.*)$")
SUB = re.compile(r"^\s*\((\d{1,2})\)\s*(.*)$")
ITEM = re.compile(r"^\s*\(([a-z]{1,2}|[ivx]{1,5})\)\s*(.*)$")
PAGE_NUMBER = re.compile(r"^\s*(page\s*)?\d{1,3}(\s*(of|/)\s*\d{1,3})?\s*$", re.IGNORECASE)
MIN_BODY_CHARS = 20


@dataclass(frozen=True)
class Segment:
    label: str
    text: str
    page: int


@dataclass
class _Cursor:
    top: str | None = None
    sub: str | None = None
    item: str | None = None

    def label(self, prefix: str) -> str | None:
        if self.top is None:
            return None
        parts = [self.top, *(f"({p})" for p in (self.sub, self.item) if p)]
        return f"{prefix} {''.join(parts)}"


def segment(pages: Sequence[str], prefix: str) -> list[Segment]:
    cursor = _Cursor()
    segments: list[Segment] = []
    lines: list[str] = []
    started_page = 1

    def close() -> None:
        label = cursor.label(prefix)
        text = " ".join(" ".join(lines).split())
        if label and len(text) >= MIN_BODY_CHARS:
            segments.append(Segment(label, text, started_page))

    for page_number, page in enumerate(pages, 1):
        for raw in page.splitlines():
            if not raw.strip() or PAGE_NUMBER.match(raw):
                continue
            top, sub, item = TOP.match(raw), SUB.match(raw), ITEM.match(raw)
            if top:
                close()
                cursor, lines, started_page = _Cursor(top=top.group(1)), [top.group(2)], page_number
            elif sub and cursor.top:
                close()
                cursor, lines, started_page = _Cursor(cursor.top, sub.group(1)), [sub.group(2)], page_number
            elif item and cursor.top:
                close()
                cursor = _Cursor(cursor.top, cursor.sub, item.group(1))
                lines, started_page = [item.group(2)], page_number
            else:
                lines.append(raw)
    close()
    unique: dict[str, Segment] = {}
    for found in segments:
        unique.setdefault(found.label, found)
    return list(unique.values())
