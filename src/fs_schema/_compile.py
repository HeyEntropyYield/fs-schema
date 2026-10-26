# pyright: reportImportCycles=false, reportPrivateUsage=false
import inspect
import keyword
import typing
import warnings
from collections.abc import Sequence
from string import Formatter
from typing import Final

from attrs import evolve
from typing_extensions import TypeIs, TypeVar

import fs_schema._errmsg as em

from ._decl import (
    FILES,
    Defn,
    Dir,
    DirDefn,
    DirLayout,
    File,
    FilesKey,
    Node,
    Xor,
    defn_node,
    normalize_name,
    unnamed_clashes,
)
from ._fmt import REF
from ._fmt_spec import spec_type_exn
from ._schema import Schema, SchemaCls, Template
from ._types import FieldSpecs, Safe

_L = TypeVar("_L")
_NAME_FMT = Formatter()


def _annotation_names(cls: type[object]) -> frozenset[str]:
    found: set[str] = set()
    for klass in cls.__mro__:
        found.update(inspect.get_annotations(klass))
    return frozenset(found)


# Names lookup finds before __getattr__. dir() is the methods. Annotations are the fields.
_COLLECTION_ATTRS: Final = frozenset(dir(Template)) | _annotation_names(Template)
INLINE: Final = "_fs_schema_inline"
CAPTURE_SCOPE: Final = "_fs_schema_capture_scope"


def is_schema_type(value: object) -> TypeIs[type[Schema]]:
    return isinstance(value, SchemaCls) and issubclass(value, Schema)


def schema_defn_for(schema_type: type[Schema]) -> DirLayout:
    value = vars(schema_type).get("_schema_defn")
    if not isinstance(value, DirLayout):
        raise AssertionError(f"{schema_type.__name__} has no compiled schema definition")
    return value


def _invalid_schema(class_name: str, detail: str) -> TypeError:
    return TypeError(em.Schema.text(class_name, detail))


def _bad(class_name: str, key: object, detail: str) -> TypeError:
    return _invalid_schema(class_name, em.Schema.Body.decl(key, detail))


def _is_dot_dir(node: Node, *, alias: bool) -> bool:
    return isinstance(node, Dir) and node.name == "." and bool(node.alias) is alias


def _extended(scope: FieldSpecs, node: Node) -> FieldSpecs:
    # Copy when this node adds fields, so a sibling does not see them
    specs = node.selector.field_specs()
    if not specs:
        return scope
    return {**scope, **specs}


def _check_assign_ref_exn(cls: type[Schema], key: object, name: str, spec: str | None, scope: FieldSpecs) -> None:
    # Same rule for a node's own ref and for a child schema's unbound refs
    if name not in scope:
        if cls.capture_refs:
            cls._unbound_refs[name] = spec
            return
        raise _bad(cls.__name__, key, em.Schema.Body.unbound(name))
    # "" is a field_spec. None means no override
    if spec is not None and spec_type_exn(spec) is not spec_type_exn(scope[name]):
        raise _bad(cls.__name__, key, em.Schema.Body.spec(name))


def _check_refs_exn(cls: type[Schema], key: object, node: Node, scope: FieldSpecs) -> None:
    # Name is ancestor-only. Fmt also sees this node's fields
    for text, seen in ((node.name, scope), (node.fmt, {**scope, **node.selector.field_specs()})):
        # Safe already applied /< . The result may contain a literal <
        if not text or isinstance(text, Safe):
            continue
        for match in REF.finditer(text):
            _check_assign_ref_exn(cls, key, match.group(1), match.group(2), seen)


def _name_format_field(name: str) -> bool:
    # {{ is a literal brace. A real field, or a broken one, belongs on fmt
    if "{" not in name:
        return False
    try:
        return any(field is not None for _, field, _, _ in _NAME_FMT.parse(name))
    except ValueError:
        return True


def _check_node_exn(cls: type[Schema], key: object, node: Node, scope: FieldSpecs) -> None:
    if _is_dot_dir(node, alias=False):
        raise _bad(cls.__name__, key, em.Node.DOT_ALIAS)
    if node.alias and (not node.alias.isidentifier() or keyword.iskeyword(node.alias) or node.alias.startswith("_")):
        raise _bad(cls.__name__, key, em.Schema.Body.ALIAS)
    if isinstance(node, Dir) and node.schema is not None and not is_schema_type(node.schema):
        raise _bad(cls.__name__, key, em.Schema.Body.DIR_SCHEMA)
    _check_refs_exn(cls, key, node, scope)
    if cls.warn and node.name and _name_format_field(node.name):
        warnings.warn(em.Node.NAME_FIELD, UserWarning, stacklevel=2)


def aliased_file(alias: str, source: File[_L]) -> File[_L]:
    return source if source.alias == alias else evolve(source, alias=alias)


def _merge_identity(defn: Defn) -> str | None:
    node = defn_node(defn)
    return node.alias or node.name or node.fmt or None


def _merge_defns_exn(base: Sequence[Defn], local: Sequence[Defn]) -> tuple[Defn, ...]:
    merged = list(base)
    positions = {identity: index for index, defn in enumerate(base) if (identity := _merge_identity(defn)) is not None}
    for defn in local:
        identity = _merge_identity(defn)
        if identity is None or identity not in positions:
            if identity is not None:
                positions[identity] = len(merged)
            merged.append(defn)
        else:
            merged[positions[identity]] = _merge_one_exn(merged[positions[identity]], defn)
    return tuple(merged)


def _merge_one_exn(base: Defn, local: Defn) -> Defn:
    if isinstance(base, DirDefn) and isinstance(local, DirDefn) and len(base.layouts) == len(local.layouts):
        layouts = tuple(
            DirLayout(
                _merge_defns_exn(base_body.defns, local_body.defns),
                local_body.child_type or base_body.child_type,
                local_body.name,
            )
            for base_body, local_body in zip(base.layouts, local.layouts, strict=True)
        )
        return DirDefn(local.defn, layouts=layouts)
    return local


def _children_satisfy(actual: Sequence[Defn], required: Sequence[Defn]) -> bool:
    matched_anonymous: set[int] = set()
    for required_child in required:
        identity = _merge_identity(required_child)
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
        actual_child = next((candidate for candidate in actual if _merge_identity(candidate) == identity), None)
        if actual_child is None or not _defn_satisfies(actual_child, required_child):
            return False
    return True


def _defn_satisfies(actual: Defn, required: Defn) -> bool:
    if isinstance(required, File):
        return isinstance(actual, File) and actual == required
    if not isinstance(actual, DirDefn) or actual.defn != required.defn or len(actual.layouts) != len(required.layouts):
        return False
    return all(
        _children_satisfy(got.defns, need.defns) for got, need in zip(actual.layouts, required.layouts, strict=True)
    )


def _compile_inline_schema_exn(
    cls: type[Schema], position: int, layout: dict[object, object], scope: FieldSpecs, *, part: int | None = None,
) -> type[Schema]:  # fmt: skip
    label = f"{position}" if part is None else f"{position}_{part}"
    generated = type(f"_{cls.__name__}Child{label}", (Schema,), {
        "__module__": cls.__module__,
        "schema": layout,
        INLINE: True,
        CAPTURE_SCOPE: dict(scope),
        "capture_refs": cls.capture_refs,  # unbound ref on this dict is recorded, same as on the caller
    })  # fmt: skip
    if not is_schema_type(generated):
        raise AssertionError("generated Schema child has an invalid type")
    return generated


def _layout_from_schema_exn(
    class_name: str, key: object, node: Dir[Schema], child_type: type[Schema], *, name: str | None = None,
) -> DirLayout:  # fmt: skip
    child_root = schema_defn_for(child_type)
    layout = DirLayout(child_root.defns, child_type, name)
    if node.schema is not None:
        contract = schema_defn_for(node.schema)
        if not _children_satisfy(layout.defns, contract.defns):
            raise _invalid_schema(class_name, f"declaration {key!r} RHS does not satisfy Dir.schema")
    return layout


def _dir_defn_exn(
    cls: type[Schema], key: object, node: Dir[Schema], entries: Sequence[tuple[str | None, object]], scope: FieldSpecs,
    *, origin: int,
) -> DirDefn:  # fmt: skip
    # A sequence is entries of (None, item). xor.entries already carries the branch name
    layouts: list[DirLayout] = []
    child_scope = _extended(scope, node)
    for index, (name, item) in enumerate(entries):
        if _is_raw_mapping(item):
            item = _compile_inline_schema_exn(cls, origin, item, child_scope, part=index)
        if not is_schema_type(item):
            raise _invalid_schema(cls.__name__, em.Schema.Body.schema_or_dict(key, item))
        # __getattr__ never runs for a name the collection already has
        if name is not None and name in _COLLECTION_ATTRS:
            raise _invalid_schema(cls.__name__, em.Xor.hidden(name))
        layouts.append(_layout_from_schema_exn(cls.__name__, key, node, item, name=name))
        for ref_name, ref_spec in item._unbound_refs.items():
            _check_assign_ref_exn(cls, key, ref_name, ref_spec, child_scope)
    if cls.warn:
        for clash in sorted(unnamed_clashes(layouts)):
            warnings.warn(em.Xor.clash(clash), UserWarning, stacklevel=2)
    return DirDefn(node, layouts=tuple(layouts))


def _is_layout_seq(value: object) -> TypeIs[Sequence[object]]:
    return isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray, memoryview))


def _is_raw_mapping(value: object) -> TypeIs[dict[object, object]]:
    return isinstance(value, dict)


def _is_raw_list(value: object) -> TypeIs[list[object]]:
    return isinstance(value, list)


def _raw_schema(cls: type[Schema]) -> object:
    return cls.schema if "schema" in cls.__dict__ else {}


def _compile_local_defns_exn(cls: type[Schema], scope: FieldSpecs) -> tuple[Defn, ...]:
    # All usages of File/Dir are here, and they also raise (Node ctor)
    raw = _raw_schema(cls)
    if not _is_raw_mapping(raw):
        raise _invalid_schema(cls.__name__, em.Schema.Body.MUST_DICT)
    entries = raw
    defns: list[Defn] = []

    def add_file_exn(node: File, key: object):
        _check_node_exn(cls, key, node, scope)
        defns.append(node)

    for key, value in entries.items():
        match key, value:
            # Normal RHS dicts/dirs
            case str() as name, layout if _is_raw_mapping(layout):
                node: Dir[Schema] = Dir(name=name)
                _check_node_exn(cls, key, node, scope)
                child_type = _compile_inline_schema_exn(cls, len(defns), layout, _extended(scope, node))
                defns.append(_dir_defn_exn(cls, key, node, ((None, child_type),), _extended(scope, node), origin=len(defns)))  # fmt: skip

            case Dir() as node, layout if _is_raw_mapping(layout):
                _check_node_exn(cls, key, node, scope)
                child_type = _compile_inline_schema_exn(cls, len(defns), layout, _extended(scope, node))
                defns.append(_dir_defn_exn(cls, key, node, ((None, child_type),), _extended(scope, node), origin=len(defns)))  # fmt: skip

            # RHS Xor (Seq)
            case Dir() as node, Xor() as rhs:
                _check_node_exn(cls, key, node, scope)
                defns.append(_dir_defn_exn(cls, key, node, rhs.entries, _extended(scope, node), origin=len(defns)))

            case str() as name, Xor() as rhs:
                node = Dir(name=name)
                _check_node_exn(cls, key, node, scope)
                defns.append(_dir_defn_exn(cls, key, node, rhs.entries, _extended(scope, node), origin=len(defns)))

            case Dir() as node, rhs if _is_layout_seq(rhs):
                _check_node_exn(cls, key, node, scope)
                defns.append(_dir_defn_exn(cls, key, node, tuple((None, item) for item in rhs), _extended(scope, node), origin=len(defns)))  # fmt: skip

            case str() as name, rhs if _is_layout_seq(rhs):
                node = Dir(name=name)
                _check_node_exn(cls, key, node, scope)
                defns.append(_dir_defn_exn(cls, key, node, tuple((None, item) for item in rhs), _extended(scope, node), origin=len(defns)))  # fmt: skip

            # Normal RHS Schema
            case str() as name, rhs if is_schema_type(rhs):
                node = Dir(name=name)
                _check_node_exn(cls, key, node, scope)
                defns.append(_dir_defn_exn(cls, key, node, ((None, rhs),), _extended(scope, node), origin=len(defns)))

            case Dir() as node, rhs if is_schema_type(rhs):
                _check_node_exn(cls, key, node, scope)
                defns.append(_dir_defn_exn(cls, key, node, ((None, rhs),), _extended(scope, node), origin=len(defns)))

            # Normal files
            case str() as alias, str() as name:
                add_file_exn(File(name=name, alias=alias), key)

            case str() as alias, File() as source:
                file = source if source.alias == alias else evolve(source, alias=alias)
                add_file_exn(file, key)

            # FilesKey Files
            case FilesKey() as token, _ if token is FILES and _is_raw_list(value):
                for item in value:
                    match item:
                        case str():
                            add_file_exn(File(name=item), key)
                        case File():
                            add_file_exn(item, key)
                        case _:
                            raise _invalid_schema(cls.__name__, f"key {key!r} member {item!r} must be a str or File")

            case FilesKey() as token, _ if token is FILES:
                raise _invalid_schema(cls.__name__, em.Schema.Body.files(key))

            # The rest is undefined
            case _:
                raise _invalid_schema(cls.__name__, em.Schema.Body.invalid(key))
    return tuple(defns)


# Public annotations on Schema. A subclass may set these. Methods stay protected
_SCHEMA_ATTRS: Final = frozenset(name for name in Schema.__annotations__ if not name.startswith("_"))
_CAPTURE_MEMBERS: Final = frozenset(("args", "kwargs"))
_UNSAFE_SCHEMA_DUNDERS: Final = frozenset(
    "RootT __delattr__ __fspath__ __getattr__ __getattribute__ __getitem__ __init__ __init_subclass__ "
    "__iter__ __len__ __new__ __setattr__ __slots__".split()  # pyright: ignore[reportImplicitStringConcatenation]
)


def schema_ctor_check_bases(class_name: str, bases: tuple[type[object], ...]) -> Exception | None:
    if len(bases) != 1 or not is_schema_type(bases[0]):
        return TypeError(em.Schema.one_base(class_name))
    return None


def schema_ctor_check_class(cls: type[Schema]) -> Exception | None:
    if type(cls) is not SchemaCls:
        return TypeError(em.Schema.metaclass(cls.__name__))

    inherited_members = {
        name for ancestor in cls.__mro__[1:] for name in ancestor.__dict__ if not name.startswith("__")
    } - _SCHEMA_ATTRS
    if unsafe := cls.__dict__.keys() & (inherited_members | _CAPTURE_MEMBERS | _UNSAFE_SCHEMA_DUNDERS):
        return TypeError(em.Schema.override(cls.__name__, sorted(unsafe)[0]))
    return None


# This is the main fn schema calls to compile everything, on subclass init
def schema_ctor_compile_defn(cls: type[Schema]) -> Exception | None:
    base = cls.__bases__[0]
    if not is_schema_type(base):
        raise AssertionError("validated Schema class lost its Schema base")
    try:  # DirDefn can raise ValueError
        cls._unbound_refs = {}
        raw_scope = vars(cls).get(CAPTURE_SCOPE)
        scope: FieldSpecs = typing.cast(dict[str, str], raw_scope) if isinstance(raw_scope, dict) else {}
        local_defns = _compile_local_defns_exn(cls, scope)  # Uses File/Dir (Node), which fails fast
        _ = DirLayout(local_defns)
        defns = _merge_defns_exn(schema_defn_for(base).defns, local_defns)
        # Inherited defs are not compiled again. Unbound refs on the base use the same rule
        for ref_name, ref_spec in base._unbound_refs.items():
            _check_assign_ref_exn(cls, cls.__name__, ref_name, ref_spec, scope)
        type.__setattr__(cls, "_schema_defn", DirLayout(defns))
    except TypeError as error:
        return error
    except ValueError as error:
        raised = _invalid_schema(cls.__name__, str(error))
        raised.__cause__ = error
        return raised
    return None


def _schema_ctor_installed_names(ancestor: type) -> frozenset[str]:
    raw = vars(ancestor).get("_child_attrs")
    if isinstance(raw, frozenset):
        return typing.cast(frozenset[str], raw)
    return frozenset()


def schema_ctor_check_defn_shadows(cls: type[Schema]) -> Exception | None:
    for defn in schema_defn_for(cls).defns:
        node = defn_node(defn)
        normalized = normalize_name(node.name) if node.name else None
        if node.name and not normalized:
            return ValueError(em.Fmt.basename(node.name))
        for name in (n for n in (node.alias, normalized) if n):
            # An installed child on a parent is that child, not a reserved member.
            reserved = name in _CAPTURE_MEMBERS or any(
                name in ancestor.__dict__ and name not in _schema_ctor_installed_names(ancestor)
                for ancestor in (*cls.__mro__, *type(cls).__mro__)
            )
            if reserved:
                return _invalid_schema(cls.__name__, em.Schema.Body.shadow(name))
    return None


def _declaration_with(node: Node) -> object:
    def with_(_cls: type[object], /, **changes: object) -> Node:
        return node.with_(**changes)

    return classmethod(with_)


def member_view(cls: type[Schema], base: type[object], node: Node) -> type[object]:
    # A view is a generated class, not the user's schema class.
    # It carries alias, fmt, match, min, max, and with_ for one file or one repeated name.
    # The schema class stores it as a real attribute, so lookup does not build another one.
    return type(
        base.__name__,
        (base,),
        {
            "__module__": cls.__module__,
            "alias": node.alias,
            "fmt": node.fmt,
            "match": node.match,
            "min": node.min,
            "max": node.max,
            "with_": _declaration_with(node),
        },
    )
