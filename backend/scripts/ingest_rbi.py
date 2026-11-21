import argparse
import asyncio
import sys
from pathlib import Path

from sqlalchemy.ext.asyncio import create_async_engine

from vapas.config import get_settings
from vapas.knowledge.clauses import Clause, clauses_from_rules
from vapas.knowledge.ingest import SourceRefusedError, instrument, pdf_clauses, replace, verified_pdf_bytes


def parse_pdf_argument(value: str) -> tuple[str, Path]:
    instrument_id, separator, path = value.partition("=")
    if not separator:
        raise argparse.ArgumentTypeError("use INSTRUMENT_ID=PATH, for example rbi.rbios_2026=C:\\rbi\\scheme.pdf")
    return instrument_id, Path(path)


async def store(clauses: list[Clause]) -> int:
    url = get_settings().migration_database_url
    if url is None:
        raise SystemExit("MIGRATION_DATABASE_URL is required to write the clause table")
    engine = create_async_engine(url.get_secret_value())
    try:
        async with engine.begin() as conn:
            return await replace(conn, clauses)
    finally:
        await engine.dispose()


def main() -> int:
    parser = argparse.ArgumentParser(description="Load verified RBI clauses into the knowledge base.")
    parser.add_argument("--rules", action="store_true", help="index the verified quotes from rules/rbi/*.yaml")
    parser.add_argument("--pdf", action="append", type=parse_pdf_argument, default=[], metavar="INSTRUMENT_ID=PATH")
    args = parser.parse_args()
    if not args.rules and not args.pdf:
        parser.error("nothing to do: pass --rules and/or --pdf")
    clauses: list[Clause] = []
    if args.rules:
        clauses.extend(clauses_from_rules(get_settings().rules_dir))
    for instrument_id, path in args.pdf:
        source = instrument(instrument_id, get_settings().rules_dir)
        try:
            data = verified_pdf_bytes(path, source.pdf_sha256)
        except SourceRefusedError as error:
            print(f"refused {instrument_id}: {error}", file=sys.stderr)
            return 1
        found = pdf_clauses(data, source)
        print(f"{instrument_id}: {len(found)} clauses from the PDF")
        clauses.extend(found)
    count = asyncio.run(store(clauses))
    print(f"stored {count} clauses")
    return 0


if __name__ == "__main__":
    sys.exit(main())
