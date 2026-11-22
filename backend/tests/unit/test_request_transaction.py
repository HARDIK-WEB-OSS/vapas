from typing import get_args

from vapas.api.routes_statements import AllowedUser
from vapas.auth.deps import CurrentUserDep, current_user


def test_user_transaction_commits_before_the_response_is_sent() -> None:
    marker = get_args(CurrentUserDep)[1]
    assert marker.dependency is current_user
    assert marker.scope == "function"


def test_processing_gate_reuses_the_function_scoped_user() -> None:
    gate = get_args(AllowedUser)[1].dependency
    assert gate is not None
    assert get_args(gate.__annotations__["user"])[1] is get_args(CurrentUserDep)[1]
