import hashlib
from dataclasses import dataclass
from pathlib import Path

NOTICES_DIR = Path(__file__).parent / "notice_texts"
CURRENT_NOTICE_VERSION = "2026-11-v1"
NOTICE_FILES = {"2026-11-v1": "v1"}


@dataclass(frozen=True)
class Notice:
    version: str
    text_en: str
    text_hi: str

    @property
    def sha256(self) -> bytes:
        return hashlib.sha256(f"{self.version}\n{self.text_en}\n{self.text_hi}".encode()).digest()


def load_notice(version: str) -> Notice:
    stem = NOTICE_FILES[version]
    return Notice(
        version=version,
        text_en=(NOTICES_DIR / f"{stem}.en.md").read_text(encoding="utf-8"),
        text_hi=(NOTICES_DIR / f"{stem}.hi.md").read_text(encoding="utf-8"),
    )
