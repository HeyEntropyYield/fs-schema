import os
import re
import typing
from collections.abc import Callable, Iterator, Mapping, Sequence
from dataclasses import KW_ONLY, InitVar, dataclass, field, replace
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
    Never,
    Protocol,
    Self,
    TypeIs,
    TypeVar,
    assert_never,
    override,
    runtime_checkable,
)

import fs_schema._errmsg as em

from ._fmt import CaptureField, CaptureMap, FmtLike, ParsedCaptures
from ._ops import MismatchErr, is_mismatch, load, put, raise_exn
from ._ops import copy_to as copy_path
from ._ops import link_to as link_path
from ._selector import Selector
from ._std_ext import CacheSeq
from ._types import CreateTop, CreateValue, FmtFields, FmtFieldT, LoadSpec, Located, PathIsh, Puttable


@final
class _MissingDefault:
    __slots__: Final = ()


# The concrete Schema subtype is preserved by root and bind operations.
_S = TypeVar("_S", bound="Schema")
# Directory declarations only produce their Schema subtype.
_D_co = TypeVar("_D_co", bound="Schema", covariant=True)
# File declarations only produce _L_co through their load specification; no
# declaration API consumes it, so the parameter is safely covariant. This says
# nothing about mutability of the loaded value.
_L = TypeVar("_L")
_L_co = TypeVar("_L_co", covariant=True, default=object)
_Model = TypeVar("_Model")
# Unannotated load() is object. An assignment annotation solves this variable.
_Loaded = TypeVar("_Loaded", default=object)
# Template collections only produce their concrete Match subtype.
_M_co = TypeVar("_M_co", bound="Match", covariant=True)
_Default = TypeVar("_Default")
_MatchT = TypeVar("_MatchT")
_MatchRes: TypeAlias = tuple[list[_MatchT], list[MismatchErr]]

_MISSING_DEFAULT: Final = _MissingDefault()


# Section order:
#   Forward-safe cycle vocabulary. Match protocol, sort key.
#   User schema file/dir declarations. Node, File, Dir, FILES, Layout.
#   Reified definitions. DirDefn and Defn.
#   Runtime values. Path passthrough and FixedFile.
#   Runtime template matches and collections. Matches, Template, Child.
#   Fixed directories. FixedDir and directory matches.
#   Plan, format, and create. Planned tree, fmt_fields, write_plan.
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


# None: a regex capture can be absent. A format field cannot. list.sort still rejects mixed None.
SortKey: TypeAlias = str | int | float | datetime | Located | None
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
    selector: Selector = field(init=False, repr=False, compare=False)

    def __post_init__(self, optional: bool) -> None:
        """Exception: Schema Nodes fail fast"""
        if optional:
            if not self.name:
                raise ValueError(em.Node.OPTIONAL)
            object.__setattr__(self, "min", 0)
        selector, maximum = _node_ctor_validate_exn(self)  # declaration error
        object.__setattr__(self, "selector", selector)
        if self.max is None and maximum is not None:
            object.__setattr__(self, "max", maximum)

    def with_(self, /, **changes: object) -> Self:
        return replace(self, **changes)

    def select(self, basename: str) -> ParsedCaptures | None:
        return self.selector.captures(basename)


def _node_ctor_validate_exn(node: Node) -> tuple[Selector, int | None]:
    if node.name == "." and node.match:
        raise ValueError(em.Node.DOT_MATCH)
    if not any((node.name, node.fmt, node.match)):
        raise ValueError(em.Node.NEEDS)
    if node.name and node.fmt is not None:
        raise ValueError(em.Node.NAME_FMT)
    if node.name:
        if node.skip_mismatch:
            raise ValueError(em.Node.SKIP)
        if node.sort is not None:
            raise ValueError(em.Node.SORT)
        if node.sort_rev:
            raise ValueError(em.Node.SORT_REV)
    if node.min < 0:
        raise ValueError(em.Node.MIN)
    if node.name:
        if node.min not in (0, 1):
            raise ValueError(em.Node.EXACT_MIN)
        if node.max not in (None, 1):
            raise ValueError(em.Node.EXACT_MAX)
        return Selector(node.fmt, node.match), 1
    if node.max is not None and node.max < node.min:
        raise ValueError(em.Node.MAX)
    return Selector(node.fmt, node.match), node.max


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
        """Exception: a layout clash is a declaration error"""
        child_defns = tuple(defns)
        lookup = _dir_defn_ctor_uniq_lookups_exn(child_defns)
        object.__setattr__(self, "defn", defn)
        object.__setattr__(self, "defns", child_defns)
        object.__setattr__(self, "lookup", MappingProxyType(lookup))
        object.__setattr__(self, "child_type", child_type)


def _dir_defn_ctor_uniq_lookups_exn(child_defns: tuple["Defn", ...]) -> dict[str, int]:
    lookup: dict[str, int] = {}
    identities: dict[str, int] = {}

    def add_uniq(target: dict[str, int], key: str, index: int) -> None:
        if key in target and target[key] != index:
            raise ValueError(em.Layout.duplicate(key))
        target[key] = index

    for index, child_defn in enumerate(child_defns):
        node = defn_node(child_defn)
        if node.name == ".":
            if not node.alias:
                raise ValueError(em.Node.DOT_ALIAS)
            add_uniq(identities, node.alias, index)
            add_uniq(lookup, node.alias, index)
            continue
        for identity in dict.fromkeys(
            key for key in (node.alias, node.name, normalize_name(node.name), node.fmt) if key
        ):
            add_uniq(identities, identity, index)
        if node.name:
            add_uniq(lookup, node.name, index)
            add_uniq(lookup, normalize_name(node.name), index)
        if node.alias:
            add_uniq(lookup, node.alias, index)
    return lookup


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

    def link_to(self, target: PathIsh, *, hard: bool = False) -> None:
        link_path(self.path, target, hard=hard)

    def copy_to(self, dest: PathIsh, *, follow_symlinks: bool = True, clean: bool = False) -> None:
        copy_path(self.path, dest, follow_symlinks=follow_symlinks, clean=clean)

    def __bool__(self) -> typing.Literal[True]:
        return True


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

    def create(self, data: Puttable | PathIsh | None = None) -> Self:
        """Exception: raises to support chaining"""
        put(self.path, data)
        return self

    def load(self, model: type[_Model] | None = None) -> _L_co | Exception:
        if schema := self.defn.schema:
            if model:
                if not isinstance(schema, type):
                    return TypeError(em.Load.loader(self.path, schema))
                elif not issubclass(schema, model):
                    return TypeError(em.Load.subclass(self.path, schema.__name__, model.__name__))
                # else OK: schema satisfies model
            # else OK: no model qualification
        elif not (schema := model):
            return Exception(em.Load.missing(self.path))
        # else OK: schema exists
        got = load(self.path, schema)
        if not model or isinstance(got, Exception | model):
            return typing.cast(_L_co | Exception, got)
        assert_never(typing.cast(Never, got))


def normalize_name(name: str) -> str:
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
    fmt_fields: FmtFields

    def __init__(
        self,
        path: PathIsh,
        matches: Sequence[_M_co],
        defn: _Defn_co,
        fmt_fields: FmtFields | None = None,
    ) -> None:
        self.path = Path(path)
        self._matches = tuple(matches)
        self.defn = defn
        self.fmt_fields = dict(fmt_fields or {})

    @overload
    def __getitem__(self, index: int) -> _M_co: ...

    @overload
    def __getitem__(self, index: slice) -> Self: ...

    @override
    def __getitem__(self, index: int | slice) -> _M_co | Self:
        if isinstance(index, slice):
            return type(self)(self.path, self._matches[index], self.defn, self.fmt_fields)
        return self._matches[index]

    @override
    def __len__(self) -> int:
        return len(self._matches)

    def filter(self, predicate: CapturePredicate, /) -> Self:
        return type(self)(
            self.path,
            tuple(match for match in self._matches if predicate(match.args, match.kwargs)),
            self.defn,
            self.fmt_fields,
        )

    def find(self, predicate: CapturePredicate, /) -> _M_co | None:
        return next((match for match in self._matches if predicate(match.args, match.kwargs)), None)

    def where(self, *args: CaptureField, **kwargs: CaptureField) -> Self:
        """Exception: raises to support chaining"""
        validate_capture_names_exn(self.defn, kwargs)  # chaining
        return self.filter(
            lambda captured_args, captured_kwargs: _matches_where_captures(captured_args, captured_kwargs, args, kwargs)
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

    @override
    def __iter__(self) -> Iterator[_M_co]:
        yield from self._matches

    def __next__(self) -> _M_co:
        return next(iter(self))

    @overload
    def parse(self: "Matches[_FileMatch[_L], File[_L]]", source: PathIsh) -> FixedFile[_L]: ...

    @overload
    def parse(self: "Matches[_DirMatch, DirDefn]", source: PathIsh) -> "FixedDir": ...

    def parse(self, source: PathIsh) -> "FixedFile[object] | FixedDir":
        """Exception: raises to support chaining"""
        basename = Path(source).name
        if not is_safe_basename(basename) or defn_node(self.defn).select(basename) is None:
            raise ValueError(em.Parse.member(basename))
        return plan_fixed(self.path / basename, self.defn)


def _matches_where_captures(
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


class Template(Matches[_M_co, _Defn_co], Generic[_M_co, _Defn_co]):
    @overload
    def format(self: "Template[_FileMatch[_L], File[_L]]", *args: FmtFieldT, **kwargs: FmtFieldT) -> FixedFile[_L]: ...

    @overload
    def format(self: "Template[_DirMatch, DirDefn]", *args: FmtFieldT, **kwargs: FmtFieldT) -> "FixedDir": ...

    def format(self, *args: FmtFieldT, **kwargs: FmtFieldT) -> "FixedFile[object] | FixedDir":
        """Exception: raises to support chaining"""
        return format_any_exn(self, *args, **kwargs)  # chaining


if TYPE_CHECKING:

    class _ChildView(Protocol):
        """Static view of a child. Not every runtime object has every method."""

        path: Path  # FixedFile, FixedDir, _FileMatch, _DirMatch
        name: str  # FixedFile, FixedDir, _FileMatch, _DirMatch
        stem: str  # FixedFile, FixedDir, _FileMatch, _DirMatch
        suffix: str  # FixedFile, FixedDir, _FileMatch, _DirMatch

        @property
        def args(self) -> tuple[CaptureField, ...]: ...  # _FileMatch, _DirMatch

        @property
        def kwargs(self) -> CaptureMap: ...  # _FileMatch, _DirMatch

        def __bool__(self) -> bool: ...  # FixedFile, FixedDir, _FileMatch, _DirMatch

        def __contains__(self, value: object) -> bool: ...  # Matches, Template

        def __fspath__(self) -> str: ...  # FixedFile, FixedDir, _FileMatch, _DirMatch

        def __getattr__(self, name: str) -> "_ChildView": ...  # FixedDir, _DirMatch

        def __getitem__(self, index: int | str) -> "_ChildView": ...  # FixedDir, Matches, Template, _DirMatch

        def __iter__(self) -> Iterator["_ChildView"]: ...  # FixedDir, Matches, Template, _DirMatch

        def __len__(self) -> int: ...  # Matches, Template

        def __lt__(self, other: object) -> bool: ...  # FixedFile, FixedDir, Matches, Template, _FileMatch, _DirMatch

        def __next__(self) -> "_ChildView": ...  # FixedDir, Matches, Template, _DirMatch

        def __reversed__(self) -> Iterator["_ChildView"]: ...  # Matches, Template

        @override
        def __str__(self) -> str: ...  # FixedFile, FixedDir, Matches, Template, _FileMatch, _DirMatch

        def copy_to(
            self, dest: PathIsh, *, follow_symlinks: bool = True, clean: bool = False
        ) -> None: ...  # FixedFile, FixedDir, _FileMatch, _DirMatch

        def count(self, value: object) -> int: ...  # Matches, Template

        def create(
            self, data: Puttable | PathIsh | None = None, /, **children: CreateTop
        ) -> "_ChildView": ...  # FixedFile, FixedDir, _FileMatch, _DirMatch

        def exists(self) -> bool: ...  # FixedFile, FixedDir, _FileMatch, _DirMatch

        def filter(self, predicate: CapturePredicate, /) -> "_ChildView": ...  # Matches, Template

        def find(self, predicate: CapturePredicate, /) -> "_ChildView | None": ...  # Matches, Template

        def format(self, *args: FmtFieldT, **kwargs: FmtFieldT) -> "_ChildView": ...  # Template

        def get(self, index: int = 0) -> "_ChildView | None": ...  # Matches, Template

        def index(self, value: object, start: int = 0, stop: int | None = None) -> int: ...  # Matches, Template

        def link_to(
            self, target: PathIsh, *, hard: bool = False
        ) -> None: ...  # FixedFile, FixedDir, _FileMatch, _DirMatch

        @overload
        def load(self) -> _Loaded | Exception: ...  # FixedFile, _FileMatch

        @overload
        def load(self, model: type[_Model]) -> _Model | Exception: ...  # FixedFile, _FileMatch

        def parse(self, source: PathIsh) -> "_ChildView": ...  # Matches, Template

        def read_bytes(self) -> bytes: ...  # FixedFile, _FileMatch

        def read_text(self) -> str: ...  # FixedFile, _FileMatch

        def where(self, *args: CaptureField, **kwargs: CaptureField) -> "_ChildView": ...  # Matches, Template

    Child: TypeAlias = "FixedFile[object] | FixedDir | Matches[_FileMatch[object] | _DirMatch]"
    # LUB of mixed slots. Optional exact may be None; required/collection never.
    BoundChild: TypeAlias = "Child | None"
    # Checker sees one view. Runtime stays Child | None so a missing optional is None.
    GetChild: TypeAlias = _ChildView
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
    fmt_fields: FmtFields
    defn: DirDefn

    def __init__(
        self,
        path: PathIsh,
        children: Sequence[BoundChild],
        defn: DirDefn,
        fmt_fields: FmtFields | None = None,
    ) -> None:
        _Fixed.__init__(self, path)
        self._children = tuple(children)
        self._lookup = defn.lookup
        self.defn = defn
        self.fmt_fields = dict(fmt_fields or {})

    def __iter__(self) -> Iterator[GetChild]:
        return iter(typing.cast(tuple[GetChild, ...], typing.cast(object, self._children)))

    def __next__(self) -> GetChild:
        return next(iter(self))

    @overload
    def __getitem__(self, index: int) -> GetChild: ...

    @overload
    def __getitem__(self, index: str) -> GetChild: ...

    @overload
    def __getitem__(self, index: slice) -> tuple[GetChild, ...]: ...

    def __getitem__(self, index: int | str | slice) -> GetChild | tuple[GetChild, ...]:
        if isinstance(index, str):
            child = self._children[self._lookup[index]]
            return typing.cast(GetChild, typing.cast(object, child))
        got = self._children[index]
        return typing.cast(GetChild | tuple[GetChild, ...], typing.cast(object, got))

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
        """Exception: raises to support chaining"""
        write_plan_exn(self, spec, **children)  # chaining
        return self


class _DirMatch(_CaptureState, FixedDir):
    def __init__(self, path: PathIsh, captures: ParsedCaptures, children: Sequence[BoundChild], defn: DirDefn) -> None:
        FixedDir.__init__(self, path, children, defn)
        self._captures: ParsedCaptures = captures


# A bound fmt directory is a generated class: the child schema plus a capture match.
# _BOUND_MATCH tells SchemaCls this is not a user schema, so it is not compiled.
_BOUND_MATCH: Final = "_fs_schema_bound_match"
_GenT = TypeVar("_GenT", bound=type)


def _stored_type(owner: type, slot: str, ok: Callable[[object], bool], build: Callable[[], _GenT]) -> _GenT:
    # Match and root share this cache: look up a slot, else build once and store it on the class.
    # The builder differs. A match uses SchemaCls so isinstance sees the schema. A root uses type() so it is not compiled.
    found = vars(owner).get(slot)
    if ok(found):
        return typing.cast(_GenT, found)
    generated = build()
    if not ok(generated):
        raise AssertionError(f"{owner.__name__}.{slot} was not the generated type")
    type.__setattr__(owner, slot, generated)
    return generated


def _is_bound_dir_match_type(value: object, schema_type: type) -> TypeIs[type[_DirMatch]]:
    return isinstance(value, type) and issubclass(value, schema_type) and issubclass(value, _DirMatch)


def _bound_dir_match_type(defn: DirDefn) -> type[_DirMatch]:
    schema_type = defn.child_type
    if schema_type is None:
        return _DirMatch

    def build() -> type[_DirMatch]:
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
        return generated

    return _stored_type(
        schema_type,
        "_bound_match_type",
        lambda value: _is_bound_dir_match_type(value, schema_type),
        build,
    )


## Plan, format, and create


def _plan_dir_defn_children(path: Path, dir_defn: DirDefn) -> tuple[Child, ...]:
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
    return FixedDir(path, _plan_dir_defn_children(path, defn), defn)


def format_any_exn(
    template: "Template[Match, Defn]",
    *args: FmtFieldT,
    **kwargs: FmtFieldT,
) -> "FixedFile[object] | FixedDir":
    for name, value in kwargs.items():
        if name in template.fmt_fields and template.fmt_fields[name] != value:
            raise ValueError(em.Fmt.capture(name))
    node = defn_node(template.defn)
    basename = _format_any_node_exn(node, *args, **kwargs)
    if not is_safe_basename(basename):
        raise ValueError(em.Fmt.basename(basename))
    created = plan_fixed(template.path / basename, template.defn)
    if isinstance(created, FixedDir):
        _format_any_fmt_fields(created, {**template.fmt_fields, **kwargs})
    return created


def _format_any_node_exn(node: Node, *args: FmtFieldT, **kwargs: FmtFieldT) -> str:
    return node.selector.format(*args, **kwargs)


def _format_any_fmt_fields(directory: FixedDir, fmt_fields: FmtFields) -> None:
    directory.fmt_fields = dict(fmt_fields)
    for child in directory._children:  # pyright: ignore[reportPrivateUsage]
        if isinstance(child, FixedDir):
            _format_any_fmt_fields(child, fmt_fields)
        elif isinstance(child, Matches):
            child.fmt_fields = dict(fmt_fields)


def write_plan_exn(directory: FixedDir, spec: Mapping[str, CreateTop] | None = None, /, **children: CreateTop) -> None:
    from ._create import apply_create_exn

    _write_plan_bound_exn(directory)
    merged: dict[str, CreateTop] = dict(spec or {})
    if overlap := merged.keys() & children.keys():
        raise TypeError(em.Create.duplicate(sorted(overlap)))
    merged.update(children)
    apply_create_exn(directory, merged)


def _write_plan_bound_exn(node: object) -> None:
    if isinstance(type(node), SchemaCls):
        raise TypeError(em.Create.bound(type(node).__name__))


## Names, captures, and declaration checks


def defn_node(defn: Defn) -> Node:
    return defn if isinstance(defn, File) else defn.defn


def capture_names(defn: Defn) -> frozenset[str]:
    return defn_node(defn).selector.capture_names()


def validate_capture_names_exn(defn: Defn, kwargs: Mapping[str, CaptureField]) -> None:
    names = capture_names(defn)
    for name in kwargs:
        if name not in names:
            raise KeyError(name)


def is_safe_basename(name: str) -> bool:
    return bool(name) and name not in {".", ".."} and "\0" not in name and "/" not in name and "\\" not in name


FsCache: TypeAlias = dict[Path, CacheSeq[Path]]
_MatchValue = TypeVar("_MatchValue", bound=Match)


## Bind


def _bind_is_kind(path: Path, defn: Defn) -> bool:
    return path.is_file() if isinstance(defn, File) else path.is_dir()


def _bind_dangling_names(defn: Defn, listing: Sequence[Path]) -> list[str]:
    node = defn_node(defn)
    names: list[str] = []
    for target in listing:
        if _bind_is_kind(target, defn) or not target.is_symlink() or target.exists():
            continue
        if node.select(target.name) is not None:
            names.append(target.name)
    return names


# str(MismatchErr).splitlines() is the failure list, so one message must stay one line.
# Filenames can contain any of these.
_LINE_BREAKS = {ord(ch): repr(ch)[1:-1] for ch in "\n\r\v\f\x1c\x1d\x1e\x85\u2028\u2029"}


def _mismatch(message: str) -> MismatchErr:
    return MismatchErr(message.translate(_LINE_BREAKS))


def _aggregate(failures: Sequence[MismatchErr]) -> MismatchErr:
    if len(failures) == 1:
        return failures[0]
    return MismatchErr("\n".join(str(failure) for failure in failures))


def _bind_children(
    path: Path, dir_defn: DirDefn, cache: FsCache, *, fast: bool = False
) -> tuple[BoundChild, ...] | MismatchErr:
    if not path.is_dir():
        return _mismatch(f"expected directory: {path}")

    children: list[BoundChild] = []
    failures: list[MismatchErr] = []
    for position, defn in enumerate(dir_defn.defns):
        if is_mismatch(child := _bind_dir_defn(path, position, defn, cache, fast=fast)):
            if fast:
                return child
            failures.append(child)
        else:
            children.append(child)
    if failures:
        return _aggregate(failures)
    return tuple(children)


def _bind_listing(path: Path, cache: FsCache) -> CacheSeq[Path]:
    listing = cache.get(path)
    if listing is None:
        listing = cache[path] = CacheSeq(lambda: sorted(path.iterdir(), key=lambda entry: entry.name))
    return listing


def _bind_dir_defn(
    path: Path, position: int, defn: Defn, cache: FsCache, *, fast: bool = False
) -> BoundChild | MismatchErr:
    node = defn_node(defn)
    if node.name:
        target = path / node.name
        if node.min == 0 and node.name != "." and not target.exists():
            return None
        if node.select(target.name) is None:
            return _mismatch(em.Bind.fixed(node.match, target))
        if not _bind_is_kind(target, defn):
            message = em.Bind.file(target) if isinstance(defn, File) else em.Bind.directory(target)
            return _mismatch(message)
        bound = _bind_fixed(target, defn, cache, fast=fast)
        if node.name == "." and node.min == 0 and is_mismatch(bound):
            return None
        return bound

    listing = _bind_listing(path, cache)
    matches, failures = _bind_matches(defn, listing, cache, fast=fast)
    if fast and failures:
        return failures[0]
    count = len(matches)
    if count < node.min or (node.max is not None and count > node.max):
        failures.append(_mismatch(em.Bind.count(
            low=node.min, high=node.max, position=position, found=count,
            dangling=_bind_dangling_names(defn, listing), path=path,
            )))  # fmt: skip
    if failures:
        return _aggregate(failures)
    return Template(path, matches, defn) if node.fmt is not None else Matches(path, matches, defn)


@overload
def _bind_fixed(path: Path, defn: File[_L], cache: FsCache, *, fast: bool = False) -> FixedFile[_L]: ...


@overload
def _bind_fixed(path: Path, defn: DirDefn, cache: FsCache, *, fast: bool = False) -> FixedDir | MismatchErr: ...


def _bind_fixed(
    path: Path, defn: Defn, cache: FsCache, *, fast: bool = False
) -> FixedFile[object] | FixedDir | MismatchErr:
    return _bind_fixed_kind(path, defn, cache, fast)  # pyright: ignore[reportArgumentType]


@dispatch
def _bind_fixed_kind(path: Path, defn: File, cache: FsCache, fast: bool = False) -> FixedFile:  # pyright: ignore[reportRedeclaration]
    return FixedFile(path, defn)


@dispatch
def _bind_fixed_kind(path: Path, defn: DirDefn, cache: FsCache, fast: bool = False) -> FixedDir | MismatchErr:
    if is_mismatch(children := _bind_children(path, defn, cache, fast=fast)):
        return children
    return (defn.child_type or FixedDir)(path, children, defn)


def _bind_sort_matches(matches: list[_MatchValue], node: Node) -> list[_MatchValue]:
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


def _bind_failed_match(node: Node, basename: str) -> MismatchErr | None:
    pattern = node.selector.match_failure(basename)
    if pattern is None:
        return None
    return _mismatch(em.Bind.failed(pattern, basename))


def _bind_file_matches(defn: File[_L], listing: Sequence[Path], *, fast: bool = False) -> _MatchRes[_FileMatch[_L]]:
    matches: list[_FileMatch[_L]] = []
    failures: list[MismatchErr] = []
    for target in listing:
        if not _bind_is_kind(target, defn):
            continue
        if is_mismatch(failed := _bind_failed_match(defn, target.name)):
            if defn.skip_mismatch:
                continue
            if fast:
                return matches, [failed]
            failures.append(failed)
            continue
        if (captures := defn.select(target.name)) is None:
            continue
        matches.append(_FileMatch(target, captures, defn))
    return _bind_sort_matches(matches, defn), failures


def _bind_dir_matches(
    defn: DirDefn, listing: Sequence[Path], cache: FsCache, *, fast: bool = False
) -> _MatchRes[_DirMatch]:
    matches: list[_DirMatch] = []
    failures: list[MismatchErr] = []
    match_type = _bound_dir_match_type(defn)
    node = defn.defn
    for target in listing:
        if not _bind_is_kind(target, defn):
            continue
        if is_mismatch(failed := _bind_failed_match(node, target.name)):
            if node.skip_mismatch:
                continue
            if fast:
                return matches, [failed]
            failures.append(failed)
            continue
        if (captures := node.select(target.name)) is None:
            continue
        if is_mismatch(children := _bind_children(target, defn, cache, fast=fast)):
            if node.skip_mismatch:
                continue
            if fast:
                return matches, [children]
            failures.append(children)
            continue
        matches.append(match_type(target, captures, children, defn))
    return _bind_sort_matches(matches, defn.defn), failures


@overload
def _bind_matches(
    defn: File[_L], listing: Sequence[Path], cache: FsCache, *, fast: bool = False
) -> _MatchRes[_FileMatch[_L]]: ...


@overload
def _bind_matches(
    defn: DirDefn, listing: Sequence[Path], cache: FsCache, *, fast: bool = False
) -> _MatchRes[_DirMatch]: ...


def _bind_matches(
    defn: Defn, listing: Sequence[Path], cache: FsCache, *, fast: bool = False
) -> tuple[Sequence[_FileMatch[object] | _DirMatch], list[MismatchErr]]:
    return _bind_matches_kind(defn, listing, cache, fast)  # pyright: ignore[reportArgumentType]


@dispatch
def _bind_matches_kind(  # pyright: ignore[reportRedeclaration]
    defn: File, listing: Sequence[Path], cache: FsCache, fast: bool = False
) -> object:
    return _bind_file_matches(defn, listing, fast=fast)


@dispatch
def _bind_matches_kind(
    defn: DirDefn, listing: Sequence[Path], cache: FsCache, fast: bool = False
) -> _MatchRes[_DirMatch]:
    return _bind_dir_matches(defn, listing, cache, fast=fast)


## Schema classes


class SchemaCls(type):
    def __new__(
        metacls: "type[SchemaCls]",
        name: str,
        bases: tuple[type[object], ...],
        namespace: dict[str, object],
        *,
        schema: Mapping[object, object] | None = None,
        **kwargs: object,
    ) -> "SchemaCls":
        if schema is not None:
            if "schema" in namespace:
                raise TypeError(em.Schema.twice(name))
            namespace["schema"] = schema
        # A user schema has a Schema base. class Schema itself does not, and a match sets _BOUND_MATCH.
        # This does not look at globals, so import order cannot skip the check.
        if namespace.get(_BOUND_MATCH) or not any(isinstance(base, SchemaCls) for base in bases):
            return super().__new__(metacls, name, bases, namespace, **kwargs)
        from ._compile import schema_ctor_check_bases

        _ = raise_exn(schema_ctor_check_bases(name, bases))
        return super().__new__(metacls, name, bases, namespace, **kwargs)

    def __getattr__(cls, name: str) -> type:
        # Installed children are descriptors, so this runs only for a missing name.
        # The checker uses this return type for a child that is not written in the class body.
        raise AttributeError(name)

    @property
    def RootT(cls) -> "type[SchemaRoot[Schema]]":
        from ._compile import is_schema_type

        if not is_schema_type(cls):
            raise AttributeError("RootT")
        return _root_type_for(cls)


class SchemaRoot(FixedDir, Generic[_S]):
    _schema_type: type[_S]

    def bind(self, *, fast: bool = False) -> "_S | MismatchErr":
        return self._schema_type.bind(self.path, fast=fast)


def _is_root_type_for(value: object, schema_type: type[_S]) -> TypeIs[type[SchemaRoot[_S]]]:
    if not isinstance(value, type) or not issubclass(value, SchemaRoot):
        return False
    namespace: Mapping[str, object] = value.__dict__
    return namespace.get("_schema_type") is schema_type


def _root_type_for(schema_type: type[_S]) -> type[SchemaRoot[_S]]:
    # relative_to returns SchemaRoot[This]. type() keeps it out of schema compilation.
    def build() -> type[SchemaRoot[_S]]:
        return type(
            f"{schema_type.__name__}Root",
            (SchemaRoot,),
            {
                "__module__": schema_type.__module__,
                "__qualname__": f"{schema_type.__qualname__}.RootT",
                "_schema_type": schema_type,
            },
        )

    return _stored_type(
        schema_type,
        "_root_type",
        lambda value: _is_root_type_for(value, schema_type),
        build,
    )


class Schema(FixedDir, metaclass=SchemaCls):
    schema: ClassVar["Layout"] = {}
    _schema_defn: ClassVar[DirDefn] = DirDefn(Dir(name="."))

    def __init_subclass__(cls) -> None:
        super().__init_subclass__()
        if cls.__dict__.get(_BOUND_MATCH):
            return
        from ._compile import schema_ctor_check_class, schema_ctor_check_defn_shadows, schema_ctor_compile_defn

        _ = raise_exn(schema_ctor_check_class(cls))
        _ = raise_exn(schema_ctor_compile_defn(cls))
        _ = raise_exn(schema_ctor_check_defn_shadows(cls))  # req compile_defn
        _schema_ctor_install_attrs(cls)

    @classmethod
    def relative_to(cls: type[_S], root: PathIsh) -> "SchemaRoot[_S]":
        path = Path(root)
        return _root_type_for(cls)(path, _plan_dir_defn_children(path, cls._schema_defn), cls._schema_defn)

    @classmethod
    def bind(cls: type[_S], root: PathIsh, *, fast: bool = False) -> "_S | MismatchErr":
        path = Path(root)
        if is_mismatch(children := _bind_children(path, cls._schema_defn, {}, fast=fast)):
            return children
        return cls(path, children, cls._schema_defn)

    def root(self) -> "SchemaRoot[Self]":
        return type(self).relative_to(self.path)


def _schema_ctor_child_names(node: Node) -> tuple[str, ...]:
    names: list[str] = []
    if node.alias:
        names.append(node.alias)
    if node.name and (normalized := normalize_name(node.name)) not in names:
        names.append(normalized)
    return tuple(names)


class _DeclAttr:
    # Class access returns the declaration: the schema class, or a view.
    # Instance access returns the bound child. A bare class attribute would hide that lookup.
    def __init__(self, name: str, target: object) -> None:
        self.name: str = name
        self.target: object = target

    def __get__(self, instance: FixedDir | None, owner: type[object]) -> object:
        if instance is None:
            return self.target
        return FixedDir.__getattr__(instance, self.name)


def _schema_ctor_install_attrs(cls: type[Schema]) -> None:
    # Runs once, after shadow checks, when the class is created.
    # A directory whose value is a schema class is that class.
    # A file or a repeated name is a view: a generated class with alias, fmt, and with_.
    # Alias and normalized basename are the same object. Nothing is built again on lookup.
    from ._compile import member_view, schema_defn_for

    installed: list[str] = []
    for defn in schema_defn_for(cls).defns:
        node = defn_node(defn)
        names = _schema_ctor_child_names(node)
        if not names:
            continue
        if node.name and isinstance(defn, File):
            target: object = member_view(cls, FixedFile, node)
        elif node.name and isinstance(defn, DirDefn):
            # An exact directory's child class is set when the directory is compiled.
            child_type = defn.child_type
            if child_type is None:
                raise AssertionError("exact directory has no child class")
            target = child_type
        elif node.fmt is not None:
            target = member_view(cls, Template, node)
        else:
            target = member_view(cls, Matches, node)
        for name in names:
            type.__setattr__(cls, name, _DeclAttr(name, target))
        installed.extend(names)
    # Shadow checks ignore these names on a parent, so a subclass can declare the same child.
    type.__setattr__(cls, "_child_attrs", frozenset(installed))
