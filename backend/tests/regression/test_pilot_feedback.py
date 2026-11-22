import pytest

from vapas.classify.channel_rules import classify
from vapas.detect.engine import detect
from vapas.detect.model import Finding, Txn, TxnKey, UserAnswers
from vapas.rules.loader import load_rulebook

from .cases import CASES, RegressionCase

RULES = load_rulebook()
LOOKBACK_MONTHS = 12


def transactions(case: RegressionCase) -> list[Txn]:
    out = []
    for index, row in enumerate(case.rows, start=1):
        label = classify(row.narration, row.direction)
        refs = frozenset({label.reference.encode()}) if label.reference else frozenset()
        out.append(
            Txn(
                key=TxnKey(index, row.on),
                statement_id=case.case_id,
                row_index=index,
                txn_date=row.on,
                value_date=row.on,
                direction=row.direction,
                amount_paise=row.amount_paise,
                balance_paise=None,
                channel=label.channel,
                kind=label.kind,
                narration=row.narration,
                references=refs,
            )
        )
    return out


def run(case: RegressionCase) -> list[Finding]:
    return detect(transactions(case), UserAnswers(), RULES, case.as_of, LOOKBACK_MONTHS, lambda name: f"g:{name}")


@pytest.mark.parametrize("case", CASES, ids=[c.case_id for c in CASES])
def test_pilot_feedback_pattern(case: RegressionCase) -> None:
    findings = run(case)
    forbidden = [f for f in findings if f.level in case.forbidden_levels]
    assert forbidden == [], f"{case.case_id}: {case.pattern}"
    for expected in case.expected:
        matching = [f for f in findings if (f.detector, f.level) == (expected.detector, expected.level)]
        assert len(matching) == 1, f"{case.case_id}: {case.pattern}: {findings}"
        assert matching[0].amount_owed_paise == expected.amount_owed_paise


def test_case_ids_are_unique() -> None:
    ids = [c.case_id for c in CASES]
    assert len(ids) == len(set(ids))
