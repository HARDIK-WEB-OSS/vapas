import asyncio
import shutil
from pathlib import Path
from typing import Any

import dns.resolver
import pytest

from vapas.rules.loader import default_rules_dir
from vapas.security.email_domains import (
    DomainListError,
    MxResult,
    Verdict,
    email_verdict,
    load_domain_policy,
    lookup_mx,
    parse_domain_list,
)


def fake_mx(result: MxResult) -> Any:
    async def lookup(domain: str) -> MxResult:
        return result

    return lookup


@pytest.fixture
def rules(tmp_path: Path) -> Path:
    shutil.copytree(default_rules_dir() / "email", tmp_path / "email")
    load_domain_policy.cache_clear()
    return tmp_path


def verdict(email: str, rules_dir: Path, mx: MxResult | None = MxResult.HAS_MX) -> Verdict:
    policy = load_domain_policy(rules_dir)
    return asyncio.run(email_verdict(email, policy, fake_mx(mx) if mx else None))


@pytest.mark.parametrize("email", ["temp@mailinator.com", "x@YOPMAIL.com", "a@inbox.mailinator.com"])
def test_disposable_domains_are_blocked(rules: Path, email: str) -> None:
    assert verdict(email, rules) is Verdict.DISPOSABLE


def test_domain_without_mail_server_is_blocked(rules: Path) -> None:
    assert verdict("asha@no-mail-here.in", rules, MxResult.NO_MX) is Verdict.NO_MAIL_SERVER


@pytest.mark.parametrize("email", ["asha@gmail.com", "asha.rao@iitb.ac.in", "ravi@mycompany.co.in", "me@asha.dev"])
def test_real_providers_college_company_and_custom_domains_are_allowed(rules: Path, email: str) -> None:
    assert verdict(email, rules) is Verdict.ALLOWED


def test_dns_failure_allows_the_signup(rules: Path) -> None:
    assert verdict("asha@college.ac.in", rules, MxResult.DNS_FAILED) is Verdict.ALLOWED


def test_mx_check_can_be_skipped_for_tests(rules: Path) -> None:
    assert verdict("asha@example.in", rules, None) is Verdict.ALLOWED


def test_blocklist_extra_adds_domains(rules: Path) -> None:
    (rules / "email" / "blocklist_extra.txt").write_text("fakeuni.edu.in\n", encoding="utf-8")
    assert verdict("x@fakeuni.edu.in", rules) is Verdict.DISPOSABLE


def test_allowlist_extra_beats_the_blocklist_and_the_mx_check(rules: Path) -> None:
    (rules / "email" / "blocklist_extra.txt").write_text("college.ac.in\n", encoding="utf-8")
    (rules / "email" / "allowlist_extra.txt").write_text("college.ac.in\nmailinator.com\n", encoding="utf-8")
    assert verdict("a@college.ac.in", rules) is Verdict.ALLOWED
    assert verdict("a@mailinator.com", rules) is Verdict.ALLOWED
    assert verdict("a@dept.college.ac.in", rules, MxResult.NO_MX) is Verdict.ALLOWED


@pytest.mark.parametrize(
    ("content", "problem"),
    [
        ("College.ac.in\n", "line 1"),
        ("good.in\nbad domain.in\n", "line 2"),
        ("good.in\n# comment\n", "line 2"),
        ("good.in\ngood.in\n", "duplicate"),
        (" good.in\n", "line 1"),
        ("localhost\n", "line 1"),
    ],
)
def test_override_files_are_validated_on_load(rules: Path, content: str, problem: str) -> None:
    (rules / "email" / "allowlist_extra.txt").write_text(content, encoding="utf-8")
    with pytest.raises(DomainListError, match=problem):
        load_domain_policy(rules)


def test_tampered_list_is_refused(rules: Path) -> None:
    listed = rules / "email" / "disposable_domains.txt"
    listed.write_text(listed.read_text(encoding="utf-8") + "gmail.com\n", encoding="utf-8")
    with pytest.raises(DomainListError, match="sha256"):
        load_domain_policy(rules)


def test_windows_line_endings_still_match_the_hash(rules: Path) -> None:
    listed = rules / "email" / "disposable_domains.txt"
    listed.write_bytes(listed.read_bytes().replace(b"\n", b"\r\n"))
    assert "mailinator.com" in load_domain_policy(rules).blocked


def test_empty_override_files_are_fine() -> None:
    assert parse_domain_list("", "allowlist_extra.txt") == frozenset()


DNS: Any = dns.resolver


class FakeResolver:
    outcome: Any = None

    def __init__(self) -> None:
        self.lifetime = 0.0
        self.timeout = 0.0

    async def resolve(self, domain: str, kind: str) -> Any:
        assert (kind, self.lifetime) == ("MX", 2.0)
        if isinstance(FakeResolver.outcome, Exception):
            raise FakeResolver.outcome
        return FakeResolver.outcome


class Record:
    def __init__(self, exchange: str) -> None:
        self.exchange = exchange


@pytest.mark.parametrize(
    ("outcome", "expected"),
    [
        ([Record("gmail-smtp-in.l.google.com.")], MxResult.HAS_MX),
        ([Record(".")], MxResult.NO_MX),
        (DNS.NXDOMAIN(), MxResult.NO_MX),
        (DNS.NoAnswer(), MxResult.NO_MX),
        (DNS.LifetimeTimeout(timeout=2.0, errors=[]), MxResult.DNS_FAILED),
        (DNS.NoNameservers(), MxResult.DNS_FAILED),
    ],
)
def test_mx_lookup_outcomes(monkeypatch: pytest.MonkeyPatch, outcome: Any, expected: MxResult) -> None:
    FakeResolver.outcome = outcome
    monkeypatch.setattr("dns.asyncresolver.Resolver", FakeResolver)
    assert asyncio.run(lookup_mx("example.in")) is expected
