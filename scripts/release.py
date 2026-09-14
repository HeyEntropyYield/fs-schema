#!/usr/bin/env python3
"""Release-maintenance checks for a uv pyproject package.

Usage:
  release.py version
  release.py check-ref [--release]
  release.py check-range <base> [<head>]
  release.py check-tag [<tag>] [--ref=REF]
  release.py check-version <target>
  release.py smoke <path_or_spec> [--expected=VERSION]
  release.py smoke-index <target>

Options:
  --release            Require a version-only release commit.
  --ref=REF            Commit ref to validate [default: HEAD].
  --expected=VERSION   Version the installed package must report.
"""

import re
import sys
from collections.abc import Callable, Sequence
from pathlib import Path
from urllib.parse import quote

import httpx
import sh
from docopt import docopt
from glom import GlomError, glom
from packaging.version import InvalidVersion, Version

from ._io import TextWriter, TomlObj, argv_tail

if sys.version_info >= (3, 11):
    from tomllib import loads as loads_toml
else:
    from tomli import loads as loads_toml

REPO = Path(__file__).resolve().parents[1]
PROJECT_ROOT = REPO
PYPROJECT = REPO / "pyproject.toml"
LOCKFILE = REPO / "uv.lock"
SMOKE = REPO / "examples" / "smoke.py"
VERSION_PATHS = {"pyproject.toml", "uv.lock"}
VERSION_SUBJECT = re.compile(r"^v\d")
ZERO_SHA = "0" * 40
INDEXES = {
    "pypi": ("https://pypi.org/pypi/{name}/json", "https://pypi.org/simple/"),
    "testpypi": ("https://test.pypi.org/pypi/{name}/json", "https://test.pypi.org/simple/"),
}

Runner = Callable[[Sequence[str]], str]


class ReleaseError(Exception):
    def __bool__(self) -> bool:
        return False


def is_error(value: object) -> bool:
    return isinstance(value, ReleaseError)


def _sh(*args: str, cwd: Path | None = None) -> str:
    try:
        return str(sh.Command(args[0])(*args[1:], _cwd=str(cwd) if cwd else None, _tty_out=False)).rstrip("\n")
    except sh.ErrorReturnCode as error:
        detail = error.stderr
        text = detail.decode("utf-8", "replace") if isinstance(detail, bytes) else str(detail)
        text = text.strip()
        command = " ".join(args)
        raise ReleaseError(f"{command}: {text}" if text else command) from None


def git(root: Path, *args: str) -> str:
    return _sh("git", *args, cwd=root)


def run_process(command: Sequence[str]) -> str:
    return _sh(*command)


def _toml(content: str) -> TomlObj:
    parsed = loads_toml(content)
    if not isinstance(parsed, dict):
        raise ReleaseError("not a table")
    return parsed


def _nv(data: TomlObj) -> tuple[str, Version]:
    return str(glom(data, "project.name")), Version(str(glom(data, "project.version")))


def _lock_ver(data: TomlObj, name: str) -> Version:
    found = [pkg["version"] for pkg in glom(data, "package") if pkg.get("name") == name]
    if len(found) != 1:
        raise ReleaseError(f"need 1 {name}")
    return Version(found[0])


def parse_project_metadata(content: str, source: str) -> tuple[str, Version]:
    try:
        return _nv(_toml(content))
    except Exception as error:
        raise ReleaseError(f"{source}: {error}") from error


def parse_lock_version(content: str, project_name: str, source: str) -> Version:
    try:
        return _lock_ver(_toml(content), project_name)
    except ReleaseError:
        raise
    except Exception as error:
        raise ReleaseError(f"{source}: {error}") from error


def read_project_metadata(path: Path = PYPROJECT) -> tuple[str, Version]:
    try:
        return parse_project_metadata(path.read_text(encoding="utf-8"), str(path))
    except OSError as error:
        raise ReleaseError(f"{path}: {error}") from error


def read_lock_version(path: Path = LOCKFILE, project_name: str | None = None) -> Version:
    name = project_name if project_name is not None else read_project_metadata()[0]
    try:
        return parse_lock_version(path.read_text(encoding="utf-8"), name, str(path))
    except OSError as error:
        raise ReleaseError(f"{path}: {error}") from error


def expected_subject(version: Version) -> str:
    return f"v{version}"


def check_version_metadata(metadata_path: Path = PYPROJECT, lock_path: Path = LOCKFILE) -> Version:
    data = _toml(metadata_path.read_text(encoding="utf-8"))
    name, version = _nv(data)
    locked = _lock_ver(_toml(lock_path.read_text(encoding="utf-8")), name)
    if locked != version:
        raise ReleaseError(f"{version} != lock {locked}")
    return version


def _require_version_commit(
    *,
    subject: str,
    version: Version,
    changed: set[str],
    version_changed: bool,
    require_release: bool,
    action: str,
) -> None:
    if not (version_changed or VERSION_SUBJECT.match(subject) or require_release):
        return
    wanted = expected_subject(version)
    if subject != wanted:
        raise ReleaseError(f"subject {subject!r} != {wanted!r}")
    if not version_changed:
        raise ReleaseError(f"{subject!r} no version bump")
    if changed != VERSION_PATHS:
        raise ReleaseError(f"{action} {', '.join(sorted(changed)) or 'no files'}")


def _metadata_at(ref: str, *, root: Path) -> tuple[str, Version]:
    return parse_project_metadata(git(root, "show", f"{ref}:pyproject.toml"), f"{ref}:pyproject.toml")


def _lock_at(ref: str, name: str, *, root: Path) -> Version:
    return parse_lock_version(git(root, "show", f"{ref}:uv.lock"), name, f"{ref}:uv.lock")


def check_commit(subject: str, *, root: Path = PROJECT_ROOT) -> Version:
    name, version = parse_project_metadata(git(root, "show", ":pyproject.toml"), ":pyproject.toml")
    locked = parse_lock_version(git(root, "show", ":uv.lock"), name, ":uv.lock")
    if locked != version:
        raise ReleaseError(f"{version} != lock {locked}")
    try:
        previous = _metadata_at("HEAD", root=root)[1]
    except ReleaseError:
        previous = None
    _require_version_commit(
        subject=subject,
        version=version,
        changed=set(git(root, "diff", "--cached", "--name-only").splitlines()),
        version_changed=previous != version,
        require_release=False,
        action="stage",
    )
    return version


def _parent_version_changed(ref: str, version: Version, *, root: Path) -> bool:
    parents = git(root, "show", "-s", "--format=%P", ref).split()
    return bool(parents) and all(_metadata_at(parent, root=root)[1] != version for parent in parents)


def check_ref(ref: str = "HEAD", *, require_release: bool = False, root: Path = PROJECT_ROOT) -> Version:
    name, version = _metadata_at(ref, root=root)
    locked = _lock_at(ref, name, root=root)
    if locked != version:
        raise ReleaseError(f"{version} != lock {locked}")
    _require_version_commit(
        subject=git(root, "show", "-s", "--format=%s", ref),
        version=version,
        changed=set(git(root, "diff-tree", "--no-commit-id", "--name-only", "-r", ref).splitlines()),
        version_changed=_parent_version_changed(ref, version, root=root),
        require_release=require_release,
        action="change",
    )
    return version


def check_range(base: str, head: str = "HEAD", *, root: Path = PROJECT_ROOT) -> tuple[str, ...]:
    if base != ZERO_SHA:
        try:
            git(root, "cat-file", "-e", f"{base}^{{commit}}")
            git(root, "merge-base", "--is-ancestor", base, head)
        except ReleaseError:
            base = ZERO_SHA
    refs = (head,) if base == ZERO_SHA else tuple(git(root, "rev-list", "--reverse", f"{base}..{head}").splitlines())
    for ref in refs:
        check_ref(ref, root=root)
    return refs


def check_tag(tag: str | None = None, *, ref: str = "HEAD", root: Path = PROJECT_ROOT) -> Version:
    version = check_ref(ref, require_release=True, root=root)
    wanted = expected_subject(version)
    candidate = tag or wanted
    if candidate != wanted:
        raise ReleaseError(f"tag {candidate!r} != {wanted!r}")
    try:
        target = git(root, "rev-parse", f"refs/tags/{candidate}^{{commit}}")
    except ReleaseError:
        raise ReleaseError(f"no tag {candidate}") from None
    if target != git(root, "rev-parse", f"{ref}^{{commit}}"):
        raise ReleaseError(f"{candidate} != {ref}")
    if git(root, "cat-file", "-t", f"refs/tags/{candidate}") != "tag":
        raise ReleaseError(f"{candidate} not annotated")
    if git(root, "for-each-ref", "--format=%(contents)", f"refs/tags/{candidate}") != candidate:
        raise ReleaseError(f"{candidate} annotation")
    return version


def _published(response: httpx.Response, target: str) -> tuple[Version, ...]:
    if response.status_code == 404:
        return ()
    if response.status_code >= 400:
        raise ReleaseError(f"HTTP {response.status_code}")
    try:
        versions: list[Version] = []
        for raw in glom(response.json(), "releases"):
            try:
                versions.append(Version(raw))
            except InvalidVersion:
                continue
        return tuple(sorted(versions))
    except (GlomError, ValueError) as error:
        raise ReleaseError(f"{target} metadata") from error


def _get(active: httpx.Client, url: str, target: str) -> httpx.Response:
    try:
        return active.get(url)
    except httpx.HTTPError as error:
        raise ReleaseError(f"{target}: {error}") from error


def fetch_published_versions(
    target: str,
    project_name: str,
    *,
    client: httpx.Client | None = None,
) -> tuple[Version, ...]:
    if target not in INDEXES:
        raise ReleaseError(f"target {target!r}")
    url = INDEXES[target][0].format(name=quote(project_name, safe=""))
    headers = {"Accept": "application/json", "User-Agent": f"{project_name}-release-check"}
    if client is not None:
        return _published(_get(client, url, target), target)
    with httpx.Client(timeout=10.0, headers=headers) as owned:
        return _published(_get(owned, url, target), target)


def check_version(target: str, *, metadata_path: Path = PYPROJECT) -> tuple[Version, tuple[Version, ...]]:
    project_name, current = read_project_metadata(metadata_path)
    published = fetch_published_versions(target, project_name)
    blocking = tuple(version for version in published if current < version)
    if blocking:
        raise ReleaseError(f"{current} < {', '.join(map(str, blocking))}")
    return current, published


def _smoke(run: Runner, *args: str) -> str:
    return run((
        "uv",
        "run",
        "--isolated",
        "--no-project",
        "--no-config",
        "--prerelease",
        "allow",
        *args,
        "--",
        "python",
        str(SMOKE),
    ))


def smoke_install(spec: str, *, expected: str | None = None, runner: Runner | None = None) -> str:
    candidate = Path(spec)
    installed = _smoke(runner or run_process, "--with", str(candidate.resolve()) if candidate.exists() else spec)
    if expected is not None and installed != expected:
        raise ReleaseError(f"{installed!r} != {expected!r}")
    return installed


def smoke_index(target: str, *, runner: Runner | None = None) -> str:
    if target not in INDEXES:
        raise ReleaseError(f"target {target!r}")
    name, version = read_project_metadata()
    extra: list[str] = ["--no-cache"]
    if target != "pypi":
        extra.extend((
            "--index-strategy",
            "unsafe-best-match",
            "--default-index",
            INDEXES["pypi"][1],
            "--index",
            INDEXES[target][1],
        ))
    extra.extend(("--with", f"{name}=={version}"))
    installed = _smoke(runner or run_process, *extra)
    if installed != str(version):
        raise ReleaseError(f"{installed!r} != {str(version)!r}")
    return installed


def _s(value: object, default: str = "") -> str:
    return default if value in (None, False) else f"{value}"


def dispatch(argv: Sequence[str] = sys.argv) -> str:
    raw = docopt(__doc__, argv=argv_tail(argv))
    match raw:
        case {"version": True}:
            return str(check_version_metadata())
        case {"check-ref": True, "--release": release}:
            return f"ok {check_ref(require_release=bool(release))}"
        case {"check-range": True, "<base>": base, "<head>": head}:
            return f"ok {len(check_range(_s(base), _s(head, 'HEAD')))} commits"
        case {"check-tag": True, "<tag>": tag, "--ref": ref}:
            checked = check_tag(_s(tag) or None, ref=_s(ref, "HEAD"))
            return f"ok v{checked} {_s(ref, 'HEAD')}"
        case {"check-version": True, "<target>": target}:
            version, published = check_version(_s(target))
            state = "exists" if version in published else "unpublished"
            return f"ok {version} {state} {_s(target)}"
        case {"smoke": True, "<path_or_spec>": spec, "--expected": expected}:
            return f"ok {smoke_install(_s(spec), expected=_s(expected) or None)}"
        case {"smoke-index": True, "<target>": target}:
            return f"ok {smoke_index(_s(target))} {_s(target)}"
        case _:
            raise ReleaseError("unhandled")


def main(
    argv: Sequence[str] = sys.argv,
    *,
    stdout: TextWriter = sys.stdout,
    stderr: TextWriter = sys.stderr,
) -> int:
    try:
        print(dispatch(argv), file=stdout)
    except Exception as error:
        print(f"error: {error}", file=stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
