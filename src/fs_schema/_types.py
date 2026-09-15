import os
from collections.abc import Callable, Mapping, Sequence
from dataclasses import Field
from pathlib import Path
from typing import ClassVar, TypeAlias, TypeVar

from typing_extensions import Protocol, runtime_checkable

# The invariant load value links LoadSpec callables to low-level load results.
LoadT = TypeVar("LoadT")

# Two classes of alias here, and mixing them up silently disables beartype.
# Anything reachable from a runtime-checked signature is built from real
# objects, which is what drives the defn order in this file. Aliases
# that are recursive cannot be, and are static-only.
PathIsh: TypeAlias = str | os.PathLike[str]

# Static-only. beartype cannot resolve a forward reference that names an alias
# rather than a class, so never annotate a checked signature with these.
Json: TypeAlias = dict[str, "Json"] | list["Json"] | str | int | float | bool | None
JsonRo: TypeAlias = Mapping[str, "JsonRo"] | Sequence["JsonRo"] | str | int | float | bool | None
JsonObj: TypeAlias = dict[str, Json]


# beartype checks Protocol params via isinstance. Bare Protocol is static-only.
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
