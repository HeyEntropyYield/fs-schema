import os
from collections.abc import Callable, Mapping, Sequence
from dataclasses import Field
from pathlib import Path
from typing import ClassVar, TypeAlias, TypeVar

from typing_extensions import Protocol, runtime_checkable

# The invariant load value links LoadSpec callables to low-level load results.
LoadT = TypeVar("LoadT")

PathIsh: TypeAlias = str | os.PathLike[str]

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
