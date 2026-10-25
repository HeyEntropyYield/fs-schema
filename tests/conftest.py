# pyright: reportUnusedFunction=false
from pathlib import Path

import _pytest.scope as _pytest_scope
import pytest
import sh
from scripts import release

import fs_schema

setattr(_pytest_scope, "_ScopeName", str)  # noqa: B010  pytest-params 0.3.0, removed in pytest 9

PROJECT_ROOT = Path(__file__).resolve().parents[1]
git_root = sh.git.bake(_tty_out=False, _cwd=str(PROJECT_ROOT))


def refuse_foreign_install(installed: Path, this_src: Path) -> None:
    # Editable install lives in src/fs_schema. A wheel does not
    package = installed.parent
    if package.name == "fs_schema" and package.parent.name == "src" and package != this_src:
        raise pytest.UsageError(f"fs_schema loaded from {package}, this checkout is {this_src}")


refuse_foreign_install(Path(fs_schema.__file__).resolve(), PROJECT_ROOT / "src" / "fs_schema")


@pytest.fixture
def git_repo(tmp_path: Path) -> tuple[Path, object]:
    repo = tmp_path / "repo"
    repo.mkdir()
    git = sh.git.bake(_tty_out=False, _cwd=str(repo))
    git("init", "-q", "-b", "master")
    git("config", "user.name", "Test")
    git("config", "user.email", "test@example.invalid")
    return repo, git


@pytest.fixture(autouse=True)
def _isolate_release_paths(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Default release paths point at an empty tmp dir, never the checkout."""
    root = tmp_path / "isolated-project-root"
    root.mkdir()
    monkeypatch.setattr(release, "PROJECT_ROOT", root)
    monkeypatch.setattr(release, "PYPROJECT", root / "pyproject.toml")
    monkeypatch.setattr(release, "LOCKFILE", root / "uv.lock")
    (root / "pyproject.toml").write_text('[project]\nname = "isolated"\nversion = "0"\ndependencies = ["beartype"]\n')
    return root
