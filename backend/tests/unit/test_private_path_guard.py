import os
from pathlib import Path

import pytest
from hypothesis import given
from hypothesis import strategies as st

from vapas.security.private_path_guard import (
    PrivatePathInsideRepoError,
    ensure_outside_code_root,
    find_code_root,
    is_inside,
)

safe_names = st.text(alphabet="abcdefghijklmnopqrstuvwxyz0123456789_-", min_size=1, max_size=12)


def test_code_root_is_the_git_repository(repo_root: Path) -> None:
    assert (repo_root / ".git").exists()
    assert (repo_root / "rules" / "schema.py").exists()


def test_repo_root_itself_is_rejected(repo_root: Path) -> None:
    with pytest.raises(PrivatePathInsideRepoError):
        ensure_outside_code_root(repo_root, repo_root)


def test_folder_inside_repo_is_rejected(repo_root: Path) -> None:
    with pytest.raises(PrivatePathInsideRepoError):
        ensure_outside_code_root(repo_root / "backend" / "tests" / "private", repo_root)


def test_default_root_detection_rejects_inside_repo(repo_root: Path) -> None:
    with pytest.raises(PrivatePathInsideRepoError):
        ensure_outside_code_root(repo_root / "statements")


def test_relative_path_resolves_against_cwd(repo_root: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(repo_root)
    with pytest.raises(PrivatePathInsideRepoError):
        ensure_outside_code_root(Path("private"), repo_root)


def test_parent_traversal_back_into_repo_is_rejected(repo_root: Path) -> None:
    sneaky = repo_root.parent / "elsewhere" / ".." / repo_root.name / "docs"
    with pytest.raises(PrivatePathInsideRepoError):
        ensure_outside_code_root(sneaky, repo_root)


def test_sibling_with_same_prefix_is_allowed(repo_root: Path) -> None:
    sibling = repo_root.parent / f"{repo_root.name}-private"
    assert ensure_outside_code_root(sibling, repo_root) == sibling.resolve()


def test_folder_outside_repo_is_allowed(tmp_path: Path, repo_root: Path) -> None:
    assert ensure_outside_code_root(tmp_path, repo_root) == tmp_path.resolve()


@pytest.mark.skipif(os.name != "nt", reason="case-insensitive paths only on Windows")
def test_different_case_inside_repo_is_rejected(repo_root: Path) -> None:
    with pytest.raises(PrivatePathInsideRepoError):
        ensure_outside_code_root(Path(str(repo_root).upper()) / "private", repo_root)


@given(parts=st.lists(safe_names, min_size=1, max_size=5))
def test_any_subpath_of_repo_is_inside(parts: list[str]) -> None:
    root = find_code_root(Path(__file__).parent)
    assert is_inside(root.joinpath(*parts), root)


def test_symlink_into_repo_is_rejected(tmp_path: Path, repo_root: Path) -> None:
    link = tmp_path / "looks_outside"
    try:
        link.symlink_to(repo_root / "docs", target_is_directory=True)
    except OSError:
        pytest.skip("creating symlinks needs Developer Mode or admin on Windows")
    with pytest.raises(PrivatePathInsideRepoError):
        ensure_outside_code_root(link, repo_root)
