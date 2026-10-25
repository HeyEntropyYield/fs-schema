import os
import typing
from collections.abc import Callable, Iterator, Mapping, Sequence
from pathlib import Path
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
    Never,
    Protocol,
    Self,
    TypeIs,
    TypeVar,
    assert_never,
    override,
)

import fs_schema._decl as _decl
import fs_schema._errmsg as em

from ._decl import (
    Defn,
    Dir,
    DirDefn,
    DirLayout,
    File,
    Layout,
    Match,
    Node,
    OneDefn,
    Xor,
    capture_names,
    child_attr,
    defn_node,
    is_union,
    normalize_name,
    unnamed_clashes,
)
from ._fmt import (
    CaptureField,
    CaptureMap,
    ParsedCaptures,
    child_path_exn,
    path_name_exn,
    safe,
    safe_path_exn,
)
from ._ops import MismatchErr, is_mismatch, load, put, raise_exn
from ._ops import copy_to as copy_path
from ._ops import link_to as link_path
from ._types import (
    CreateTop,
    CreateValue,
    FmtFields,
    FmtFieldT,
    FmtStr,
    MatchPat,
    Name,
    Open,
    PathIsh,
    Puttable,
    Raw,
    SafePath,
)


@final
class _MissingDefault:
    __slots__: Final = ()


# The concrete Schema subtype is preserved by root and bind operations.
_S = TypeVar("_S", bound="Schema")
_Model = TypeVar("_Model")
# Unannotated load() is object. An assignment annotation solves this variable.
_Loaded = TypeVar("_Loaded", default=object)
# Substituted into File and FixedFile. Not the TypeVar on File.
_L = TypeVar("_L")
_L_co = TypeVar("_L_co", covariant=True, default=object)
# Template collections only produce their concrete Match subtype.
_M_co = TypeVar("_M_co", bound="Match", covariant=True)
_Default = TypeVar("_Default")

_MISSING_DEFAULT: Final = _MissingDefault()


# Section order:
#   Declarations live in _decl.py. Match, Node, File, Dir, FILES, Layout, DirDefn.
#   Runtime values. Path passthrough and FixedFile.
#   Runtime template matches and collections. Matches, Template, Child.
#   Fixed directories. FixedDir and directory matches.
#   Schema classes. SchemaCls, SchemaRoot, Schema.
# Plan and format live in _plan.py. Bind lives in _bind.py.
# Compilation and class member views live in _compile.py.


_Defn_co = TypeVar("_Defn_co", bound=Defn, covariant=True, default=Defn)


## Runtime values


class _Fixed:
    _path: SafePath

    def __init__(self, path: PathIsh) -> None:
        self._path = safe_path_exn(Path(path))  # caller error

    @property
    def path(self) -> SafePath:
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
        # Exact str for callers. path_name_exn stays Safe for select and close
        return str(path_name_exn(self.path))

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
    fmt: ClassVar[Open[FmtStr] | None]
    match: ClassVar[Raw[MatchPat] | None]
    min: ClassVar[int]
    max: ClassVar[int | None]
    defn: File[_L_co]
    _scope: CaptureMap | None

    def __init__(self, path: PathIsh, defn: File[_L_co], *, scope: CaptureMap | None = None) -> None:
        _Fixed.__init__(self, path)
        self.defn = defn
        self._scope = scope

    def __getattr__(self, name: str) -> CaptureMap:
        # Present only when an ancestor frame resolved this name
        if name == "kwargs" and self._scope is not None:
            return self._scope
        raise AttributeError(name)

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


class FileMatch(_CaptureState, FixedFile[_L_co], Generic[_L_co]):
    def __init__(self, path: PathIsh, captures: ParsedCaptures, defn: File[_L_co]) -> None:
        FixedFile.__init__(self, path, defn)
        self._captures: ParsedCaptures = captures


class Matches(Sequence[_M_co], Generic[_M_co, _Defn_co]):
    alias: ClassVar[str | None]
    fmt: ClassVar[Open[FmtStr] | None]
    match: ClassVar[Raw[MatchPat] | None]
    min: ClassVar[int]
    max: ClassVar[int | None]
    path: SafePath
    _matches: tuple[_M_co, ...]
    defn: _Defn_co
    fmt_fields: FmtFields
    scope: CaptureMap | None

    def __init__(
        self, path: PathIsh, matches: Sequence[_M_co], defn: _Defn_co, fmt_fields: FmtFields | None = None, *, scope: CaptureMap | None = None,
    ) -> None:  # fmt: skip
        self.path = safe_path_exn(Path(path))  # caller error
        self._matches = tuple(matches)
        self.defn = defn
        self.fmt_fields = dict(fmt_fields or {})
        # where() walks this frame. A slice is a new collection, so the frame is an argument
        self.scope = scope

    @overload
    def __getitem__(self, index: int) -> _M_co: ...

    @overload
    def __getitem__(self, index: slice) -> Self: ...

    @override
    def __getitem__(self, index: int | slice) -> _M_co | Self:
        if isinstance(index, slice):
            return type(self)(self.path, self._matches[index], self.defn, self.fmt_fields, scope=self.scope)
        return self._matches[index]

    @override
    def __len__(self) -> int:
        return len(self._matches)

    def filter(self, predicate: CapturePredicate, /) -> Self:
        matches = tuple(match for match in self._matches if predicate(match.args, match.kwargs))
        return type(self)(self.path, matches, self.defn, self.fmt_fields, scope=self.scope)

    def find(self, predicate: CapturePredicate, /) -> _M_co | None:
        return next((match for match in self._matches if predicate(match.args, match.kwargs)), None)

    def where(self, *args: CaptureField, **kwargs: CaptureField) -> Self:
        """Exception: raises to support chaining"""
        names = capture_names(self.defn)
        for name in kwargs:
            if name not in names and (self.scope is None or name not in self.scope):
                raise KeyError(name)
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
    def parse(self: "Matches[FileMatch[_L], File[_L]]", source: PathIsh) -> FixedFile[_L]: ...

    @overload
    def parse(self: "Matches[DirMatch, DirDefn]", source: PathIsh) -> "FixedDir | XorDir": ...

    def parse(self, source: PathIsh) -> "FixedFile[object] | FixedDir | XorDir":
        """Exception: raises to support chaining"""
        from ._plan import plan_fixed_exn

        basename = Path(source).name
        node = defn_node(self.defn)
        if not (name := safe(Raw[Name](basename))) or (held := node.select(name)) is None:
            raise ValueError(em.Parse.member(basename))
        child = child_path_exn(self.path, name)
        if isinstance(self.defn, File):
            return plan_fixed_exn(child, self.defn)
        return plan_fixed_exn(child, self.defn, held.kwargs.chain(self.scope))


def _matches_where_captures(
    captured_args: tuple[CaptureField, ...], captured_kwargs: CaptureMap, args: tuple[CaptureField, ...], kwargs: Mapping[str, CaptureField],
) -> bool:  # fmt: skip
    if len(args) > len(captured_args):
        return False
    if any(expected is not None and actual != expected for actual, expected in zip(captured_args, args, strict=False)):
        return False
    return all(captured_kwargs[name] == value for name, value in kwargs.items())


class Template(Matches[_M_co, _Defn_co], Generic[_M_co, _Defn_co]):
    @overload
    def format(self: "Template[FileMatch[_L], File[_L]]", *args: FmtFieldT, **kwargs: FmtFieldT) -> FixedFile[_L]: ...

    @overload
    def format(self: "Template[DirMatch, DirDefn]", *args: FmtFieldT, **kwargs: FmtFieldT) -> "FixedDir | XorDir": ...

    def format(self, *args: FmtFieldT, **kwargs: FmtFieldT) -> "FixedFile[object] | FixedDir | XorDir":
        """Exception: raises to support chaining"""
        from ._plan import format_any_exn

        return format_any_exn(self, *args, **kwargs)  # chaining


if TYPE_CHECKING:

    class _ChildView(Protocol):
        """Static view of a child. Not every runtime object has every method."""

        path: Path  # FixedFile, FixedDir, FileMatch, DirMatch
        name: str  # FixedFile, FixedDir, FileMatch, DirMatch
        stem: str  # FixedFile, FixedDir, FileMatch, DirMatch
        suffix: str  # FixedFile, FixedDir, FileMatch, DirMatch

        @property
        def args(self) -> tuple[CaptureField, ...]: ...  # FileMatch, DirMatch

        @property
        def kwargs(self) -> CaptureMap: ...  # FileMatch, DirMatch

        def __bool__(self) -> bool: ...  # FixedFile, FixedDir, FileMatch, DirMatch

        def __contains__(self, value: object) -> bool: ...  # Matches, Template

        def __fspath__(self) -> str: ...  # FixedFile, FixedDir, FileMatch, DirMatch

        def __getattr__(self, name: str) -> "_ChildView": ...  # FixedDir, DirMatch

        def __getitem__(self, index: int | str) -> "_ChildView": ...  # FixedDir, Matches, Template, DirMatch

        def __iter__(self) -> Iterator["_ChildView"]: ...  # FixedDir, Matches, Template, DirMatch

        def __len__(self) -> int: ...  # Matches, Template

        def __lt__(self, other: object) -> bool: ...  # FixedFile, FixedDir, Matches, Template, FileMatch, DirMatch

        def __next__(self) -> "_ChildView": ...  # FixedDir, Matches, Template, DirMatch

        def __reversed__(self) -> Iterator["_ChildView"]: ...  # Matches, Template

        @override
        def __str__(self) -> str: ...  # FixedFile, FixedDir, Matches, Template, FileMatch, DirMatch

        def copy_to(
            self, dest: PathIsh, *, follow_symlinks: bool = True, clean: bool = False
        ) -> None: ...  # FixedFile, FixedDir, FileMatch, DirMatch

        def count(self, value: object) -> int: ...  # Matches, Template

        def create(
            self, data: Puttable | PathIsh | None = None, /, **children: CreateTop
        ) -> "_ChildView": ...  # FixedFile, FixedDir, FileMatch, DirMatch

        def exists(self) -> bool: ...  # FixedFile, FixedDir, FileMatch, DirMatch

        def filter(self, predicate: CapturePredicate, /) -> "_ChildView": ...  # Matches, Template

        def find(self, predicate: CapturePredicate, /) -> "_ChildView | None": ...  # Matches, Template

        def format(self, *args: FmtFieldT, **kwargs: FmtFieldT) -> "_ChildView": ...  # Template

        def get(self, index: int = 0) -> "_ChildView | None": ...  # Matches, Template

        def index(self, value: object, start: int = 0, stop: int | None = None) -> int: ...  # Matches, Template

        def link_to(
            self, target: PathIsh, *, hard: bool = False
        ) -> None: ...  # FixedFile, FixedDir, FileMatch, DirMatch

        @overload
        def load(self) -> _Loaded | Exception: ...  # FixedFile, FileMatch

        @overload
        def load(self, model: type[_Model]) -> _Model | Exception: ...  # FixedFile, FileMatch

        def parse(self, source: PathIsh) -> "_ChildView": ...  # Matches, Template

        def read_bytes(self) -> bytes: ...  # FixedFile, FileMatch

        def read_text(self) -> str: ...  # FixedFile, FileMatch

        def where(self, *args: CaptureField, **kwargs: CaptureField) -> "_ChildView": ...  # Matches, Template

    Child: TypeAlias = "FixedFile[object] | FixedDir | XorDir | Matches[FileMatch[object] | DirMatch]"
    # LUB of mixed slots. Optional exact may be None; required/collection never.
    BoundChild: TypeAlias = "Child | None"
    # Checker sees one view. Runtime stays Child | None so a missing optional is None.
    GetChild: TypeAlias = _ChildView
else:
    Child: TypeAlias = typing.Union[  # noqa: UP007
        FixedFile[object],
        ForwardRef("fs_schema._schema.FixedDir"),
        ForwardRef("fs_schema._schema.XorDir"),
        Matches[typing.Union[FileMatch[object], ForwardRef("fs_schema._schema.DirMatch")]],  # noqa: UP007
    ]
    BoundChild: TypeAlias = Child | None
    GetChild: TypeAlias = BoundChild


## Fixed directories


class FixedDir(_Fixed):
    alias: ClassVar[str | None]
    fmt: ClassVar[Open[FmtStr] | None]
    match: ClassVar[Raw[MatchPat] | None]
    min: ClassVar[int]
    max: ClassVar[int | None]
    _children: tuple[BoundChild, ...]
    _lookup: Mapping[str, int]
    fmt_fields: FmtFields
    defn: OneDefn

    def __init__(
        self, path: PathIsh, children: Sequence[BoundChild], defn: OneDefn, fmt_fields: FmtFields | None = None,
    ) -> None:  # fmt: skip
        _Fixed.__init__(self, path)
        self._children = tuple(children)
        self._lookup = defn.layout.lookup
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
        held = self.defn.layout.defns[index] if child is None else child.defn
        node = held.defn if isinstance(held, OneDefn) else defn_node(held)
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
        from ._create import write_plan_exn

        write_plan_exn(self, spec, **children)  # chaining
        return self


class XorDir(_Fixed):
    """Plan of a union. Bind replaces this with the winning layout"""

    defn: DirDefn
    _arms: tuple[FixedDir, ...]
    _clashes: frozenset[str]

    def __init__(self, path: PathIsh, defn: DirDefn, scope: CaptureMap | None = None) -> None:
        from ._plan import layout_scope, plan_layout_children_exn

        _Fixed.__init__(self, path)
        self.defn = defn
        self._clashes = unnamed_clashes(defn.layouts)
        self._arms = tuple(FixedDir(
            self.path,
            plan_layout_children_exn(self.path, layout, layout_scope(layout, scope)),  # caller error
            OneDefn(defn.defn, layout),
        ) for layout in defn.layouts)  # fmt: skip

    @overload
    def __getitem__(self, index: int) -> FixedDir: ...

    @overload
    def __getitem__(self, index: str) -> FixedDir: ...

    def __getitem__(self, index: int | str) -> FixedDir:
        if isinstance(index, str):
            for layout, arm in zip(self.defn.layouts, self._arms, strict=True):
                if layout.name == index:
                    return arm
            raise KeyError(index)
        unnamed = tuple(arm for layout, arm in zip(self.defn.layouts, self._arms, strict=True) if layout.name is None)
        return unnamed[index]

    def __getattr__(self, name: str) -> Child:
        for layout, arm in zip(self.defn.layouts, self._arms, strict=True):
            if layout.name == name:
                return arm
        if name in self._clashes:
            raise AttributeError(em.Xor.clash(name))
        # Unnamed branches only. Their children are promoted. Named children stay on the branch
        found: list[Child] = []
        for layout, arm in zip(self.defn.layouts, self._arms, strict=True):
            if layout.name is not None:
                continue
            for child in layout.defns:
                if child_attr(child) != name:
                    continue
                found.append(typing.cast(Child, getattr(arm, name)))
        if not found:
            raise AttributeError(name)
        return found[0]

    def create(self, spec: Mapping[str, CreateTop] | None = None, /, **children: CreateTop) -> Never:
        raise TypeError(em.Xor.single(self.path))


class DirMatch(_CaptureState, FixedDir):
    def __init__(self, path: PathIsh, captures: ParsedCaptures, children: Sequence[BoundChild], defn: OneDefn) -> None:
        FixedDir.__init__(self, path, children, defn)
        self._captures: ParsedCaptures = captures


# A bound fmt directory is a generated class: the child schema plus a capture match.
# BOUND_MATCH tells SchemaCls this is not a user schema, so it is not compiled.
BOUND_MATCH: Final = "_fs_schema_bound_match"
_GenT = TypeVar("_GenT", bound=type)


def stored_type(owner: type, slot: str, ok: Callable[[object], bool], build: Callable[[], _GenT]) -> _GenT:
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
        # A user schema has a Schema base. class Schema itself does not, and a match sets BOUND_MATCH.
        # This does not look at globals, so import order cannot skip the check.
        if namespace.get(BOUND_MATCH) or not any(isinstance(base, SchemaCls) for base in bases):
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

    return stored_type(
        schema_type,
        "_root_type",
        lambda value: _is_root_type_for(value, schema_type),
        build,
    )


def _root_bound(body: DirLayout) -> OneDefn:
    return OneDefn(Dir(name="."), body)


class Schema(FixedDir, metaclass=SchemaCls):
    schema: ClassVar["Layout"] = {}
    warn: ClassVar[bool] = True
    _schema_defn: ClassVar[DirLayout] = DirLayout()

    def __init_subclass__(cls) -> None:
        super().__init_subclass__()
        if cls.__dict__.get(BOUND_MATCH):
            return
        from ._compile import schema_ctor_check_class, schema_ctor_check_defn_shadows, schema_ctor_compile_defn

        _ = raise_exn(schema_ctor_check_class(cls))
        _ = raise_exn(schema_ctor_compile_defn(cls))
        _ = raise_exn(schema_ctor_check_defn_shadows(cls))  # req compile_defn
        _schema_ctor_install_attrs(cls)

    @classmethod
    def relative_to(cls: type[_S], root: PathIsh) -> "SchemaRoot[_S]":
        """Exception: raises on an unsafe path"""
        from ._plan import plan_layout_children_exn

        path = safe_path_exn(Path(root))  # caller error
        body = cls._schema_defn
        return _root_type_for(cls)(path, plan_layout_children_exn(path, body), _root_bound(body))  # caller error

    @classmethod
    def bind(cls: type[_S], root: PathIsh, *, fast: bool = False) -> "_S | MismatchErr":
        """Exception: raises on an unsafe path"""
        from ._bind import bind_children

        path = safe_path_exn(Path(root))  # caller error
        body = cls._schema_defn
        if is_mismatch(children := bind_children(path, body, {}, fast=fast)):
            return children
        return cls(path, children, _root_bound(body))

    def root(self) -> "SchemaRoot[Self]":
        return type(self).relative_to(self.path)


def _schema_ctor_child_names(node: Node) -> tuple[str, ...]:
    names: list[str] = []
    if node.alias:
        names.append(node.alias)
    if node.name and (normalized := normalize_name(node.name)) and normalized not in names:
        names.append(normalized)
    return tuple(names)


class _BranchTable:
    """Declaration of a union. Not a schema class, and not the bound value"""

    _branches: tuple[tuple[str | None, type[Schema]], ...]

    def __init__(self, layouts: Sequence[DirLayout]) -> None:
        branches: list[tuple[str | None, type[Schema]]] = []
        for layout in layouts:
            child = layout.child_type
            if child is None:
                continue
            branches.append((layout.name, child))
            if layout.name is not None:
                setattr(self, layout.name, child)
        self._branches = tuple(branches)

    def __getitem__(self, key: str | int) -> type[Schema]:
        if isinstance(key, str):
            for name, child in self._branches:
                if name == key:
                    return child
            raise KeyError(key)
        unnamed = tuple(child for name, child in self._branches if name is None)
        try:
            return unnamed[key]
        except IndexError:
            raise KeyError(key) from None


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
    # One unnamed directory schema is that class. A union stays a table so each branch stays addressable.
    # A file or a repeated name is a view: a generated class with alias, fmt, and with_.
    # Alias and normalized basename are the same object. Nothing is built again on lookup.
    from ._compile import member_view, schema_defn_for

    installed: list[str] = []
    for defn in schema_defn_for(cls).defns:
        node = defn_node(defn)
        names = _schema_ctor_child_names(node)
        if not names:
            continue
        if isinstance(defn, DirDefn) and is_union(defn.layouts):
            target: object = _BranchTable(defn.layouts)
        elif node.name and isinstance(defn, File):
            target = member_view(cls, FixedFile, node)
        elif node.name and isinstance(defn, DirDefn):
            # An exact directory's child class is set when the directory is compiled.
            child_type = defn.layouts[0].child_type if defn.layouts else None
            if child_type is None:
                raise AssertionError("exact directory has no child class")
            target = child_type
        elif node.fmt:
            target = member_view(cls, Template, node)
        else:
            target = member_view(cls, Matches, node)
        for name in names:
            type.__setattr__(cls, name, _DeclAttr(name, target))
        installed.extend(names)
    # Shadow checks ignore these names on a parent, so a subclass can declare the same child.
    type.__setattr__(cls, "_child_attrs", frozenset(installed))


# Beartype resolves DirDefn's quoted Schema on this module, after the class exists.
_decl.Schema = Schema  # pyright: ignore[reportPrivateLocalImportUsage]

# Layout is static-only. A branch body is a dict the checker cannot pair with its key.
_XorBody: TypeAlias = dict[str | Dir[Schema] | _decl.FilesKey, object]


def xor(*branches: type[Schema] | _XorBody, **named: type[Schema] | _XorBody) -> Xor:
    entries = tuple((None, branch) for branch in branches)
    entries += tuple(named.items())
    return Xor(entries)
