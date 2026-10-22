# pyright: reportImportCycles=false
from pathlib import Path

from plum import dispatch
from typing_extensions import TypeVar, overload

import fs_schema._errmsg as em

from ._decl import Defn, DirDefn, File, Match, Node, defn_node
from ._fmt import child_path_exn, safe_exn
from ._schema import Child, FixedDir, FixedFile, Matches, Template
from ._types import FmtFields, FmtFieldT, Name, Raw, SafePath

_L = TypeVar("_L")


## Plan and format


def plan_dir_defn_children(path: SafePath, dir_defn: DirDefn) -> tuple[Child, ...]:
    return tuple(_plan_dir_defn(path, defn) for defn in dir_defn.defns)


def _plan_dir_defn(path: SafePath, defn: Defn) -> Child:
    node = defn_node(defn)
    if node.name:
        return plan_fixed(child_path_exn(path, node.name), defn)
    return Template(path, (), defn) if node.fmt else Matches(path, (), defn)


@overload
def plan_fixed(path: SafePath, defn: File[_L]) -> FixedFile[_L]: ...


@overload
def plan_fixed(path: SafePath, defn: DirDefn) -> FixedDir: ...


def plan_fixed(path: SafePath, defn: Defn) -> FixedFile[object] | FixedDir:
    return _plan_fixed(path, defn)  # pyright: ignore[reportArgumentType]


@dispatch
def _plan_fixed(path: Path, defn: File) -> FixedFile:  # pyright: ignore[reportRedeclaration]
    path = SafePath(path)  # plum boundary
    return FixedFile(path, defn)


@dispatch
def _plan_fixed(path: Path, defn: DirDefn) -> FixedDir:
    path = SafePath(path)  # plum boundary
    return FixedDir(path, plan_dir_defn_children(path, defn), defn)


def format_any_exn(
    template: Template[Match, Defn],
    *args: FmtFieldT,
    **kwargs: FmtFieldT,
) -> FixedFile[object] | FixedDir:
    for name, value in kwargs.items():
        if name in template.fmt_fields and template.fmt_fields[name] != value:
            raise ValueError(em.Fmt.capture(name))
    node = defn_node(template.defn)
    basename = safe_exn(_format_any_node_exn(node, *args, **kwargs))
    created = plan_fixed(child_path_exn(template.path, basename), template.defn)
    if isinstance(created, FixedDir):
        _format_any_fmt_fields(created, {**template.fmt_fields, **kwargs})
    return created


def _format_any_node_exn(node: Node, *args: FmtFieldT, **kwargs: FmtFieldT) -> Raw[Name]:
    return node.selector.format(*args, **kwargs)


def _format_any_fmt_fields(directory: FixedDir, fmt_fields: FmtFields) -> None:
    directory.fmt_fields = dict(fmt_fields)
    for child in directory._children:  # pyright: ignore[reportPrivateUsage]
        if isinstance(child, FixedDir):
            _format_any_fmt_fields(child, fmt_fields)
        elif isinstance(child, Matches):
            child.fmt_fields = dict(fmt_fields)
