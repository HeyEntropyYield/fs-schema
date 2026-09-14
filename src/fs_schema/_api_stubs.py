import os
from collections.abc import Callable, Iterator, Mapping, Sequence
from dataclasses import KW_ONLY, Field, dataclass
from datetime import datetime
from pathlib import Path
from typing import ClassVar, Final, Generic, TypeAlias, TypeVar, final, overload

from typing_extensions import Protocol, Self, TypeIs, override, runtime_checkable

_T = TypeVar("_T")
_S = TypeVar("_S", bound="Schema")
_D_co = TypeVar("_D_co", bound="Schema", covariant=True)
_L = TypeVar("_L")
# File declarations only produce _L_co through their load specification; no
# declaration API consumes it, so the parameter is safely covariant. This says
# nothing about mutability of the loaded value.
_L_co = TypeVar("_L_co", covariant=True)
_M_co = TypeVar("_M_co", bound="Match", covariant=True)

# Two classes of alias here, and mixing them up silently disables beartype.
# Anything reachable from a runtime-checked signature is built from real
# objects, which is what drives the definition order in this file. Aliases
# that are recursive cannot be, and are static-only.
PathIsh: TypeAlias = str | os.PathLike[str]


def exists_opt(path: PathIsh) -> Path | None:
    raise NotImplementedError


# Static-only. beartype cannot resolve a forward reference that names an alias
# rather than a class, so never annotate a checked signature with these.
Json: TypeAlias = dict[str, "Json"] | list["Json"] | str | int | float | bool | None
JsonRo: TypeAlias = Mapping[str, "JsonRo"] | Sequence["JsonRo"] | str | int | float | bool | None
JsonObj: TypeAlias = dict[str, Json]

# TODO: namefmt.Fmt (parse + format). A str pattern is the handle today.
FmtLike: TypeAlias = str


def dt(pattern: str) -> FmtLike:
    return f"{{:{pattern}}}"


class MismatchErr(Exception):
    pass


def is_mismatch(x: object) -> TypeIs[MismatchErr]:
    raise NotImplementedError


def raise_mismatch(x: _T | MismatchErr) -> _T:
    raise NotImplementedError


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
LoadSpec: TypeAlias = type[_L] | Callable[[Path], _L]


# Public structural vocabulary for one path. Concrete fs-schema values add
# convenience methods such as exists() and path ordering through _Fixed.
@runtime_checkable
class Located(Protocol):
    @property
    def path(self) -> Path: ...

    def __fspath__(self) -> str: ...


## Runtime template collection matches

# A parsed template field: {n:d} -> int, {stem} -> str, dt() -> datetime.
FmtField: TypeAlias = str | int | datetime


class CaptureMap(Mapping[str, FmtField]):
    @override
    def __getitem__(self, key: str) -> FmtField:
        raise NotImplementedError

    @override
    def __iter__(self) -> Iterator[str]:
        raise NotImplementedError

    @override
    def __len__(self) -> int:
        raise NotImplementedError

    def __getattr__(self, name: str) -> FmtField:
        raise NotImplementedError


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


## User schema file/dir defs


# Declaration specs. Only `name` is positional. `name` and `fmt`/`match` are
# exclusive. `match` is re.fullmatch over basename. `max` defaults to 1 when
# named, else unbounded.
@dataclass(frozen=True)
class Node:
    name: str = ""
    _: KW_ONLY
    fmt: FmtLike | None = None
    match: str | None = None
    min: int = 1
    max: int | None = None
    alias: str | None = None
    sort: SortFn | None = None
    sort_rev: bool = False


@dataclass(frozen=True, kw_only=True)
class File(Node, Generic[_L_co]):
    schema: LoadSpec[_L_co] | None = None


@dataclass(frozen=True, kw_only=True)
class Dir(Node, Generic[_D_co]):
    # Optional extra layout contract for whatever appears on this Dir's RHS.
    schema: type[_D_co] | None = None


## Runtime access


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


@final
class FilesKey:
    __slots__ = ()

    @override
    def __repr__(self) -> str:
        return "FILES"

    @override
    def __hash__(self) -> int:
        return hash("FILES")

    @override
    def __eq__(self, other: object) -> bool:
        return isinstance(other, FilesKey)


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


## Codecs, put, load


def put(path: PathIsh, data: Puttable) -> None:
    # Creates missing parent directories.
    raise NotImplementedError


def load(path: PathIsh, decoder: Callable[[Path], _L]) -> _L | Exception:
    raise NotImplementedError
