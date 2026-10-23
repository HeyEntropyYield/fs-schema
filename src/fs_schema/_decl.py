# pyright: reportImportCycles=false
import re
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from types import MappingProxyType
from typing import TYPE_CHECKING, Final, Generic, TypeAlias, final, overload

from attrs import Converter, define, evolve
from attrs import field as attr_field
from typing_extensions import Protocol, Self, TypeVar, override, runtime_checkable

import fs_schema._errmsg as em

from ._fmt import CaptureField, CaptureMap, ParsedCaptures, open_str, safe, valid_fmt_exn
from ._selector import Selector
from ._types import FmtStr, LoadSpec, Located, MatchPat, Name, Open, Raw, Safe

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


def _node_ctor_name_exn(name: str, node: object) -> Open[Name]:
    # "" and "." are this path. open_str rejects both. child_path_exn keeps the parent
    if not name or (isinstance(node, Dir) and name == "."):
        return Safe[Name](name)
    if not (opened := open_str(Raw[Name](name))):
        raise ValueError(em.Schema.Body.NAME)
    return opened


# Declaration specs. Exact names are positional scalars (max implicit 1).
# Collections are keyword-only and need fmt and/or match.
# `optional` is ctor sugar for min=0. It is not part of equality.
@define(frozen=True, slots=True, kw_only=True)
class Node:
    # "" is this path, not a missing name
    name: Open[Name] = attr_field(
        default=Safe[Name](""),
        kw_only=False,
        converter=Converter(_node_ctor_name_exn, takes_self=True),
    )
    # "" fmt and match are stored as None. A stored value is a real pattern
    fmt: Open[FmtStr] | None = attr_field(default=None, converter=valid_fmt_exn)
    match: Raw[MatchPat] | None = attr_field(default=None, converter=lambda m: Raw[MatchPat](m) if m else None)  # pyright: ignore[reportAny]
    min: int = attr_field(default=1)
    max: int | None = attr_field(default=None)
    # "" is stored as None. A stored alias is an identifier
    alias: str | None = attr_field(default=None, converter=lambda a: a if a else None)  # pyright: ignore[reportAny]
    optional: bool = attr_field(default=False, eq=False, repr=False)
    sort: SortFn | None = attr_field(default=None)
    sort_rev: bool = attr_field(default=False)
    skip_mismatch: bool = attr_field(default=False)
    selector: Selector = attr_field(init=False, eq=False, repr=False)

    def __attrs_post_init__(self) -> None:
        """Exception: Schema Nodes fail fast"""
        if self.optional:
            if not self.name:
                raise ValueError(em.Node.OPTIONAL)
            object.__setattr__(self, "min", 0)
        selector, maximum = _node_ctor_validate_exn(self)  # declaration error
        object.__setattr__(self, "selector", selector)
        if self.max is None and maximum is not None:
            object.__setattr__(self, "max", maximum)

    def with_(self, /, **changes: object) -> Self:
        return evolve(self, **changes)

    def select(self, basename: Safe[Name]) -> ParsedCaptures | None:
        return self.selector.captures(basename)


def _node_ctor_validate_exn(node: Node) -> tuple[Selector, int | None]:
    if node.name == "." and node.match:
        raise ValueError(em.Node.DOT_MATCH)
    if not any((node.name, node.fmt, node.match)):
        raise ValueError(em.Node.NEEDS)
    if node.name and node.fmt:
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


@define(frozen=True, slots=True, kw_only=True)
class File(Node, Generic[_L_co]):
    schema: LoadSpec[_L_co] | None = attr_field(default=None)

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
            fmt: str,
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


@define(frozen=True, slots=True, kw_only=True)
class Dir(Node, Generic[_D_co]):
    # Optional extra layout contract for whatever appears on this Dir's RHS.
    schema: type[_D_co] | None = attr_field(default=None)

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
            fmt: str,
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
DirRhs: TypeAlias = "Layout | type[Schema] | Xor | Sequence[Layout | type[Schema]]"
FileRhs: TypeAlias = str | File[object]
FilesRhs: TypeAlias = list[FileRhs]

LayoutKey: TypeAlias = "str | Dir[Schema] | FilesKey"
LayoutValue: TypeAlias = "DirRhs | FileRhs | FilesRhs"
Layout: TypeAlias = dict[LayoutKey, LayoutValue]

LayoutEntry: TypeAlias = "tuple[Dir[Schema] | str, DirRhs] | tuple[FilesKey, FilesRhs] | tuple[str, FileRhs]"


@final
class Xor:
    """Exclusive layouts. Not a directory node"""

    __slots__ = ("entries",)
    entries: tuple[tuple[str | None, object], ...]

    def __init__(self, entries: tuple[tuple[str | None, object], ...]) -> None:
        self.entries = entries


## Reified definitions


@dataclass(frozen=True, slots=True, init=False)
class DirLayout:
    """Children of one directory layout. Not a directory node"""

    defns: tuple["Defn", ...]
    lookup: Mapping[str, int]
    child_type: "type[Schema] | None"
    name: str | None

    def __init__(
        self,
        defns: "Sequence[Defn]" = (),
        child_type: "type[Schema] | None" = None,
        name: str | None = None,
    ) -> None:
        """Exception: a layout clash is a declaration error"""
        child_defns = tuple(defns)
        lookup = _dir_defn_ctor_uniq_lookups_exn(child_defns)
        object.__setattr__(self, "defns", child_defns)
        object.__setattr__(self, "lookup", MappingProxyType(lookup))
        object.__setattr__(self, "child_type", child_type)
        object.__setattr__(self, "name", name)


@dataclass(frozen=True, slots=True, init=False)
class DirDefn:
    """Directory node. `layouts` includes a plain RHS of length 1"""

    defn: Dir["Schema"]
    layouts: tuple[DirLayout, ...]

    def __init__(
        self,
        defn: Dir["Schema"],
        defns: "Sequence[Defn]" = (),
        child_type: "type[Schema] | None" = None,
        *,
        name: str | None = None,
        layouts: Sequence[DirLayout] | None = None,
    ) -> None:
        if layouts is not None:
            if defns or child_type is not None or name is not None:
                raise AssertionError("layouts replaces defns")
            chosen = tuple(layouts)
        else:
            chosen = (DirLayout(defns, child_type, name),)
        object.__setattr__(self, "defn", defn)
        object.__setattr__(self, "layouts", chosen)


@dataclass(frozen=True, slots=True)
class OneDefn:
    """One layout on a directory. Not a `DirDefn`: no `layouts` tuple"""

    defn: Dir["Schema"]
    layout: DirLayout


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
        normalized = normalize_name(node.name) if node.name else None
        for identity in dict.fromkeys(key for key in (node.alias, node.name, normalized, node.fmt) if key):
            add_uniq(identities, identity, index)
        if node.name:
            if normalized is None:
                raise ValueError(em.Fmt.basename(node.name))
            add_uniq(lookup, node.name, index)
            add_uniq(lookup, normalized, index)
        if node.alias:
            add_uniq(lookup, node.alias, index)
    return lookup


Defn: TypeAlias = File[object] | DirDefn


def normalize_name(name: Raw[Name]) -> Safe[Name] | None:
    normalized = re.sub(r"[^A-Za-z0-9_]+", "_", name)
    if isinstance(name, Safe) and normalized == name:
        return name
    return safe(Raw[Name](normalized))


def defn_node(defn: Defn) -> Node:
    return defn if isinstance(defn, File) else defn.defn


def is_union(layouts: Sequence[DirLayout]) -> bool:
    # One unnamed layout is that schema. A name, or more than one layout, stays a union
    return len(layouts) != 1 or layouts[0].name is not None


def child_attr(defn: Defn) -> str | None:
    node = defn_node(defn)
    if node.alias:
        return node.alias
    if node.name:
        return normalize_name(node.name)
    return None


def unnamed_clashes(layouts: Sequence[DirLayout]) -> frozenset[str]:
    groups: dict[str, list[Defn]] = {}
    for layout in layouts:
        if layout.name is not None:
            continue
        seen: set[str] = set()
        for child in layout.defns:
            attr = child_attr(child)
            if attr is None or attr in seen:
                continue
            seen.add(attr)
            groups.setdefault(attr, []).append(child)
    return frozenset(
        key
        for key, children in groups.items()
        if len(children) > 1 and any(child != children[0] for child in children[1:])
    )


def capture_names(defn: Defn) -> frozenset[str]:
    return defn_node(defn).selector.capture_names()


def validate_capture_names_exn(defn: Defn, kwargs: Mapping[str, CaptureField]) -> None:
    names = capture_names(defn)
    for name in kwargs:
        if name not in names:
            raise KeyError(name)
