# pyright: reportPrivateUsage=false
# This file deliberately tests private runtime implementation classes.

import os
import re
from pathlib import Path

import pytest
from beartype.roar import BeartypeCallHintParamViolation

import fs_schema as fss
from fs_schema._fmt import CaptureMap, CompiledFormat, FmtField
from fs_schema._schema import (
    _ChildEntry,
    _DirMatch,
    _FileMatch,
    _FixedDir,
    _FixedFile,
    _LoadableFile,
    _LoadableFileMatch,
    _TemplateCollection,
)


def test_fixed_file_owns_path_and_performs_io(tmp_path: Path) -> None:
    path = tmp_path / "nested" / "value.txt"
    fixed = _FixedFile(os.fspath(path))

    assert fixed.path == path
    assert str(fixed) == os.fspath(path)
    assert fixed.name == "value.txt"
    assert fixed.stem == "value"
    assert fixed.suffix == ".txt"
    assert fixed < _FixedFile(tmp_path / "nested" / "z.txt", defn)
    assert fixed.__lt__(object()) is NotImplemented
    assert os.fspath(fixed) == os.fspath(path)
    assert not fixed.exists()

    fixed.put("first")
    assert fixed.exists()
    assert fixed.read_text() == "first"
    fixed.put(b"second")
    assert fixed.read_bytes() == b"second"


def test_fixed_directories_own_recursive_children_and_lookup(tmp_path: Path) -> None:
    leaf = _FixedFile(tmp_path / "inner" / "leaf.txt")
    inner_source = [_ChildEntry(leaf, "leaf.txt", "leaf_alias")]
    inner = _FixedDir(tmp_path / "inner", inner_source)
    outer_file = _FixedFile(tmp_path / "outer.txt")
    anonymous = _FixedFile(tmp_path / "anonymous.txt")
    outer_source = [
        _ChildEntry(outer_file, "outer-file.txt", "outer_alias"),
        _ChildEntry(inner, "inner-dir", "inner_alias"),
        _ChildEntry(anonymous),
    ]
    outer = _FixedDir(tmp_path, outer_source)

    inner_source.clear()
    outer_source.reverse()
    outer_source.clear()

    assert tuple(inner) == (leaf,)
    assert tuple(outer) == (outer_file, inner, anonymous)
    assert outer[0] is outer_file
    assert outer[-2] is inner
    assert outer["outer-file.txt"] is outer_file
    assert outer["outer_alias"] is outer_file
    assert outer["outer_file_txt"] is outer_file
    assert outer.outer_alias is outer_file
    assert outer.outer_file_txt is outer_file
    assert inner["leaf.txt"] is leaf
    assert inner.leaf_alias is leaf
    assert outer[2] is anonymous
    with pytest.raises(KeyError):
        _ = outer["anonymous.txt"]
    with pytest.raises(AttributeError):
        _ = outer.anonymous
    with pytest.raises(AttributeError):
        getattr(outer, "outer-file.txt")
    with pytest.raises(KeyError):
        _ = outer["missing"]
    with pytest.raises(AttributeError):
        _ = outer.missing
    with pytest.raises(IndexError):
        _ = outer[3]
    with pytest.raises(IndexError):
        _ = outer[-4]
    with pytest.raises(BeartypeCallHintParamViolation):
        outer.__getitem__(slice(None))  # pyright: ignore[reportCallIssue, reportArgumentType]
    with pytest.raises(BeartypeCallHintParamViolation):
        _FixedDir(42, ())  # pyright: ignore[reportArgumentType]
    with pytest.raises(TypeError):
        outer._lookup["new"] = 0  # pyright: ignore[reportIndexIssue]

    iterator = iter(outer)
    assert iter(iterator) is iterator
    assert next(iterator) is outer_file
    assert next(iterator) is inner
    assert next(iterator) is anonymous
    with pytest.raises(StopIteration):
        _ = next(iterator)

    captures = CaptureMap({"part": 7})
    match_source = [
        _ChildEntry(inner, "inner-dir", "inner_alias"),
        _ChildEntry(outer_file, "outer-file.txt", "outer_alias"),
    ]
    match = _DirMatch(tmp_path / "part-7", ("part",), captures, match_source)
    match_source.reverse()
    match_source.clear()
    captures._values["part"] = 8

    assert match.args == ("part",)
    assert match.kwargs is not captures
    assert dict(match.kwargs) == {"part": 7}
    assert tuple(match) == (inner, outer_file)
    assert match[0] is match["inner-dir"] is match.inner_alias is inner
    assert match[-1] is match.outer_file_txt is outer_file
    assert inner[0] is leaf


@pytest.mark.parametrize(
    ("first", "second", "key"),
    [
        (("same", None), ("same", None), "same"),
        (("same", None), ("other", "same"), "same"),
        (("same_name", None), ("same-name", None), "same_name"),
        (("first", "same"), ("second", "same"), "same"),
        (("first", "same_name"), ("same-name", None), "same_name"),
        (("same name", None), ("same-name", None), "same_name"),
    ],
)
def test_fixed_directories_reject_cross_child_key_collisions(
    tmp_path: Path,
    first: tuple[str, str | None],
    second: tuple[str, str | None],
    key: str,
) -> None:
    one = _FixedFile(tmp_path / "one")
    two = _FixedFile(tmp_path / "two")
    with pytest.raises(ValueError, match=repr(key)):
        _FixedDir(
            tmp_path,
            [
                _ChildEntry(one, first[0], first[1]),
                _ChildEntry(two, second[0], second[1]),
            ],
        )


def test_fixed_directories_accept_same_child_coincident_keys(tmp_path: Path) -> None:
    child = _FixedFile(tmp_path / "same")
    directory = _FixedDir(tmp_path, [_ChildEntry(child, "same", "same")])

    assert directory["same"] is directory.same is child


def test_fixed_directories_support_every_child_family(tmp_path: Path) -> None:
    fixed_file = _FixedFile(tmp_path / "fixed.txt")
    loadable_file = _LoadableFile[object](tmp_path / "loadable.txt")
    fixed_dir = _FixedDir(tmp_path / "fixed-dir", ())
    dir_match = _DirMatch(tmp_path / "dir-match", (), CaptureMap({}), ())
    file_match = _FileMatch(tmp_path / "file-match.txt", (), CaptureMap({}))
    loadable_match = _LoadableFileMatch[object](tmp_path / "loadable-match.txt")
    collection_children = (
        _TemplateCollection(tmp_path, (file_match,)),
        _TemplateCollection(tmp_path, (loadable_match,)),
        _TemplateCollection(tmp_path, (dir_match,)),
    )
    children = (
        fixed_file,
        loadable_file,
        fixed_dir,
        file_match,
        loadable_match,
        dir_match,
        *collection_children,
    )
    entries = [_ChildEntry(child, f"child-{index}.value", f"alias_{index}") for index, child in enumerate(children)]
    directory = _FixedDir(tmp_path / "parent", entries)

    for index, child in enumerate(children):
        normalized = re.sub(r"[^A-Za-z0-9_]+", "_", f"child-{index}.value")
        assert directory[index] is child
        assert directory[f"child-{index}.value"] is child
        assert directory[f"alias_{index}"] is child
        assert directory[normalized] is child
        assert getattr(directory, f"alias_{index}") is child
        assert getattr(directory, normalized) is child


class _OtherMatch:
    path = Path("other")
    args: tuple[FmtField, ...] = ()
    kwargs = CaptureMap({})

    def __fspath__(self) -> str:
        return os.fspath(self.path)

    def format(self, *args: FmtField, **kwargs: FmtField) -> "fss.SchemaRoot[fss.Schema]":
        _ = args, kwargs
        raise NotImplementedError


def test_fixed_directories_enforce_runtime_child_families(tmp_path: Path) -> None:
    valid = _TemplateCollection(tmp_path, (_FileMatch(tmp_path / "match", (), CaptureMap({})),))
    directory = _FixedDir(tmp_path, [_ChildEntry(valid, "valid")])
    assert directory[0] is valid

    with pytest.raises(BeartypeCallHintParamViolation):
        _ChildEntry(object())  # pyright: ignore[reportArgumentType]
    invalid = _TemplateCollection(tmp_path, (_OtherMatch(),))
    with pytest.raises(BeartypeCallHintParamViolation):
        _ChildEntry(invalid)  # pyright: ignore[reportArgumentType]


def test_matches_and_collections_own_observed_values(tmp_path: Path) -> None:
    first_path = tmp_path / "ready-part-2.txt"
    second_path = tmp_path / "later-part-3.txt"
    third_path = tmp_path / "final-part-4.txt"
    _ = first_path.write_text("ready")
    _ = second_path.write_text("later")
    _ = third_path.write_text("final")

    compiled = CompiledFormat("{}-part-{part:d}.txt")
    first_captures = compiled.parse(first_path.name)
    second_captures = compiled.parse(second_path.name)
    third_captures = compiled.parse(third_path.name)
    assert first_captures is not None
    assert second_captures is not None
    assert third_captures is not None
    first = _FileMatch(first_path, first_captures.args, first_captures.kwargs)
    second = _FileMatch(second_path, second_captures.args, second_captures.kwargs)
    third = _FileMatch(third_path, third_captures.args, third_captures.kwargs)

    assert isinstance(first, _FixedFile)
    assert isinstance(first.args, tuple)
    assert first.args == ("ready",)
    assert first.kwargs is not first_captures.kwargs
    assert first_captures.kwargs["part"] == 2
    assert dict(first.kwargs) == dict(first_captures.kwargs)
    assert first.kwargs["part"] == 2

    source = [first, second, third]
    collection = _TemplateCollection(tmp_path, source)
    sliced = collection[:1]
    assert collection.path == tmp_path
    assert tuple(collection) == (first, second, third)
    assert collection[0] is first
    assert sliced is not collection
    assert sliced.path == collection.path
    assert tuple(sliced) == (first,)

    source.reverse()
    source.clear()
    assert tuple(collection) == (first, second, third)
    assert tuple(sliced) == (first,)

    calls: list[tuple[tuple[FmtField, ...], CaptureMap]] = []

    def has_even_part(args: tuple[FmtField, ...], kwargs: CaptureMap) -> bool:
        calls.append((args, kwargs))
        return kwargs["part"] in (2, 4)

    filtered = collection.filter(has_even_part)
    assert iter(filtered) is filtered
    assert calls == []
    assert next(filtered) is first
    assert calls == [(first.args, first.kwargs)]
    assert calls[0][0] is first.args
    assert calls[0][1] is first.kwargs
    assert next(filtered) is third
    assert calls == [
        (first.args, first.kwargs),
        (second.args, second.kwargs),
        (third.args, third.kwargs),
    ]
    assert list(filtered) == []

    def always_false(args: tuple[FmtField, ...], kwargs: CaptureMap) -> bool:
        _ = args, kwargs
        return False

    assert list(collection.filter(always_false)) == []

    find_calls: list[tuple[tuple[FmtField, ...], CaptureMap]] = []

    def first_eligible(args: tuple[FmtField, ...], kwargs: CaptureMap) -> bool:
        find_calls.append((args, kwargs))
        return True

    assert collection.find(first_eligible) is first
    assert find_calls == [(first.args, first.kwargs)]

    none_calls: list[tuple[tuple[FmtField, ...], CaptureMap]] = []

    def none_eligible(args: tuple[FmtField, ...], kwargs: CaptureMap) -> bool:
        none_calls.append((args, kwargs))
        return False

    assert collection.find(none_eligible) is None
    assert none_calls == [
        (first.args, first.kwargs),
        (second.args, second.kwargs),
        (third.args, third.kwargs),
    ]

    first_path.unlink()
    _ = (tmp_path / "new-part-5.txt").write_text("new")
    assert not first.exists()
    assert tuple(collection) == (first, second, third)
