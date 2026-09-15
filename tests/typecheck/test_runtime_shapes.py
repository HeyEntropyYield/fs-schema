# Static assert_type fixture: basedpyright checks this module; pytest does not execute check().
# pyright: reportPrivateUsage=false, reportUnusedParameter=false
from collections.abc import Iterator
from pathlib import Path

from typing_extensions import assert_type

import fs_schema as fss
from fs_schema import _fmt, _ops, _schema


def accepts_located(value: fss.Located) -> None: ...
def accepts_match(value: fss.Match) -> None: ...
def plain_files() -> _schema._TemplateCollection[_schema._FileMatch]: ...
def loaded_files() -> _schema._TemplateCollection[_schema._LoadableFileMatch[int]]: ...
def directories() -> _schema._TemplateCollection[_schema._DirMatch]: ...
def fixed_file() -> _schema._FixedFile: ...
def loaded_file() -> _schema._LoadableFile[int]: ...
def fixed_dir() -> _schema._FixedDir: ...


def capture_predicate(args: tuple[_fmt.FmtField, ...], kwargs: _fmt.CaptureMap) -> bool: ...


def check() -> None:
    fixed: _schema._Fixed = fixed_file()
    accepts_located(fixed)
    accepts_located(fixed_dir())
    accepts_located(plain_files()[0])
    accepts_match(plain_files()[0])
    plain = plain_files()
    assert_type(plain[0], _schema._FileMatch)
    assert_type(plain[:], _schema._TemplateCollection[_schema._FileMatch])
    assert_type(plain.find(capture_predicate), _schema._FileMatch | None)
    assert_type(plain.filter(capture_predicate), Iterator[_schema._FileMatch])
    assert_type(plain[0].read_text(), str)
    assert_type(plain.format(), fss.SchemaRoot[fss.Schema])
    loaded = loaded_files()
    assert_type(loaded[0].load(), int | Exception)
    assert_type(loaded_file().load(), int | Exception)
    dirs = directories()
    assert_type(dirs[0], _schema._DirMatch)
    assert_type(dirs[:], _schema._TemplateCollection[_schema._DirMatch])
    assert_type(dirs.format(), fss.SchemaRoot[fss.Schema])
    entries = [
        _schema._ChildEntry(fixed_file(), "fixed.txt", "fixed"),
        _schema._ChildEntry(fixed_dir(), "directory", "directory_alias"),
        _schema._ChildEntry(plain_files(), "plain", "plain_alias"),
        _schema._ChildEntry(loaded_files(), "loaded", "loaded_alias"),
        _schema._ChildEntry(directories(), "dirs", "dirs_alias"),
    ]
    directory = _schema._FixedDir(Path("root"), entries)
    assert_type(len(directory), int)
    assert_type(directory[0], _schema.Child)
    assert_type(directory["fixed.txt"], _schema.Child)
    assert_type(directory.fixed, _schema.Child)
    assert_type(iter(directory), Iterator[_schema.Child])
    for child in directory:
        assert_type(child, _schema.Child)

    def decode(path: Path) -> int: ...

    assert_type(_ops.load(Path("value"), decode), int | Exception)
