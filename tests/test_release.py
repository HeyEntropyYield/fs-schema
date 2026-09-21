# pyright: reportAny=false, reportArgumentType=false, reportUnknownArgumentType=false
# pyright: reportUnknownLambdaType=false, reportUnknownVariableType=false
# pyright: reportUnknownMemberType=false, reportUnknownParameterType=false
# pyright: reportExplicitAny=false
import io
import sys
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Any

import httpx
import pytest
from packaging.version import Version
from scripts.release import (
    SMOKE,
    ZERO_SHA,
    ReleaseError,
    changelog_notes,
    check_commit,
    check_range,
    check_ref,
    check_tag,
    check_version,
    check_version_metadata,
    fetch_published_versions,
    git,
    is_error,
    is_prerelease,
    main,
    parse_lock_version,
    parse_project_metadata,
    read_project_metadata,
    run_process,
    smoke_index,
    smoke_install,
)
from tests.conftest import git_root

Git = Any


def _error(match: str, fn: Callable[..., object], *args: object, **kwargs: object) -> None:
    with pytest.raises(ReleaseError, match=match):
        fn(*args, **kwargs)


def _write_version_files(path: Path, version: str) -> None:
    (path / "pyproject.toml").write_text(f'[project]\nname = "sample"\nversion = "{version}"\n')
    (path / "uv.lock").write_text(
        f'''version = 1
revision = 3
requires-python = ">=3.10"

[[package]]
name = "sample"
version = "{version}"
'''
    )


def _commit(git: Git, subject: str, *files: str) -> str:
    git("add", *files)
    git("-c", "user.name=Test", "-c", "user.email=test@example.invalid", "commit", "-m", subject)
    return str(git("rev-parse", "HEAD")).rstrip("\n")


@pytest.fixture
def release_repo(git_repo: tuple[Path, Git]) -> tuple[Path, Git]:
    repo, git_cmd = git_repo
    _write_version_files(repo, "1.0")
    _commit(git_cmd, "Initial package", "pyproject.toml", "uv.lock")
    return repo, git_cmd


def test_parse_project_metadata_rejects_invalid_toml() -> None:
    _error("src:", parse_project_metadata, "[[[", "src")


def test_parse_project_metadata_requires_project_table() -> None:
    _error("src:", parse_project_metadata, "name = 1\n", "src")


def test_parse_lock_version_requires_one_package() -> None:
    _error("lock:", parse_lock_version, "version = 1\n", "sample", "lock")
    _error("need 1", parse_lock_version, '[[package]]\nname = "other"\nversion = "1"\n', "sample", "lock")


def test_parse_project_and_lock_reject_invalid_versions() -> None:
    _error("src:", parse_project_metadata, '[project]\nname = "x"\nversion = "nope"\n', "src")
    _error("lock:", parse_lock_version, '[[package]]\nname = "sample"\nversion = "nope"\n', "sample", "lock")


def test_read_project_metadata_missing_file(tmp_path: Path) -> None:
    _error(f"{tmp_path / 'missing.toml'}:", read_project_metadata, tmp_path / "missing.toml")


def test_git_returns_error_outside_a_repo(tmp_path: Path) -> None:
    _error("git status", git, tmp_path, "status")


def test_run_process_returns_error_on_failure() -> None:
    _error("false", run_process, ("false",))


def test_run_process_includes_stderr() -> None:
    _error("nope-xyz", run_process, (sys.executable, "-c", "import sys; sys.stderr.write('nope-xyz'); sys.exit(1)"))


def test_version_metadata_requires_lockfile_agreement(release_repo: tuple[Path, Git]) -> None:
    repo, _ = release_repo
    (repo / "uv.lock").write_text('version = 1\n[[package]]\nname = "sample"\nversion = "1.1"\n')
    _error("!= lock", check_version_metadata, repo / "pyproject.toml", repo / "uv.lock")


def test_check_commit_requires_exact_subject_and_only_version_files(release_repo: tuple[Path, Git]) -> None:
    repo, git_cmd = release_repo
    _write_version_files(repo, "1.1rc1")
    (repo / "extra.txt").write_text("extra")
    git_cmd("add", "pyproject.toml", "uv.lock")

    _error(r"subject 'Release candidate' != 'v1\.1rc1'", check_commit, "Release candidate", root=repo)
    assert check_commit("v1.1rc1", root=repo) == Version("1.1rc1")

    git_cmd("add", "extra.txt")
    _error("stage", check_commit, "v1.1rc1", root=repo)


def test_check_commit_rejects_version_subject_without_bump(release_repo: tuple[Path, Git]) -> None:
    repo, _ = release_repo
    _error("no version bump", check_commit, "v1.0", root=repo)


def test_check_ref_and_tag_require_matching_version_commit(release_repo: tuple[Path, Git]) -> None:
    repo, git_cmd = release_repo
    _write_version_files(repo, "1.1")
    release_head = _commit(git_cmd, "v1.1", "pyproject.toml", "uv.lock")
    assert check_ref(root=repo, require_release=True) == Version("1.1")

    git_cmd("tag", "-a", "v1.1", "-m", "v1.1")
    assert check_tag("v1.1", root=repo) == Version("1.1")
    _error("tag", check_tag, "1.1", root=repo)

    (repo / "extra.txt").write_text("extra")
    _commit(git_cmd, "Post-release work", "extra.txt")
    _error("subject", check_tag, "v1.1", root=repo)
    assert check_tag("v1.1", ref=release_head, root=repo) == Version("1.1")


def test_check_range_validates_each_new_commit(release_repo: tuple[Path, Git], monkeypatch: pytest.MonkeyPatch) -> None:
    repo, git_cmd = release_repo
    base = str(git_cmd("rev-parse", "HEAD")).rstrip("\n")
    (repo / "first.txt").write_text("first")
    first = _commit(git_cmd, "First", "first.txt")
    (repo / "second.txt").write_text("second")
    second = _commit(git_cmd, "Second", "second.txt")
    checked: list[str] = []
    original = check_ref

    def check(ref: str, **_: object) -> Version:
        checked.append(ref)
        return original(ref, root=repo)

    monkeypatch.setattr("scripts.release.check_ref", check)
    from scripts import release as release_mod

    assert release_mod.check_range(base, second, root=repo) == (first, second)
    assert checked == [first, second]


def test_check_range_zero_sha_checks_head_only(release_repo: tuple[Path, Git]) -> None:
    repo, git_cmd = release_repo
    head = str(git_cmd("rev-parse", "HEAD")).rstrip("\n")
    assert check_range(ZERO_SHA, head, root=repo) == (head,)


def test_check_range_missing_base_checks_head_only(release_repo: tuple[Path, Git]) -> None:
    repo, git_cmd = release_repo
    head = str(git_cmd("rev-parse", "HEAD")).rstrip("\n")
    assert check_range("85ab4a6704d977cf134973f1d55dfb2a68c86180", head, root=repo) == (head,)


def test_check_range_unrelated_base_checks_head_only(release_repo: tuple[Path, Git]) -> None:
    repo, git_cmd = release_repo
    head = str(git_cmd("rev-parse", "HEAD")).rstrip("\n")
    orphan = str(git_cmd("commit-tree", f"{head}^{{tree}}", "-m", "orphan")).rstrip("\n")
    assert check_range(orphan, head, root=repo) == (head,)


def test_check_tag_requires_annotated_matching_annotation(release_repo: tuple[Path, Git]) -> None:
    repo, git_cmd = release_repo
    _write_version_files(repo, "1.1")
    _commit(git_cmd, "v1.1", "pyproject.toml", "uv.lock")

    git_cmd("tag", "v1.1")
    _error("not annotated", check_tag, "v1.1", root=repo)

    git_cmd("tag", "-d", "v1.1")
    git_cmd("tag", "-a", "v1.1", "-m", "wrong")
    _error("annotation", check_tag, "v1.1", root=repo)

    git_cmd("tag", "-d", "v1.1")
    message = repo / "tag-message.txt"
    message.write_text("v1.1\n\nextra body\n")
    git_cmd("tag", "-a", "v1.1", "-F", str(message))
    _error("annotation", check_tag, "v1.1", root=repo)


def test_check_tag_missing_local_tag(release_repo: tuple[Path, Git]) -> None:
    repo, git_cmd = release_repo
    _write_version_files(repo, "1.1")
    _commit(git_cmd, "v1.1", "pyproject.toml", "uv.lock")
    _error("no tag", check_tag, "v1.1", root=repo)


def test_check_ref_rejects_version_subject_without_bump(release_repo: tuple[Path, Git]) -> None:
    repo, git_cmd = release_repo
    (repo / "extra.txt").write_text("extra")
    _commit(git_cmd, "v1.0", "extra.txt")
    _error("no version bump", check_ref, root=repo)


def test_check_ref_allows_merge_of_existing_version_commit(release_repo: tuple[Path, Git]) -> None:
    repo, git_cmd = release_repo
    git_cmd("checkout", "-q", "-b", "release")
    _write_version_files(repo, "1.1")
    _commit(git_cmd, "v1.1", "pyproject.toml", "uv.lock")
    git_cmd("checkout", "-q", "master")
    (repo / "main.txt").write_text("main")
    _commit(git_cmd, "Main work", "main.txt")
    git_cmd(
        "-c",
        "user.name=Test",
        "-c",
        "user.email=test@example.invalid",
        "merge",
        "--no-ff",
        "release",
        "-m",
        "Merge release",
    )
    assert check_ref(root=repo) == Version("1.1")
    _error("subject", check_ref, root=repo, require_release=True)


def test_check_ref_rejects_misnamed_version_commit(release_repo: tuple[Path, Git]) -> None:
    repo, git_cmd = release_repo
    _write_version_files(repo, "1.1")
    _commit(git_cmd, "Forgot release subject", "pyproject.toml", "uv.lock")
    _error(r"subject 'Forgot release subject' != 'v1\.1'", check_ref, root=repo)


def test_check_ref_rejects_version_commit_with_extra_files(release_repo: tuple[Path, Git]) -> None:
    repo, git_cmd = release_repo
    _write_version_files(repo, "1.1")
    (repo / "extra.txt").write_text("extra")
    _commit(git_cmd, "v1.1", "pyproject.toml", "uv.lock", "extra.txt")
    _error("change", check_ref, root=repo)


def test_read_project_metadata_accepts_pep440_version(tmp_path: Path) -> None:
    pyproject = tmp_path / "pyproject.toml"
    pyproject.write_text('[project]\nname = "sample"\nversion = "1.0rc1"\n')
    assert read_project_metadata(pyproject) == ("sample", Version("1.0rc1"))


def _client(handler: object) -> httpx.Client:
    return httpx.Client(transport=httpx.MockTransport(handler))


def test_fetch_published_versions_builds_index_request() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200, json={"releases": {"0.9": [], "1.0rc1": [], "not-a-version": []}})

    with _client(handler) as client:
        assert fetch_published_versions("testpypi", "sample project", client=client) == (
            Version("0.9"),
            Version("1.0rc1"),
        )
    assert str(requests[0].url) == "https://test.pypi.org/pypi/sample%20project/json"


def test_fetch_published_versions_treats_not_found_as_available() -> None:
    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(404)

    with _client(handler) as client:
        assert fetch_published_versions("pypi", "sample", client=client) == ()


def test_fetch_published_versions_reports_http_and_network_failure() -> None:
    def http_fail(_: httpx.Request) -> httpx.Response:
        return httpx.Response(500)

    with _client(http_fail) as client:
        _error("HTTP 500", fetch_published_versions, "pypi", "sample", client=client)

    def offline(_: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("offline")

    with _client(offline) as client:
        _error("pypi:", fetch_published_versions, "pypi", "sample", client=client)


def test_fetch_published_versions_rejects_unknown_target_and_bad_payload() -> None:
    _error("target", fetch_published_versions, "other", "sample")

    def bad(_: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=["not-an-object"])

    with _client(bad) as client:
        _error("metadata", fetch_published_versions, "pypi", "sample", client=client)


def test_check_version_rejects_older_than_published(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("scripts.release.read_project_metadata", lambda _: ("sample", Version("1.0")))
    monkeypatch.setattr("scripts.release.fetch_published_versions", lambda *_: (Version("0.9"), Version("1.1")))
    _error("<", check_version, "pypi")


def test_check_version_allows_already_published(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("scripts.release.read_project_metadata", lambda _: ("sample", Version("1.0")))
    monkeypatch.setattr("scripts.release.fetch_published_versions", lambda *_: (Version("0.9"), Version("1.0")))
    assert check_version("pypi") == (Version("1.0"), (Version("0.9"), Version("1.0")))


def test_main_version_prints_metadata(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("scripts.release.check_version_metadata", lambda: Version("2.0"))
    stdout = io.StringIO()
    assert main(["version"], stdout=stdout) == 0
    assert stdout.getvalue() == "2.0\n"


def test_main_check_version_reports_available_package(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("scripts.release.check_version", lambda _: (Version("2.0"), (Version("1.0"),)))
    stdout = io.StringIO()
    assert main(["check-version", "pypi"], stdout=stdout) == 0
    assert stdout.getvalue() == "ok 2.0 unpublished pypi\n"


def test_main_check_version_reports_existing_package(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("scripts.release.check_version", lambda _: (Version("2.0"), (Version("2.0"),)))
    stdout = io.StringIO()
    assert main(["check-version", "pypi"], stdout=stdout) == 0
    assert stdout.getvalue() == "ok 2.0 exists pypi\n"


def test_changelog_notes_extracts_named_section(tmp_path: Path) -> None:
    path = tmp_path / "CHANGELOG.md"
    path.write_text("# Changelog\n\n## v2.0\n\n- new\n\n## v1.0\n\n- old\n")
    assert changelog_notes(version=Version("2.0"), changelog_path=path) == "## v2.0\n\n- new\n"
    assert changelog_notes(version=Version("1.0"), changelog_path=path) == "## v1.0\n\n- old\n"
    _error("missing", changelog_notes, version=Version("3.0"), changelog_path=path)


def test_is_prerelease_reads_metadata(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("scripts.release.read_project_metadata", lambda _: ("sample", Version("1.0rc1")))
    assert is_prerelease() is True
    monkeypatch.setattr("scripts.release.read_project_metadata", lambda _: ("sample", Version("1.0")))
    assert is_prerelease() is False


def test_main_notes_and_prerelease(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("scripts.release.changelog_notes", lambda: "## v1.0\n\n- x\n")
    stdout = io.StringIO()
    assert main(["notes"], stdout=stdout) == 0
    assert stdout.getvalue() == "## v1.0\n\n- x\n"
    monkeypatch.setattr("scripts.release.is_prerelease", lambda: True)
    stdout = io.StringIO()
    assert main(["is-prerelease"], stdout=stdout) == 0
    assert stdout.getvalue() == "yes\n"


def test_main_reports_release_error(monkeypatch: pytest.MonkeyPatch) -> None:
    def fail(_: str) -> tuple[Version, tuple[Version, ...]]:
        raise ReleaseError("already published")

    monkeypatch.setattr("scripts.release.check_version", fail)
    stderr = io.StringIO()
    assert main(["check-version", "pypi"], stderr=stderr) == 1
    assert stderr.getvalue() == "error: already published\n"


def test_main_check_ref_and_range(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("scripts.release.check_ref", lambda **_: Version("1.2"))
    monkeypatch.setattr("scripts.release.check_range", lambda *args: ("abc",))
    stdout = io.StringIO()
    assert main(["check-ref", "--release"], stdout=stdout) == 0
    assert "1.2" in stdout.getvalue()
    stdout = io.StringIO()
    assert main(["check-range", "base", "head"], stdout=stdout) == 0
    assert stdout.getvalue() == "ok 1 commits\n"


def test_main_smoke_and_index(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("scripts.release.smoke_install", lambda *args, **kwargs: "1.0")
    monkeypatch.setattr("scripts.release.smoke_index", lambda *_: "1.0")
    stdout = io.StringIO()
    assert main(["smoke", "pkg.whl", "--expected", "1.0"], stdout=stdout) == 0
    assert "1.0" in stdout.getvalue()
    stdout = io.StringIO()
    assert main(["smoke-index", "pypi"], stdout=stdout) == 0
    assert "pypi" in stdout.getvalue()


def test_smoke_install_uses_uv_run(tmp_path: Path) -> None:
    wheel = tmp_path / "fs_schema-1.0-py3-none-any.whl"
    wheel.write_bytes(b"")
    commands: list[Sequence[str]] = []

    def runner(command: Sequence[str]) -> str:
        commands.append(command)
        return "1.0"

    assert smoke_install(str(wheel), runner=runner) == "1.0"
    assert [list(command) for command in commands] == [
        [
            "uv",
            "run",
            "--isolated",
            "--no-project",
            "--no-config",
            "--prerelease",
            "allow",
            "--with",
            str(wheel.resolve()),
            "--",
            "python",
            str(SMOKE),
        ]
    ]


def test_smoke_install_expected_mismatch(tmp_path: Path) -> None:
    wheel = tmp_path / "pkg.whl"
    wheel.write_bytes(b"")
    _error("!=", smoke_install, str(wheel), expected="2.0", runner=lambda _: "1.0")


def test_smoke_index_installs_from_target(monkeypatch: pytest.MonkeyPatch) -> None:
    commands: list[Sequence[str]] = []

    def runner(command: Sequence[str]) -> str:
        commands.append(command)
        return "1.0"

    monkeypatch.setattr("scripts.release.read_project_metadata", lambda: ("fs-schema", Version("1.0")))
    assert smoke_index("testpypi", runner=runner) == "1.0"
    command = list(commands[0])
    assert command[:7] == ["uv", "run", "--isolated", "--no-project", "--no-config", "--prerelease", "allow"]
    assert "--index-strategy" in command and "unsafe-best-match" in command
    assert any("test.pypi.org" in part for part in command)
    assert "pypi.org/simple" in " ".join(command)


def test_smoke_index_pypi_uses_default_index_only(monkeypatch: pytest.MonkeyPatch) -> None:
    commands: list[Sequence[str]] = []

    def runner(command: Sequence[str]) -> str:
        commands.append(command)
        return "1.0"

    monkeypatch.setattr("scripts.release.read_project_metadata", lambda: ("fs-schema", Version("1.0")))
    assert smoke_index("pypi", runner=runner) == "1.0"
    command = list(commands[0])
    assert "--index-strategy" not in command
    assert all("test.pypi.org" not in part for part in command)
    assert "--with" in command and "fs-schema==1.0" in command


def test_error_is_falsy() -> None:
    assert is_error(ReleaseError("x"))
    assert not ReleaseError("x")
    assert not is_error("x")


def test_baked_checkout_git_is_read_only() -> None:
    head = str(git_root("rev-parse", "HEAD")).strip()
    assert len(head) >= 40
