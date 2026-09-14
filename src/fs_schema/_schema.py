import os
from collections.abc import Callable, Sequence
from dataclasses import KW_ONLY, dataclass
from datetime import datetime
from pathlib import Path
from typing import (
    ClassVar,
    Final,
    Generic,
    TypeAlias,
    TypeVar,
    final,
    overload,
)

from typing_extensions import (
    Protocol,
    Self,
    override,
    runtime_checkable,
)

from ._fmt import CaptureMap, FmtField
from ._ops import MismatchErr
from ._types import LoadSpec, Located, PathIsh, Puttable

# The concrete Schema subtype is preserved by root and bind operations.
_S = TypeVar("_S", bound="Schema")
# Directory declarations only produce their Schema subtype.
_D_co = TypeVar("_D_co", bound="Schema", covariant=True)
# File declarations only produce _L_co through their load specification; no
# declaration API consumes it, so the parameter is safely covariant. This says
# nothing about mutability of the loaded value.
_L_co = TypeVar("_L_co", covariant=True)
# Template collections only produce their concrete Match subtype.
_M_co = TypeVar("_M_co", bound="Match", covariant=True)


## Forward-safe cycle vocabulary


@runtime_checkable
class Match(Located, Protocol):
    @property
    def args(self) -> tuple[FmtField, ...]: ...

    @property
    def kwargs(self) -> CaptureMap: ...

    # Formatting a template candidate plans its associated root layout. It
    # intentionally drops any claim that a prior filesystem match still exists.
    def format(self, *args: FmtField, **kwargs: FmtField) -> "SchemaRoot[Schema]": ...


SortKey: TypeAlias = str | int | float | datetime | Located
SortFn: TypeAlias = Callable[[Match], SortKey]


## User schema file/dir declarations


# Declaration specs. Only `name` is positional. `name` and `fmt`/`match` are
# exclusive. `match` is re.fullmatch over basename. `max` defaults to 1 when
# named, else unbounded.
@dataclass(frozen=True, slots=True)
class Node:
    name: str = ""
    _: KW_ONLY
    fmt: str | None = None
    match: str | None = None
    min: int = 1
    max: int | None = None
    alias: str | None = None
    sort: SortFn | None = None
    sort_rev: bool = False

    def __post_init__(self) -> None:
        if self.name and (self.fmt is not None or self.match is not None):
            raise ValueError("name cannot be combined with fmt or match")
        maximum = 1 if self.name and self.max is None else self.max
        if self.min < 0:
            raise ValueError("min must be at least zero")
        if maximum is not None and maximum < self.min:
            raise ValueError("max must be at least min")
        if self.name and self.max is None:
            object.__setattr__(self, "max", maximum)


@dataclass(frozen=True, slots=True, kw_only=True)
class File(Node, Generic[_L_co]):
    schema: LoadSpec[_L_co] | None = None


@dataclass(frozen=True, slots=True, kw_only=True)
class Dir(Node, Generic[_D_co]):
    # Optional extra layout contract for whatever appears on this Dir's RHS.
    schema: type[_D_co] | None = None


@final
class FilesKey:
    __slots__ = ()

    @override
    def __repr__(self) -> str:
        return "FILES"


FILES: Final = FilesKey()

# Three kinds of mapping, and a dict cannot say that a key's type constrains
# its value's type:
#
#   Dir | str naming a dir  ->  DirRhs
#   FILES                   ->  FilesRhs
#   str aliasing a file     ->  FileRhs
#
# `Layout` is the loosest honest type, so it still rejects anything outside
# the unions. `LayoutEntry` is the truth, and is what the reifier matches on,
# which is where the remaining pairings are enforced. Recursive, so this whole
# family is static-only -- fine, since only ClassVar[Layout] ever uses it.
DirRhs: TypeAlias = "Layout | type[Schema]"
FileRhs: TypeAlias = str | File[object]
FilesRhs: TypeAlias = list[FileRhs]

LayoutKey: TypeAlias = "str | Dir[Schema] | FilesKey"
LayoutValue: TypeAlias = "DirRhs | FileRhs | FilesRhs"
Layout: TypeAlias = dict[LayoutKey, LayoutValue]

LayoutEntry: TypeAlias = "tuple[Dir[Schema] | str, DirRhs] | tuple[FilesKey, FilesRhs] | tuple[str, FileRhs]"


## Runtime fixed files and directories


class _Fixed:
    # Structural Located implementation: nominal Protocol inheritance would give
    # Schema(_FixedDir, metaclass=SchemaCls) an incompatible metaclass.
    @property
    def path(self) -> Path:
        raise NotImplementedError

    @property
    def _defn(self) -> Node:
        raise NotImplementedError

    def __fspath__(self) -> str:
        return os.fspath(self.path)

    def __lt__(self, other: object) -> bool:
        # runtime_checkable protocols only test member presence, not types.
        path = getattr(other, "path", None)
        if not isinstance(path, Path):
            return NotImplemented
        return self.path < path

    def exists(self) -> bool:
        return self.path.exists()


class _FixedFile(_Fixed):
    @property
    @override
    def _defn(self) -> File[object]:
        raise NotImplementedError

    def read_bytes(self) -> bytes:
        raise NotImplementedError

    def read_text(self) -> str:
        raise NotImplementedError

    def put(self, data: Puttable) -> None:
        raise NotImplementedError


class _LoadableFile(_FixedFile, Generic[_L_co]):
    def load(self) -> _L_co | Exception:
        raise NotImplementedError


class _FixedDir(_Fixed):
    @property
    @override
    def _defn(self) -> "Dir[Schema]":
        raise NotImplementedError

    def __getattr__(self, name: str) -> "Child":
        raise NotImplementedError

    def __getitem__(self, key: str | int) -> "Child":
        raise NotImplementedError


## Runtime template matches and collections


class _MatchBase:
    @property
    def args(self) -> tuple[FmtField, ...]:
        raise NotImplementedError

    @property
    def kwargs(self) -> CaptureMap:
        raise NotImplementedError


class _FileMatch(_MatchBase, _FixedFile):
    def format(self, *args: FmtField, **kwargs: FmtField) -> "SchemaRoot[Schema]":
        raise NotImplementedError


class _LoadableFileMatch(_MatchBase, _LoadableFile[_L_co], Match, Generic[_L_co]):
    @override
    def format(self, *args: FmtField, **kwargs: FmtField) -> "SchemaRoot[Schema]":
        raise NotImplementedError


class _DirMatch(_MatchBase, _FixedDir):
    def format(self, *args: FmtField, **kwargs: FmtField) -> "SchemaRoot[Schema]":
        raise NotImplementedError


class _TemplateCollection(Sequence[_M_co], Generic[_M_co]):
    path: Path

    @overload
    def __getitem__(self, index: int) -> _M_co: ...

    @overload
    def __getitem__(self, index: slice) -> Self: ...

    @override
    def __getitem__(self, index: int | slice) -> _M_co | Self:
        raise NotImplementedError

    @override
    def __len__(self) -> int:
        raise NotImplementedError

    def filter(self, *args: FmtField, **kwargs: FmtField) -> tuple[_M_co, ...]:
        raise NotImplementedError

    def find(self, *args: FmtField, **kwargs: FmtField) -> _M_co | MismatchErr:
        raise NotImplementedError

    def format(self, *args: FmtField, **kwargs: FmtField) -> "SchemaRoot[Schema]":
        raise NotImplementedError


Child: TypeAlias = (
    _FixedFile
    | _LoadableFile[object]
    | _FixedDir
    | _TemplateCollection[_FileMatch]
    | _TemplateCollection[_LoadableFileMatch[object]]
    | _TemplateCollection[_DirMatch]
)


## Schemas


# Class-level surface. A metaclass because __getattr__ on a parent serves
# instances, so `MySchema.dir` would not resolve. __new__ reifies `schema`
# once, caching a child class per node in declaration order.
class SchemaCls(type):
    # Must raise for any name it does not own. beartype probes __parameters__
    # on every hint, and resolves forward refs by attribute lookup, so a
    # catch-all here surfaces as an error inside unrelated functions.
    def __getattr__(cls, name: str) -> "type[Schema]":
        raise AttributeError(name)

    # For `def f(x: "MySchema.RootT")`. Widens to SchemaRoot[Schema]; prefer
    # fss.SchemaRoot[MySchema] where a checker should see the exact schema.
    @property
    def RootT(cls) -> "type[SchemaRoot[Schema]]":
        raise NotImplementedError


# A layout pointed at a root. Paths are known, nothing is checked, and the
# schema is carried in the parameter so bind() returns that type.
class SchemaRoot(_FixedDir, Generic[_S]):
    # Planned implicit dot directory. It is a concrete Located directory, but
    # bind() is the transition that verifies its declared layout.
    def bind(self) -> "_S | MismatchErr":
        raise NotImplementedError


class Schema(_FixedDir, metaclass=SchemaCls):
    # Validated implicit dot directory. Reified children carry the file,
    # collection, and match capabilities appropriate to their declarations.
    schema: ClassVar["Layout"]

    @classmethod
    def relative_to(cls: type[_S], root: PathIsh) -> "SchemaRoot[_S]":
        raise NotImplementedError

    @classmethod
    def bind(cls: type[_S], root: PathIsh | Located) -> "_S | MismatchErr":
        raise NotImplementedError

    def root(self) -> "SchemaRoot[Self]":
        raise NotImplementedError
