import os
import re
import typing
from collections.abc import Callable, Iterator, Mapping, Sequence
from dataclasses import KW_ONLY, InitVar, dataclass, field
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

from plum import dispatch
from typing_extensions import (
    Protocol,
    Self,
    TypeIs,
    TypeVar,
    override,
    runtime_checkable,
)

from ._fmt import CaptureField, CaptureMap, FmtField, FmtLike, ParsedCaptures
from ._ops import MismatchErr, is_mismatch, load, put
from ._selector import Selector
from ._std_ext import CacheSeq
from ._types import CreateTop, CreateValue, LoadSpec, Located, PathIsh, Puttable

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
_Default = TypeVar("_Default")


# Section order:
#   Forward-safe cycle vocabulary. Match protocol, sort key.
#   User schema file/dir declarations. Node, File, Dir, FILES, Layout.
#   Reified definitions. DirDefn and Defn.
#   Runtime values. Path passthrough and FixedFile.
#   Runtime template matches and collections. Matches, Template, Child.
#   Fixed directories. FixedDir and directory matches.
#   Plan, format, and create. Planned tree, stamps, write_plan.
#   Names, captures, and declaration checks.
#   Bind. A directory listing becomes bound nodes or MismatchErr.
#   Schema classes. SchemaCls, SchemaRoot, Schema.
# Compilation and class member views live in _compile.py.


## Forward-safe cycle vocabulary


@runtime_checkable
class Match(Located, Protocol):
    @property
    def args(self) -> tuple[CaptureField, ...]: ...

    @property
    def kwargs(self) -> CaptureMap: ...


SortKey: TypeAlias = str | int | float | datetime | Located
SortFn: TypeAlias = Callable[[Match], SortKey]


## User schema file/dir declarations


# Declaration specs. Exact names are positional scalars (max implicit 1).
# Collections are keyword-only and need fmt and/or match.
# `optional` is InitVar: exact ctor sugar for min=0, not stored, not on collections.
@dataclass(frozen=True, slots=True)
class Node:
    name: str = ""
    _: KW_ONLY
    fmt: FmtLike | None = None
    match: str | None = None
    min: int = 1
    max: int | None = None
    alias: str | None = None
    optional: InitVar[bool] = False
    sort: SortFn | None = None
    sort_rev: bool = False
    skip_mismatch: bool = False
    _selector: Selector = field(init=False, repr=False, compare=False)

    def __post_init__(self, optional: bool) -> None:
        if optional:
            if not self.name:
                raise ValueError("optional is only valid for exact-name declarations")
            object.__setattr__(self, "min", 0)
        selector, maximum = _validate_node(self)
        object.__setattr__(self, "_selector", selector)
        if self.max is None and maximum is not None:
            object.__setattr__(self, "max", maximum)

    def select(self, basename: str) -> ParsedCaptures | None:
        return self._selector.captures(basename)


@dataclass(frozen=True, slots=True, kw_only=True)
class File(Node, Generic[_L_co]):
    schema: LoadSpec[_L_co] | None = None

    # Overloads are static. A runtime overload stack would replace the generated __init__.
    if TYPE_CHECKING:

        @overload
        def __init__(
            self,
            name: str,
            *,
            alias: str | None = None,
            match: str | None = None,
            optional: bool = False,
            schema: LoadSpec[_L_co] | None = None,
        ) -> None: ...

        @overload
        def __init__(
            self,
            *,
            fmt: FmtLike,
            match: str | None = None,
            min: int = 1,
            max: int | None = None,
            alias: str | None = None,
            sort: SortFn | None = None,
            sort_rev: bool = False,
            skip_mismatch: bool = False,
            schema: LoadSpec[_L_co] | None = None,
        ) -> None: ...

        @overload
        def __init__(
            self,
            *,
            match: str,
            fmt: None = None,
            min: int = 1,
            max: int | None = None,
            alias: str | None = None,
            sort: SortFn | None = None,
            sort_rev: bool = False,
            skip_mismatch: bool = False,
            schema: LoadSpec[_L_co] | None = None,
        ) -> None: ...

        def __init__(self, *args: object, **kwargs: object) -> None: ...  # pyright: ignore[reportMissingSuperCall]


@dataclass(frozen=True, slots=True, kw_only=True)
class Dir(Node, Generic[_D_co]):
    # Optional extra layout contract for whatever appears on this Dir's RHS.
    schema: type[_D_co] | None = None

    if TYPE_CHECKING:

        @overload
        def __init__(
            self,
            name: str,
            *,
            alias: str | None = None,
            match: str | None = None,
            optional: bool = False,
            schema: type[_D_co] | None = None,
        ) -> None: ...

        @overload
        def __init__(
            self,
            *,
            fmt: FmtLike,
            match: str | None = None,
            min: int = 1,
            max: int | None = None,
            alias: str | None = None,
            sort: SortFn | None = None,
            sort_rev: bool = False,
            skip_mismatch: bool = False,
            schema: type[_D_co] | None = None,
        ) -> None: ...

        @overload
        def __init__(
            self,
            *,
            match: str,
            fmt: None = None,
            min: int = 1,
            max: int | None = None,
            alias: str | None = None,
            sort: SortFn | None = None,
            sort_rev: bool = False,
            skip_mismatch: bool = False,
            schema: type[_D_co] | None = None,
        ) -> None: ...

        def __init__(self, *args: object, **kwargs: object) -> None: ...  # pyright: ignore[reportMissingSuperCall]


@final
class FilesKey:
    __slots__: Final = ()

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
class DirDefn:
    defn: Dir["Schema"]
    defns: tuple["Defn", ...]
    lookup: Mapping[str, int]
    child_type: "type[Schema] | None"

    def __init__(
        self,
        defn: Dir["Schema"],
        defns: "Sequence[File[object] | DirDefn]" = (),
        child_type: "type[Schema] | None" = None,
    ) -> None:
        child_defns = tuple(defns)
        lookup: dict[str, int] = {}
        identities: dict[str, int] = {}

        def add(target: dict[str, int], key: str, index: int) -> None:
            if key in target and target[key] != index:
                raise ValueError(f"duplicate child key: {key!r}")
            target[key] = index

        for index, child_defn in enumerate(child_defns):
            node = defn_node(child_defn)
            for identity in dict.fromkeys(
                key
                for key in (node.alias, node.name, normalize_name(node.name) if node.name else None, node.fmt)
                if key
            ):
                add(identities, identity, index)
            if node.name:
                add(lookup, node.name, index)
                add(lookup, normalize_name(node.name), index)
            if node.alias:
                add(lookup, node.alias, index)
        object.__setattr__(self, "defn", defn)
        object.__setattr__(self, "defns", child_defns)
        object.__setattr__(self, "lookup", MappingProxyType(lookup))
        object.__setattr__(self, "child_type", child_type)


Defn: TypeAlias = File[object] | DirDefn
_Defn_co = TypeVar("_Defn_co", bound=Defn, covariant=True, default=Defn)


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

    def __bool__(self) -> typing.Literal[True]:
        return True


def _load_model(path: Path, schema: type[_L_co]) -> _L_co | Exception:
    return load(path, schema)


class FixedFile(_Fixed, Generic[_L_co]):
    alias: ClassVar[str | None]
    fmt: ClassVar[FmtLike | None]
    match: ClassVar[str | None]
    min: ClassVar[int]
    max: ClassVar[int | None]
    defn: File[_L_co]

    def __init__(self, path: PathIsh, defn: File[_L_co]) -> None:
        _Fixed.__init__(self, path)
        self.defn = defn

    def read_bytes(self) -> bytes:
        return self.path.read_bytes()

    def read_text(self) -> str:
        return self.path.read_text()

    def create(self, data: Puttable | None = None) -> Self:
        put(self.path, data)
        return self

    def load(self) -> _L_co | Exception:
        schema = self.defn.schema
        if schema is None:
            return Exception(f"file has no declared loader: {self.path}")
        if isinstance(schema, type):
            return typing.cast(_L_co | Exception, _load_model(self.path, schema))
        return load(self.path, schema)


def normalize_name(name: str) -> str:
    return re.sub(r"[^A-Za-z0-9_]+", "_", name)


## Runtime template matches and collections


CapturePredicate: TypeAlias = Callable[[tuple[CaptureField, ...], CaptureMap], bool]


def _capture_values_match(
    captured_args: tuple[CaptureField, ...],
    captured_kwargs: CaptureMap,
    args: tuple[CaptureField, ...],
    kwargs: Mapping[str, CaptureField],
) -> bool:
    if len(args) > len(captured_args):
        return False
    if any(expected is not None and actual != expected for actual, expected in zip(captured_args, args, strict=False)):
        return False
    return all(captured_kwargs[name] == value for name, value in kwargs.items())


@final
class _MissingDefault:
    __slots__: Final = ()


_MISSING_DEFAULT: Final = _MissingDefault()


class _CaptureState:
    _captures: ParsedCaptures

    @property
    def args(self) -> tuple[CaptureField, ...]:
        return self._captures.args

    @property
    def kwargs(self) -> CaptureMap:
        return self._captures.kwargs


class _FileMatch(_CaptureState, FixedFile[_L_co], Generic[_L_co]):
    def __init__(self, path: PathIsh, captures: ParsedCaptures, defn: File[_L_co]) -> None:
        FixedFile.__init__(self, path, defn)
        self._captures: ParsedCaptures = captures


class Matches(Sequence[_M_co], Generic[_M_co, _Defn_co]):
    alias: ClassVar[str | None]
    fmt: ClassVar[FmtLike | None]
    match: ClassVar[str | None]
    min: ClassVar[int]
    max: ClassVar[int | None]
    path: Path
    _matches: tuple[_M_co, ...]
    defn: _Defn_co

    stamps: dict[str, FmtField]

    def __init__(
        self,
        path: PathIsh,
        matches: Sequence[_M_co],
        defn: _Defn_co,
        stamps: Mapping[str, FmtField] | None = None,
    ) -> None:
        self.path = Path(path)
        self._matches = tuple(matches)
        self.defn = defn
        self.stamps = dict(stamps or {})

    @overload
    def __getitem__(self, index: int) -> _M_co: ...

    @overload
    def __getitem__(self, index: slice) -> Self: ...

    @override
    def __getitem__(self, index: int | slice) -> _M_co | Self:
        if isinstance(index, slice):
            return type(self)(self.path, self._matches[index], self.defn, self.stamps)
        return self._matches[index]

    @override
    def __len__(self) -> int:
        return len(self._matches)

    def filter(self, predicate: CapturePredicate, /) -> Self:
        return type(self)(
            self.path,
            tuple(match for match in self._matches if predicate(match.args, match.kwargs)),
            self.defn,
            self.stamps,
        )

    def find(self, predicate: CapturePredicate, /) -> _M_co | None:
        return next((match for match in self._matches if predicate(match.args, match.kwargs)), None)

    def where(self, *args: CaptureField, **kwargs: CaptureField) -> Self:
        validate_capture_names(self.defn, kwargs)
        return self.filter(
            lambda captured_args, captured_kwargs: _capture_values_match(captured_args, captured_kwargs, args, kwargs)
        )

    @overload
    def get(self, index: int = 0) -> _M_co | None: ...

    @overload
    def get(self, index: int, default: _Default) -> _M_co | _Default: ...

    @overload
    def get(self, *, default: _Default) -> _M_co | _Default: ...

    def get(self, index: int = 0, default: _Default | _MissingDefault = _MISSING_DEFAULT) -> _M_co | _Default | None:
        try:
            return self._matches[index]
        except IndexError:
            if default is _MISSING_DEFAULT:
                return None
            return typing.cast(_Default, default)

    @overload
    def parse(self: "Matches[_FileMatch[_L], File[_L]]", basename: str) -> FixedFile[_L]: ...

    @overload
    def parse(self: "Matches[_DirMatch, DirDefn]", basename: str) -> "FixedDir": ...

    def parse(self, basename: str) -> "FixedFile[object] | FixedDir":
        if not is_safe_basename(basename) or defn_node(self.defn).select(basename) is None:
            raise ValueError(f"member {basename!r} does not match")
        return plan_fixed(self.path / basename, self.defn)


class Template(Matches[_M_co, _Defn_co], Generic[_M_co, _Defn_co]):
    @overload
    def format(self: "Template[_FileMatch[_L], File[_L]]", *args: FmtField, **kwargs: FmtField) -> FixedFile[_L]: ...

    @overload
    def format(self: "Template[_DirMatch, DirDefn]", *args: FmtField, **kwargs: FmtField) -> "FixedDir": ...

    def format(self, *args: FmtField, **kwargs: FmtField) -> "FixedFile[object] | FixedDir":
        return format_any(self, *args, **kwargs)


if TYPE_CHECKING:
    Child: TypeAlias = "FixedFile[object] | FixedDir | Matches[_FileMatch[object] | _DirMatch]"
    # LUB of mixed slots. Optional exact may be None; required/collection never.
    BoundChild: TypeAlias = "Child | None"
    GetChild: TypeAlias = Child
else:
    Child: TypeAlias = typing.Union[  # noqa: UP007
        FixedFile[object],
        ForwardRef("fs_schema._schema.FixedDir"),
        Matches[typing.Union[_FileMatch[object], ForwardRef("fs_schema._schema._DirMatch")]],  # noqa: UP007
    ]
    BoundChild: TypeAlias = Child | None
    GetChild: TypeAlias = BoundChild


## Fixed directories


class FixedDir(_Fixed):
    alias: ClassVar[str | None]
    fmt: ClassVar[FmtLike | None]
    match: ClassVar[str | None]
    min: ClassVar[int]
    max: ClassVar[int | None]
    _children: tuple[BoundChild, ...]
    _lookup: Mapping[str, int]
    stamps: dict[str, FmtField]
    defn: DirDefn

    def __init__(
        self,
        path: PathIsh,
        children: Sequence[BoundChild],
        defn: DirDefn,
        stamps: Mapping[str, FmtField] | None = None,
    ) -> None:
        _Fixed.__init__(self, path)
        self._children = tuple(children)
        self._lookup = defn.lookup
        self.defn = defn
        self.stamps = dict(stamps or {})

    def __iter__(self) -> Iterator[GetChild]:
        return iter(typing.cast(tuple[GetChild, ...], typing.cast(object, self._children)))

    def __len__(self) -> int:
        return len(self._children)

    @overload
    def __getitem__(self, index: int) -> GetChild: ...

    @overload
    def __getitem__(self, index: str) -> GetChild: ...

    def __getitem__(self, index: int | str) -> GetChild:
        child = self._children[self._lookup[index]] if isinstance(index, str) else self._children[index]
        return typing.cast(GetChild, typing.cast(object, child))

    def __getattr__(self, name: str) -> GetChild:
        try:
            index = self._lookup[name]
        except KeyError:
            raise AttributeError(name) from None
        child = self._children[index]
        defn = self.defn.defns[index] if child is None else child.defn
        node = defn_node(defn)
        if name != node.alias and name != normalize_name(node.name):
            raise AttributeError(name)
        return typing.cast(GetChild, typing.cast(object, child))

    @overload
    def create(  # pyright: ignore[reportInconsistentOverload]
        self,
        spec: Mapping[str, CreateValue] | None = None,
        /,
        **children: CreateValue,
    ) -> Self: ...

    def create(self, spec: Mapping[str, CreateTop] | None = None, /, **children: CreateTop) -> Self:
        write_plan(self, spec, **children)
        return self


class _DirMatch(_CaptureState, FixedDir):
    def __init__(self, path: PathIsh, captures: ParsedCaptures, children: Sequence[BoundChild], defn: DirDefn) -> None:
        FixedDir.__init__(self, path, children, defn)
        self._captures: ParsedCaptures = captures


_BOUND_MATCH: Final = "_fs_schema_bound_match"


def _is_bound_dir_match_type(value: object, schema_type: type) -> TypeIs[type[_DirMatch]]:
    return isinstance(value, type) and issubclass(value, schema_type) and issubclass(value, _DirMatch)


def _bound_dir_match_type(defn: DirDefn) -> type[_DirMatch]:
    schema_type = defn.child_type
    if schema_type is None:
        return _DirMatch
    cached = vars(schema_type).get("_bound_match_type")
    if _is_bound_dir_match_type(cached, schema_type):
        return cached
    generated = SchemaCls(
        f"{schema_type.__name__}Match",
        (schema_type, _DirMatch),
        {
            "__module__": schema_type.__module__,
            "__qualname__": f"{schema_type.__qualname__}Match",
            _BOUND_MATCH: True,
            "__init__": _DirMatch.__init__,
        },
    )
    if not _is_bound_dir_match_type(generated, schema_type):
        raise AssertionError("bound match type must subclass schema and _DirMatch")
    type.__setattr__(schema_type, "_bound_match_type", generated)
    return generated


## Plan, format, and create


def _plan_children(path: Path, dir_defn: DirDefn) -> tuple[Child, ...]:
    return tuple(_plan_dir_defn(path, defn) for defn in dir_defn.defns)


def _plan_dir_defn(path: Path, defn: Defn) -> Child:
    node = defn_node(defn)
    if node.name:
        return plan_fixed(path / node.name, defn)
    return Template(path, (), defn) if node.fmt is not None else Matches(path, (), defn)


@overload
def plan_fixed(path: Path, defn: File[_L]) -> FixedFile[_L]: ...


@overload
def plan_fixed(path: Path, defn: DirDefn) -> FixedDir: ...


def plan_fixed(path: Path, defn: Defn) -> FixedFile[object] | FixedDir:
    return _plan_fixed(path, defn)  # pyright: ignore[reportArgumentType]


@dispatch
def _plan_fixed(path: Path, defn: File) -> FixedFile:  # pyright: ignore[reportRedeclaration]
    return FixedFile(path, defn)


@dispatch
def _plan_fixed(path: Path, defn: DirDefn) -> FixedDir:
    return FixedDir(path, _plan_children(path, defn), defn)


def _stamp_tree(directory: FixedDir, stamps: Mapping[str, FmtField]) -> None:
    directory.stamps = dict(stamps)
    for child in directory._children:  # pyright: ignore[reportPrivateUsage]
        if isinstance(child, FixedDir):
            _stamp_tree(child, stamps)
        elif isinstance(child, Matches):
            child.stamps = dict(stamps)


def format_any(
    template: "Template[Match, Defn]",
    *args: FmtField,
    **kwargs: FmtField,
) -> "FixedFile[object] | FixedDir":
    for name, value in kwargs.items():
        if name in template.stamps and template.stamps[name] != value:
            raise ValueError(f"capture {name!r} disagrees with the enclosing stamp")
    node = defn_node(template.defn)
    basename = _format_node(node, *args, **kwargs)
    if not is_safe_basename(basename):
        raise ValueError(f"formatted name must be a basename: {basename!r}")
    created = plan_fixed(template.path / basename, template.defn)
    if isinstance(created, FixedDir):
        _stamp_tree(created, {**template.stamps, **kwargs})
    return created


def write_plan(directory: FixedDir, spec: Mapping[str, CreateTop] | None = None, /, **children: CreateTop) -> None:
    from ._create import apply_create

    _reject_bound_create(directory)
    merged: dict[str, CreateTop] = dict(spec or {})
    if overlap := merged.keys() & children.keys():
        raise TypeError(f"duplicate create keys: {sorted(overlap)}")
    merged.update(children)
    apply_create(directory, merged)


def _reject_bound_create(node: object) -> None:
    if isinstance(type(node), SchemaCls):
        raise TypeError(f"create on bound {type(node).__name__}; use root()")


## Names, captures, and declaration checks


def defn_node(defn: Defn) -> Node:
    return defn if isinstance(defn, File) else defn.defn


def _format_node(node: Node, *args: FmtField, **kwargs: FmtField) -> str:
    return node._selector.format(*args, **kwargs)  # pyright: ignore[reportPrivateUsage]


def capture_names(defn: Defn) -> frozenset[str]:
    return defn_node(defn)._selector.capture_names()  # pyright: ignore[reportPrivateUsage]


def validate_capture_names(defn: Defn, kwargs: Mapping[str, CaptureField]) -> None:
    names = capture_names(defn)
    for name in kwargs:
        if name not in names:
            raise KeyError(name)


def is_safe_basename(name: str) -> bool:
    return bool(name) and name not in {".", ".."} and "\0" not in name and "/" not in name and "\\" not in name


def _validate_node(node: Node) -> tuple[Selector, int | None]:
    if not any((node.name, node.fmt, node.match)):
        raise ValueError("declaration requires name, fmt, or match")
    if node.name and node.fmt is not None:
        raise ValueError("name cannot be combined with fmt")
    if node.name:
        if node.skip_mismatch:
            raise ValueError("skip_mismatch is only valid for collection declarations")
        if node.sort is not None:
            raise ValueError("sort is only valid for collection declarations")
        if node.sort_rev:
            raise ValueError("sort_rev is only valid for collection declarations")
    if node.min < 0:
        raise ValueError("min must be at least zero")
    if node.name:
        if node.min not in (0, 1):
            raise ValueError("exact-name min must be 0 or 1")
        if node.max not in (None, 1):
            raise ValueError("exact-name max is implicit")
        return Selector(node.fmt, node.match), 1
    if node.max is not None and node.max < node.min:
        raise ValueError("max must be at least min")
    return Selector(node.fmt, node.match), node.max


FsCache: TypeAlias = dict[Path, CacheSeq[Path]]
_MatchValue = TypeVar("_MatchValue", bound=Match)


## Bind


def _is_kind(path: Path, defn: Defn) -> bool:
    return path.is_file() if isinstance(defn, File) else path.is_dir()


def _dangling_names(defn: Defn, listing: Sequence[Path]) -> list[str]:
    node = defn_node(defn)
    names: list[str] = []
    for target in listing:
        if _is_kind(target, defn) or not target.is_symlink() or target.exists():
            continue
        if node.select(target.name) is not None:
            names.append(target.name)
    return names


def _bind_children(path: Path, dir_defn: DirDefn, cache: FsCache) -> tuple[BoundChild, ...] | MismatchErr:
    if not path.is_dir():
        return MismatchErr(f"expected directory: {path}")

    children: list[BoundChild] = []
    for position, defn in enumerate(dir_defn.defns):
        if is_mismatch(child := _bind_dir_defn(path, position, defn, cache)):
            return child
        children.append(child)
    return tuple(children)


def _listing(path: Path, cache: FsCache) -> CacheSeq[Path]:
    listing = cache.get(path)
    if listing is None:
        listing = cache[path] = CacheSeq(lambda: sorted(path.iterdir(), key=lambda entry: entry.name))
    return listing


def _bind_dir_defn(path: Path, position: int, defn: Defn, cache: FsCache) -> BoundChild | MismatchErr:
    node = defn_node(defn)
    if node.name:
        target = path / node.name
        if node.min == 0 and not target.exists():
            return None
        if node.select(target.name) is None:
            return MismatchErr(f"fixed basename does not match {node.match!r}: {target}")
        if not _is_kind(target, defn):
            kind = "file" if isinstance(defn, File) else "directory"
            return MismatchErr(f"expected {kind}: {target}")
        return _bind_fixed(target, defn, cache)

    listing = _listing(path, cache)
    if is_mismatch(matches := _bind_matches(defn, listing, cache)):
        return matches
    count = len(matches)
    if count < node.min or (node.max is not None and count > node.max):
        upper = "unbounded" if node.max is None else str(node.max)
        dangling = _dangling_names(defn, listing)
        suffix = f" (dangling: {', '.join(dangling)})" if dangling else ""
        return MismatchErr(f"expected {node.min}..{upper} matches for defn {position}, found {count}{suffix}: {path}")
    return Template(path, matches, defn) if node.fmt is not None else Matches(path, matches, defn)


@overload
def _bind_fixed(path: Path, defn: File[_L], cache: FsCache) -> FixedFile[_L]: ...


@overload
def _bind_fixed(path: Path, defn: DirDefn, cache: FsCache) -> FixedDir | MismatchErr: ...


def _bind_fixed(path: Path, defn: Defn, cache: FsCache) -> FixedFile[object] | FixedDir | MismatchErr:
    return _bind_fixed_kind(path, defn, cache)  # pyright: ignore[reportArgumentType]


@dispatch
def _bind_fixed_kind(path: Path, defn: File, cache: FsCache) -> FixedFile:  # pyright: ignore[reportRedeclaration]
    return FixedFile(path, defn)


@dispatch
def _bind_fixed_kind(path: Path, defn: DirDefn, cache: FsCache) -> FixedDir | MismatchErr:
    if is_mismatch(children := _bind_children(path, defn, cache)):
        return children
    return (defn.child_type or FixedDir)(path, children, defn)


def _sort_matches(matches: list[_MatchValue], node: Node) -> list[_MatchValue]:
    if node.sort is not None:
        sort = typing.cast(Callable[[Match], typing.Any], node.sort)
        matches.sort(key=sort, reverse=node.sort_rev)
    else:
        captured = [match.args + tuple(match.kwargs.values()) for match in matches]
        if captured and all(len(values) == 1 and isinstance(values[0], datetime) for values in captured):
            order = sorted(range(len(matches)), key=captured.__getitem__, reverse=node.sort_rev)
            matches = [matches[index] for index in order]
        else:
            matches.sort(key=lambda match: match.path.name, reverse=node.sort_rev)
    return matches


def _failed_match(node: Node, basename: str) -> MismatchErr | None:
    pattern = node._selector.match_failure(basename)  # pyright: ignore[reportPrivateUsage]
    if pattern is None:
        return None
    return MismatchErr(f"failed match {pattern!r}: {basename}")


def _bind_file_matches(defn: File[_L], listing: Sequence[Path]) -> list[_FileMatch[_L]] | MismatchErr:
    matches: list[_FileMatch[_L]] = []
    for target in listing:
        if not _is_kind(target, defn):
            continue
        if is_mismatch(failed := _failed_match(defn, target.name)):
            if defn.skip_mismatch:
                continue
            return failed
        if (captures := defn.select(target.name)) is None:
            continue
        matches.append(_FileMatch(target, captures, defn))
    return _sort_matches(matches, defn)


def _bind_dir_matches(defn: DirDefn, listing: Sequence[Path], cache: FsCache) -> list[_DirMatch] | MismatchErr:
    matches: list[_DirMatch] = []
    match_type = _bound_dir_match_type(defn)
    node = defn.defn
    for target in listing:
        if not _is_kind(target, defn):
            continue
        if is_mismatch(failed := _failed_match(node, target.name)):
            if node.skip_mismatch:
                continue
            return failed
        if (captures := node.select(target.name)) is None:
            continue
        if is_mismatch(children := _bind_children(target, defn, cache)):
            if node.skip_mismatch:
                continue
            return children
        matches.append(match_type(target, captures, children, defn))
    return _sort_matches(matches, defn.defn)


@overload
def _bind_matches(
    defn: File[_L], listing: Sequence[Path], cache: FsCache
) -> Sequence[_FileMatch[_L]] | MismatchErr: ...


@overload
def _bind_matches(defn: DirDefn, listing: Sequence[Path], cache: FsCache) -> Sequence[_DirMatch] | MismatchErr: ...


def _bind_matches(
    defn: Defn, listing: Sequence[Path], cache: FsCache
) -> Sequence[_FileMatch[object] | _DirMatch] | MismatchErr:
    return _bind_matches_kind(defn, listing, cache)  # pyright: ignore[reportArgumentType]


@dispatch
def _bind_matches_kind(  # pyright: ignore[reportRedeclaration]
    defn: File, listing: Sequence[Path], cache: FsCache
) -> object:
    return _bind_file_matches(defn, listing)


@dispatch
def _bind_matches_kind(defn: DirDefn, listing: Sequence[Path], cache: FsCache) -> Sequence[_DirMatch] | MismatchErr:
    return _bind_dir_matches(defn, listing, cache)


def bind_defns(root: PathIsh, defns: Sequence[Defn]) -> FixedDir | MismatchErr:
    path = Path(root)
    dir_defn = DirDefn(Dir(name="."), defns)
    if is_mismatch(children := _bind_children(path, dir_defn, {})):
        return children
    return FixedDir(path, children, dir_defn)


## Schema classes


class SchemaCls(type):
    def __new__(
        metacls: "type[SchemaCls]",
        name: str,
        bases: tuple[type[object], ...],
        namespace: dict[str, object],
        **kwargs: object,
    ) -> "SchemaCls":
        if namespace.get(_BOUND_MATCH) or "Schema" not in globals():
            return super().__new__(metacls, name, bases, namespace, **kwargs)
        from ._compile import validate_schema_bases

        validate_schema_bases(name, bases)
        return super().__new__(metacls, name, bases, namespace, **kwargs)

    def __getattr__(cls, name: str) -> type:
        if name.startswith("_"):
            raise AttributeError(name)
        from ._compile import is_schema_type, member_view, schema_defn_for

        if not is_schema_type(cls):
            raise AttributeError(name)
        try:
            root_defn = schema_defn_for(cls)
            defn = root_defn.defns[root_defn.lookup[name]]
        except (AssertionError, KeyError):
            raise AttributeError(name) from None
        node = defn_node(defn)
        if name != node.alias and name != normalize_name(node.name):
            raise AttributeError(name)
        if node.name:
            if isinstance(defn, File):
                base: type[object] = FixedFile
            elif defn.child_type is not None:
                return defn.child_type
            else:
                base = FixedDir
        elif node.fmt is not None:
            base = Template
        else:
            base = Matches
        return member_view(cls, name, base, node)

    @property
    def RootT(cls) -> "type[SchemaRoot[Schema]]":
        from ._compile import is_schema_type

        if not is_schema_type(cls):
            raise AttributeError("RootT")
        return _root_type_for(cls)


class SchemaRoot(FixedDir, Generic[_S]):
    _schema_type: type[_S]

    def bind(self) -> "_S | MismatchErr":
        return self._schema_type.bind(self.path)


def _is_root_type_for(value: object, schema_type: type[_S]) -> TypeIs[type[SchemaRoot[_S]]]:
    if not isinstance(value, type) or not issubclass(value, SchemaRoot):
        return False
    namespace: Mapping[str, object] = value.__dict__
    return namespace.get("_schema_type") is schema_type


def _root_type_for(schema_type: type[_S]) -> type[SchemaRoot[_S]]:
    cached = vars(schema_type).get("_root_type")
    if _is_root_type_for(cached, schema_type):
        return cached

    generated = type(
        f"{schema_type.__name__}Root",
        (SchemaRoot,),
        {
            "__module__": schema_type.__module__,
            "__qualname__": f"{schema_type.__qualname__}.RootT",
            "_schema_type": schema_type,
        },
    )
    if not _is_root_type_for(generated, schema_type):
        raise AssertionError("generated SchemaRoot has an invalid type")
    type.__setattr__(schema_type, "_root_type", generated)
    return generated


class Schema(FixedDir, metaclass=SchemaCls):
    schema: ClassVar["Layout"] = {}
    _schema_defn: ClassVar[DirDefn] = DirDefn(Dir(name="."))

    def __init_subclass__(cls) -> None:
        super().__init_subclass__()
        if cls.__dict__.get(_BOUND_MATCH):
            return
        from ._compile import compile_schema, validate_child_shadows, validate_schema_class

        validate_schema_class(cls)
        compile_schema(cls)
        validate_child_shadows(cls)

    @classmethod
    def relative_to(cls: type[_S], root: PathIsh) -> "SchemaRoot[_S]":
        path = Path(root)
        return _root_type_for(cls)(path, _plan_children(path, cls._schema_defn), cls._schema_defn)

    @classmethod
    def bind(cls: type[_S], root: PathIsh) -> "_S | MismatchErr":
        path = Path(root)
        if is_mismatch(children := _bind_children(path, cls._schema_defn, {})):
            return children
        return cls(path, children, cls._schema_defn)

    def root(self) -> "SchemaRoot[Self]":
        return type(self).relative_to(self.path)
