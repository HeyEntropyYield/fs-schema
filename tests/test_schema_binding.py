# pyright: reportPrivateUsage=false, reportUnknownMemberType=false, reportUnknownArgumentType=false
# pyright: reportAttributeAccessIssue=false
from collections.abc import Sequence
from datetime import datetime
from pathlib import Path

import pytest

import fs_schema._bind as bind_mod
from fs_schema import FILES, Match, MismatchErr, is_mismatch
from fs_schema import _errmsg as em
from fs_schema._bind import bind_children
from fs_schema._decl import Defn, Dir, DirDefn, File
from fs_schema._fmt import dt
from fs_schema._schema import (
    BoundChild,
    FileMatch,
    FixedDir,
    FixedFile,
    Matches,
    Schema,
    Template,
)


def _bind(root: Path, defns: Sequence[Defn], *, fast: bool = False) -> FixedDir | MismatchErr:
    dir_defn = DirDefn(Dir(name="."), defns)  # raises
    if is_mismatch(children := bind_children(root, dir_defn, {}, fast=fast)):
        return children
    return FixedDir(root, children, dir_defn)


def _touch(parent: Path, *names: str) -> None:
    parent.mkdir(parents=True, exist_ok=True)
    for name in names:
        _ = (parent / name).write_text(name)


def test_file_is_a_defn_and_directory_copies_children() -> None:
    child = File(name="child")
    source = [child]
    defn = DirDefn(Dir(name="directory"), source)
    source.clear()
    assert defn.defns == (child,)
    assert defn.child_type is None
    assert isinstance(child, File) and not hasattr(child, "children")


def test_missing_root_and_nested_file_are_mismatches(tmp_path: Path) -> None:
    missing = _bind(tmp_path / "missing", ())
    assert isinstance(missing, MismatchErr)
    root = tmp_path / "root"
    (root / "nested").mkdir(parents=True)
    nested = DirDefn(Dir("nested"), (File("note.txt"),))
    mismatch = _bind(root, (nested,))
    assert isinstance(mismatch, MismatchErr)
    assert str(mismatch) == em.Bind.file(root / "nested" / "note.txt")


def test_fixed_name_binds_exact_path(tmp_path: Path) -> None:
    root = tmp_path / "root"
    _touch(root, "fixed.txt")
    defn = File(name="fixed.txt")
    bound = _bind(root, (defn,))
    assert isinstance(bound, FixedDir)
    assert isinstance(bound[0], FixedFile) and bound[0].defn is defn


def test_fixed_and_template_selector_matrix_with_regex_captures(tmp_path: Path) -> None:
    root = tmp_path / "root"
    _touch(root, "fixed.txt", "part-2.txt", "part-1.txt", "regex-a-7.txt", "regex-b.txt")
    defns = (
        File(name="fixed.txt", match=r"fixed[.]txt", alias="fixed_alias"),
        File(fmt="part-{part:d}.txt", match=r"part-[12][.]txt", min=2, alias="parts"),
        File(match=r"regex-([a-z]+)(?:-(?P<num>[0-9]+))?[.]txt", min=2, alias="regexes"),
    )
    bound = _bind(root, defns)
    assert isinstance(bound, FixedDir)
    fixed, parts, regexes = tuple(bound)
    assert isinstance(fixed, FixedFile) and bound.fixed_alias is fixed
    assert isinstance(parts, Template) and [match.kwargs["part"] for match in parts] == [1, 2]
    assert isinstance(regexes, Matches) and not isinstance(regexes, Template)
    assert [(match.args, dict(match.kwargs)) for match in regexes] == [
        (("a",), {"num": "7"}),
        (("b",), {"num": None}),
    ]
    bad = _bind(root, (File(name="fixed.txt", match=r"other"),))
    assert isinstance(bad, MismatchErr)
    assert str(bad) == em.Bind.fixed("other", root / "fixed.txt")

    planned = _bind(root, (File(fmt="absent-{part:d}.txt", match=r"absent-[0-9]+[.]txt", min=0),))
    assert isinstance(planned, FixedDir)
    planned_collection = planned[0]
    assert isinstance(planned_collection, Template)
    with pytest.raises(KeyError, match="missing"):
        planned_collection.where(missing=None)


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
    assert isinstance(bound.formatted, Template)
    assert isinstance(bound.formatted[0], Child) and isinstance(bound.formatted[0], Match)
    assert bound.formatted[0].kwargs["n"] == 2
    assert isinstance(bound.regexes, Matches) and not isinstance(bound.regexes, Template)
    assert isinstance(bound.regexes[0], Match) and bound.regexes[0].kwargs["label"] == "a"
    assert bound.regexes[0].leaf.path.name == "leaf.txt"
    assert isinstance(bound.both, Template) and bound.both[0].kwargs["n"] == 3
    assert isinstance(bound.both[0], Child) and isinstance(bound.both[0], Match)
    assert Root.fixed is Child
    assert issubclass(Root.formatted, Template)
    assert issubclass(Root.regexes, Matches)
    assert not hasattr(bound.formatted[0], "format")


def test_fixed_absence_kind_and_template_cardinality(tmp_path: Path) -> None:
    root = tmp_path / "root"
    _touch(root, "one.txt", "two.txt", "as-file")
    (root / "as-directory").mkdir()
    for defn in (File(name="missing"), File(name="as-directory"), DirDefn(Dir(name="as-file"))):
        assert isinstance(_bind(root, (defn,)), MismatchErr)
    zero = _bind(root, (File(fmt="missing-{n:d}", min=0, max=0),))
    assert isinstance(zero, FixedDir)
    zero_matches = zero[0]
    assert isinstance(zero_matches, Template) and len(zero_matches) == 0
    assert isinstance(_bind(root, (File(match=r".+[.]txt", min=0, max=1),)), MismatchErr)
    assert isinstance(_bind(root, (File(fmt="absent-{n:d}", min=1),)), MismatchErr)


def test_collection_ignores_wrong_kind_candidates(tmp_path: Path) -> None:
    root = tmp_path / "root"
    _touch(root, "entry-1")
    (root / "entry-2").mkdir(parents=True)
    files = _bind(root, (File(fmt="entry-{n:d}", min=1, max=1),))
    directories = _bind(root, (DirDefn(Dir(fmt="entry-{n:d}", min=1, max=1)),))
    assert isinstance(files, FixedDir)
    file_matches = files[0]
    assert isinstance(file_matches, Template) and file_matches[0].path.name == "entry-1"
    assert isinstance(directories, FixedDir)
    dir_matches = directories[0]
    assert isinstance(dir_matches, Template) and dir_matches[0].path.name == "entry-2"


def test_sorting_and_nested_selected_directory_mismatch_propagates(tmp_path: Path) -> None:
    root = tmp_path / "root"
    _touch(root, "20250102", "20240101", "part-2.txt", "part-1.txt")
    _touch(root / "run-2", "note.txt")
    (root / "run-1").mkdir(parents=True)
    run = DirDefn(Dir(fmt="run-{n:d}", min=2), (File(name="note.txt"),))
    defns = (File(fmt=dt("%Y%m%d"), min=2), File(fmt="part-{n:d}.txt", min=2, sort=lambda _match: 0), run)

    mismatch = _bind(root, defns)
    assert isinstance(mismatch, MismatchErr)
    assert str(mismatch).splitlines() == [
        em.Bind.file(root / "run-1" / "note.txt"),
        em.Bind.count(low=2, high=None, position=2, found=1, dangling=[], path=root),
    ]

    sorted_only = _bind(root, defns[:2])
    assert isinstance(sorted_only, FixedDir)
    dates, items = sorted_only
    assert isinstance(dates, Template) and isinstance(items, Template)
    assert [match.kwargs["ts"] for match in dates] == [datetime(2024, 1, 1), datetime(2025, 1, 2)]
    assert [match.path.name for match in items] == ["part-1.txt", "part-2.txt"]


def test_bind_reports_every_sibling_failure_in_declaration_order(tmp_path: Path) -> None:
    root = tmp_path / "root"
    _touch(root / "inner", "present")
    _touch(root, "present")
    inner = DirDefn(Dir(name="inner"), (File(name="gone-a"), File(name="present"), File(name="gone-b")))
    defns = (File(name="missing-1"), File(name="present"), inner, File(name="missing-2"))

    mismatch = _bind(root, defns)
    assert isinstance(mismatch, MismatchErr)
    assert str(mismatch).splitlines() == [
        em.Bind.file(root / "missing-1"),
        em.Bind.file(root / "inner" / "gone-a"),
        em.Bind.file(root / "inner" / "gone-b"),
        em.Bind.file(root / "missing-2"),
    ]
    assert not str(mismatch).endswith("\n")
    assert str(_bind(root, defns, fast=True)) == str(mismatch).splitlines()[0]


def test_fast_bind_does_not_visit_later_siblings(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    class Pair(Schema):
        schema = {"a": "a.txt", "b": "b.txt"}

    root = tmp_path / "root"
    root.mkdir()
    seen: list[Path] = []
    original = Path.is_file

    def track(path: Path) -> bool:
        seen.append(path)
        return original(path)

    monkeypatch.setattr(Path, "is_file", track)
    mismatch = Pair.bind(root, fast=True)
    assert isinstance(mismatch, MismatchErr)
    assert str(mismatch) == em.Bind.file(root / "a.txt")
    assert root / "b.txt" not in seen
    assert str(Pair.relative_to(root).bind(fast=True)) == str(mismatch)


def test_fixed_and_match_have_no_length(tmp_path: Path) -> None:
    class Roll(Schema):
        schema = {
            "note": "note.txt",
            "shots": File(fmt="{stem}.png", min=0),
            Dir(alias="days", fmt="day-{n:d}", min=0): {"note": "note.txt"},
        }

    root = tmp_path / "root"
    _touch(root, "note.txt", "a.png")
    _touch(root / "day-1", "note.txt")
    bound = Roll.bind(root)
    assert isinstance(bound, Roll)
    assert len(bound.days) == 1
    assert len(bound.shots) == 1
    with pytest.raises(TypeError):
        _ = len(bound)  # pyright: ignore[reportArgumentType]
    for node in (bound.note, bound.days[0], bound.shots[0]):
        with pytest.raises(TypeError):
            _ = len(node)


def test_fast_bind_does_not_open_a_later_collection_member(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    class Runs(Schema):
        schema = {Dir(fmt="run-{n}", min=0): {"body": "body.txt"}}

    root = tmp_path / "root"
    _touch(root / "run-1", "other")
    _touch(root / "run-2", "other")
    seen: list[Path] = []
    original = Path.is_dir

    def track(path: Path) -> bool:
        seen.append(path)
        return original(path)

    monkeypatch.setattr(Path, "is_dir", track)
    mismatch = Runs.bind(root, fast=True)
    assert isinstance(mismatch, MismatchErr)
    assert str(mismatch) == em.Bind.file(root / "run-1" / "body.txt")
    assert root / "run-2" not in seen


def test_fast_bind_stops_on_the_first_failed_match(tmp_path: Path) -> None:
    class Files(Schema):
        schema = {"files": File(fmt="{stem}.txt", match=r"ok-.+", min=0)}

    files = tmp_path / "files"
    _touch(files, "bad-1.txt", "bad-2.txt")
    file_mismatch = Files.bind(files, fast=True)
    assert isinstance(file_mismatch, MismatchErr)
    assert str(file_mismatch) == em.Bind.failed("ok-.+", "bad-1.txt")

    class Dirs(Schema):
        schema = {Dir(fmt="{stem}", match=r"ok-.+", min=0): {"body": "body.txt"}}

    dirs = tmp_path / "dirs"
    (dirs / "bad-1").mkdir(parents=True)
    (dirs / "bad-2").mkdir()
    dir_mismatch = Dirs.bind(dirs, fast=True)
    assert isinstance(dir_mismatch, MismatchErr)
    assert str(dir_mismatch) == em.Bind.failed("ok-.+", "bad-1")


def test_fast_bind_still_passes_a_skipped_mismatch(tmp_path: Path) -> None:
    class Bundle(Schema):
        schema = {
            "files": File(fmt="{stem}.txt", match=r"ok-.+", skip_mismatch=True, min=0),
            "note": "note.txt",
        }

    root = tmp_path / "root"
    _touch(root, "bad.txt")
    mismatch = Bundle.bind(root, fast=True)
    assert isinstance(mismatch, MismatchErr)
    assert str(mismatch) == em.Bind.file(root / "note.txt")


def test_bind_single_failure_is_one_line(tmp_path: Path) -> None:
    mismatch = _bind(tmp_path, (File(name="missing"),))
    assert isinstance(mismatch, MismatchErr)
    assert str(mismatch) == em.Bind.file(tmp_path / "missing")


def test_bind_reports_count_and_member_failures_in_one_directory(tmp_path: Path) -> None:
    root = tmp_path / "root"
    _touch(root / "run-1", "other")
    _touch(root / "run-2", "note.txt")
    _touch(root, "bad.txt", "part-2.txt")
    run = DirDefn(Dir(fmt="run-{n:d}", min=2), (File(name="note.txt"),))
    parts = File(fmt="part-{n:d}.txt", match=r"part-1[.]txt", min=1)

    mismatch = _bind(root, (run, parts))
    assert isinstance(mismatch, MismatchErr)
    assert str(mismatch).splitlines() == [
        em.Bind.file(root / "run-1" / "note.txt"),
        em.Bind.count(low=2, high=None, position=0, found=1, dangling=[], path=root),
        em.Bind.failed(r"part-1[.]txt", "part-2.txt"),
        em.Bind.count(low=1, high=None, position=1, found=0, dangling=[], path=root),
    ]


def test_aggregate_of_aggregates_matches_a_flat_list(tmp_path: Path) -> None:
    leaves = [bind_mod._mismatch(f"line {index}") for index in range(4)]
    nested = bind_mod._aggregate([bind_mod._aggregate(leaves[:2]), bind_mod._aggregate(leaves[2:])])
    flat = bind_mod._aggregate(leaves)
    assert str(nested) == str(flat)
    assert str(nested).splitlines() == [f"line {index}" for index in range(4)]

    root = tmp_path / "root"
    root.mkdir()
    _ = (root / "not-a-dir").write_text("x")
    (root / "left").mkdir()
    (root / "right").mkdir()
    bad = DirDefn(Dir(name="not-a-dir"), (File(name="a"),))
    left = DirDefn(Dir(name="left"), (File(name="a"), File(name="b")))
    right = DirDefn(Dir(name="right"), (File(name="a"), File(name="b")))
    mismatch = _bind(root, (bad, left, right))
    lines = [
        em.Bind.directory(root / "not-a-dir"),
        em.Bind.file(root / "left" / "a"),
        em.Bind.file(root / "left" / "b"),
        em.Bind.file(root / "right" / "a"),
        em.Bind.file(root / "right" / "b"),
    ]
    built = bind_mod._aggregate([
        bind_mod._mismatch(lines[0]),
        bind_mod._aggregate([bind_mod._mismatch(line) for line in lines[1:3]]),
        bind_mod._aggregate([bind_mod._mismatch(line) for line in lines[3:]]),
    ])
    assert isinstance(mismatch, MismatchErr)
    assert str(mismatch) == str(built)
    assert str(mismatch).splitlines() == lines


def test_bind_flattens_nested_aggregates_from_members(tmp_path: Path) -> None:
    root = tmp_path / "root"
    (root / "run-1").mkdir(parents=True)
    (root / "run-2").mkdir()
    run = DirDefn(Dir(fmt="run-{n:d}", min=0), (File(name="a"), File(name="b")))

    mismatch = _bind(root, (run,))
    assert isinstance(mismatch, MismatchErr)
    assert str(mismatch).splitlines() == [
        em.Bind.file(root / "run-1" / "a"),
        em.Bind.file(root / "run-1" / "b"),
        em.Bind.file(root / "run-2" / "a"),
        em.Bind.file(root / "run-2" / "b"),
    ]


def test_bind_message_stays_one_line_for_odd_filenames(tmp_path: Path) -> None:
    odd = "a\nb\u2028c"
    _touch(tmp_path, odd)
    mismatch = _bind(tmp_path, (File(fmt="{n}", match=r"1", min=0),))
    assert isinstance(mismatch, MismatchErr)
    assert str(mismatch).splitlines() == [str(bind_mod._mismatch(em.Bind.failed("1", odd)))]


def test_callable_loading_preserves_generic_runtime_declaration(tmp_path: Path) -> None:
    root = tmp_path / "root"
    _touch(root, "fixed.num", "match-2.num")

    def decode(path: Path) -> int:
        return 2 if "match" in path.name else 7

    fixed_defn: File[int] = File(name="fixed.num", schema=decode)
    match_defn: File[int] = File(fmt="match-{n:d}.num", schema=decode)
    bound = _bind(root, (fixed_defn, match_defn))
    assert isinstance(bound, FixedDir)
    fixed, matches = bound
    assert isinstance(fixed, FixedFile) and fixed.defn is fixed_defn and fixed.load() == 7
    loader_clash = fixed.load(int)
    assert isinstance(loader_clash, TypeError) and str(loader_clash) == em.Load.loader(fixed.path, decode)
    assert isinstance(matches, Template)
    first_match = matches[0]
    assert isinstance(first_match, FileMatch) and first_match.defn is match_defn and first_match.load() == 2

    model = _bind(root, (File(name="fixed.num", schema=int),))
    assert isinstance(model, FixedDir)
    model_file = model[0]
    assert isinstance(model_file, FixedFile)
    failure = model_file.load()
    assert isinstance(failure, TypeError) and str(failure) == em.Json.suffix(".num")
    assert isinstance(model_file.load(int), TypeError)
    model_clash = model_file.load(str)
    assert isinstance(model_clash, TypeError) and str(model_clash) == em.Load.subclass(model_file.path, "int", "str")
    bare = _bind(root, (File(name="fixed.num"),))
    assert isinstance(bare, FixedDir)
    bare_file = bare[0]
    assert isinstance(bare_file, FixedFile)
    missing = bare_file.load()
    assert isinstance(missing, Exception) and "no declared loader" in str(missing)
    used_model = bare_file.load(int)
    assert isinstance(used_model, Exception) and "no declared loader" not in str(used_model)


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
    assert type(bound.inline.deep) is Root.inline.deep
    assert issubclass(Root.inline.deep.leaf, FixedFile)
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
    assert isinstance(bound.explicit, Template)
    assert isinstance(bound.inline, Matches) and not isinstance(bound.inline, Template)
    assert issubclass(Root.explicit, Template) and issubclass(Root.inline, Matches)
    assert all(isinstance(item, Item) and isinstance(item, Match) for item in bound.explicit)
    assert [item.kwargs["number"] for item in bound.explicit] == [1, 2]
    assert isinstance(bound.inline[0], Match) and bound.inline[0].kwargs["number"] == "3"
    first_explicit = bound.explicit[0]
    assert isinstance(first_explicit, Item) and first_explicit.leaf.path.name == "leaf.txt"
    assert isinstance(bound.explicit[0], Item)


def test_bind_result_bool_and_empty_collection(tmp_path: Path) -> None:
    class Empty(Schema):
        pass

    class OptionalParts(Schema):
        schema = {"parts": File(fmt="n{n:d}.txt", min=0)}

    assert not MismatchErr("missing")
    empty = Empty.bind(tmp_path)
    assert empty and type(empty) is Empty
    bound = OptionalParts.bind(tmp_path)
    assert bound and type(bound) is OptionalParts
    assert not bound.parts


def test_dangling_symlink_is_named(tmp_path: Path) -> None:
    (tmp_path / "gone.png").symlink_to(tmp_path / "missing.png")
    (tmp_path / "note.txt").symlink_to(tmp_path / "missing.txt")

    class Pics(Schema):
        schema = {"images": File(match=r".+\.png", min=1)}

    err = Pics.bind(tmp_path)
    assert isinstance(err, MismatchErr)
    assert "gone.png" in str(err)
    (tmp_path / "here.png").write_bytes(b"png")
    assert not isinstance(Pics.bind(tmp_path), MismatchErr)


def test_bound_file_exists_rejects_raw_basename(tmp_path: Path) -> None:
    _ = (tmp_path / "my-note.txt").write_text("n")

    class Named(Schema):
        schema = {"note": "my-note.txt"}

    bound = Named.bind(tmp_path)
    assert isinstance(bound, Named)
    assert bound.note.exists()
    with pytest.raises(AttributeError):
        getattr(bound, "my-note.txt")


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
            assert str(mismatch) == em.Bind.directory(root)


def test_dir_schema_has_no_runtime_merge_or_second_binding(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    class Required(Schema):
        schema = {"parts": File(match=r"part-.+", min=1)}

    class Exposed(Schema):
        schema = {
            "parts": File(match=r"part-.+", min=1),
            "extra": File(match=r"extra-.+", min=1),
        }

    class Root(Schema):
        schema = {Dir("nested", schema=Required): Exposed}

    nested = tmp_path / "root" / "nested"
    _touch(nested, "part-1", "extra-1")
    original = bind_mod.bind_children
    visited: list[Path] = []

    def counted(
        path: Path, defn: DirDefn, cache: bind_mod._FsCache, *, fast: bool = False
    ) -> tuple[BoundChild, ...] | MismatchErr:
        visited.append(path)
        return original(path, defn, cache, fast=fast)

    monkeypatch.setattr(bind_mod, "bind_children", counted)
    bound = Root.bind(tmp_path / "root")
    assert isinstance(bound, Root)
    assert type(bound.nested) is Exposed
    assert hasattr(bound.nested, "parts") and hasattr(bound.nested, "extra")
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
    assert isinstance(runs, Template)
    old_runs = tuple(runs)

    _touch(root / "run-2", "leaf")
    (root / "fixed").unlink()
    assert tuple(old) == old_children
    assert tuple(runs) == old_runs
    assert old["nested"] is old.nested
    assert isinstance(Root.bind(root), MismatchErr)

    _touch(root, "fixed")
    fresh = Root.bind(root)
    assert isinstance(fresh, Root)
    fresh_runs = fresh.runs
    assert isinstance(fresh_runs, Template) and len(fresh_runs) == 2
