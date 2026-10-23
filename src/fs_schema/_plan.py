# pyright: reportImportCycles=false
from pathlib import Path

from attrs import evolve
from plum import dispatch
from typing_extensions import TypeVar, overload

import fs_schema._errmsg as em

from ._compile import INLINE
from ._decl import Defn, DirDefn, DirLayout, File, Match, Node, OneDefn, defn_node, is_union
from ._fmt import CaptureMap, CompiledFormat, child_path_exn, close_exn, safe_exn
from ._schema import Child, FixedDir, FixedFile, Matches, Template, XorDir
from ._types import FmtFieldT, Name, Raw, Safe, SafePath

_L = TypeVar("_L")

## Plan and format


def layout_scope(layout: DirLayout, scope: CaptureMap | None) -> CaptureMap | None:
    # A named schema class does not see the caller's captures. An inline dict does
    child_type = layout.child_type
    if child_type is not None and vars(child_type).get(INLINE) is not True:
        return None
    return scope


def plan_layout_children_exn(path: SafePath, layout: DirLayout, scope: CaptureMap | None = None) -> tuple[Child, ...]:
    return tuple(_plan_dir_defn_exn(path, defn, scope) for defn in layout.defns)


def _plan_dir_defn_exn(path: SafePath, defn: Defn, scope: CaptureMap | None) -> Child:
    node = defn_node(defn)
    if node.name:
        return plan_fixed_exn(child_path_exn(path, close_exn(node.name, scope)), defn, scope)
    return Template(path, (), defn, scope=scope) if node.fmt else Matches(path, (), defn, scope=scope)


@overload
def plan_fixed_exn(path: SafePath, defn: File[_L], scope: CaptureMap | None = None) -> FixedFile[_L]: ...


@overload
def plan_fixed_exn(path: SafePath, defn: DirDefn, scope: CaptureMap | None = None) -> FixedDir | XorDir: ...


def plan_fixed_exn(
    path: SafePath, defn: Defn, scope: CaptureMap | None = None
) -> FixedFile[object] | FixedDir | XorDir:
    return _plan_fixed_exn(path, defn, scope)  # pyright: ignore[reportArgumentType]


@dispatch
def _plan_fixed_exn(path: Path, defn: File, scope: CaptureMap | None = None) -> FixedFile:  # pyright: ignore[reportRedeclaration]
    path = SafePath(path)  # plum boundary
    return FixedFile(path, defn, scope=scope)


@dispatch
def _plan_fixed_exn(path: Path, defn: DirDefn, scope: CaptureMap | None = None) -> FixedDir | XorDir:
    path = SafePath(path)  # plum boundary
    if is_union(defn.layouts):
        return XorDir(path, defn, scope)
    layout = defn.layouts[0]
    return FixedDir(
        path,
        plan_layout_children_exn(path, layout, layout_scope(layout, scope)),
        OneDefn(defn.defn, layout),
    )


def format_any_exn(
    template: Template[Match, Defn],
    *args: FmtFieldT,
    **kwargs: FmtFieldT,
) -> FixedFile[object] | FixedDir | XorDir:
    for name, value in kwargs.items():
        if name in template.fmt_fields and template.fmt_fields[name] != value:
            raise ValueError(em.Fmt.capture(name))
    node = defn_node(template.defn)
    basename = safe_exn(_format_any_node_exn(node, template.scope, *args, **kwargs))
    frame = CaptureMap(kwargs, node.selector.field_specs()).chain(template.scope)
    # format() of a file yields the file. The ancestor frame stays on a bound fixed name
    child_scope = None if isinstance(template.defn, File) else frame
    created = plan_fixed_exn(child_path_exn(template.path, basename), template.defn, child_scope)
    fields = {**template.fmt_fields, **kwargs}
    if isinstance(created, XorDir):
        for arm in created._arms:  # pyright: ignore[reportPrivateUsage]
            arm.fmt_fields = dict(fields)
    elif isinstance(created, FixedDir):
        created.fmt_fields = dict(fields)
    return created


def _format_any_node_exn(node: Node, scope: CaptureMap | None, *args: FmtFieldT, **kwargs: FmtFieldT) -> Raw[Name]:
    if node.selector.fmt is None or isinstance(node.selector.fmt.pattern, Safe):
        return node.selector.format(*args, **kwargs)
    closed = evolve(node.selector, fmt=CompiledFormat(close_exn(node.selector.fmt.pattern, scope)))
    return closed.format(*args, **kwargs)
