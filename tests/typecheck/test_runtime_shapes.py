# Static assert_type fixture: basedpyright checks this module; pytest does not execute check().
# pyright: reportPrivateUsage=false, reportUnusedParameter=false
from pathlib import Path

from typing_extensions import assert_type

import fs_schema as fss
from fs_schema._api_stubs import (
    _DirMatch,
    _FileMatch,
    _Fixed,
    _FixedDir,
    _FixedFile,
    _LoadableFile,
    _LoadableFileMatch,
    _TemplateCollection,
    load,
)


def accepts_located(value: fss.Located) -> None: ...
def accepts_match(value: fss.Match) -> None: ...
def plain_files() -> _TemplateCollection[_FileMatch]: ...
def loaded_files() -> _TemplateCollection[_LoadableFileMatch[int]]: ...
def directories() -> _TemplateCollection[_DirMatch]: ...
def fixed_file() -> _FixedFile: ...
def loaded_file() -> _LoadableFile[int]: ...
def fixed_dir() -> _FixedDir: ...


def check() -> None:
    fixed: _Fixed = fixed_file()
    accepts_located(fixed)
    accepts_located(fixed_dir())
    accepts_located(plain_files()[0])
    accepts_match(plain_files()[0])
    plain = plain_files()
    assert_type(plain[0], _FileMatch)
    assert_type(plain[:], _TemplateCollection[_FileMatch])
    assert_type(plain.find(), _FileMatch | fss.MismatchErr)
    assert_type(plain.filter(), tuple[_FileMatch, ...])
    assert_type(plain[0].read_text(), str)
    assert_type(plain.format(), fss.SchemaRoot[fss.Schema])
    loaded = loaded_files()
    assert_type(loaded[0].load(), int | Exception)
    assert_type(loaded_file().load(), int | Exception)
    dirs = directories()
    assert_type(dirs[0], _DirMatch)
    assert_type(dirs[:], _TemplateCollection[_DirMatch])
    assert_type(dirs.format(), fss.SchemaRoot[fss.Schema])
    assert_type(
        fixed_dir()["child"],
        _FixedFile
        | _LoadableFile[object]
        | _FixedDir
        | _TemplateCollection[_FileMatch]
        | _TemplateCollection[_LoadableFileMatch[object]]
        | _TemplateCollection[_DirMatch],
    )

    def decode(path: Path) -> int: ...

    assert_type(load(Path("value"), decode), int | Exception)
