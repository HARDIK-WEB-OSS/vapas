import argparse
import hashlib
import os
import sys
from datetime import UTC, datetime
from pathlib import Path

import httpx
import yaml

from vapas.rules.loader import default_rules_dir
from vapas.security.email_domains import (
    ALLOWLIST_EXTRA_FILE,
    DISPOSABLE_FILE,
    DOMAIN_PATTERN,
    EMAIL_RULES_DIR,
    SOURCE_FILE,
    parse_domain_list,
)

SOURCE_URL = (
    "https://raw.githubusercontent.com/disposable-email-domains/disposable-email-domains/main/"
    "disposable_email_blocklist.conf"
)
SOURCE_LICENSE = "CC0 1.0 Universal (public domain dedication), per LICENSE.txt in the same repository"
MIN_DOMAINS = 1_000
UPDATE_AVAILABLE = 3
MAX_CHANGE_SHARE = 0.20
MAX_INVALID_SHARE = 0.01
NEVER_DISPOSABLE = frozenset(
    {
        "gmail.com",
        "googlemail.com",
        "outlook.com",
        "hotmail.com",
        "live.com",
        "yahoo.com",
        "icloud.com",
        "rediffmail.com",
    }
)


class RefreshError(RuntimeError):
    pass


def fetch(url: str) -> str:
    try:
        response = httpx.get(url, timeout=30.0, follow_redirects=True)
    except httpx.HTTPError as error:
        raise RefreshError(f"source unreachable: {type(error).__name__}") from error
    if response.status_code != 200:
        raise RefreshError(f"source answered HTTP {response.status_code}")
    return response.text


def normalize(raw: str) -> tuple[list[str], int]:
    candidates = {line.strip().lower() for line in raw.splitlines() if line.strip()}
    valid = sorted(domain for domain in candidates if DOMAIN_PATTERN.match(domain))
    return valid, len(candidates) - len(valid)


def check(domains: list[str], invalid: int, current: int, protected: frozenset[str], force: bool) -> None:
    if len(domains) < MIN_DOMAINS:
        raise RefreshError(f"only {len(domains)} domains, expected at least {MIN_DOMAINS}")
    if invalid > MAX_INVALID_SHARE * (len(domains) + invalid):
        raise RefreshError(f"{invalid} invalid lines in the source")
    clash = sorted(protected & set(domains))
    if clash:
        raise RefreshError(f"source lists domains that must never be blocked: {', '.join(clash)}")
    if current and not force and abs(len(domains) - current) > MAX_CHANGE_SHARE * current:
        raise RefreshError(f"size changed from {current} to {len(domains)}; rerun with --force after checking")


def write_atomically(path: Path, content: str) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(content, encoding="utf-8", newline="\n")
    os.replace(temporary, path)


def refresh(rules_dir: Path, url: str, force: bool) -> int:
    directory = rules_dir / EMAIL_RULES_DIR
    current_path = directory / DISPOSABLE_FILE
    current = (
        parse_domain_list(current_path.read_text(encoding="utf-8"), DISPOSABLE_FILE)
        if current_path.exists()
        else frozenset()
    )
    allow_path = directory / ALLOWLIST_EXTRA_FILE
    allowed = (
        parse_domain_list(allow_path.read_text(encoding="utf-8"), ALLOWLIST_EXTRA_FILE)
        if allow_path.exists()
        else frozenset()
    )
    domains, invalid = normalize(fetch(url))
    check(domains, invalid, len(current), NEVER_DISPOSABLE | allowed, force)
    content = "\n".join(domains) + "\n"
    if current_path.exists() and set(domains) == current:
        print(f"{len(domains)} domains, unchanged")
        return 0
    meta = {
        "source_url": url,
        "license": SOURCE_LICENSE,
        "fetched_on": datetime.now(UTC).date().isoformat(),
        "sha256": hashlib.sha256(content.encode("utf-8")).hexdigest(),
        "domains": len(domains),
        "invalid_lines_skipped": invalid,
    }
    directory.mkdir(parents=True, exist_ok=True)
    write_atomically(current_path, content)
    write_atomically(directory / SOURCE_FILE, yaml.safe_dump(meta, sort_keys=False))
    print(f"{len(domains)} domains (was {len(current)}), {invalid} invalid lines skipped")
    return 0


def compare(rules_dir: Path, url: str, summary: Path | None) -> int:
    directory = rules_dir / EMAIL_RULES_DIR
    current_text = (directory / DISPOSABLE_FILE).read_text(encoding="utf-8").replace("\r\n", "\n")
    current = parse_domain_list(current_text, DISPOSABLE_FILE)
    domains, invalid = normalize(fetch(url))
    content = "\n".join(domains) + "\n"
    current_sha = hashlib.sha256(current_text.encode("utf-8")).hexdigest()
    latest_sha = hashlib.sha256(content.encode("utf-8")).hexdigest()
    if latest_sha == current_sha:
        print(f"{len(domains)} domains, unchanged")
        return 0
    latest = set(domains)
    allow_path = directory / ALLOWLIST_EXTRA_FILE
    allowed = (
        parse_domain_list(allow_path.read_text(encoding="utf-8"), ALLOWLIST_EXTRA_FILE)
        if allow_path.exists()
        else frozenset()
    )
    try:
        check(domains, invalid, len(current), NEVER_DISPOSABLE | allowed, force=False)
        verdict = "passes the safety checks"
    except RefreshError as error:
        verdict = f"would be refused by the safety checks: {error}"
    lines = [
        f"Source: {url}",
        f"Checked: {datetime.now(UTC).date().isoformat()}",
        "",
        "| | Domains | sha256 |",
        "|---|---|---|",
        f"| In the repo | {len(current)} | `{current_sha}` |",
        f"| Latest | {len(domains)} | `{latest_sha}` |",
        "",
        f"Added: {len(latest - current)}, removed: {len(current - latest)}, invalid lines skipped: {invalid}.",
        f"The latest list {verdict}.",
        "",
        "To update: `cd backend; uv run python scripts/refresh_disposable_domains.py`, "
        "review the diff, run the tests, push.",
    ]
    text = "\n".join(lines) + "\n"
    if summary is not None:
        summary.write_text(text, encoding="utf-8")
    print(text)
    return UPDATE_AVAILABLE


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Refresh the disposable email domain list. Leaves files unchanged on error."
    )
    parser.add_argument("--rules-dir", type=Path, default=default_rules_dir())
    parser.add_argument("--url", default=SOURCE_URL)
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--check", action="store_true", help="only compare with the repo list; write nothing")
    parser.add_argument("--summary", type=Path, default=None, help="with --check: write a markdown summary here")
    args = parser.parse_args()
    try:
        if args.check:
            return compare(args.rules_dir, args.url, args.summary)
        return refresh(args.rules_dir, args.url, args.force)
    except RefreshError as error:
        print(f"REFRESH FAILED: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
