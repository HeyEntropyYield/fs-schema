# pyright: reportImportCycles=false
import re
from collections.abc import Callable, Mapping, Sequence
from dataclasses import KW_ONLY, InitVar, dataclass, field, replace
from datetime import datetime
from types import MappingProxyType
from typing import TYPE_CHECKING, Final, Generic, TypeAlias, final, overload

from typing_extensions import Protocol, Self, TypeVar, override, runtime_checkable

import fs_schema._errmsg as em

from ._fmt import CaptureField, CaptureMap, FmtLike, ParsedCaptures
from ._selector import Selector
from ._types import LoadSpec, Located

if TYPE_CHECKING:
    from ._schema import Schema

# The concrete Schema subtype is preserved by directory declarations.
_D_co = TypeVar("_D_co", bound="Schema", covariant=True)
# File declarations only produce _L_co through their load specification; no
# declaration API consumes it, so the parameter is safely covariant. This says
# nothing about mutability of the loaded value.
_L = TypeVar("_L")
_L_co = TypeVar("_L_co", covariant=True, default=object)


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


def normalize_name(name: str) -> str:
    return re.sub(r"[^A-Za-z0-9_]+", "_", name)


def defn_node(defn: Defn) -> Node:
    return defn if isinstance(defn, File) else defn.defn


def capture_names(defn: Defn) -> frozenset[str]:
    return defn_node(defn).selector.capture_names()


def validate_capture_names_exn(defn: Defn, kwargs: Mapping[str, CaptureField]) -> None:
    names = capture_names(defn)
    for name in kwargs:
        if name not in names:
            raise KeyError(name)
