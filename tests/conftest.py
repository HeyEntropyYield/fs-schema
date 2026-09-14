# pyright: reportUnusedFunction=false
from pathlib import Path

import pytest
import sh
from scripts import release

PROJECT_ROOT = Path(__file__).resolve().parents[1]
git_root = sh.git.bake(_tty_out=False, _cwd=str(PROJECT_ROOT))


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
