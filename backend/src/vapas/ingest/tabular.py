import csv
import io
import zipfile
from datetime import date, datetime

import xlrd
from openpyxl import load_workbook

from vapas.ingest.table import Grid

TEXT_ENCODINGS = ("utf-8-sig", "cp1252")
DELIMITERS = ",;\t|"
DATE_OUT = "%d/%m/%Y"


def decode_text(data: bytes) -> str:
    for encoding in TEXT_ENCODINGS:
        try:
            return data.decode(encoding)
        except UnicodeDecodeError:
            continue
    return data.decode("latin-1")


def csv_grid(data: bytes) -> Grid:
    text = decode_text(data)
    try:
        dialect: type[csv.Dialect] | csv.Dialect = csv.Sniffer().sniff(text[:4096], delimiters=DELIMITERS)
    except csv.Error:
        dialect = csv.excel
    return [list(row) for row in csv.reader(io.StringIO(text), dialect)]


def _cell_text(value: object) -> str:
    if value is None:
        return ""
    if isinstance(value, datetime | date):
        return value.strftime(DATE_OUT)
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value)


def xlsx_grid(data: bytes) -> Grid:
    workbook = load_workbook(io.BytesIO(data), read_only=True, data_only=True)
    try:
        sheet = workbook.worksheets[0]
        return [[_cell_text(v) for v in row] for row in sheet.iter_rows(values_only=True)]
    finally:
        workbook.close()


def _xls_cell(book: xlrd.Book, cell: xlrd.sheet.Cell) -> str:
    if cell.ctype == xlrd.XL_CELL_DATE:
        return str(xlrd.xldate_as_datetime(cell.value, book.datemode).strftime(DATE_OUT))
    return _cell_text(cell.value)


def xls_grid(data: bytes) -> Grid:
    book = xlrd.open_workbook(file_contents=data, on_demand=True)
    try:
        sheet = book.sheet_by_index(0)
        return [[_xls_cell(book, c) for c in sheet.row(r)] for r in range(sheet.nrows)]
    finally:
        book.release_resources()


def is_xlsx(data: bytes) -> bool:
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as archive:
            names = set(archive.namelist())
    except zipfile.BadZipFile:
        return False
    return "[Content_Types].xml" in names and "xl/workbook.xml" in names
