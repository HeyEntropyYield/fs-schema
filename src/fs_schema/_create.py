# pyright: reportImportCycles=false
import os
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import TypeAlias, cast, final

from plum import dispatch
from typing_extensions import TypeIs

import fs_schema._errmsg as em

from ._decl import Defn, DirDefn, File, Match, capture_names, defn_node, validate_capture_names_exn
from ._fmt import Captures, captures, child_path_exn, safe
from ._plan import format_any_exn, plan_fixed_exn
from ._schema import FixedDir, FixedFile, Matches, SchemaCls, Template
from ._types import CreateTop, FmtFields, Name, Puttable, Raw

_Member: TypeAlias = tuple[FmtFields | Captures, CreateTop]


@final
class _Absent:
    """No spec entry named this child."""


_ABSENT: _Absent = _Absent()


def write_plan_exn(directory: FixedDir, spec: Mapping[str, CreateTop] | None = None, /, **children: CreateTop) -> None:
    _write_plan_bound_exn(directory)
    merged: dict[str, CreateTop] = dict(spec or {})
    if overlap := merged.keys() & children.keys():
        raise TypeError(em.Create.duplicate(sorted(overlap)))
    merged.update(children)
    apply_create_exn(directory, merged)


def _write_plan_bound_exn(node: object) -> None:
    if isinstance(type(node), SchemaCls):
        raise TypeError(em.Create.bound(type(node).__name__))


def apply_create_exn(directory: FixedDir, spec: Mapping[str, CreateTop]) -> None:
    directory.path.mkdir(parents=True, exist_ok=True)  # OSError
    body = directory.defn.layout
    for key in spec:
        if key not in body.lookup:
            raise KeyError(f"unknown create key: {key!r}")
    for index, defn in enumerate(body.defns):
        key = _create_child_key_exn(defn)
        value = _create_spec_entry_exn(body.lookup, spec, index)
        if isinstance(value, _Absent):
            if _is_required_exact_dir(defn):
                child = directory[key]
                if not isinstance(child, FixedDir):
                    raise AssertionError("required directory")
                _ = child.create()
            continue
        if value is None:
            continue
        _write_child_exn(directory, defn, key, value)


def _create_child_key_exn(defn: Defn) -> str:
    node = defn_node(defn)
    key = node.alias or node.name
    if not key:
        raise AssertionError("declaration has no alias or name")
    return key


def _create_spec_entry_exn(lookup: Mapping[str, int], spec: Mapping[str, CreateTop], index: int) -> CreateTop | _Absent:
    keys = [key for key, idx in lookup.items() if idx == index and key in spec]
    if not keys:
        return _ABSENT
    first = spec[keys[0]]
    if any(spec[key] != first for key in keys[1:]):
        raise TypeError(em.Create.one_child(keys))
    return first


def _is_required_exact_dir(defn: Defn) -> bool:
    node = defn_node(defn)
    return not isinstance(defn, File) and bool(node.name) and node.min >= 1


def _is_basename_map(value: object) -> TypeIs[Mapping[str, CreateTop]]:
    return isinstance(value, Mapping)


def _is_member_seq(value: object) -> TypeIs[Sequence[_Member]]:
    return isinstance(value, Sequence) and not isinstance(value, (str, bytes, Path))


# CreateTop with os.PathLike[str] replaced by Path. plum can resolve this
_CreatePath: TypeAlias = Puttable | Path | Mapping[str, object] | Sequence[object] | None


def _create_path(value: object) -> object:
    # str and bytes stay file bodies. int stays int so plum can reject a bad spec
    if isinstance(value, os.PathLike) and not isinstance(value, (str, bytes)):
        return Path(os.fsdecode(value))
    if isinstance(value, Mapping):
        spec = cast(Mapping[object, object], value)
        return {key: _create_path(item) for key, item in spec.items()}
    return value


def _write_child_exn(directory: FixedDir, defn: Defn, key: str, value: CreateTop) -> None:
    child = directory[key]
    if not defn_node(defn).name:
        if not isinstance(child, Matches):
            raise AssertionError("collection child")
        _write_child_matches_exn(child, defn, key, value)
        return
    _write_child_exact_exn(defn, child, _create_path(value))  # pyright: ignore[reportArgumentType]


@dispatch
def _write_child_exact_exn(defn: File, child: FixedFile, value: Puttable | Path | None) -> None:  # pyright: ignore[reportRedeclaration]
    _ = child.create(value)


@dispatch
def _write_child_exact_exn(defn: DirDefn, child: FixedDir, value: Mapping[str, _CreatePath] | None) -> None:
    write_plan_exn(child, value)


def _write_child_matches_exn(template: Matches[Match, Defn], defn: Defn, key: str, value: CreateTop) -> None:
    if _is_basename_map(value):
        _write_matches_named_exn(template, defn, key, value)
        return
    if isinstance(defn, File) and isinstance(value, Puttable):
        _write_matches_fmt_file_exn(template, defn, key, value)
        return
    if isinstance(defn, File) and isinstance(value, os.PathLike):
        _write_matches_fmt_file_exn(template, defn, key, Path(value))
        return
    if _is_member_seq(value):
        if _is_member(value):
            raise TypeError(em.Create.pair(key))
        if not defn_node(defn).fmt:
            raise TypeError(em.Create.names(key))
        if not isinstance(template, Template):
            raise AssertionError("formatted collection")
        _write_matches_collection_exn(template, defn, key, value)
        return
    raise TypeError(em.Create.collection(key))


def _write_matches_fmt_file_exn(template: Matches[Match, Defn], defn: File[object], key: str, body: Puttable) -> None:
    node = defn_node(defn)
    names = capture_names(defn)
    if not node.fmt or not isinstance(template, Template):
        raise TypeError(em.Create.collection(key))
    missing = names - template.fmt_fields.keys()
    if missing:
        raise TypeError(em.Create.file(key, sorted(missing), sorted(names & template.fmt_fields.keys())))
    created = format_any_exn(template, **{name: template.fmt_fields[name] for name in names})
    if not isinstance(created, FixedFile):
        raise AssertionError("file collection planned a directory")
    _ = created.create(body)


def _write_matches_collection_exn(
    template: Template[Match, Defn], defn: Defn, key: str, pairs: Sequence[_Member]
) -> None:
    for item in pairs:
        fields, payload = item
        held = fields if isinstance(fields, Captures) else captures(**fields)
        validate_capture_names_exn(defn, held.kwargs)
        _write_formatted_exn(defn, format_any_exn(template, *held.args, **held.kwargs), _create_path(payload))  # pyright: ignore[reportArgumentType]


def _is_member(item: object) -> TypeIs[_Member]:
    match item:
        case (Mapping(), object()) | (Captures(), object()):
            return True
        case _:
            return False


def _write_matches_named_exn(
    template: Matches[Match, Defn], defn: Defn, key: str, value: Mapping[str, CreateTop]
) -> None:
    names = capture_names(defn)
    node = defn_node(defn)
    for name, body in value.items():
        if not (safe_name := safe(Raw[Name](name))) or node.select(safe_name) is None:
            raise ValueError(em.Create.member(key, name, filenames=name in names))
        _write_formatted_exn(defn, plan_fixed_exn(child_path_exn(template.path, safe_name), defn), _create_path(body))  # pyright: ignore[reportArgumentType]


@dispatch
def _write_formatted_exn(defn: File, created: FixedFile, payload: Puttable | Path | None) -> None:  # pyright: ignore[reportRedeclaration]
    _ = created.create(payload)


@dispatch
def _write_formatted_exn(defn: DirDefn, created: FixedDir, payload: Mapping[str, _CreatePath] | None) -> None:
    write_plan_exn(created, payload)
