# pyright: reportImportCycles=false
import os
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import TypeAlias, final

from plum import dispatch
from typing_extensions import TypeIs

from ._fmt import FmtField
from ._schema import (
    Defn,
    DirDefn,
    File,
    FixedDir,
    FixedFile,
    Match,
    Matches,
    Template,
    capture_names,
    defn_node,
    format_any,
    is_safe_basename,
    plan_fixed,
    validate_capture_names,
    write_plan,
)
from ._types import CreateTop, PathIsh, Puttable

_Member: TypeAlias = tuple[Mapping[str, FmtField], CreateTop]


@final
class _Absent:
    """No spec entry named this child."""


_ABSENT: _Absent = _Absent()


def apply_create(directory: FixedDir, spec: Mapping[str, CreateTop]) -> None:
    directory.path.mkdir(parents=True, exist_ok=True)
    for key in spec:
        if key not in directory.defn.lookup:
            raise KeyError(f"unknown create key: {key!r}")
    for index, defn in enumerate(directory.defn.defns):
        key = _child_key(defn)
        value = _spec_entry(directory.defn.lookup, spec, index)
        if isinstance(value, _Absent):
            if _is_required_exact_dir(defn):
                child = directory[key]
                if not isinstance(child, FixedDir):
                    raise AssertionError("required directory")
                _ = child.create()
            continue
        if value is None:
            continue
        _write_child(directory, defn, key, value)


def _child_key(defn: Defn) -> str:
    node = defn_node(defn)
    key = node.alias or node.name
    if not key:
        raise AssertionError("declaration has no alias or name")
    return key


def _spec_entry(lookup: Mapping[str, int], spec: Mapping[str, CreateTop], index: int) -> CreateTop | _Absent:
    keys = [key for key, idx in lookup.items() if idx == index and key in spec]
    if not keys:
        return _ABSENT
    first = spec[keys[0]]
    if any(spec[key] != first for key in keys[1:]):
        raise TypeError(f"create keys {keys} name one child")
    return first


def _is_required_exact_dir(defn: Defn) -> bool:
    node = defn_node(defn)
    return not isinstance(defn, File) and bool(node.name) and node.min >= 1


def _is_basename_map(value: object) -> TypeIs[Mapping[str, CreateTop]]:
    return isinstance(value, Mapping)


def _is_member_seq(value: object) -> TypeIs[Sequence[_Member]]:
    return isinstance(value, Sequence) and not isinstance(value, (str, bytes, Path))


def _write_child(directory: FixedDir, defn: Defn, key: str, value: CreateTop) -> None:
    child = directory[key]
    if not defn_node(defn).name:
        if not isinstance(child, Matches):
            raise AssertionError("collection child")
        _dispatch_collection(child, defn, key, value)
        return
    _write_exact(defn, child, value)  # pyright: ignore[reportArgumentType]


@dispatch
def _write_exact(defn: File, child: FixedFile, value: Puttable | PathIsh | None) -> None:  # pyright: ignore[reportRedeclaration]
    _ = child.create(value)


@dispatch
def _write_exact(defn: DirDefn, child: FixedDir, value: Mapping[str, CreateTop] | None) -> None:
    write_plan(child, value)


def _dispatch_collection(template: Matches[Match, Defn], defn: Defn, key: str, value: CreateTop) -> None:
    if _is_basename_map(value):
        _fill_named(template, defn, key, value)
        return
    if isinstance(defn, File) and isinstance(value, Puttable):
        _fill_stamped_file(template, defn, key, value)
        return
    if isinstance(defn, File) and isinstance(value, os.PathLike):
        _fill_stamped_file(template, defn, key, Path(value))
        return
    if _is_member_seq(value):
        if _is_member(value):
            raise TypeError(f"{key!r} value is one (captures, payload) pair; pass a list of pairs")
        if defn_node(defn).fmt is None:
            raise TypeError(f"{key!r} has no formatter; pass a basename mapping")
        if not isinstance(template, Template):
            raise AssertionError("formatted collection")
        _fill_collection(template, defn, key, value)
        return
    raise TypeError(f"{key!r} is a collection; pass a basename mapping or (captures, payload) pairs")


def _fill_stamped_file(template: Matches[Match, Defn], defn: File[object], key: str, body: Puttable) -> None:
    node = defn_node(defn)
    names = capture_names(defn)
    if node.fmt is None or not isinstance(template, Template):
        raise TypeError(f"{key!r} is a collection; pass a basename mapping or (captures, payload) pairs")
    missing = names - template.stamps.keys()
    if missing:
        stamped = sorted(names & template.stamps.keys())
        detail = f"missing captures {sorted(missing)}"
        if stamped:
            detail += f"; already stamped {stamped}"
        raise TypeError(f"{key!r} is a file collection; {detail}; pass (captures, payload) pairs")
    created = format_any(template, **{name: template.stamps[name] for name in names})
    if not isinstance(created, FixedFile):
        raise AssertionError("file collection planned a directory")
    _ = created.create(body)


def _fill_collection(
    template: Template[Match, Defn],
    defn: Defn,
    key: str,
    pairs: Sequence[_Member],
) -> None:
    for item in pairs:
        if not _is_member(item):
            raise TypeError(f"{key!r} member must be a (captures, payload) pair")
        fields, payload = item
        validate_capture_names(defn, fields)
        _write_formatted(defn, format_any(template, **fields), payload)  # pyright: ignore[reportArgumentType]


def _is_member(item: object) -> TypeIs[_Member]:
    match item:
        case (Mapping(), object()):
            return True
        case _:
            return False


def _fill_named(
    template: Matches[Match, Defn],
    defn: Defn,
    key: str,
    value: Mapping[str, CreateTop],
) -> None:
    names = capture_names(defn)
    node = defn_node(defn)
    for name, body in value.items():
        if node.select(name) is None or not is_safe_basename(name):
            hint = "; keys are filenames, not captures" if name in names else ""
            raise ValueError(f"{key!r} member {name!r} does not match{hint}")
        _write_formatted(defn, plan_fixed(template.path / name, defn), body)  # pyright: ignore[reportArgumentType]


@dispatch
def _write_formatted(defn: File, created: FixedFile, payload: Puttable | PathIsh | None) -> None:  # pyright: ignore[reportRedeclaration]
    _ = created.create(payload)


@dispatch
def _write_formatted(defn: DirDefn, created: FixedDir, payload: Mapping[str, CreateTop] | None) -> None:
    write_plan(created, payload)
