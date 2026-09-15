# pyright: reportPrivateUsage=false
from datetime import datetime
from pathlib import Path

import pytest

from fs_schema import MismatchErr, _schema
from fs_schema._fmt import dt
from fs_schema._schema import (
    Dir,
    File,
    Schema,
    _DirDefn,
    _DirMatch,
    _FileMatch,
    _FixedDir,
    _FixedFile,
    _Matches,
    _Template,
    bind_defns,
)


def _touch(parent: Path, *names: str) -> None:
    parent.mkdir(parents=True, exist_ok=True)
    for name in names:
        _ = (parent / name).write_text(name)


def test_file_is_a_defn_and_directory_copies_children() -> None:
    child = File(name="child")
    source = [child]
    defn = _DirDefn(Dir(name="directory"), source)
    source.clear()
    assert defn.defns == (child,)
    assert isinstance(child, File) and not hasattr(child, "children")


def test_fixed_name_binds_exact_path(tmp_path: Path) -> None:
    root = tmp_path / "root"
    _touch(root, "fixed.txt")
    defn = File(name="fixed.txt")
    bound = bind_defns(root, (defn,))
    assert isinstance(bound, _FixedDir)
    assert isinstance(bound[0], _FixedFile) and bound[0].defn is defn


def test_fixed_and_template_selector_matrix_with_regex_captures(tmp_path: Path) -> None:
    root = tmp_path / "root"
    _touch(root, "fixed.txt", "part-2.txt", "part-1.txt", "regex-a-7.txt", "regex-b.txt")
    defns = (
        File(name="fixed.txt", match=r"fixed[.]txt", alias="fixed_alias"),
        File(fmt="part-{part:d}.txt", match=r"part-[12][.]txt", min=2, alias="parts"),
        File(match=r"regex-([a-z]+)(?:-(?P<num>[0-9]+))?[.]txt", min=2, alias="regexes"),
    )
    bound = bind_defns(root, defns)
    assert isinstance(bound, _FixedDir)
    fixed, parts, regexes = tuple(bound)
    assert isinstance(fixed, _FixedFile) and bound.fixed_alias is fixed
    assert isinstance(parts, _Template) and [m.kwargs["part"] for m in parts] == [1, 2]
    assert isinstance(regexes, _Matches) and not isinstance(regexes, _Template)
    assert [(m.args, dict(m.kwargs)) for m in regexes] == [(("a",), {"num": "7"}), (("b",), {"num": None})]
    bad = bind_defns(root, (File(name="fixed.txt", match=r"other"),))
    assert isinstance(bad, MismatchErr) and "does not match" in str(bad)


def test_directory_regex_only_and_fmt_intersection_capture_semantics(tmp_path: Path) -> None:
    root = tmp_path / "root"
    for name in ("fixed-dir", "fmt-2", "regex-a", "both-3", "both-x"):
        (root / name).mkdir(parents=True)
    defns = (
        _DirDefn(Dir(name="fixed-dir", match=r"fixed-dir")),
        _DirDefn(Dir(fmt="fmt-{n:d}")),
        _DirDefn(Dir(match=r"regex-(?P<letter>.+)")),
        _DirDefn(Dir(fmt="both-{n:d}", match=r"both-3")),
    )
    bound = bind_defns(root, defns)
    assert isinstance(bound, _FixedDir)
    fixed, by_fmt, by_regex, intersection = tuple(bound)
    assert isinstance(fixed, _FixedDir) and not isinstance(fixed, _DirMatch)
    assert not hasattr(fixed, "args")
    assert isinstance(by_fmt, _Template) and by_fmt[0].kwargs["n"] == 2
    assert isinstance(by_regex, _Matches) and not isinstance(by_regex, _Template)
    assert isinstance(by_regex[0], _DirMatch) and dict(by_regex[0].kwargs) == {"letter": "a"}
    assert isinstance(intersection, _Template) and intersection[0].kwargs["n"] == 3


def test_fixed_absence_kind_and_template_cardinality(tmp_path: Path) -> None:
    root = tmp_path / "root"
    _touch(root, "one.txt", "two.txt", "as-file")
    (root / "as-directory").mkdir()
    for defn in (File(name="missing"), File(name="as-directory"), _DirDefn(Dir(name="as-file"))):
        assert isinstance(bind_defns(root, (defn,)), MismatchErr)
    zero = bind_defns(root, (File(fmt="missing-{n:d}", min=0, max=0),))
    assert isinstance(zero, _FixedDir)
    empty = zero[0]
    assert isinstance(empty, _Template) and len(empty) == 0
    assert isinstance(bind_defns(root, (File(match=r".+[.]txt", min=0, max=1),)), MismatchErr)
    assert isinstance(bind_defns(root, (File(fmt="absent-{n:d}", min=1),)), MismatchErr)


def test_binder_lists_only_for_collections_and_only_once_per_directory(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = tmp_path / "root"
    _touch(root, "fixed.txt", "one-1.txt", "two-1.txt")
    original = Path.iterdir
    calls: list[Path] = []

    def counted(path: Path):
        calls.append(path)
        return original(path)

    monkeypatch.setattr(Path, "iterdir", counted)
    fixed = bind_defns(root, (File(name="fixed.txt"),))
    assert isinstance(fixed, _FixedDir) and calls == []
    collections = bind_defns(root, (File(fmt="one-{n:d}.txt"), File(fmt="two-{n:d}.txt")))
    assert isinstance(collections, _FixedDir)
    assert calls == [root]


def test_sorting_and_nested_selected_directory_mismatch_propagates(tmp_path: Path) -> None:
    root = tmp_path / "root"
    _touch(root, "20250102", "20240101", "item-2.txt", "item-1.txt")
    _touch(root / "run-2", "required")
    (root / "run-1").mkdir(parents=True)
    run = _DirDefn(Dir(fmt="run-{n:d}", min=2), (File(name="required"),))
    defns = (File(fmt=dt("%Y%m%d"), min=2), File(fmt="item-{n:d}.txt", min=2, sort=lambda _match: 0), run)

    mismatch = bind_defns(root, defns)
    assert isinstance(mismatch, MismatchErr)
    assert str(mismatch) == f"expected file: {root / 'run-1' / 'required'}"

    sorted_only = bind_defns(root, defns[:2])
    assert isinstance(sorted_only, _FixedDir)
    dates, items = sorted_only
    assert isinstance(dates, _Template) and isinstance(items, _Template)
    assert [m.args[0] for m in dates] == [datetime(2024, 1, 1), datetime(2025, 1, 2)]
    assert [m.path.name for m in items] == ["item-1.txt", "item-2.txt"]


def test_collection_ignores_wrong_kind_candidates(tmp_path: Path) -> None:
    root = tmp_path / "root"
    _touch(root, "entry-1")
    (root / "entry-2").mkdir(parents=True)
    files = bind_defns(root, (File(fmt="entry-{n:d}", min=1, max=1),))
    directories = bind_defns(root, (_DirDefn(Dir(fmt="entry-{n:d}", min=1, max=1)),))
    assert isinstance(files, _FixedDir)
    file_matches = files[0]
    assert isinstance(file_matches, _Template) and file_matches[0].path.name == "entry-1"
    assert isinstance(directories, _FixedDir)
    dir_matches = directories[0]
    assert isinstance(dir_matches, _Template) and dir_matches[0].path.name == "entry-2"


def test_callable_loading_and_deferred_directory_schema_seam(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    root = tmp_path / "root"
    _touch(root, "fixed.num", "match-2.num")

    def decode(path: Path) -> int:
        return 2 if "match" in path.name else 7

    bound = bind_defns(root, (File(name="fixed.num", schema=decode), File(fmt="match-{n:d}.num", schema=decode)))
    assert isinstance(bound, _FixedDir)
    fixed, matches = bound
    assert isinstance(fixed, _FixedFile) and fixed.load() == 7
    assert isinstance(matches, _Template)
    first_match = matches[0]
    assert isinstance(first_match, _FileMatch) and first_match.load() == 2
    model = bind_defns(root, (File(name="fixed.num", schema=int),))
    assert isinstance(model, _FixedDir)
    model_file = model[0]
    assert isinstance(model_file, _FixedFile)
    failure = model_file.load()
    assert isinstance(failure, Exception) and "codec connector is not connected" in str(failure)
    defn = _DirDefn(Dir(name="nested", schema=Schema), (File(name="required"),))
    _touch(root / "nested", "required")
    assert isinstance(bind_defns(root, (defn,)), MismatchErr)
    calls: list[Path] = []

    def validate(path: Path, schema: type[Schema]) -> None:
        assert schema is Schema
        calls.append(path)

    monkeypatch.setattr(_schema, "_validate_schema_contract", validate)
    assert isinstance(bind_defns(root, (defn,)), _FixedDir) and calls == [root / "nested"]
