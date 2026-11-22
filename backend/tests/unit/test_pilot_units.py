import pytest

from vapas.analytics.impact import Precision
from vapas.auth.invites import CODE_ALPHABET, invite_code_hash, new_invite_code, normalize_invite_code


def test_new_codes_are_grouped_and_unambiguous() -> None:
    code = new_invite_code()
    groups = code.split("-")
    assert [len(g) for g in groups] == [4, 4, 4, 4]
    assert set(code.replace("-", "")) <= set(CODE_ALPHABET)
    assert not set("01ILO") & set(CODE_ALPHABET)
    assert len({new_invite_code() for _ in range(200)}) == 200


@pytest.mark.parametrize("typed", ["abcd-efgh-jkmn-pqrs", " ABCD EFGH JKMN PQRS ", "abcdefghjkmnpqrs"])
def test_typing_variants_hash_the_same(typed: str) -> None:
    assert normalize_invite_code(typed) == "ABCDEFGHJKMNPQRS"
    assert invite_code_hash(typed) == invite_code_hash("ABCD-EFGH-JKMN-PQRS")


def test_precision_ignores_not_sure_and_reports_a_wilson_interval() -> None:
    precision = Precision(correct=19, wrong=1, not_sure=5)
    assert precision.value == pytest.approx(0.95)
    interval = precision.interval
    assert interval is not None
    assert interval[0] == pytest.approx(0.7639, abs=1e-3)
    assert interval[1] == pytest.approx(0.9911, abs=1e-3)


def test_precision_without_judgements_is_unknown() -> None:
    assert Precision(0, 0, 3).value is None
    assert Precision(0, 0, 3).interval is None
