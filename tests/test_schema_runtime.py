# pyright: reportPrivateUsage=false

import os
from pathlib import Path

import pytest
from beartype.roar import BeartypeCallHintParamViolation

from fs_schema import Match
from fs_schema._fmt import CaptureMap, ParsedCaptures
from fs_schema._schema import (
    Dir,
    File,
    _DirDefn,
    _DirMatch,
    _FileMatch,
    _FixedDir,
    _FixedFile,
    _Matches,
    _Template,
)


def _defn(*, alias: str | None = None) -> File[object]:
    return File(name="value.txt", alias=alias)


def test_fixed_file_owns_declaration_path_and_performs_io(tmp_path: Path) -> None:
    defn = _defn()
    path = tmp_path / "nested" / "value.txt"
    fixed = _FixedFile(os.fspath(path), defn)

    assert fixed.defn is defn
    assert fixed.path == path
    assert str(fixed) == os.fspath(path)
    assert fixed.name == "value.txt"
    assert fixed.stem == "value"
    assert fixed.suffix == ".txt"
    assert fixed < _FixedFile(tmp_path / "nested" / "z.txt", defn)
    assert fixed.__lt__(object()) is NotImplemented
    assert os.fspath(fixed) == os.fspath(path)
    fixed.put("first")
    assert fixed.read_text() == "first"
    fixed.put(b"second")
    assert fixed.read_bytes() == b"second"
    assert isinstance(fixed.load(), Exception)


def test_matches_and_collections_keep_observed_capture_values(tmp_path: Path) -> None:
    defn = File(fmt="{part:d}.txt", min=0)
    first = _FileMatch(tmp_path / "2.txt", ParsedCaptures((), CaptureMap({"part": 2})), defn)
    second = _FileMatch(tmp_path / "3.txt", ParsedCaptures((), CaptureMap({"part": 3})), defn)
    source = [first, second]
    collection = _Template(tmp_path, source, defn)
    sliced = collection[:1]

    # ParsedCaptures is the trusted immutable-ish parse result passed to a match;
    # match constructors do not defensively clone its CaptureMap.
    source.clear()
    assert first.defn is defn
    assert dict(first.kwargs) == {"part": 2}
    assert collection.defn is defn and tuple(collection) == (first, second)
    assert isinstance(sliced, _Template) and tuple(sliced) == (first,)
    assert list(collection.filter(lambda _args, kwargs: kwargs["part"] == 3)) == [second]
    assert collection.find(lambda _args, kwargs: kwargs["part"] == 2) is first
    assert collection.find(lambda _args, _kwargs: False) is None


def test_matches_and_templates_are_distinct_but_constructors_copy_collections(tmp_path: Path) -> None:
    plain = File(match=r"part-(.+)")
    formatted = File(fmt="part-{part:d}")
    match = _FileMatch(tmp_path / "part-one", ParsedCaptures(("one",), CaptureMap({})), plain)
    template_match = _FileMatch(tmp_path / "part-1", ParsedCaptures((), CaptureMap({"part": 1})), formatted)

    matches = _Matches(tmp_path, (match,), plain)
    template = _Template(tmp_path, (template_match,), formatted)
    assert tuple(matches) == (match,)
    assert tuple(template) == (template_match,)
    copied = _Matches(tmp_path, (template_match,), plain)
    assert tuple(copied) == (template_match,) and copied.defn is plain
    assert not hasattr(matches, "format")


@pytest.mark.parametrize(
    ("first", "second", "key"),
    [
        (("same", None), ("same", None), "same"),
        (("same", None), ("other", "same"), "same"),
        (("same_name", None), ("same-name", None), "same_name"),
        (("first", "same"), ("second", "same"), "same"),
    ],
)
def test_directory_definition_rejects_cross_child_lookup_collisions(
    first: tuple[str, str | None], second: tuple[str, str | None], key: str
) -> None:
    with pytest.raises(ValueError, match=repr(key)):
        _DirDefn(Dir(name="."), (File(name=first[0], alias=first[1]), File(name=second[0], alias=second[1])))


def test_directory_lookup_derives_keys_and_keeps_anonymous_collection_integer_only(tmp_path: Path) -> None:
    fixed = _FixedFile(tmp_path / "same-name", File(name="same-name", alias="same-name"))
    anonymous = _Matches(tmp_path, (), File(fmt="{n:d}", min=0))
    defn = _DirDefn(Dir(name="."), (fixed.defn, anonymous.defn))
    directory = _FixedDir(tmp_path, (fixed, anonymous), defn)
    assert directory["same-name"] is directory["same_name"] is fixed
    assert directory.same_name is fixed and directory[1] is anonymous
    with pytest.raises(AttributeError):
        _ = directory.wrong_attribute
    with pytest.raises(KeyError):
        _ = directory["anonymous"]
    with pytest.raises(AttributeError):
        _ = directory.anonymous


def test_runtime_constructors_are_beartype_checked(tmp_path: Path) -> None:
    with pytest.raises(BeartypeCallHintParamViolation):
        _FixedFile(tmp_path, object())  # pyright: ignore[reportArgumentType]
    with pytest.raises(BeartypeCallHintParamViolation):
        _DirDefn(File(name="wrong"))  # pyright: ignore[reportArgumentType]


def test_directory_match_carries_its_defn_and_captures(tmp_path: Path) -> None:
    defn = _DirDefn(Dir(match=r"run-(?P<n>[0-9]+)"))
    matched = _DirMatch(tmp_path / "run-1", ParsedCaptures((), CaptureMap({"n": "1"})), (), defn)
    assert matched.defn is defn and matched.defn.defn is defn.defn
    assert matched.kwargs["n"] == "1"


def test_schema_ordinary_construction_has_fixed_directory_protocol(tmp_path: Path) -> None:
    from fs_schema._schema import Schema

    class Concrete(Schema):
        pass

    defn = _DirDefn(Dir(name="."))
    fixed = Concrete(tmp_path, (), defn)
    assert type(fixed) is Concrete and fixed.path == tmp_path
    assert not hasattr(fixed, "args") and not hasattr(fixed, "kwargs")
    assert not isinstance(fixed, Match)
