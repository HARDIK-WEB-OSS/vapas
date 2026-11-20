import io
import zipfile
from typing import Any

from vapas.ingest.model import FileKind
from vapas.ingest.tabular import decode_text, is_xlsx

MAX_UPLOAD_BYTES = 10 * 1024 * 1024
MAX_PDF_PAGES = 60
MAX_TEXT_ROWS = 20_000
MAX_XLSX_UNCOMPRESSED_BYTES = 50 * 1024 * 1024
MAX_XLSX_ENTRIES = 200
PDF_MAGIC = b"%PDF-"
OLE_MAGIC = bytes.fromhex("D0CF11E0A1B11AE1")
ZIP_MAGIC = b"PK\x03\x04"
ACTIVE_PDF_MARKERS = (b"/JavaScript", b"/JS ", b"/JS(", b"/JS<", b"/Launch", b"/EmbeddedFile", b"/RichMedia")
DANGEROUS_ACTIONS = ("/JavaScript", "/Launch")
ACTIVE_NAME_TREES = ("/JavaScript", "/EmbeddedFiles")
MACRO_PARTS = ("xl/vbaProject.bin", "xl/macrosheets/")


class UploadRejectedError(ValueError):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


def sniff_kind(data: bytes) -> FileKind | None:
    if data.startswith(PDF_MAGIC):
        return FileKind.PDF
    if data.startswith(OLE_MAGIC):
        return FileKind.XLS
    if data.startswith(ZIP_MAGIC):
        return FileKind.XLSX if is_xlsx(data) else None
    if b"\x00" in data[:4096]:
        return None
    return FileKind.CSV


def _check_xlsx(data: bytes) -> None:
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        entries = archive.infolist()
        if len(entries) > MAX_XLSX_ENTRIES:
            raise UploadRejectedError("too_many_parts")
        if sum(e.file_size for e in entries) > MAX_XLSX_UNCOMPRESSED_BYTES:
            raise UploadRejectedError("too_large_uncompressed")
        if any(e.filename.startswith(MACRO_PARTS) for e in entries):
            raise UploadRejectedError("macros_not_allowed")


def check_upload(data: bytes, declared: FileKind) -> FileKind:
    if not data:
        raise UploadRejectedError("empty_file")
    if len(data) > MAX_UPLOAD_BYTES:
        raise UploadRejectedError("too_large")
    kind = sniff_kind(data)
    if kind is None:
        raise UploadRejectedError("unsupported_type")
    if kind is not declared:
        raise UploadRejectedError("type_mismatch")
    if kind is FileKind.PDF and any(marker in data for marker in ACTIVE_PDF_MARKERS):
        raise UploadRejectedError("active_content")
    if kind is FileKind.XLSX:
        _check_xlsx(data)
    if kind is FileKind.CSV and decode_text(data).count("\n") > MAX_TEXT_ROWS:
        raise UploadRejectedError("too_many_rows")
    return kind


def check_pdf_document(reader: Any) -> None:
    if len(reader.pages) > MAX_PDF_PAGES:
        raise UploadRejectedError("too_many_pages")
    catalog = reader.trailer["/Root"]
    if "/AA" in catalog:
        raise UploadRejectedError("active_content")
    open_action = catalog.get("/OpenAction")
    action = open_action.get_object() if open_action is not None else None
    if isinstance(action, dict) and action.get("/S") in DANGEROUS_ACTIONS:
        raise UploadRejectedError("active_content")
    names = catalog.get("/Names")
    if names is not None and any(tree in names.get_object() for tree in ACTIVE_NAME_TREES):
        raise UploadRejectedError("active_content")
