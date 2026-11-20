import io
import zipfile

import pytest
from pypdf import PdfReader, PdfWriter
from pypdf.generic import DictionaryObject, NameObject, TextStringObject

from vapas.ingest.model import FileKind
from vapas.security.upload_guard import (
    MAX_PDF_PAGES,
    MAX_UPLOAD_BYTES,
    UploadRejectedError,
    check_pdf_document,
    check_upload,
    sniff_kind,
)
from vapas.synthetic.generator import generate, render_csv, render_pdf, render_xls, render_xlsx

STATEMENT = generate("SBI", 1, count=5)


def rejected(data: bytes, kind: FileKind) -> str:
    with pytest.raises(UploadRejectedError) as caught:
        check_upload(data, kind)
    return caught.value.code


def pdf_bytes(writer: PdfWriter) -> bytes:
    buffer = io.BytesIO()
    writer.write(buffer)
    return buffer.getvalue()


@pytest.mark.parametrize(
    ("render", "kind"),
    [(render_pdf, FileKind.PDF), (render_csv, FileKind.CSV), (render_xlsx, FileKind.XLSX), (render_xls, FileKind.XLS)],
)
def test_real_formats_are_recognised(render: object, kind: FileKind) -> None:
    assert callable(render)
    data = render(STATEMENT)
    assert sniff_kind(data) is kind
    assert check_upload(data, kind) is kind


def test_declared_type_must_match_content() -> None:
    assert rejected(render_csv(STATEMENT), FileKind.PDF) == "type_mismatch"


def test_empty_and_oversized_files_are_rejected() -> None:
    assert rejected(b"", FileKind.CSV) == "empty_file"
    assert rejected(b"%PDF-" + b"0" * MAX_UPLOAD_BYTES, FileKind.PDF) == "too_large"


def test_binary_garbage_is_rejected() -> None:
    assert rejected(b"\x7fELF\x00\x01\x02", FileKind.CSV) == "unsupported_type"
    assert rejected(b"PK\x03\x04" + b"\x00" * 20, FileKind.XLSX) == "unsupported_type"


def test_pdf_with_javascript_is_rejected() -> None:
    writer = PdfWriter()
    writer.add_blank_page(200, 200)
    action = DictionaryObject(
        {NameObject("/S"): NameObject("/JavaScript"), NameObject("/JS"): TextStringObject("app.alert('x');")}
    )
    writer.root_object[NameObject("/OpenAction")] = writer._add_object(action)
    assert rejected(pdf_bytes(writer), FileKind.PDF) == "active_content"


def test_pdf_with_embedded_file_is_rejected() -> None:
    writer = PdfWriter()
    writer.add_blank_page(200, 200)
    writer.add_attachment("payload.exe", b"MZ")
    assert rejected(pdf_bytes(writer), FileKind.PDF) == "active_content"


def test_pdf_with_too_many_pages_is_rejected() -> None:
    writer = PdfWriter()
    for _ in range(MAX_PDF_PAGES + 1):
        writer.add_blank_page(100, 100)
    with pytest.raises(UploadRejectedError) as caught:
        check_pdf_document(PdfReader(io.BytesIO(pdf_bytes(writer))))
    assert caught.value.code == "too_many_pages"


def test_xlsx_with_macros_is_rejected() -> None:
    buffer = io.BytesIO()
    with zipfile.ZipFile(io.BytesIO(render_xlsx(STATEMENT))) as source, zipfile.ZipFile(buffer, "w") as target:
        for item in source.infolist():
            target.writestr(item, source.read(item.filename))
        target.writestr("xl/vbaProject.bin", b"macro")
    assert rejected(buffer.getvalue(), FileKind.XLSX) == "macros_not_allowed"


def test_xlsx_zip_bomb_is_rejected() -> None:
    buffer = io.BytesIO()
    with (
        zipfile.ZipFile(io.BytesIO(render_xlsx(STATEMENT))) as source,
        zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as target,
    ):
        for item in source.infolist():
            target.writestr(item, source.read(item.filename))
        target.writestr("xl/media/huge.bin", b"\x00" * (60 * 1024 * 1024))
    assert len(buffer.getvalue()) < MAX_UPLOAD_BYTES
    assert rejected(buffer.getvalue(), FileKind.XLSX) == "too_large_uncompressed"
