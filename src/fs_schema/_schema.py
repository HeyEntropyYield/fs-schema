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
    File,
    Layout,
    Match,
    Node,
    defn_node,
    normalize_name,
    validate_capture_names_exn,
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
    PathIsh,
    Puttable,
    Raw,
    Safe,
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
    def name(self) -> Safe[Name]:
        return path_name_exn(self.path)

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
    fmt: ClassVar[Safe[FmtStr] | None]
    match: ClassVar[Raw[MatchPat] | None]
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
    fmt: ClassVar[Safe[FmtStr] | None]
    match: ClassVar[Raw[MatchPat] | None]
    min: ClassVar[int]
    max: ClassVar[int | None]
    path: SafePath
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
        self.path = safe_path_exn(Path(path))  # caller error
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
    def parse(self: "Matches[FileMatch[_L], File[_L]]", source: PathIsh) -> FixedFile[_L]: ...

    @overload
    def parse(self: "Matches[DirMatch, DirDefn]", source: PathIsh) -> "FixedDir": ...

    def parse(self, source: PathIsh) -> "FixedFile[object] | FixedDir":
        """Exception: raises to support chaining"""
        from ._plan import plan_fixed

        basename = Path(source).name
        if not (name := safe(Raw[Name](basename))) or defn_node(self.defn).select(name) is None:
            raise ValueError(em.Parse.member(basename))
        return plan_fixed(child_path_exn(self.path, name), self.defn)


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
    def format(self: "Template[FileMatch[_L], File[_L]]", *args: FmtFieldT, **kwargs: FmtFieldT) -> FixedFile[_L]: ...

    @overload
    def format(self: "Template[DirMatch, DirDefn]", *args: FmtFieldT, **kwargs: FmtFieldT) -> "FixedDir": ...

    def format(self, *args: FmtFieldT, **kwargs: FmtFieldT) -> "FixedFile[object] | FixedDir":
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

    Child: TypeAlias = "FixedFile[object] | FixedDir | Matches[FileMatch[object] | DirMatch]"
    # LUB of mixed slots. Optional exact may be None; required/collection never.
    BoundChild: TypeAlias = "Child | None"
    # Checker sees one view. Runtime stays Child | None so a missing optional is None.
    GetChild: TypeAlias = _ChildView
else:
    Child: TypeAlias = typing.Union[  # noqa: UP007
        FixedFile[object],
        ForwardRef("fs_schema._schema.FixedDir"),
        Matches[typing.Union[FileMatch[object], ForwardRef("fs_schema._schema.DirMatch")]],  # noqa: UP007
    ]
    BoundChild: TypeAlias = Child | None
    GetChild: TypeAlias = BoundChild


## Fixed directories


class FixedDir(_Fixed):
    alias: ClassVar[str | None]
    fmt: ClassVar[Safe[FmtStr] | None]
    match: ClassVar[Raw[MatchPat] | None]
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
        from ._create import write_plan_exn

        write_plan_exn(self, spec, **children)  # chaining
        return self


class DirMatch(_CaptureState, FixedDir):
    def __init__(self, path: PathIsh, captures: ParsedCaptures, children: Sequence[BoundChild], defn: DirDefn) -> None:
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


class Schema(FixedDir, metaclass=SchemaCls):
    schema: ClassVar["Layout"] = {}
    _schema_defn: ClassVar[DirDefn] = DirDefn(Dir(name="."))

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
        from ._plan import plan_dir_defn_children

        path = safe_path_exn(Path(root))  # caller error
        return _root_type_for(cls)(path, plan_dir_defn_children(path, cls._schema_defn), cls._schema_defn)

    @classmethod
    def bind(cls: type[_S], root: PathIsh, *, fast: bool = False) -> "_S | MismatchErr":
        """Exception: raises on an unsafe path"""
        from ._bind import bind_children

        path = safe_path_exn(Path(root))  # caller error
        if is_mismatch(children := bind_children(path, cls._schema_defn, {}, fast=fast)):
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
