# pyright: reportPrivateUsage=false, reportUnknownMemberType=false, reportUnknownArgumentType=false
from datetime import datetime
from pathlib import Path

import pytest

from fs_schema import FILES, Match, MismatchErr, _schema
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
    assert defn.child_type is None
    assert isinstance(child, File) and not hasattr(child, "children")


def test_private_bind_defns_rejects_bad_root_and_propagates_nested_mismatch(tmp_path: Path) -> None:
    missing = bind_defns(tmp_path / "missing", ())
    assert isinstance(missing, MismatchErr)
    root = tmp_path / "root"
    (root / "nested").mkdir(parents=True)
    nested = _DirDefn(Dir("nested"), (File("required"),))
    mismatch = bind_defns(root, (nested,))
    assert isinstance(mismatch, MismatchErr)
    assert str(mismatch) == f"expected file: {root / 'nested' / 'required'}"


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
    assert isinstance(parts, _Template) and [match.kwargs["part"] for match in parts] == [1, 2]
    assert isinstance(regexes, _Matches) and not isinstance(regexes, _Template)
    assert [(match.args, dict(match.kwargs)) for match in regexes] == [
        (("a",), {"num": "7"}),
        (("b",), {"num": None}),
    ]
    bad = bind_defns(root, (File(name="fixed.txt", match=r"other"),))
    assert isinstance(bad, MismatchErr) and "does not match" in str(bad)


def test_directory_matches_are_ordinary_dir_matches_with_captures(tmp_path: Path) -> None:
    class Child(Schema):
        schema = {"leaf": "leaf.txt"}

    class Root(Schema):
        schema = {
            Dir(name="fixed", match=r"fixed"): Child,
            Dir(fmt="fmt-{n:d}", alias="formatted"): Child,
            Dir(match=r"regex-(?P<label>.+)", alias="regexes"): {"leaf": "leaf.txt"},
            Dir(fmt="both-{n:d}", match=r"both-3", alias="both"): Child,
        }

    root = tmp_path / "root"
    for name in ("fixed", "fmt-2", "regex-a", "both-3", "both-x"):
        _touch(root / name, "leaf.txt")

    bound = Root.bind(root)
    assert isinstance(bound, Root)
    assert type(bound.fixed) is Child and not isinstance(bound.fixed, Match)
    assert isinstance(bound.formatted, _Template)
    assert isinstance(bound.formatted[0], _DirMatch) and bound.formatted[0].kwargs["n"] == 2
    assert type(bound.formatted[0]) is _DirMatch
    assert isinstance(bound.regexes, _Matches) and not isinstance(bound.regexes, _Template)
    assert isinstance(bound.regexes[0], _DirMatch) and bound.regexes[0].kwargs["label"] == "a"
    assert isinstance(bound.both, _Template) and bound.both[0].kwargs["n"] == 3
    assert Root.fixed is Child
    assert Root.formatted is _Template
    assert Root.regexes is _Matches
    assert not hasattr(bound.formatted[0], "format")


def test_fixed_absence_kind_and_template_cardinality(tmp_path: Path) -> None:
    root = tmp_path / "root"
    _touch(root, "one.txt", "two.txt", "as-file")
    (root / "as-directory").mkdir()
    for defn in (File(name="missing"), File(name="as-directory"), _DirDefn(Dir(name="as-file"))):
        assert isinstance(bind_defns(root, (defn,)), MismatchErr)
    zero = bind_defns(root, (File(fmt="missing-{n:d}", min=0, max=0),))
    assert isinstance(zero, _FixedDir)
    zero_matches = zero[0]
    assert isinstance(zero_matches, _Template) and len(zero_matches) == 0
    assert isinstance(bind_defns(root, (File(match=r".+[.]txt", min=0, max=1),)), MismatchErr)
    assert isinstance(bind_defns(root, (File(fmt="absent-{n:d}", min=1),)), MismatchErr)


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
    assert [match.args[0] for match in dates] == [datetime(2024, 1, 1), datetime(2025, 1, 2)]
    assert [match.path.name for match in items] == ["item-1.txt", "item-2.txt"]


def test_callable_loading_preserves_generic_runtime_declaration(tmp_path: Path) -> None:
    root = tmp_path / "root"
    _touch(root, "fixed.num", "match-2.num")

    def decode(path: Path) -> int:
        return 2 if "match" in path.name else 7

    fixed_defn: File[int] = File(name="fixed.num", schema=decode)
    match_defn: File[int] = File(fmt="match-{n:d}.num", schema=decode)
    bound = bind_defns(root, (fixed_defn, match_defn))
    assert isinstance(bound, _FixedDir)
    fixed, matches = bound
    assert isinstance(fixed, _FixedFile) and fixed.defn is fixed_defn and fixed.load() == 7
    assert isinstance(matches, _Template)
    first_match = matches[0]
    assert isinstance(first_match, _FileMatch) and first_match.defn is match_defn and first_match.load() == 2

    model = bind_defns(root, (File(name="fixed.num", schema=int),))
    assert isinstance(model, _FixedDir)
    model_file = model[0]
    assert isinstance(model_file, _FixedFile)
    failure = model_file.load()
    assert isinstance(failure, Exception) and "codec connector is not connected" in str(failure)


def test_exact_root_and_fixed_explicit_inline_child_types(tmp_path: Path) -> None:
    class Explicit(Schema):
        schema = {"leaf": "leaf.txt"}

    class Root(Schema):
        schema = {"explicit": Explicit, "inline": {"deep": {"leaf": "leaf.txt"}}}

    root = tmp_path / "root"
    _touch(root / "explicit", "leaf.txt")
    _touch(root / "inline" / "deep", "leaf.txt")

    bound = Root.bind(root)
    assert type(bound) is Root
    assert type(bound.explicit) is Explicit
    assert type(bound.inline) is Root.inline
    assert type(bound.inline.deep) is Root.inline.deep  # pyright: ignore[reportAttributeAccessIssue]
    assert Root.inline.deep.leaf is _FixedFile
    assert not hasattr(bound, "args") and not isinstance(bound, Match)
    assert not hasattr(bound.explicit, "kwargs")


def test_repeated_schema_rhs_uses_shared_collection_and_dir_match_types(tmp_path: Path) -> None:
    class Item(Schema):
        schema = {"leaf": "leaf.txt"}

    class Root(Schema):
        schema = {
            Dir(fmt="explicit-{number:d}", alias="explicit"): Item,
            Dir(match=r"inline-(?P<number>[0-9]+)", alias="inline"): {"leaf": "leaf.txt"},
        }

    root = tmp_path / "root"
    for name in ("explicit-1", "explicit-2", "inline-3"):
        _touch(root / name, "leaf.txt")

    bound = Root.bind(root)
    assert isinstance(bound, Root)
    assert isinstance(bound.explicit, _Template)
    assert isinstance(bound.inline, _Matches) and not isinstance(bound.inline, _Template)
    assert Root.explicit is _Template and Root.inline is _Matches
    assert all(type(item) is _DirMatch and isinstance(item, Match) for item in bound.explicit)
    assert [item.kwargs["number"] for item in bound.explicit] == [1, 2]
    assert type(bound.inline[0]) is _DirMatch and bound.inline[0].kwargs["number"] == "3"
    first_explicit = bound.explicit[0]
    assert isinstance(first_explicit, _DirMatch) and first_explicit.leaf.path.name == "leaf.txt"
    assert not isinstance(bound.explicit[0], Item)


def test_root_kind_validation_including_empty_schemas(tmp_path: Path) -> None:
    class Empty(Schema):
        pass

    class Nonempty(Schema):
        schema = {"value": "value"}

    missing = tmp_path / "missing"
    file_root = tmp_path / "file"
    file_root.write_text("x")
    for schema in (Empty, Nonempty):
        for root in (missing, file_root):
            mismatch = schema.bind(root)
            assert isinstance(mismatch, MismatchErr)
            assert str(mismatch) == f"expected directory: {root}"


def test_dir_schema_has_no_runtime_merge_or_second_binding(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    class Required(Schema):
        schema = {"required": File(match=r"required-.+", min=1)}

    class Exposed(Schema):
        schema = {
            "required": File(match=r"required-.+", min=1),
            "visible": File(match=r"visible-.+", min=1),
        }

    class Root(Schema):
        schema = {Dir("nested", schema=Required): Exposed}

    nested = tmp_path / "root" / "nested"
    _touch(nested, "required-1", "visible-1")
    original = _schema._bind_children
    visited: list[Path] = []

    def counted(path: Path, defn: _DirDefn, cache: _schema.FsCache) -> tuple[_schema.Child, ...] | MismatchErr:
        visited.append(path)
        return original(path, defn, cache)

    monkeypatch.setattr(_schema, "_bind_children", counted)
    bound = Root.bind(tmp_path / "root")
    assert isinstance(bound, Root)
    assert type(bound.nested) is Exposed
    assert hasattr(bound.nested, "required") and hasattr(bound.nested, "visible")
    assert Root.nested is Exposed
    assert visited.count(nested) == 1


def test_bind_cache_lists_each_lexical_path_once_across_overlapping_traversal(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    class Root(Schema):
        schema = {
            FILES: [File(match=r"root-.+", alias="roots", min=1)],
            Dir(fmt="run-{n:d}", alias="by_fmt"): {FILES: [File(match=r"part-.+", alias="parts", min=1)]},
            Dir(match=r"run-.+", alias="by_regex"): {FILES: [File(match=r"part-.+", alias="parts", min=1)]},
        }

    root = tmp_path / "root"
    _touch(root, "root-one")
    _touch(root / "run-1", "part-one")
    original = Path.iterdir
    calls: list[Path] = []

    def counted(path: Path):
        calls.append(path)
        return original(path)

    monkeypatch.setattr(Path, "iterdir", counted)
    first = Root.bind(root)
    assert isinstance(first, Root)
    assert calls.count(root) == 1 and calls.count(root / "run-1") == 1 and len(calls) == 2

    calls.clear()
    second = Root.bind(root)
    assert isinstance(second, Root)
    assert calls.count(root) == 1 and calls.count(root / "run-1") == 1 and len(calls) == 2


def test_all_fixed_tree_does_not_list(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    class Fixed(Schema):
        schema = {"fixed": "fixed", "nested": {"inside": "inside"}}

    root = tmp_path / "root"
    _touch(root, "fixed")
    _touch(root / "nested", "inside")

    def fail(_path: Path):
        raise AssertionError("fixed binding listed a directory")

    monkeypatch.setattr(Path, "iterdir", fail)
    assert isinstance(Fixed.bind(root), Fixed)


def test_bound_graph_is_immutable_history_and_new_bind_observes_changes(tmp_path: Path) -> None:
    class Root(Schema):
        schema = {
            "fixed": "fixed",
            "nested": {"inside": "inside"},
            Dir(alias="runs", fmt="run-{n:d}", min=1): {"leaf": "leaf"},
        }

    root = tmp_path / "root"
    _touch(root, "fixed")
    _touch(root / "nested", "inside")
    _touch(root / "run-1", "leaf")
    old = Root.bind(root)
    assert isinstance(old, Root)
    old_children = tuple(old)
    runs = old.runs
    assert isinstance(runs, _Template)
    old_runs = tuple(runs)

    _touch(root / "run-2", "leaf")
    (root / "fixed").unlink()
    assert tuple(old) == old_children
    assert tuple(runs) == old_runs
    assert old["nested"] is old.nested
    assert len(old) == len(old_children)
    assert isinstance(Root.bind(root), MismatchErr)

    _touch(root, "fixed")
    fresh = Root.bind(root)
    assert isinstance(fresh, Root)
    fresh_runs = fresh.runs
    assert isinstance(fresh_runs, _Template) and len(fresh_runs) == 2
