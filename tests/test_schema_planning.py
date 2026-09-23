# pyright: reportPrivateUsage=false, reportUnknownMemberType=false, reportUnknownArgumentType=false
# pyright: reportUnknownVariableType=false, reportAttributeAccessIssue=false, reportCallIssue=false
# pyright: reportIndexIssue=false, reportAssignmentType=false, reportArgumentType=false
from pathlib import Path

import pytest
from beartype import beartype
from beartype.roar import BeartypeCallHintParamViolation

from fs_schema import FILES, Dir, File, Layout, Match, MismatchErr, Schema, SchemaRoot
from fs_schema._schema import FixedDir, FixedFile, Matches, Template


def _decode_number(path: Path) -> int:
    return int(path.stem.rsplit("-", 1)[-1])


_DEEP_LAYOUT: Layout = {
    Dir(fmt="batch-{batch:d}", alias="batches"): {
        FILES: [File(fmt="part-{part:d}.bin", alias="parts", schema=_decode_number)],
    }
}


class _PlannedRoot(Schema):
    schema = {
        FILES: [
            File(fmt="loose-{number:d}.dat", alias="loose", schema=_decode_number),
            File(match=r"regex-.+", alias="regex_only", min=0),
            File(fmt="{name}", alias="unsafe", min=0),
            File(fmt="{}-{:d}", alias="positional", min=0),
        ],
        "fixed dir": {"child": {"deep": _DEEP_LAYOUT}},
        Dir(fmt="run-{run:d}", match=r"run-[1-9][0-9]*", alias="runs"): {"child": {"deep": _DEEP_LAYOUT}},
    }


class _OtherRoot(Schema):
    schema = {"value": "value.txt"}


class _TransitionRoot(Schema):
    schema = {"value": "value.txt"}


@beartype
def _accepts_planned_root(value: "_PlannedRoot.RootT") -> None:
    assert type(value) is _PlannedRoot.RootT


def _forbid_filesystem(monkeypatch: pytest.MonkeyPatch) -> None:
    def fail(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("planned navigation performed filesystem I/O")

    for name in (
        "exists",
        "is_dir",
        "is_file",
        "iterdir",
        "mkdir",
        "open",
        "read_bytes",
        "read_text",
        "stat",
        "write_bytes",
        "write_text",
    ):
        monkeypatch.setattr(Path, name, fail)


def test_relative_to_has_stable_exact_root_type_and_supports_forward_beartype() -> None:
    first = _PlannedRoot.relative_to("missing")
    second = _PlannedRoot.relative_to("elsewhere")
    other = _OtherRoot.relative_to("missing")

    assert _PlannedRoot.RootT is _PlannedRoot.RootT
    assert _PlannedRoot.RootT is not _OtherRoot.RootT
    with pytest.raises(AttributeError, match="RootT"):
        _ = type(_PlannedRoot).RootT.__get__(SchemaRoot, type(SchemaRoot))
    assert type(first) is type(second) is _PlannedRoot.RootT
    assert type(other) is _OtherRoot.RootT
    assert issubclass(_PlannedRoot.RootT, SchemaRoot)
    assert isinstance(first, (_PlannedRoot.RootT, SchemaRoot))
    _accepts_planned_root(first)
    with pytest.raises(BeartypeCallHintParamViolation):
        _accepts_planned_root(other)


def test_planned_tree_is_canonical_path_bearing_and_only_root_can_bind(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = tmp_path / "absent" / "root"
    _forbid_filesystem(monkeypatch)

    plan = _PlannedRoot.relative_to(root)
    fixed = plan.fixed_dir
    child = fixed.child
    deep = child.deep

    assert plan.path == root and plan.defn is _PlannedRoot._schema_defn
    assert plan[4] is fixed and plan["fixed dir"] is fixed
    assert fixed.path == root / "fixed dir"
    assert fixed.defn is _PlannedRoot._schema_defn.defns[4]
    assert fixed[0] is child and fixed["child"] is child
    assert child[0] is deep and child["deep"] is deep
    assert all(isinstance(node.path, Path) for node in (plan, *plan, fixed, child, deep, deep.batches))

    assert isinstance(plan, SchemaRoot) and hasattr(plan, "bind")
    for descendant in (plan.loose, plan.regex_only, fixed, child, deep, deep.batches):
        assert not isinstance(descendant, SchemaRoot)
        assert not hasattr(descendant, "bind")
    assert not hasattr(fixed, "root")


def test_planned_collections_are_empty_until_format_or_bind() -> None:
    plan = _PlannedRoot.relative_to("missing")

    for collection in (plan.loose, plan.runs, plan.regex_only):
        assert isinstance(collection, Matches)
        assert len(collection) == 0 and tuple(collection) == ()
        with pytest.raises(IndexError):
            _ = collection[0]
    assert isinstance(plan.loose, Template) and len(plan.loose[:]) == 0
    assert isinstance(plan.runs, Template)
    assert isinstance(plan.regex_only, Matches) and not isinstance(plan.regex_only, Template)
    assert not hasattr(plan.regex_only, "format")


def test_formatting_files_and_nested_directories_is_recursive_planning_without_io(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = tmp_path / "does-not-exist"
    _forbid_filesystem(monkeypatch)
    plan = _PlannedRoot.relative_to(root)

    run = plan.runs.format(run=12)
    batch = run.child.deep.batches.format(batch=3)
    part = batch.parts.format(part=7)
    loose = plan.loose.format(number=9)

    assert isinstance(run, FixedDir) and run.path == root / "run-12"
    assert run.child.deep.path == root / "run-12" / "child" / "deep"
    assert isinstance(batch, FixedDir) and batch.path == root / "run-12" / "child" / "deep" / "batch-3"
    assert isinstance(part, FixedFile) and part.path == batch.path / "part-7.bin"
    assert isinstance(loose, FixedFile) and loose.path == root / "loose-9.dat"
    assert part.defn.schema is _decode_number and loose.defn.schema is _decode_number
    assert all(hasattr(part, name) for name in ("read_bytes", "read_text", "load", "put"))

    for concrete in (run, batch, part, loose):
        assert not isinstance(concrete, Match)
        assert not hasattr(concrete, "args") and not hasattr(concrete, "kwargs")
        assert not hasattr(concrete, "bind")


def test_formatting_uses_native_errors_then_regex_and_safe_basename_validation() -> None:
    plan = _PlannedRoot.relative_to("missing")

    with pytest.raises(KeyError):
        plan.loose.format()
    with pytest.raises(ValueError):
        plan.loose.format(number="not-an-int")
    with pytest.raises(IndexError):
        plan.positional.format("name")
    with pytest.raises(ValueError):
        plan.positional.format("name", "not-an-int")
    with pytest.raises(ValueError, match="does not match"):
        plan.runs.format(run=0)

    for unsafe in ("", ".", "..", "../name", "dir/name", r"dir\name", "nul\0name"):
        with pytest.raises(ValueError, match="must be a basename"):
            plan.unsafe.format(name=unsafe)


def test_plan_bind_and_bound_root_are_fresh_exact_top_level_transitions(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = tmp_path / "root"
    plan = _TransitionRoot.relative_to(root)
    assert type(plan) is _TransitionRoot.RootT

    root.mkdir()
    (root / "value.txt").write_text("value")
    first = plan.bind()
    assert type(first) is _TransitionRoot

    (root / "value.txt").unlink()
    assert isinstance(plan.bind(), MismatchErr)

    (root / "value.txt").write_text("again")
    second = plan.bind()
    assert type(second) is _TransitionRoot and second is not first

    _forbid_filesystem(monkeypatch)
    reopened = second.root()
    assert type(reopened) is _TransitionRoot.RootT
    assert reopened.path == second.path


def test_root_plan_accepts_pathlike_without_touching_it(monkeypatch: pytest.MonkeyPatch) -> None:
    class PathToken:
        def __fspath__(self) -> str:
            return "still-missing"

    _forbid_filesystem(monkeypatch)
    assert _TransitionRoot.relative_to(PathToken()).path == Path("still-missing")
