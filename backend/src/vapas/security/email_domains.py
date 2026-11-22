import hashlib
import logging
import re
from collections.abc import Iterable
from dataclasses import dataclass
from enum import StrEnum
from functools import lru_cache
from pathlib import Path
from typing import Protocol

import dns.asyncresolver
import dns.exception
import dns.resolver
import yaml

log = logging.getLogger(__name__)

EMAIL_RULES_DIR = "email"
DISPOSABLE_FILE = "disposable_domains.txt"
SOURCE_FILE = "disposable_source.yaml"
BLOCKLIST_EXTRA_FILE = "blocklist_extra.txt"
ALLOWLIST_EXTRA_FILE = "allowlist_extra.txt"
MX_TIMEOUT_SECONDS = 2.0
CRLF = chr(13) + chr(10)
LF = chr(10)
DOMAIN_PATTERN = re.compile(r"^(?=.{1,253}$)(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z][a-z0-9-]{0,61}[a-z0-9]$")


class DomainListError(ValueError):
    pass


class Verdict(StrEnum):
    ALLOWED = "allowed"
    DISPOSABLE = "disposable"
    NO_MAIL_SERVER = "no_mail_server"


class MxResult(StrEnum):
    HAS_MX = "has_mx"
    NO_MX = "no_mx"
    DNS_FAILED = "dns_failed"


class MxLookup(Protocol):
    async def __call__(self, domain: str) -> MxResult: ...


def parse_domain_list(text: str, name: str) -> frozenset[str]:
    domains: set[str] = set()
    for number, raw in enumerate(text.splitlines(), start=1):
        if raw == "":
            continue
        if raw != raw.strip() or not DOMAIN_PATTERN.match(raw):
            raise DomainListError(f"{name} line {number}: not a lowercase domain name")
        if raw in domains:
            raise DomainListError(f"{name} line {number}: duplicate domain")
        domains.add(raw)
    return frozenset(domains)


def domain_of(email: str) -> str:
    domain = email.rsplit("@", 1)[-1].strip().rstrip(".").lower()
    return domain.encode("idna").decode("ascii")


def _suffixes(domain: str) -> Iterable[str]:
    parts = domain.split(".")
    return (".".join(parts[index:]) for index in range(len(parts) - 1))


@dataclass(frozen=True)
class DomainPolicy:
    blocked: frozenset[str]
    allowed: frozenset[str]

    def is_allowlisted(self, domain: str) -> bool:
        return any(suffix in self.allowed for suffix in _suffixes(domain))

    def is_disposable(self, domain: str) -> bool:
        if self.is_allowlisted(domain):
            return False
        return any(suffix in self.blocked for suffix in _suffixes(domain))


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8") if path.exists() else ""


def check_source(directory: Path, listed: str) -> None:
    meta = yaml.safe_load(_read(directory / SOURCE_FILE)) or {}
    expected = meta.get("sha256")
    normalized = listed.replace(CRLF, LF)
    if expected != hashlib.sha256(normalized.encode("utf-8")).hexdigest():
        raise DomainListError(f"{DISPOSABLE_FILE} does not match the sha256 in {SOURCE_FILE}")


@lru_cache(maxsize=4)
def load_domain_policy(rules_dir: Path) -> DomainPolicy:
    directory = rules_dir / EMAIL_RULES_DIR
    listed = _read(directory / DISPOSABLE_FILE)
    check_source(directory, listed)
    blocked = parse_domain_list(listed, DISPOSABLE_FILE)
    extra = parse_domain_list(_read(directory / BLOCKLIST_EXTRA_FILE), BLOCKLIST_EXTRA_FILE)
    allowed = parse_domain_list(_read(directory / ALLOWLIST_EXTRA_FILE), ALLOWLIST_EXTRA_FILE)
    return DomainPolicy(blocked | extra, allowed)


async def lookup_mx(domain: str) -> MxResult:
    resolver = dns.asyncresolver.Resolver()
    resolver.lifetime = MX_TIMEOUT_SECONDS
    resolver.timeout = MX_TIMEOUT_SECONDS
    try:
        answer = await resolver.resolve(domain, "MX")
    except (dns.resolver.NXDOMAIN, dns.resolver.NoAnswer):
        return MxResult.NO_MX
    except dns.exception.DNSException as error:
        log.warning("mx lookup failed, allowing signup", extra={"error_type": type(error).__name__})
        return MxResult.DNS_FAILED
    exchanges = {str(record.exchange).rstrip(".") for record in answer}
    return MxResult.NO_MX if exchanges <= {""} else MxResult.HAS_MX


async def email_verdict(email: str, policy: DomainPolicy, mx: MxLookup | None) -> Verdict:
    domain = domain_of(email)
    if policy.is_allowlisted(domain):
        return Verdict.ALLOWED
    if policy.is_disposable(domain):
        return Verdict.DISPOSABLE
    if mx is not None and await mx(domain) is MxResult.NO_MX:
        return Verdict.NO_MAIL_SERVER
    return Verdict.ALLOWED
