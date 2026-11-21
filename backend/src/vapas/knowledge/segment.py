import re
from collections.abc import Sequence
from dataclasses import dataclass

TOP = re.compile(r"^\s*(\d{1,2})\.\s+(\S.*)$")
SUB = re.compile(r"^\s*\((\d{1,2})\)\s*(.*)$")
ITEM = re.compile(r"^\s*\(([a-z]{1,2}|[ivx]{1,5})\)\s*(.*)$")
PAGE_NUMBER = re.compile(r"^\s*(page\s*)?\d{1,3}(\s*(of|/)\s*\d{1,3})?\s*$", re.IGNORECASE)
MIN_BODY_CHARS = 20
ANNEX = re.compile(r"^\s*(ANNEX|Annex|ANNEXURE|Annexure|APPENDIX|Appendix)\b")
ROMAN = ("i", "ii", "iii", "iv", "v", "vi", "vii", "viii", "ix", "x", "xi", "xii")


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
    subitem: str | None = None

    def label(self, prefix: str) -> str | None:
        if self.top is None:
            return None
        parts = [self.top, *(f"({p})" for p in (self.sub, self.item, self.subitem) if p)]
        return f"{prefix} {''.join(parts)}"

    def next_letter(self, marker: str) -> bool:
        return (
            self.item is not None
            and len(self.item) == 1
            and len(marker) == 1
            and self.subitem is None
            and ord(marker) == ord(self.item) + 1
        )

    def is_subitem(self, marker: str) -> bool:
        if marker not in ROMAN or self.item is None or self.item in ROMAN[1:] or self.next_letter(marker):
            return False
        if marker == "i":
            return True
        return self.subitem is not None and ROMAN.index(marker) == ROMAN.index(self.subitem) + 1


def _unique(segments: list[Segment]) -> list[Segment]:
    unique: dict[str, Segment] = {}
    for found in segments:
        unique.setdefault(found.label, found)
    return list(unique.values())


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
            if ANNEX.match(raw) and cursor.top is not None:
                close()
                return _unique(segments)
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
                marker = item.group(1)
                if cursor.is_subitem(marker):
                    cursor = _Cursor(cursor.top, cursor.sub, cursor.item, marker)
                else:
                    cursor = _Cursor(cursor.top, cursor.sub, marker)
                lines, started_page = [item.group(2)], page_number
            else:
                lines.append(raw)
    close()
    return _unique(segments)
