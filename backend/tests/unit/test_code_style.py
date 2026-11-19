import ast
import io
import re
import subprocess
import tokenize
from collections.abc import Iterator
from pathlib import Path

import pytest

HASH_COMMENT_FILES = {"Dockerfile", ".gitignore", ".dockerignore", ".env.example", "alembic.ini", ".python-version"}
HASH_COMMENT_SUFFIXES = {".yaml", ".yml", ".toml", ".ini"}
SLASH_COMMENT_SUFFIXES = {".ts", ".tsx", ".js", ".mjs", ".cjs", ".css"}
SLASH_COMMENT_LINE = re.compile(r"^\s*(//|/\*|\*/|\{\s*/\*)")
HASH_COMMENT_LINE = re.compile(r"^\s*#")


def repo_files(root: Path) -> Iterator[Path]:
    listed = subprocess.run(
        ["git", "ls-files", "--cached", "--others", "--exclude-standard", "-z"],
        cwd=root,
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    for name in filter(None, listed.split(chr(0))):
        path = root / name
        if path.is_file():
            yield path


def python_comments(source: str) -> list[int]:
    tokens = tokenize.generate_tokens(io.StringIO(source).readline)
    return [token.start[0] for token in tokens if token.type == tokenize.COMMENT]


def python_docstrings(source: str) -> list[int]:
    tree = ast.parse(source)
    owners = [
        tree,
        *(n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef)),
    ]
    return [owner.body[0].lineno for owner in owners if ast.get_docstring(owner, clean=False) is not None]


def line_comments(source: str, pattern: re.Pattern[str]) -> list[int]:
    return [number for number, line in enumerate(source.splitlines(), 1) if pattern.match(line)]


def violations(path: Path) -> list[int]:
    if path.suffix == ".py":
        source = path.read_text(encoding="utf-8")
        return python_comments(source) + python_docstrings(source)
    if path.name in HASH_COMMENT_FILES or path.suffix in HASH_COMMENT_SUFFIXES:
        return line_comments(path.read_text(encoding="utf-8"), HASH_COMMENT_LINE)
    if path.suffix in SLASH_COMMENT_SUFFIXES:
        return line_comments(path.read_text(encoding="utf-8"), SLASH_COMMENT_LINE)
    return []


def test_no_comments_or_docstrings_anywhere(repo_root: Path) -> None:
    found = {str(p.relative_to(repo_root)): lines for p in repo_files(repo_root) if (lines := violations(p))}
    assert found == {}


@pytest.mark.parametrize(
    ("source", "expected"),
    [("x = 1  # note\n", [1]), ('def f():\n    """doc"""\n', [2]), ('x = "# not a comment"\n', [])],
)
def test_python_detection(source: str, expected: list[int]) -> None:
    assert python_comments(source) + python_docstrings(source) == expected
