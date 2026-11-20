import multiprocessing
from collections.abc import Sequence

from vapas.ingest.layouts import Layout
from vapas.ingest.model import FileKind, ParsedStatement, ParseError
from vapas.ingest.parse import parse_document


class ParseTimeoutError(ParseError):
    code = "parse_timeout"


def parse_isolated(
    data: bytes, kind: FileKind, password: str | None, extra_layouts: Sequence[Layout], timeout_seconds: float
) -> ParsedStatement:
    context = multiprocessing.get_context("spawn")
    with context.Pool(processes=1, maxtasksperchild=1) as pool:
        pending = pool.apply_async(parse_document, (data, kind, password, tuple(extra_layouts)))
        try:
            return pending.get(timeout=timeout_seconds)
        except multiprocessing.TimeoutError as error:
            pool.terminate()
            raise ParseTimeoutError(f"parsing took longer than {timeout_seconds}s") from error
