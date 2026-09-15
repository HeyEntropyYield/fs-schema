import os
import re
import typing
from collections.abc import Callable, Iterator, Mapping, Sequence
from dataclasses import KW_ONLY, dataclass, field
from datetime import datetime
from pathlib import Path
from types import MappingProxyType
from typing import (
    TYPE_CHECKING,
    ClassVar,
    Final,
    ForwardRef,
    Generic,
    TypeAlias,
    final,
    overload,
)

from typing_extensions import (
    Protocol,
    Self,
    TypeVar,
    override,
    runtime_checkable,
)

from ._fmt import CaptureField, CaptureMap, CompiledFormat, FmtField, FmtLike, ParsedCaptures
from ._ops import MismatchErr, is_mismatch, load, put
from ._std_ext import CacheSeq
from ._types import LoadSpec, Located, PathIsh, Puttable

# The concrete Schema subtype is preserved by root and bind operations.
_S = TypeVar("_S", bound="Schema")
# Directory declarations only produce their Schema subtype.
_D_co = TypeVar("_D_co", bound="Schema", covariant=True)
# File declarations only produce _L_co through their load specification; no
# declaration API consumes it, so the parameter is safely covariant. This says
# nothing about mutability of the loaded value.
_L = TypeVar("_L")
_L_co = TypeVar("_L_co", covariant=True, default=object)
# Template collections only produce their concrete Match subtype.
_M_co = TypeVar("_M_co", bound="Match", covariant=True)


## Forward-safe cycle vocabulary


@runtime_checkable
class Match(Located, Protocol):
    @property
    def args(self) -> tuple[CaptureField, ...]: ...

    @property
    def kwargs(self) -> CaptureMap: ...


SortKey: TypeAlias = str | int | float | datetime | Located
SortFn: TypeAlias = Callable[[Match], SortKey]


@final
class _Selector:
    """One declaration's compiled basename selector."""

    __slots__: Final = ("_fmt", "_match")
    _fmt: CompiledFormat | None
    _match: re.Pattern[str] | None

    def __init__(self, fmt: FmtLike | None, match: str | None) -> None:
        self._fmt = CompiledFormat(fmt) if fmt is not None else None
        self._match = re.compile(match) if match is not None else None

    def captures(self, basename: str) -> ParsedCaptures | None:
        if self._fmt is not None:
            if (captures := self._fmt.parse(basename)) is None:
                return None
            return captures if self._match is None or self._match.fullmatch(basename) else None
        if self._match is None:
            return ParsedCaptures((), CaptureMap({}))
        if (matched := self._match.fullmatch(basename)) is None:
            return None
        named = set(matched.re.groupindex.values())
        return ParsedCaptures(
            tuple(value for index, value in enumerate(matched.groups(), 1) if index not in named),
            CaptureMap(matched.groupdict()),
        )


## User schema file/dir declarations


# Declaration specs. Only `name` is positional. Every declaration needs an
# exact-name, format, or regex selector. Exact names have cardinality one.
@dataclass(frozen=True, slots=True)
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
    _selector: _Selector = field(init=False, repr=False, compare=False)

    def __post_init__(self) -> None:
        selector, maximum = _validate_node(self)
        object.__setattr__(self, "_selector", selector)
        if self.max is None and maximum is not None:
            object.__setattr__(self, "max", maximum)

    def select(self, basename: str) -> ParsedCaptures | None:
        return self._selector.captures(basename)


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


## Reified definitions


@dataclass(frozen=True, slots=True, init=False)
class _DirDefn:
    defn: Dir["Schema"]
    defns: tuple["_Defn", ...]
    lookup: Mapping[str, int]

    def __init__(self, defn: Dir["Schema"], defns: "Sequence[File[object] | _DirDefn]" = ()) -> None:
        child_defns = tuple(defns)
        lookup: dict[str, int] = {}

        def add(key: str, index: int) -> None:
            if key in lookup and lookup[key] != index:
                raise ValueError(f"duplicate child key: {key!r}")
            lookup[key] = index

        for index, child_defn in enumerate(child_defns):
            node = _node(child_defn)
            if node.name:
                add(node.name, index)
                add(_normalize_name(node.name), index)
            if node.alias is not None:
                add(node.alias, index)
        object.__setattr__(self, "defn", defn)
        object.__setattr__(self, "defns", child_defns)
        object.__setattr__(self, "lookup", MappingProxyType(lookup))


_Defn: TypeAlias = File[object] | _DirDefn
_Defn_co = TypeVar("_Defn_co", covariant=True, default=_Defn)


## Runtime values


class _Fixed:
    _path: Path

    def __init__(self, path: PathIsh) -> None:
        self._path = Path(path)

    @property
    def path(self) -> Path:
        return self._path

    def __fspath__(self) -> str:
        return os.fspath(self.path)

    @override
    def __str__(self) -> str:
        return str(self.path)

    def __lt__(self, other: object) -> bool:
        path = getattr(other, "path", None)
        if not isinstance(path, Path):
            return NotImplemented
        return self.path < path

    @property
    def name(self) -> str:
        return self.path.name

    @property
    def stem(self) -> str:
        return self.path.stem

    @property
    def suffix(self) -> str:
        return self.path.suffix

    def exists(self) -> bool:
        return self.path.exists()


def _load_model(path: Path, schema: type[_L_co]) -> _L_co | Exception:
    return Exception(f"model schema codec connector is not connected for {path} ({schema.__name__})")


class _FixedFile(_Fixed, Generic[_L_co]):
    defn: File[_L_co]

    def __init__(self, path: PathIsh, defn: File[_L_co]) -> None:
        _Fixed.__init__(self, path)
        self.defn = defn

    def read_bytes(self) -> bytes:
        return self.path.read_bytes()

    def read_text(self) -> str:
        return self.path.read_text()

    def put(self, data: Puttable) -> None:
        put(self.path, data)

    def load(self) -> _L_co | Exception:
        schema = self.defn.schema
        if schema is None:
            return Exception(f"file has no declared loader: {self.path}")
        if isinstance(schema, type):
            return typing.cast(_L_co | Exception, _load_model(self.path, schema))
        return load(self.path, schema)

    def as_match(self, captures: ParsedCaptures) -> "_FileMatch[_L_co]":
        return _FileMatch(self.path, captures, self.defn)


def _normalize_name(name: str) -> str:
    return re.sub(r"[^A-Za-z0-9_]+", "_", name)


## Runtime template matches and collections


CapturePredicate: TypeAlias = Callable[[tuple[CaptureField, ...], CaptureMap], bool]


class _CaptureState:
    _captures: ParsedCaptures

    @property
    def args(self) -> tuple[CaptureField, ...]:
        return self._captures.args

    @property
    def kwargs(self) -> CaptureMap:
        return self._captures.kwargs


class _FileMatch(_CaptureState, _FixedFile[_L_co], Generic[_L_co]):
    def __init__(self, path: PathIsh, captures: ParsedCaptures, defn: File[_L_co]) -> None:
        _FixedFile.__init__(self, path, defn)
        self._captures: ParsedCaptures = captures


class _Matches(Sequence[_M_co], Generic[_M_co, _Defn_co]):
    path: Path
    _matches: tuple[_M_co, ...]
    defn: _Defn_co

    def __init__(self, path: PathIsh, matches: Sequence[_M_co], defn: _Defn_co) -> None:
        self.path = Path(path)
        self._matches = tuple(matches)
        self.defn = defn

    @overload
    def __getitem__(self, index: int) -> _M_co: ...

    @overload
    def __getitem__(self, index: slice) -> Self: ...

    @override
    def __getitem__(self, index: int | slice) -> _M_co | Self:
        if isinstance(index, slice):
            return type(self)(self.path, self._matches[index], self.defn)
        return self._matches[index]

    @override
    def __len__(self) -> int:
        return len(self._matches)

    def filter(self, predicate: CapturePredicate) -> Iterator[_M_co]:
        return (match for match in self._matches if predicate(match.args, match.kwargs))

    def find(self, predicate: CapturePredicate) -> _M_co | None:
        return next(self.filter(predicate), None)


class _Template(_Matches[_M_co, _Defn_co], Generic[_M_co, _Defn_co]):
    def format(self, *args: FmtField, **kwargs: FmtField) -> "SchemaRoot[Schema]":
        raise NotImplementedError


if TYPE_CHECKING:
    Child: TypeAlias = "_FixedFile[object] | _FixedDir | _Matches[_FileMatch[object] | _DirMatch]"
else:
    Child: TypeAlias = typing.Union[  # noqa: UP007
        _FixedFile[object],
        ForwardRef("fs_schema._schema._FixedDir"),
        _Matches[typing.Union[_FileMatch[object], ForwardRef("fs_schema._schema._DirMatch")]],  # noqa: UP007
    ]


class _FixedDir(_Fixed):
    _children: tuple[Child, ...]
    _lookup: Mapping[str, int]
    defn: _DirDefn

    def __init__(
        self,
        path: PathIsh,
        children: Sequence[Child],
        defn: _DirDefn,
    ) -> None:
        _Fixed.__init__(self, path)
        self._children = tuple(children)
        self._lookup = defn.lookup
        self.defn = defn

    def __iter__(self) -> Iterator[Child]:
        return iter(self._children)

    def __len__(self) -> int:
        return len(self._children)

    @overload
    def __getitem__(self, index: int) -> Child: ...

    @overload
    def __getitem__(self, index: str) -> Child: ...

    def __getitem__(self, index: int | str) -> Child:
        if isinstance(index, str):
            return self._children[self._lookup[index]]
        return self._children[index]

    def __getattr__(self, name: str) -> Child:
        try:
            child = self._children[self._lookup[name]]
        except KeyError:
            raise AttributeError(name) from None
        node = _node(child.defn)
        if name != node.alias and name != _normalize_name(node.name):
            raise AttributeError(name)
        return child

    def as_match(self, captures: ParsedCaptures) -> "_DirMatch":
        return _DirMatch(self.path, captures, self._children, self.defn)


class _DirMatch(_CaptureState, _FixedDir):
    def __init__(self, path: PathIsh, captures: ParsedCaptures, children: Sequence[Child], defn: _DirDefn) -> None:
        _FixedDir.__init__(self, path, children, defn)
        self._captures: ParsedCaptures = captures


def _node(defn: _Defn) -> Node:
    return defn if isinstance(defn, File) else defn.defn


def _validate_node(node: Node) -> tuple[_Selector, int | None]:
    if not any((node.name, node.fmt, node.match)):
        raise ValueError("declaration requires name, fmt, or match")
    if node.name and node.fmt is not None:
        raise ValueError("name cannot be combined with fmt")
    maximum = 1 if node.name and node.max is None else node.max
    if node.min < 0:
        raise ValueError("min must be at least zero")
    if maximum is not None and maximum < node.min:
        raise ValueError("max must be at least min")
    if node.name and (node.min != 1 or maximum != 1):
        raise ValueError("exact-name declarations require min=max=1")
    return _Selector(node.fmt, node.match), maximum


def _validate_schema_contract(path: Path, schema: type["Schema"]) -> MismatchErr | None:
    return MismatchErr(f"directory schema connector is not connected for {path} ({schema.__name__})")


def _is_kind(path: Path, defn: _Defn) -> bool:
    return path.is_file() if isinstance(defn, File) else path.is_dir()


_Listing: TypeAlias = CacheSeq[Path]


def _bind_dir(path: Path, dir_defn: _DirDefn) -> _FixedDir | MismatchErr:
    listing = CacheSeq(lambda: sorted(path.iterdir(), key=lambda entry: entry.name))

    # Wrapped in lambda instead of direct pass else beartype would eval it early
    def get_listing() -> _Listing:
        return listing

    children: list[Child] = []
    for position, defn in enumerate(dir_defn.defns):
        if is_mismatch(child := _bind_dir_defn(path, position, defn, get_listing)):
            return child
        children.append(child)

    if dir_defn.defn.schema is not None:
        if is_mismatch(mismatch := _validate_schema_contract(path, dir_defn.defn.schema)):
            return mismatch
    return _FixedDir(path, children, dir_defn)


def _bind_dir_defn(path: Path, position: int, defn: _Defn, listing: Callable[[], _Listing]) -> Child | MismatchErr:
    node = _node(defn)
    if node.name:
        target = path / node.name
        if node.select(target.name) is None:
            return MismatchErr(f"fixed basename does not match {node.match!r}: {target}")
        if not _is_kind(target, defn):
            kind = "file" if isinstance(defn, File) else "directory"
            return MismatchErr(f"expected {kind}: {target}")
        return _bind_fixed(target, defn)

    if is_mismatch(matches := _bind_matches(defn, listing())):
        return matches
    count = len(matches)
    if count < node.min or (node.max is not None and count > node.max):
        upper = "unbounded" if node.max is None else str(node.max)
        return MismatchErr(f"expected {node.min}..{upper} matches for defn {position}, found {count}: {path}")
    return _Template(path, matches, defn) if node.fmt is not None else _Matches(path, matches, defn)


@overload
def _bind_fixed(path: Path, defn: File[_L]) -> _FixedFile[_L]: ...


@overload
def _bind_fixed(path: Path, defn: _DirDefn) -> _FixedDir | MismatchErr: ...


def _bind_fixed(path: Path, defn: _Defn) -> _FixedFile[object] | _FixedDir | MismatchErr:
    if isinstance(defn, File):
        return _FixedFile(path, defn)
    return _bind_dir(path, defn)


@overload
def _bind_matches(defn: File[_L], listing: _Listing) -> Sequence[_FileMatch[_L]]: ...


@overload
def _bind_matches(defn: _DirDefn, listing: _Listing) -> Sequence[_DirMatch] | MismatchErr: ...


def _bind_matches(defn: _Defn, listing: _Listing) -> Sequence[_FileMatch[object] | _DirMatch] | MismatchErr:
    node = _node(defn)
    matches: list[_FileMatch[object] | _DirMatch] = []
    for target in listing:
        if (captures := node.select(target.name)) is None or not _is_kind(target, defn):
            continue
        if is_mismatch(fixed := _bind_fixed(target, defn)):
            return fixed
        matches.append(fixed.as_match(captures))

    if node.sort is not None:
        sort = typing.cast(Callable[[_FileMatch[object] | _DirMatch], typing.Any], node.sort)
        matches.sort(key=sort, reverse=node.sort_rev)
    else:
        captures = [match.args + tuple(match.kwargs.values()) for match in matches]
        if captures and all(len(values) == 1 and isinstance(values[0], datetime) for values in captures):
            order = sorted(range(len(matches)), key=captures.__getitem__, reverse=node.sort_rev)
            matches = [matches[index] for index in order]
        else:
            matches.sort(key=lambda match: match.path.name, reverse=node.sort_rev)
    return matches


def bind_defns(root: PathIsh, defns: Sequence[_Defn]) -> _FixedDir | MismatchErr:
    path = Path(root)
    if not path.is_dir():
        return MismatchErr(f"expected directory: {path}")
    return _bind_dir(path, _DirDefn(Dir(name="."), defns))


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
