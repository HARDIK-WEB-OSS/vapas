from datetime import date, timedelta
from typing import Any

import pytest
from fastapi.testclient import TestClient

from vapas.config import Settings
from vapas.ingest.model import FileKind
from vapas.jobs.context import WorkerContext
from vapas.jobs.detection import today_ist

from .conftest import bearer, confirm, drain, owner_sql, upload, verified_user
from .test_rls_isolation import attempt

pytestmark = pytest.mark.integration

HEADER = "Txn Date,Value Date,Description,Ref No./Cheque No.,Debit,Credit,Balance"


def statement_csv(
    rows: list[tuple[date, str, int, int]], opening: int = 5_000_000, skew_row: int | None = None
) -> bytes:
    balance = opening
    lines = ["State Bank of India", HEADER, f",,Opening Balance,,,,{opening / 100:.2f}"]
    for index, (day, text, debit, credit) in enumerate(sorted(rows, key=lambda r: r[0])):
        balance += credit - debit + (100 if index == skew_row else 0)
        stamp = day.strftime("%d/%m/%Y")
        lines.append(f"{stamp},{stamp},{text},,{debit / 100:.2f}" if debit else f"{stamp},{stamp},{text},,")
        lines[-1] += f",{credit / 100:.2f},{balance / 100:.2f}" if credit else f",,{balance / 100:.2f}"
    return ("\n".join(lines) + "\n").encode()


def findings(client: TestClient, token: str) -> list[dict[str, Any]]:
    response = client.get("/findings", headers=bearer(token))
    assert response.status_code == 200
    result: list[dict[str, Any]] = response.json()
    return result


def by_rule(items: list[dict[str, Any]], rule_id: str) -> dict[str, Any]:
    matching = [f for f in items if f["rule_id"] == rule_id]
    assert len(matching) == 1, items
    return matching[0]


def test_detection_after_upload_and_answering_a_question(
    client: TestClient, live_settings: Settings, worker: WorkerContext
) -> None:
    token = verified_user(client, "asha@example.in")
    start = today_ist() - timedelta(days=90)
    data = statement_csv(
        [
            (start, "ATM WDL/412345678901/PUNE", 200_000, 0),
            (start + timedelta(days=12), "REV ATM WDL 412345678901 PUNE", 0, 200_000),
            (start + timedelta(days=20), "UPI/DR/512345678901/SWIGGY/swiggy@okaxis", 45_000, 0),
            (start + timedelta(days=29), "UPI/REV/512345678901/SWIGGY", 0, 45_000),
            (start + timedelta(days=30), "NEFT CR-HDFC0001234-ACME-SALARY", 0, 5_000_000),
        ]
    )
    sid = upload(client, token, data, FileKind.CSV)["statement_id"]
    confirm(client, token, sid)
    drain(worker)

    first = findings(client, token)
    atm = by_rule(first, "rbi.tat.atm_cash_not_dispensed")
    assert (atm["level"], atm["delay_days"], atm["amount_owed_paise"], atm["confidence"]) == (
        "claim",
        7,
        70_000,
        "high",
    )
    upi = by_rule(first, "rbi.tat.upi_merchant")
    assert (upi["level"], upi["question"], upi["amount_owed_paise"]) == ("needs_user_input", "payee_was_merchant", None)

    detail = client.get(f"/findings/{atm['id']}", headers=bearer(token)).json()
    assert detail["snapshot"]["debit"]["narration"] == "ATM WDL/412345678901/PUNE"

    answer = client.post(f"/findings/{upi['id']}/answer", headers=bearer(token), json={"value": True})
    assert answer.status_code == 202
    drain(worker)
    after = findings(client, token)
    upi_after = by_rule(after, "rbi.tat.upi_merchant")
    assert (upi_after["id"], upi_after["level"], upi_after["amount_owed_paise"]) == (upi["id"], "claim", 40_000)
    assert len(after) == len(first)

    drain(worker)
    count = owner_sql(live_settings, "SELECT count(*) AS n FROM findings WHERE superseded_at IS NULL")
    assert count[0].n == len(after)
    events = owner_sql(live_settings, "SELECT props FROM analytics_events WHERE event_type = 'statement_analysed'")
    assert len(events) == 1
    props = events[0].props
    assert (props["bank_code"], props["rows"], props["questions_total"]) == ("SBI", 5, 1)
    assert props["questions_by_type"] == {"payee_was_merchant": 1}
    assert "asha" not in str(props)
    assert sid not in str(props)
    owner_sql(live_settings, "UPDATE jobs SET locked_by = NULL")


def test_unreconciled_statements_are_not_used_for_claims(
    client: TestClient, live_settings: Settings, worker: WorkerContext
) -> None:
    token = verified_user(client, "asha@example.in")
    start = today_ist() - timedelta(days=60)
    broken = statement_csv(
        [
            (start, "ATM WDL/412345678901/PUNE", 200_000, 0),
            (start + timedelta(days=15), "REV ATM WDL 412345678901 PUNE", 0, 200_000),
        ],
        skew_row=0,
    )
    sid = upload(client, token, broken, FileKind.CSV)["statement_id"]
    confirm(client, token, sid)
    drain(worker)
    statement = client.get(f"/statements/{sid}", headers=bearer(token)).json()
    assert statement["status"] == "needs_review"
    assert "did not add up" in statement["analysis_note"]
    assert findings(client, token) == []
    owner_sql(live_settings, "UPDATE jobs SET locked_by = NULL")


def test_database_refuses_amounts_on_reversal_only_findings(live_settings: Settings) -> None:
    owner_sql(
        live_settings,
        "INSERT INTO rule_versions (rules_sha256, policy_sha256, legal_content, policy_content) "
        "VALUES ('\\x01', '\\x02', '{}', '{}')",
    )
    user = owner_sql(
        live_settings,
        "INSERT INTO users (id, email, password_hash) VALUES (gen_random_uuid(), 'x@example.in', 'h') RETURNING id",
    )[0].id
    insert = (
        "INSERT INTO findings (id, user_id, finding_key, detector, level, confidence, rule_version_id, policy_version, "
        "detector_version, letter_scope, amount_owed_paise, why, snapshot_enc) VALUES (gen_random_uuid(), :u, '\\x03', "
        "'late_reversal', :level, 'high', (SELECT max(id) FROM rule_versions), 'p', 1, :scope, 100, 'w', '\\x00')"
    )
    with pytest.raises(Exception, match="check constraint"):
        owner_sql(live_settings, insert, {"u": user, "level": "claim", "scope": "reversal_only"})
    with pytest.raises(Exception, match="check constraint"):
        owner_sql(live_settings, insert, {"u": user, "level": "worth_checking", "scope": "claim"})


def test_app_role_can_change_status_but_not_the_finding(
    client: TestClient, live_settings: Settings, worker: WorkerContext
) -> None:
    token = verified_user(client, "asha@example.in")
    start = today_ist() - timedelta(days=60)
    data = statement_csv(
        [
            (start, "ATM WDL/412345678901/PUNE", 200_000, 0),
            (start + timedelta(days=15), "REV ATM 412345678901", 0, 200_000),
        ]
    )
    sid = upload(client, token, data, FileKind.CSV)["statement_id"]
    confirm(client, token, sid)
    drain(worker)
    finding = findings(client, token)[0]
    user_id = client.get("/account/me", headers=bearer(token)).json()["id"]
    assert "permission denied" in attempt(live_settings, user_id, "UPDATE findings SET amount_owed_paise = 999999")
    assert (
        client.post(
            f"/findings/{finding['id']}/status", headers=bearer(token), json={"status": "dismissed"}
        ).status_code
        == 200
    )
    assert findings(client, token)[0]["status"] == "dismissed"
    owner_sql(live_settings, "UPDATE jobs SET locked_by = NULL")
