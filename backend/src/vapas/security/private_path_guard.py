import os
from pathlib import Path

CODE_ROOT_MARKERS = (".git", "pyproject.toml")


class PrivatePathInsideRepoError(ValueError):
    pass


def find_code_root(start: Path) -> Path:
    candidates = [start.resolve(), *start.resolve().parents]
    for marker in CODE_ROOT_MARKERS:
        for folder in candidates:
            if (folder / marker).exists():
                return folder
    raise FileNotFoundError(f"no code root found above {start}")


def _normalized(path: Path) -> str:
    return os.path.normcase(str(path.resolve()))


def is_inside(path: Path, root: Path) -> bool:
    target = _normalized(path)
    base = _normalized(root)
    return target == base or target.startswith(base.rstrip(os.sep) + os.sep)


def ensure_outside_code_root(private_dir: Path, code_root: Path | None = None) -> Path:
    root = code_root if code_root is not None else find_code_root(Path(__file__).parent)
    if is_inside(private_dir, root):
        raise PrivatePathInsideRepoError(f"PRIVATE_FIXTURES_DIR must be outside the repository ({root})")
    return private_dir.resolve()
