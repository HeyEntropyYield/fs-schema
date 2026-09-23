import keyword
import os
import re
import typing
from collections.abc import Callable, Iterator, Mapping, Sequence
from dataclasses import KW_ONLY, dataclass, field, replace
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
    TypeIs,
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
_Default = TypeVar("_Default")


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

    def format(self, *args: FmtField, **kwargs: FmtField) -> str:
        if self._fmt is None:
            raise TypeError("declaration has no formatter")
        basename = self._fmt.format(*args, **kwargs)
        if self._match is not None and self._match.fullmatch(basename) is None:
            raise ValueError(f"formatted basename does not match {self._match.pattern!r}: {basename!r}")
        return basename

    def capture_names(self) -> frozenset[str]:
        if self._fmt is not None:
            return frozenset(field.name for field in self._fmt.fields if not field.positional)
        if self._match is not None:
            return frozenset(self._match.groupindex)
        return frozenset()


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
                for key in (node.alias, node.name, _normalize_name(node.name) if node.name else None, node.fmt)
                if key
            ):
                add(identities, identity, index)
            if node.name:
                add(lookup, node.name, index)
                add(lookup, _normalize_name(node.name), index)
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


def _load_model(path: Path, schema: type[_L_co]) -> _L_co | Exception:
    return load(path, schema)


class FixedFile(_Fixed, Generic[_L_co]):
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


def _normalize_name(name: str) -> str:
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

    def filter(self, predicate: CapturePredicate, /) -> Self:
        return type(self)(
            self.path,
            tuple(match for match in self._matches if predicate(match.args, match.kwargs)),
            self.defn,
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


class Template(Matches[_M_co, _Defn_co], Generic[_M_co, _Defn_co]):
    @overload
    def format(self: "Template[_FileMatch[_L], File[_L]]", *args: FmtField, **kwargs: FmtField) -> FixedFile[_L]: ...

    @overload
    def format(self: "Template[_DirMatch, DirDefn]", *args: FmtField, **kwargs: FmtField) -> "FixedDir": ...

    def format(self, *args: FmtField, **kwargs: FmtField) -> "FixedFile[object] | FixedDir":
        node = defn_node(self.defn)
        basename = _format_node(node, *args, **kwargs)
        if not is_safe_basename(basename):
            raise ValueError(f"formatted name must be a basename: {basename!r}")
        return plan_fixed(self.path / basename, self.defn)


if TYPE_CHECKING:
    Child: TypeAlias = "FixedFile[object] | FixedDir | Matches[_FileMatch[object] | _DirMatch]"
else:
    Child: TypeAlias = typing.Union[  # noqa: UP007
        FixedFile[object],
        ForwardRef("fs_schema._schema.FixedDir"),
        Matches[typing.Union[_FileMatch[object], ForwardRef("fs_schema._schema._DirMatch")]],  # noqa: UP007
    ]


class FixedDir(_Fixed):
    _children: tuple[Child, ...]
    _lookup: Mapping[str, int]
    defn: DirDefn

    def __init__(
        self,
        path: PathIsh,
        children: Sequence[Child],
        defn: DirDefn,
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
        node = defn_node(child.defn)
        if name != node.alias and name != _normalize_name(node.name):
            raise AttributeError(name)
        return child


class _DirMatch(_CaptureState, FixedDir):
    def __init__(self, path: PathIsh, captures: ParsedCaptures, children: Sequence[Child], defn: DirDefn) -> None:
        FixedDir.__init__(self, path, children, defn)
        self._captures: ParsedCaptures = captures


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
    if isinstance(defn, File):
        return FixedFile(path, defn)
    return FixedDir(path, _plan_children(path, defn), defn)


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


FsCache: TypeAlias = dict[Path, CacheSeq[Path]]
_MatchValue = TypeVar("_MatchValue", bound=Match)


def _is_kind(path: Path, defn: Defn) -> bool:
    return path.is_file() if isinstance(defn, File) else path.is_dir()


def _bind_children(path: Path, dir_defn: DirDefn, cache: FsCache) -> tuple[Child, ...] | MismatchErr:
    if not path.is_dir():
        return MismatchErr(f"expected directory: {path}")

    children: list[Child] = []
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


def _bind_dir_defn(path: Path, position: int, defn: Defn, cache: FsCache) -> Child | MismatchErr:
    node = defn_node(defn)
    if node.name:
        target = path / node.name
        if node.select(target.name) is None:
            return MismatchErr(f"fixed basename does not match {node.match!r}: {target}")
        if not _is_kind(target, defn):
            kind = "file" if isinstance(defn, File) else "directory"
            return MismatchErr(f"expected {kind}: {target}")
        return _bind_fixed(target, defn, cache)

    if is_mismatch(matches := _bind_matches(defn, _listing(path, cache), cache)):
        return matches
    count = len(matches)
    if count < node.min or (node.max is not None and count > node.max):
        upper = "unbounded" if node.max is None else str(node.max)
        return MismatchErr(f"expected {node.min}..{upper} matches for defn {position}, found {count}: {path}")
    return Template(path, matches, defn) if node.fmt is not None else Matches(path, matches, defn)


@overload
def _bind_fixed(path: Path, defn: File[_L], cache: FsCache) -> FixedFile[_L]: ...


@overload
def _bind_fixed(path: Path, defn: DirDefn, cache: FsCache) -> FixedDir | MismatchErr: ...


def _bind_fixed(path: Path, defn: Defn, cache: FsCache) -> FixedFile[object] | FixedDir | MismatchErr:
    if isinstance(defn, File):
        return FixedFile(path, defn)
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


def _bind_file_matches(defn: File[_L], listing: Sequence[Path]) -> list[_FileMatch[_L]]:
    matches: list[_FileMatch[_L]] = []
    for target in listing:
        if (captures := defn.select(target.name)) is None or not _is_kind(target, defn):
            continue
        matches.append(_FileMatch(target, captures, defn))
    return _sort_matches(matches, defn)


def _bind_dir_matches(defn: DirDefn, listing: Sequence[Path], cache: FsCache) -> list[_DirMatch] | MismatchErr:
    matches: list[_DirMatch] = []
    for target in listing:
        if (captures := defn.defn.select(target.name)) is None or not _is_kind(target, defn):
            continue
        if is_mismatch(children := _bind_children(target, defn, cache)):
            return children
        matches.append(_DirMatch(target, captures, children, defn))
    return _sort_matches(matches, defn.defn)


@overload
def _bind_matches(defn: File[_L], listing: Sequence[Path], cache: FsCache) -> Sequence[_FileMatch[_L]]: ...


@overload
def _bind_matches(defn: DirDefn, listing: Sequence[Path], cache: FsCache) -> Sequence[_DirMatch] | MismatchErr: ...


def _bind_matches(
    defn: Defn, listing: Sequence[Path], cache: FsCache
) -> Sequence[_FileMatch[object] | _DirMatch] | MismatchErr:
    if isinstance(defn, File):
        return _bind_file_matches(defn, listing)
    return _bind_dir_matches(defn, listing, cache)


def bind_defns(root: PathIsh, defns: Sequence[Defn]) -> FixedDir | MismatchErr:
    path = Path(root)
    dir_defn = DirDefn(Dir(name="."), defns)
    if is_mismatch(children := _bind_children(path, dir_defn, {})):
        return children
    return FixedDir(path, children, dir_defn)


## Schemas


def _is_schema_type(value: object) -> TypeIs["type[Schema]"]:
    return isinstance(value, SchemaCls) and issubclass(value, Schema)


def _schema_defn_for(schema_type: "type[Schema]") -> DirDefn:
    value = vars(schema_type).get("_schema_defn")
    if not isinstance(value, DirDefn):
        raise AssertionError(f"{schema_type.__name__} has no compiled schema definition")
    return value


def _invalid_schema(class_name: str, detail: str) -> TypeError:
    return TypeError(f"{class_name}.schema {detail}")


def _validate_schema_node(class_name: str, key: object, node: Node) -> None:
    if node.name and not is_safe_basename(node.name):
        raise _invalid_schema(class_name, f"declaration {key!r} name must be a basename")
    if node.alias and (not node.alias.isidentifier() or keyword.iskeyword(node.alias) or node.alias.startswith("_")):
        raise _invalid_schema(class_name, f"declaration {key!r} alias must be a public identifier")
    if isinstance(node, Dir) and node.schema is not None and not _is_schema_type(node.schema):
        raise _invalid_schema(class_name, f"declaration {key!r} Dir.schema must be a Schema subclass")


def _aliased_file(alias: str, source: File[_L]) -> File[_L]:
    return source if source.alias == alias else replace(source, alias=alias)


def _identity(defn: Defn) -> str | None:
    node = defn_node(defn)
    return node.alias or node.name or node.fmt or None


def _merge_defns(base: Sequence[Defn], local: Sequence[Defn]) -> tuple[Defn, ...]:
    merged = list(base)
    positions = {identity: index for index, defn in enumerate(base) if (identity := _identity(defn)) is not None}
    for defn in local:
        identity = _identity(defn)
        if identity is None or identity not in positions:
            if identity is not None:
                positions[identity] = len(merged)
            merged.append(defn)
        else:
            merged[positions[identity]] = defn
    return tuple(merged)


def _children_satisfy(actual: Sequence[Defn], required: Sequence[Defn]) -> bool:
    matched_anonymous: set[int] = set()
    for required_child in required:
        identity = _identity(required_child)
        if identity is None:
            found = next(
                (
                    index
                    for index, candidate in enumerate(actual)
                    if index not in matched_anonymous and _defn_satisfies(candidate, required_child)
                ),
                None,
            )
            if found is None:
                return False
            matched_anonymous.add(found)
            continue
        actual_child = next((candidate for candidate in actual if _identity(candidate) == identity), None)
        if actual_child is None or not _defn_satisfies(actual_child, required_child):
            return False
    return True


def _defn_satisfies(actual: Defn, required: Defn) -> bool:
    if isinstance(required, File):
        return isinstance(actual, File) and actual == required
    return (
        isinstance(actual, DirDefn) and actual.defn == required.defn and _children_satisfy(actual.defns, required.defns)
    )


def _make_inline_schema(class_name: str, module: str, position: int, layout: dict[object, object]) -> "type[Schema]":
    generated = type(
        f"_{class_name}Child{position}",
        (Schema,),
        {"__module__": module, "schema": layout},
    )
    if not _is_schema_type(generated):
        raise AssertionError("generated Schema child has an invalid type")
    return generated


def _directory_defn(class_name: str, key: object, node: "Dir[Schema]", child_type: "type[Schema]") -> DirDefn:
    child_root = _schema_defn_for(child_type)
    compiled = DirDefn(node, child_root.defns, child_type)
    if node.schema is not None:
        contract = _schema_defn_for(node.schema)
        if not _children_satisfy(compiled.defns, contract.defns):
            raise _invalid_schema(class_name, f"declaration {key!r} RHS does not satisfy Dir.schema")
    return compiled


def _is_schema_dir(value: object) -> TypeIs["Dir[Schema]"]:
    return isinstance(value, Dir)


def _is_raw_mapping(value: object) -> TypeIs[dict[object, object]]:
    return isinstance(value, dict)


def _is_raw_list(value: object) -> TypeIs[list[object]]:
    return isinstance(value, list)


def _raw_schema(cls: "type[Schema]") -> object:
    return cls.schema if "schema" in cls.__dict__ else {}


def _compile_local_defns(cls: "type[Schema]") -> tuple[Defn, ...]:
    raw = _raw_schema(cls)
    if not _is_raw_mapping(raw):
        raise _invalid_schema(cls.__name__, "must be a dict")
    entries = raw
    defns: list[Defn] = []
    for key, value in entries.items():
        match key, value:
            case FilesKey() as token, _ if token is FILES and _is_raw_list(value):
                for item in value:
                    if isinstance(item, str):
                        file = File(name=item)
                    elif isinstance(item, File):
                        file = item
                    else:
                        raise _invalid_schema(cls.__name__, f"key {key!r} member {item!r} must be a str or File")
                    _validate_schema_node(cls.__name__, key, file)
                    defns.append(file)
            case str() as name, _ if _is_raw_mapping(value):
                node: Dir[Schema] = Dir(name=name)
                _validate_schema_node(cls.__name__, key, node)
                child_type = _make_inline_schema(cls.__name__, cls.__module__, len(defns), value)
                defns.append(_directory_defn(cls.__name__, key, node, child_type))
            case lhs, _ if _is_schema_dir(lhs) and _is_raw_mapping(value):
                node = lhs
                _validate_schema_node(cls.__name__, key, node)
                child_type = _make_inline_schema(cls.__name__, cls.__module__, len(defns), value)
                defns.append(_directory_defn(cls.__name__, key, node, child_type))
            case str() as name, rhs if _is_schema_type(rhs):
                node = Dir(name=name)
                _validate_schema_node(cls.__name__, key, node)
                defns.append(_directory_defn(cls.__name__, key, node, rhs))
            case lhs, rhs if _is_schema_dir(lhs) and _is_schema_type(rhs):
                node = lhs
                _validate_schema_node(cls.__name__, key, node)
                defns.append(_directory_defn(cls.__name__, key, node, rhs))
            case str() as alias, str() as name:
                file = File(name=name, alias=alias)
                _validate_schema_node(cls.__name__, key, file)
                defns.append(file)
            case str() as alias, File() as source:
                file = _aliased_file(alias, source)
                _validate_schema_node(cls.__name__, key, file)
                defns.append(file)
            case FilesKey() as token, _ if token is FILES:
                raise _invalid_schema(cls.__name__, f"key {key!r} requires a list of file declarations")
            case _:
                raise _invalid_schema(cls.__name__, f"invalid entry at key {key!r}")
    return tuple(defns)


_CAPTURE_MEMBERS: Final = frozenset(("args", "kwargs"))
_UNSAFE_SCHEMA_DUNDERS: Final = frozenset(
    "RootT __delattr__ __fspath__ __getattr__ __getattribute__ __getitem__ __init__ __init_subclass__ "
    "__iter__ __len__ __new__ __setattr__ __slots__".split()  # pyright: ignore[reportImplicitStringConcatenation]
)


def _validate_schema_bases(class_name: str, bases: tuple[type[object], ...]) -> None:
    if "Schema" not in globals():
        return
    if len(bases) != 1 or not _is_schema_type(bases[0]):
        raise TypeError(f"{class_name} must have exactly one direct Schema base and no mixins")


def _validate_schema_class(cls: "type[Schema]") -> None:
    if type(cls) is not SchemaCls:
        raise TypeError(f"{cls.__name__} must use the exact Schema metaclass")
    if len(cls.__bases__) != 1 or not _is_schema_type(cls.__bases__[0]):
        raise TypeError(f"{cls.__name__} must have exactly one direct Schema base and no mixins")

    inherited_members = {
        name for ancestor in cls.__mro__[1:] for name in ancestor.__dict__ if not name.startswith("__")
    } - {"schema"}
    if unsafe := cls.__dict__.keys() & (inherited_members | _CAPTURE_MEMBERS | _UNSAFE_SCHEMA_DUNDERS):
        raise TypeError(f"{cls.__name__} Schema declaration cannot override {sorted(unsafe)[0]!r}")


def _compile_schema(cls: "type[Schema]") -> None:
    base = cls.__bases__[0]
    if not _is_schema_type(base):
        raise AssertionError("validated Schema class lost its Schema base")
    local_defns = _compile_local_defns(cls)
    try:
        _ = DirDefn(Dir(name="."), local_defns)
        defns = _merge_defns(_schema_defn_for(base).defns, local_defns)
        type.__setattr__(cls, "_schema_defn", DirDefn(Dir(name="."), defns))
    except ValueError as error:
        raise _invalid_schema(cls.__name__, str(error)) from error


def _validate_child_shadows(cls: "type[Schema]") -> None:
    for defn in _schema_defn_for(cls).defns:
        node = defn_node(defn)
        for name in (node.alias or None, _normalize_name(node.name) if node.name else None):
            if name is not None and (
                name in _CAPTURE_MEMBERS
                or any(name in ancestor.__dict__ for ancestor in (*cls.__mro__, *type(cls).__mro__))
            ):
                raise _invalid_schema(cls.__name__, f"child {name!r} shadows a Schema member")


class SchemaCls(type):
    def __new__(
        metacls: "type[SchemaCls]",
        name: str,
        bases: tuple[type[object], ...],
        namespace: dict[str, object],
        **kwargs: object,
    ) -> "SchemaCls":
        _validate_schema_bases(name, bases)
        return super().__new__(metacls, name, bases, namespace, **kwargs)

    def __getattr__(cls, name: str) -> type:
        if name.startswith("_") or not _is_schema_type(cls):
            raise AttributeError(name)
        try:
            root_defn = _schema_defn_for(cls)
            defn = root_defn.defns[root_defn.lookup[name]]
        except (AssertionError, KeyError):
            raise AttributeError(name) from None
        node = defn_node(defn)
        if name != node.alias and name != _normalize_name(node.name):
            raise AttributeError(name)
        if node.name:
            child_type: type[object] = FixedFile if isinstance(defn, File) else defn.child_type or FixedDir
        else:
            child_type = Template if node.fmt is not None else Matches
        return child_type

    @property
    def RootT(cls) -> "type[SchemaRoot[Schema]]":
        if not _is_schema_type(cls):
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
        _validate_schema_class(cls)
        _compile_schema(cls)
        _validate_child_shadows(cls)

    @classmethod
    def relative_to(cls: type[_S], root: PathIsh) -> "SchemaRoot[_S]":
        path = Path(root)
        return _root_type_for(cls)(path, _plan_children(path, cls._schema_defn), cls._schema_defn)

    @classmethod
    def bind(cls: type[_S], root: PathIsh | Located) -> "_S | MismatchErr":
        path = root.path if isinstance(root, Located) else Path(root)
        if is_mismatch(children := _bind_children(path, cls._schema_defn, {})):
            return children
        return cls(path, children, cls._schema_defn)

    def root(self) -> "SchemaRoot[Self]":
        return type(self).relative_to(self.path)
