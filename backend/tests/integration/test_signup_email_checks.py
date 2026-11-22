from typing import cast

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from vapas.config import Settings
from vapas.privacy.notices import CURRENT_NOTICE_VERSION
from vapas.security.email_domains import MxResult

from .conftest import PASSWORD, owner_sql

pytestmark = pytest.mark.integration


def with_mx(client: TestClient, result: MxResult) -> None:
    async def lookup(domain: str) -> MxResult:
        return result

    cast(FastAPI, client.app).state.services.auth._mx = lookup


def signup(client: TestClient, email: str) -> tuple[int, str | None]:
    body = {"email": email, "password": PASSWORD, "consent_notice_version": CURRENT_NOTICE_VERSION}
    response = client.post("/auth/signup", json=body)
    return response.status_code, response.json().get("error") if response.status_code != 202 else None


def test_disposable_email_is_refused(client: TestClient, live_settings: Settings) -> None:
    with_mx(client, MxResult.HAS_MX)
    assert signup(client, "temp@mailinator.com") == (400, "email_disposable")
    assert owner_sql(live_settings, "SELECT count(*) AS n FROM users")[0].n == 0


def test_domain_without_mail_server_is_refused(client: TestClient) -> None:
    with_mx(client, MxResult.NO_MX)
    assert signup(client, "asha@no-mail-here.in") == (400, "email_no_mail_server")


@pytest.mark.parametrize("email", ["asha@gmail.com", "asha.rao@iitb.ac.in"])
def test_gmail_and_college_domains_are_accepted(client: TestClient, email: str) -> None:
    with_mx(client, MxResult.HAS_MX)
    assert signup(client, email) == (202, None)


def test_dns_failure_lets_the_signup_through(client: TestClient) -> None:
    with_mx(client, MxResult.DNS_FAILED)
    assert signup(client, "asha@college.ac.in") == (202, None)
