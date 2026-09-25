# pyright: reportImportCycles=false
import keyword
import typing
from collections.abc import Sequence
from dataclasses import replace
from typing import Final

from typing_extensions import TypeIs, TypeVar

from ._schema import (
    FILES,
    Defn,
    Dir,
    DirDefn,
    File,
    FilesKey,
    Node,
    Schema,
    SchemaCls,
    defn_node,
    is_safe_basename,
    normalize_name,
)

_L = TypeVar("_L")


def is_schema_type(value: object) -> TypeIs[type[Schema]]:
    return isinstance(value, SchemaCls) and issubclass(value, Schema)


def schema_defn_for(schema_type: type[Schema]) -> DirDefn:
    value = vars(schema_type).get("_schema_defn")
    if not isinstance(value, DirDefn):
        raise AssertionError(f"{schema_type.__name__} has no compiled schema definition")
    return value


def _invalid_schema(class_name: str, detail: str) -> TypeError:
    return TypeError(f"{class_name}.schema {detail}")


def _is_dot_dir(node: Node, *, alias: bool) -> bool:
    return isinstance(node, Dir) and node.name == "." and bool(node.alias) is alias


def _validate_schema_node(class_name: str, key: object, node: Node) -> None:
    if _is_dot_dir(node, alias=False):
        raise _invalid_schema(class_name, f"declaration {key!r} Dir('.') requires alias")
    if node.name and not is_safe_basename(node.name) and not _is_dot_dir(node, alias=True):
        raise _invalid_schema(class_name, f"declaration {key!r} name must be a basename")
    if node.alias and (not node.alias.isidentifier() or keyword.iskeyword(node.alias) or node.alias.startswith("_")):
        raise _invalid_schema(class_name, f"declaration {key!r} alias must be a public identifier")
    if isinstance(node, Dir) and node.schema is not None and not is_schema_type(node.schema):
        raise _invalid_schema(class_name, f"declaration {key!r} Dir.schema must be a Schema subclass")


def aliased_file(alias: str, source: File[_L]) -> File[_L]:
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
            merged[positions[identity]] = _merge_one(merged[positions[identity]], defn)
    return tuple(merged)


def _merge_one(base: Defn, local: Defn) -> Defn:
    if isinstance(base, DirDefn) and isinstance(local, DirDefn):
        return DirDefn(local.defn, _merge_defns(base.defns, local.defns), local.child_type or base.child_type)
    return local


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


def _make_inline_schema(class_name: str, module: str, position: int, layout: dict[object, object]) -> type[Schema]:
    generated = type(
        f"_{class_name}Child{position}",
        (Schema,),
        {"__module__": module, "schema": layout},
    )
    if not is_schema_type(generated):
        raise AssertionError("generated Schema child has an invalid type")
    return generated


def _directory_defn(class_name: str, key: object, node: Dir[Schema], child_type: type[Schema]) -> DirDefn:
    child_root = schema_defn_for(child_type)
    compiled = DirDefn(node, child_root.defns, child_type)
    if node.schema is not None:
        contract = schema_defn_for(node.schema)
        if not _children_satisfy(compiled.defns, contract.defns):
            raise _invalid_schema(class_name, f"declaration {key!r} RHS does not satisfy Dir.schema")
    return compiled


def _is_schema_dir(value: object) -> TypeIs[Dir[Schema]]:
    return isinstance(value, Dir)


def _is_raw_mapping(value: object) -> TypeIs[dict[object, object]]:
    return isinstance(value, dict)


def _is_raw_list(value: object) -> TypeIs[list[object]]:
    return isinstance(value, list)


def _raw_schema(cls: type[Schema]) -> object:
    return cls.schema if "schema" in cls.__dict__ else {}


def _compile_local_defns(cls: type[Schema]) -> tuple[Defn, ...]:
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
            case str() as name, rhs if is_schema_type(rhs):
                node = Dir(name=name)
                _validate_schema_node(cls.__name__, key, node)
                defns.append(_directory_defn(cls.__name__, key, node, rhs))
            case lhs, rhs if _is_schema_dir(lhs) and is_schema_type(rhs):
                node = lhs
                _validate_schema_node(cls.__name__, key, node)
                defns.append(_directory_defn(cls.__name__, key, node, rhs))
            case str() as alias, str() as name:
                file = File(name=name, alias=alias)
                _validate_schema_node(cls.__name__, key, file)
                defns.append(file)
            case str() as alias, File() as source:
                file = aliased_file(alias, source)
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


def validate_schema_bases(class_name: str, bases: tuple[type[object], ...]) -> None:
    if len(bases) != 1 or not is_schema_type(bases[0]):
        raise TypeError(f"{class_name} must have exactly one direct Schema base and no mixins")


def validate_schema_class(cls: type[Schema]) -> None:
    if type(cls) is not SchemaCls:
        raise TypeError(f"{cls.__name__} must use the exact Schema metaclass")
    if len(cls.__bases__) != 1 or not is_schema_type(cls.__bases__[0]):
        raise TypeError(f"{cls.__name__} must have exactly one direct Schema base and no mixins")

    inherited_members = {
        name for ancestor in cls.__mro__[1:] for name in ancestor.__dict__ if not name.startswith("__")
    } - {"schema"}
    if unsafe := cls.__dict__.keys() & (inherited_members | _CAPTURE_MEMBERS | _UNSAFE_SCHEMA_DUNDERS):
        raise TypeError(f"{cls.__name__} Schema declaration cannot override {sorted(unsafe)[0]!r}")


def compile_schema(cls: type[Schema]) -> None:
    base = cls.__bases__[0]
    if not is_schema_type(base):
        raise AssertionError("validated Schema class lost its Schema base")
    local_defns = _compile_local_defns(cls)
    try:
        _ = DirDefn(Dir(name="."), local_defns)
        defns = _merge_defns(schema_defn_for(base).defns, local_defns)
        type.__setattr__(cls, "_schema_defn", DirDefn(Dir(name="."), defns))
    except ValueError as error:
        raise _invalid_schema(cls.__name__, str(error)) from error


def validate_child_shadows(cls: type[Schema]) -> None:
    for defn in schema_defn_for(cls).defns:
        node = defn_node(defn)
        for name in (node.alias or None, normalize_name(node.name) if node.name else None):
            if name is not None and (
                name in _CAPTURE_MEMBERS
                or any(name in ancestor.__dict__ for ancestor in (*cls.__mro__, *type(cls).__mro__))
            ):
                raise _invalid_schema(cls.__name__, f"child {name!r} shadows a Schema member")


def member_view(cls: type[Schema], name: str, base: type[object], node: Node) -> type[object]:
    raw = vars(cls).get("_member_views")
    if not isinstance(raw, dict):
        raw = {}
        type.__setattr__(cls, "_member_views", raw)
    cache = typing.cast(dict[str, type[object]], raw)
    cached = cache.get(name)
    if isinstance(cached, type):
        return cached
    viewed = type(
        base.__name__,
        (base,),
        {
            "__module__": cls.__module__,
            "alias": node.alias,
            "fmt": node.fmt,
            "match": node.match,
            "min": node.min,
            "max": node.max,
        },
    )
    cache[name] = viewed
    return viewed
