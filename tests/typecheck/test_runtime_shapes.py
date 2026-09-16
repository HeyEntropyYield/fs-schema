# Static assert_type fixture: basedpyright checks this module; pytest does not execute check().
# pyright: reportPrivateUsage=false, reportUnusedParameter=false
from collections.abc import Iterator, Sequence
from pathlib import Path

from typing_extensions import assert_type

import fs_schema as fss
from fs_schema import _fmt, _ops, _schema
from fs_schema._std_ext import CacheSeq


def accepts_located(value: fss.Located) -> None: ...
def accepts_match(value: fss.Match) -> None: ...
def capture_predicate(args: tuple[_fmt.CaptureField, ...], kwargs: _fmt.CaptureMap) -> bool: ...


def check() -> None:
    file_defn: _schema._Defn = _schema.File[object](name="value.txt")
    dir_defn = _schema._DirDefn(_schema.Dir(name="directory"), (file_defn,))
    fixed = _schema._FixedFile(Path("value.txt"), _schema.File[object](name="value.txt"))
    loaded = _schema._FixedFile[int](Path("loaded"), _schema.File(name="loaded", schema=lambda _path: 1))
    captures = _fmt.ParsedCaptures((), _fmt.CaptureMap({"part": 1}))
    match = _schema._FileMatch(Path("part-1"), captures, _schema.File(name="part-1"))
    plain = _schema._Matches(Path("root"), (match,), _schema.File(match=r"part-(.+)"))
    template = _schema._Template(Path("root"), (match,), _schema.File(fmt="part-{part:d}"))
    dir_match = _schema._DirMatch(Path("directory"), _fmt.ParsedCaptures((), _fmt.CaptureMap({})), (), dir_defn)
    directories = _schema._Matches(Path("root"), (dir_match,), dir_defn)
    directory = _schema._FixedDir(Path("root"), (fixed, plain, template, directories), dir_defn)
    listing: CacheSeq[Path] = CacheSeq(lambda: [Path("part-1")])
    text_defn: _schema.File[str] = _schema.File(name="text", schema=lambda path: path.name)
    aliased_text = _schema._aliased_file("text_alias", text_defn)

    accepts_located(fixed)
    accepts_match(match)
    accepts_located(directory)
    accepts_located(dir_match)
    accepts_match(dir_match)
    assert_type(file_defn, _schema.File[object])
    assert_type(aliased_text, _schema.File[str])
    assert_type(dir_defn.defns, tuple[_schema._Defn, ...])
    assert_type(fixed.defn, _schema.File[object])
    assert_type(plain[0], _schema._FileMatch[object])
    assert_type(plain[:], _schema._Matches[_schema._FileMatch[object], _schema.File[object]])
    assert_type(template[:], _schema._Template[_schema._FileMatch[object], _schema.File[object]])
    assert_type(template.find(capture_predicate), _schema._FileMatch[object] | None)
    assert_type(template.filter(capture_predicate), Iterator[_schema._FileMatch[object]])
    assert_type(loaded.load(), int | Exception)
    assert_type(directories.defn, _schema._DirDefn)
    assert_type(directories[0], _schema._DirMatch)
    assert_type(directory[0], _schema.Child)
    assert_type(iter(directory), Iterator[_schema.Child])
    assert_type(_schema._bind_matches(text_defn, listing, {}), Sequence[_schema._FileMatch[str]])
    assert_type(_schema._bind_matches(dir_defn, listing, {}), Sequence[_schema._DirMatch] | fss.MismatchErr)
    assert_type(_schema._bind_fixed(Path("text"), text_defn, {}), _schema._FixedFile[str])
    assert_type(_schema._bind_fixed(Path("directory"), dir_defn, {}), _schema._FixedDir | fss.MismatchErr)
    assert_type(_schema._bind_children(Path("root"), dir_defn, {}), tuple[_schema.Child, ...] | fss.MismatchErr)
    bound = _schema.bind_defns(Path("root"), (file_defn, dir_defn))
    assert_type(bound, _schema._FixedDir | fss.MismatchErr)

    class Concrete(_schema.Schema):
        schema = {"child": {"value": "value.txt"}}

    assert_type(Concrete.bind(Path("root")), Concrete | fss.MismatchErr)
    assert_type(Concrete.child, type)
    assert Concrete.child.value  # pyright: ignore[reportUnknownMemberType]

    class Repeated(_schema.Schema):
        schema = {_schema.Dir(fmt="run-{n:d}", alias="runs"): Concrete}

    assert_type(Repeated.runs, type)

    def narrow_schema_type(candidate: object) -> None:
        if _schema._is_schema_type(candidate):
            assert_type(candidate, type[_schema.Schema])

    narrow_schema_type(Concrete)

    def decode(path: Path) -> str: ...

    text = _schema._FixedFile(Path("text"), _schema.File(name="text", schema=decode))
    assert_type(text, _schema._FixedFile[str])
    assert_type(text.load(), str | Exception)
    assert_type(_ops.load(Path("value"), decode), str | Exception)
