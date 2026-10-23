import os
from collections.abc import Callable, Mapping, Sequence
from dataclasses import Field
from datetime import datetime
from pathlib import Path
from typing import ClassVar, Generic, NewType, TypeAlias, TypeVar

from typing_extensions import Protocol, Self, runtime_checkable

# The invariant load value links LoadSpec callables to low-level load results.
LoadT = TypeVar("LoadT")
_K = TypeVar("_K")


class _Text(str, Generic[_K]):
    def __new__(cls, value: str) -> Self:
        return str.__new__(cls, value)


class Raw(_Text[_K]):
    """Boundary text. Not checked"""


class Open(Raw[_K]):
    """Checked text. A ref may remain"""


class Resolved(Raw[_K]):
    """No refs left. Not checked as one path component"""


class Safe(Resolved[_K], Open[_K]):
    """One path component. Passable as Open or Resolved"""


class Name:
    """basename"""


class FmtStr:
    """format pattern"""


class MatchPat:
    """match regex"""


SafePath = NewType("SafePath", Path)

PathIsh: TypeAlias = str | os.PathLike[str]
# A parsed template field: {n:d} -> int, {stem} -> str, dt() -> datetime
FmtFieldT: TypeAlias = str | int | datetime
FmtFields: TypeAlias = Mapping[str, FmtFieldT]
# field_name -> field_spec. field_spec is the text after {field_name:}, or ""
FieldSpecs: TypeAlias = dict[str, str]

Json: TypeAlias = dict[str, "Json"] | list["Json"] | str | int | float | bool | None
JsonRo: TypeAlias = Mapping[str, "JsonRo"] | Sequence["JsonRo"] | str | int | float | bool | None
JsonObj: TypeAlias = dict[str, Json]


@runtime_checkable
class HasSave(Protocol):
    def save(self, path: Path) -> None: ...


@runtime_checkable
class DataclassInstance(Protocol):
    __dataclass_fields__: ClassVar["dict[str, Field[object]]"]


FileBody: TypeAlias = bytes | str | Path
Puttable: TypeAlias = FileBody | HasSave | DataclassInstance

CreateValue: TypeAlias = Puttable | Mapping[str, "CreateValue"] | Sequence[tuple[FmtFields, "CreateValue"]] | None
CreateTop: TypeAlias = Puttable | PathIsh | Mapping[str, object] | Sequence[object] | None

# A class is resolved through the target file's format codec. With the
# mashumaro extra, plain dataclasses work without mixins. A callable is an
# explicit path loader.
LoadSpec: TypeAlias = type[LoadT] | Callable[[Path], LoadT]


# Public structural vocabulary for one path. Concrete fs-schema values add
# convenience methods such as exists() and path ordering through _Fixed.
@runtime_checkable
class Located(Protocol):
    @property
    def path(self) -> Path: ...

    def __fspath__(self) -> str: ...


# A bound file a caller can pass without naming _ChildView. Narrow on purpose:
# the full view is not one runtime object, so it cannot be runtime_checkable.
_LoadAsT = TypeVar("_LoadAsT")


@runtime_checkable
class Loadable(Protocol):
    def load(self, model: type[_LoadAsT]) -> _LoadAsT | Exception: ...
