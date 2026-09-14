# pyright: reportAny=false, reportUnknownVariableType=false, reportUnknownMemberType=false
# pyright: reportUnknownLambdaType=false, reportUnknownArgumentType=false
import io
import subprocess
from pathlib import Path

import pytest
from scripts.commit_msg import first_subject
from scripts.commit_msg import main as commit_msg_main
from scripts.pre_push import check_updates, parse_update
from scripts.pre_push import main as pre_push_main
from scripts.pyproject_mvp import PyprojectError, extract
from scripts.pyproject_mvp import main as mvp_main
from scripts.release import ZERO_SHA, ReleaseError

PROJECT_ROOT = Path(__file__).parents[1]


def test_first_subject_skips_comments_and_trailers() -> None:
    assert first_subject("# comment\n\nCo-authored-by: A <a@b>\nv1.2\nbody\n") == "v1.2"
    assert first_subject("# only comments\n") == ""


def test_commit_msg_enforces_release_provenance(tmp_path: Path) -> None:
    message = tmp_path / "COMMIT_EDITMSG"
    message.write_text("v1.2\n\nbody\n")
    checked: list[str] = []
    assert commit_msg_main([str(message)], checker=checked.append) == 0
    assert checked == ["v1.2"]
    assert message.read_text() == "v1.2\n"


def test_commit_msg_reports_empty_non_ascii_and_checker_error(tmp_path: Path) -> None:
    message = tmp_path / "COMMIT_EDITMSG"
    stderr = io.StringIO()
    message.write_text("# empty\n")
    assert commit_msg_main([str(message)], stderr=stderr) == 1
    assert "empty commit subject" in stderr.getvalue()

    message.write_text("café\n")
    stderr = io.StringIO()
    assert commit_msg_main([str(message)], stderr=stderr) == 1
    assert "must be ASCII" in stderr.getvalue()

    message.write_text("v1.2\n")
    stderr = io.StringIO()
    assert commit_msg_main([str(message)], stderr=stderr, checker=lambda _: ReleaseError("bad version commit")) == 1
    assert stderr.getvalue() == "error: bad version commit\n"


def test_parse_update_requires_four_fields() -> None:
    with pytest.raises(ReleaseError, match="want 4 fields"):
        parse_update("a b c")
    update = parse_update("refs/heads/master 1 refs/heads/master 0")
    assert update.local_ref == "refs/heads/master"


def test_pre_push_checks_branch_commits_and_tags() -> None:
    branch_sha = "1" * 40
    tag_sha = "2" * 40
    stdin = (
        f"refs/heads/master {branch_sha} refs/heads/master {ZERO_SHA}\n"
        f"refs/tags/v1.2 {tag_sha} refs/tags/v1.2 {ZERO_SHA}\n"
        f"refs/tags/deleted {ZERO_SHA} refs/tags/deleted {tag_sha}\n"
        "\n"
    )
    commits: list[str] = []
    tags: list[tuple[str, str]] = []
    assert (
        pre_push_main(
            [],
            stdin=iter(stdin.splitlines(keepends=True)),
            range_checker=lambda base, head: commits.extend([base, head]),
            tag_checker=lambda tag, *, ref: tags.append((tag, ref)),
        )
        == 0
    )
    assert commits == [ZERO_SHA, branch_sha]
    assert tags == [("v1.2", "refs/tags/v1.2^{commit}")]


def test_pre_push_reports_invalid_tag() -> None:
    tag_sha = "2" * 40
    stderr = io.StringIO()

    def fail_tag(_tag: str, *, ref: str) -> None:
        raise ReleaseError(f"invalid {ref}")

    assert (
        pre_push_main(
            [],
            stdin=iter([f"refs/tags/wrong {tag_sha} refs/tags/wrong {ZERO_SHA}\n"]),
            stderr=stderr,
            range_checker=lambda *_: None,
            tag_checker=fail_tag,
        )
        == 1
    )
    assert "invalid refs/tags/wrong^{commit}" in stderr.getvalue()


def test_check_updates_rejects_malformed_line() -> None:
    with pytest.raises(ReleaseError, match="want 4 fields"):
        check_updates(
            ["only-three fields here"],
            range_checker=lambda *_: None,
            tag_checker=lambda *_args, **_kwargs: None,
        )


def test_pyproject_mvp_extracts_dependency_tables() -> None:
    reduced = extract({
        "project": {
            "name": "fs-schema",
            "version": "1.0",
            "requires-python": ">=3.10",
            "dependencies": ["beartype"],
            "readme": "README.md",
        },
        "dependency-groups": {"dev": ["pytest"]},
        "build-system": {"requires": ["uv_build"]},
        "tool": {"uv": {"required-version": ">=0.11"}, "ruff": {"line-length": 120}},
    })
    assert reduced == {
        "project": {
            "name": "fs-schema",
            "version": "1.0",
            "requires-python": ">=3.10",
            "dependencies": ["beartype"],
        },
        "dependency-groups": {"dev": ["pytest"]},
        "build-system": {"requires": ["uv_build"]},
        "tool": {"uv": {"required-version": ">=0.11"}},
    }


def test_pyproject_mvp_main_roundtrip(tmp_path: Path) -> None:
    source = tmp_path / "pyproject.toml"
    source.write_text(
        "\n".join([
            "[project]",
            'name = "x"',
            'version = "1"',
            'requires-python = ">=3.10"',
            "dependencies = []",
            'readme = "README.md"',
            "[tool.uv]",
            'required-version = ">=0.11"',
            "[tool.ruff]",
            "line-length = 80",
            "",
        ])
    )
    stdout = io.StringIO()
    assert mvp_main(["-i", str(source), "-o", "-"], stdout=stdout) == 0
    text = stdout.getvalue()
    assert 'name = "x"' in text
    assert "readme" not in text
    assert "[tool.ruff]" not in text
    assert "[tool.uv]" in text


def test_pyproject_mvp_rejects_bad_toml() -> None:
    stderr = io.StringIO()
    assert mvp_main(["-i", "-", "-o", "-"], stdin=io.StringIO("[[["), stdout=io.StringIO(), stderr=stderr) == 1
    assert stderr.getvalue().startswith("error:")
    assert not PyprojectError("x")


def test_beartype_launcher_runs_pyproject_mvp(tmp_path: Path) -> None:
    source = tmp_path / "in.toml"
    source.write_text('[project]\nname = "x"\nversion = "1"\n')
    result = subprocess.run(
        [
            str(PROJECT_ROOT / "scripts" / "beartype"),
            str(PROJECT_ROOT / "scripts" / "pyproject_mvp.py"),
            "-i",
            str(source),
            "-o",
            "-",
        ],
        cwd=PROJECT_ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    assert 'name = "x"' in result.stdout
    assert result.returncode == 0


def test_commit_msg_missing_file(tmp_path: Path) -> None:
    stderr = io.StringIO()
    assert commit_msg_main([str(tmp_path / "missing")], stderr=stderr) == 1
    assert stderr.getvalue().startswith("error:")
