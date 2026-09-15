# pyright: reportPrivateUsage=false
# This file deliberately tests private runtime implementation classes.

import os
from pathlib import Path

from fs_schema._fmt import CaptureMap, CompiledFormat, FmtField
from fs_schema._schema import _FileMatch, _FixedFile, _TemplateCollection


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
