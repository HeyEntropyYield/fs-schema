# pyright: reportImportCycles=false
import typing
from collections.abc import Callable, Sequence
from datetime import datetime
from pathlib import Path
from typing import TypeAlias, overload

from attrs import evolve
from plum import dispatch
from typing_extensions import TypeIs, TypeVar

import fs_schema._errmsg as em

from ._decl import Defn, DirDefn, DirLayout, File, Match, Node, OneDefn, defn_node
from ._fmt import (
    CaptureMap,
    CompiledFormat,
    ParsedCaptures,
    child_path_exn,
    close_exn,
    safe,
    safe_path_exn,
)
from ._ops import MismatchErr, is_mismatch
from ._plan import layout_scope
from ._schema import (
    BOUND_MATCH,
    BoundChild,
    DirMatch,
    FileMatch,
    FixedDir,
    FixedFile,
    Matches,
    SchemaCls,
    Template,
    stored_type,
)
from ._selector import Selector
from ._std_ext import CacheSeq
from ._types import Name, Raw, Safe, SafePath

_L = TypeVar("_L")
_MatchT = TypeVar("_MatchT")
_MatchRes: TypeAlias = tuple[list[_MatchT], list[MismatchErr]]


def _is_bound_dir_match_type(value: object, schema_type: type) -> TypeIs[type[DirMatch]]:
    return isinstance(value, type) and issubclass(value, schema_type) and issubclass(value, DirMatch)


def _bound_dir_match_type(layout: DirLayout) -> type[DirMatch]:
    schema_type = layout.child_type
    if schema_type is None:
        return DirMatch

    def build() -> type[DirMatch]:
        generated = SchemaCls(
            f"{schema_type.__name__}Match",
            (schema_type, DirMatch),
            {
                "__module__": schema_type.__module__,
                "__qualname__": f"{schema_type.__qualname__}Match",
                BOUND_MATCH: True,
                "__init__": DirMatch.__init__,
            },
        )
        if not _is_bound_dir_match_type(generated, schema_type):
            raise AssertionError("bound match type must subclass schema and DirMatch")
        return generated

    return stored_type(
        schema_type,
        "_bound_match_type",
        lambda value: _is_bound_dir_match_type(value, schema_type),
        build,
    )


# Proved directory keys. Values stay iterdir entries so _listed can reject a name
_FsCache: TypeAlias = dict[Path, CacheSeq[Path]]
_SeqCache: TypeAlias = dict[Path, Sequence[Path]]  # plum boundary
_MatchValue = TypeVar("_MatchValue", bound=Match)


## Bind


def _bind_is_kind(path: Path, node: Node) -> bool:
    return path.is_file() if isinstance(node, File) else path.is_dir()


def _listed(target: Path) -> tuple[SafePath, Safe[Name]] | None:
    # Directory entry. Not an alias or a format field. Unsafe names are skipped
    if not (name := safe(Raw[Name](target.name))):
        return None
    return safe_path_exn(target), name


def _bind_dangling_names(defn: Defn, listing: Sequence[Path]) -> list[Safe[Name]]:
    node = defn_node(defn)
    names: list[Safe[Name]] = []
    for target in listing:
        if _bind_is_kind(target, node) or not target.is_symlink() or target.exists():
            continue
        if (listed := _listed(target)) is None:
            continue
        _, name = listed
        if node.select(name) is not None:
            names.append(name)
    return names


# str(MismatchErr).splitlines() is the failure list, so one message must stay one line.
# Filenames can contain any of these.
_LINE_BREAKS = {ord(ch): repr(ch)[1:-1] for ch in "\n\r\v\f\x1c\x1d\x1e\x85\u2028\u2029"}


def _mismatch(message: str) -> MismatchErr:
    return MismatchErr(message.translate(_LINE_BREAKS))


def _aggregate(failures: Sequence[MismatchErr]) -> MismatchErr:
    if len(failures) == 1:
        return failures[0]
    return MismatchErr("\n".join(str(failure) for failure in failures))


def _bound_selector(node: Node, scope: CaptureMap | None) -> Selector:
    if node.selector.fmt is None or isinstance(node.selector.fmt.pattern, Safe):
        return node.selector
    return evolve(node.selector, fmt=CompiledFormat(close_exn(node.selector.fmt.pattern, scope)))


def bind_children(
    path: Path, layout: DirLayout, cache: _FsCache, *, fast: bool = False, scope: CaptureMap | None = None
) -> tuple[BoundChild, ...] | MismatchErr:
    path = safe_path_exn(path)  # caller error
    if not path.is_dir():
        return _mismatch(f"expected directory: {path}")

    children: list[BoundChild] = []
    failures: list[MismatchErr] = []
    for position, defn in enumerate(layout.defns):
        if is_mismatch(child := _bind_dir_defn(path, position, defn, cache, fast=fast, scope=scope)):
            if fast:
                return child
            failures.append(child)
        else:
            children.append(child)
    if failures:
        return _aggregate(failures)
    return tuple(children)


def _bind_listing(path: Path, cache: _FsCache) -> CacheSeq[Path]:
    listing = cache.get(path)
    if listing is None:
        listing = cache[path] = CacheSeq(lambda: sorted(path.iterdir(), key=lambda entry: entry.name))
    return listing


def _bind_dir_defn(
    path: SafePath, position: int, defn: Defn, cache: _FsCache, *, fast: bool = False, scope: CaptureMap | None = None
) -> BoundChild | MismatchErr:
    node = defn_node(defn)
    if node.name:
        return _bind_named(path, defn, node, cache, fast=fast, scope=scope)
    return _bind_matched(path, position, defn, node, cache, fast=fast, scope=scope)


def _bind_named(
    path: SafePath, defn: Defn, node: Node, cache: _FsCache, *, fast: bool = False, scope: CaptureMap | None = None,
) -> BoundChild | MismatchErr:  # fmt: skip
    basename = close_exn(node.name, scope)  # declaration error
    target = child_path_exn(path, basename)  # caller error
    if node.min == 0 and node.name != "." and not target.exists():
        return None
    if node.select(basename) is None:
        return _mismatch(em.Bind.fixed(node.match, target))
    if not _bind_is_kind(target, node):
        message = em.Bind.file(target) if isinstance(defn, File) else em.Bind.directory(target)
        return _mismatch(message)
    bound = _bind_fixed(target, defn, cache, fast=fast, scope=scope)
    if node.name == "." and node.min == 0 and is_mismatch(bound):
        return None
    return bound


def _bind_matched(
    path: SafePath, position: int, defn: Defn, node: Node, cache: _FsCache, *, fast: bool = False, scope: CaptureMap | None = None,
) -> BoundChild | MismatchErr:  # fmt: skip
    listing = _bind_listing(path, cache)
    matches, failures = _bind_matches(defn, listing, cache, fast=fast, scope=scope)
    if fast and failures:
        return failures[0]
    count = len(matches)
    if count < node.min or (node.max is not None and count > node.max):
        failures.append(_mismatch(em.Bind.count(
            low=node.min, high=node.max, position=position, found=count,
            dangling=_bind_dangling_names(defn, listing), path=path,
            )))  # fmt: skip
    if failures:
        return _aggregate(failures)
    if node.fmt:
        return Template(path, matches, defn, scope=scope)
    return Matches(path, matches, defn, scope=scope)


# plum cannot carry SafePath. child_path_exn or _listed already returned SafePath
@overload
def _bind_fixed(
    path: Path, defn: File[_L], cache: _FsCache, *, fast: bool = False, scope: CaptureMap | None = None
) -> FixedFile[_L]: ...


@overload
def _bind_fixed(
    path: Path, defn: DirDefn, cache: _FsCache, *, fast: bool = False, scope: CaptureMap | None = None
) -> FixedDir | MismatchErr: ...


def _bind_fixed(
    path: Path, defn: Defn, cache: _FsCache, *, fast: bool = False, scope: CaptureMap | None = None
) -> FixedFile[object] | FixedDir | MismatchErr:
    return _bind_fixed_kind(path, defn, cache, fast, scope)  # pyright: ignore[reportArgumentType]


@dispatch
def _bind_fixed_kind(  # pyright: ignore[reportRedeclaration]
    path: Path, defn: File, cache: _SeqCache, fast: bool = False, scope: CaptureMap | None = None
) -> FixedFile:
    path = SafePath(path)  # plum boundary
    return FixedFile(path, defn, scope=scope)


def _first_layout(
    path: SafePath, layouts: Sequence[DirLayout], cache: _FsCache, *, fast: bool, scope: CaptureMap | None = None
) -> tuple[DirLayout, tuple[BoundChild, ...]] | MismatchErr:
    # fast fails one layout fast. The next layout is still tried. skip_mismatch is the caller's job
    failures: list[MismatchErr] = []
    for layout in layouts:
        children = bind_children(path, layout, cache, fast=fast, scope=layout_scope(layout, scope))
        if is_mismatch(children):
            failures.append(children)
            continue
        return layout, children
    return _aggregate(failures) if failures else _mismatch(em.Xor.empty(path))


@dispatch
def _bind_fixed_kind(
    path: Path, defn: DirDefn, cache: _SeqCache, fast: bool = False, scope: CaptureMap | None = None
) -> FixedDir | MismatchErr:
    path = SafePath(path)  # plum boundary
    if is_mismatch(chosen := _first_layout(path, defn.layouts, typing.cast(_FsCache, cache), fast=fast, scope=scope)):
        return chosen
    layout, children = chosen
    return (layout.child_type or FixedDir)(path, children, OneDefn(defn.defn, layout))


def _bind_sort_matches(matches: list[_MatchValue], node: Node) -> list[_MatchValue]:
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


def _bind_failed_match(node: Node, basename: Safe[Name], scope: CaptureMap | None) -> MismatchErr | None:
    if (pattern := _bound_selector(node, scope).match_failure(basename)) is None:
        return None
    return _mismatch(em.Bind.failed(pattern, basename))


def _bind_linked(
    node: Node, target: Path, selector: Selector, scope: CaptureMap | None, failures: list[MismatchErr],
) -> tuple[SafePath, ParsedCaptures] | None:  # fmt: skip
    if not _bind_is_kind(target, node):
        return None
    if (listed := _listed(target)) is None:
        return None
    target, name = listed
    if is_mismatch(failed := _bind_failed_match(node, name, scope)):
        if not node.skip_mismatch:
            failures.append(failed)
        return None
    if (captures := selector.captures(name)) is None:
        return None
    return target, captures.chain(scope)


def _bind_file_matches(
    defn: File[_L], listing: Sequence[Path], *, fast: bool = False, scope: CaptureMap | None = None
) -> _MatchRes[FileMatch[_L]]:
    matches: list[FileMatch[_L]] = []
    failures: list[MismatchErr] = []
    selector = _bound_selector(defn, scope)
    for target in listing:
        if not (found := _bind_linked(defn, target, selector, scope, failures)):
            if fast and failures:
                return matches, failures
            continue
        safe_target, linked = found
        matches.append(FileMatch(safe_target, linked, defn))
    return _bind_sort_matches(matches, defn), failures


def _bind_dir_matches(
    defn: DirDefn, listing: Sequence[Path], cache: _FsCache, *, fast: bool = False, scope: CaptureMap | None = None
) -> _MatchRes[DirMatch]:
    matches: list[DirMatch] = []
    failures: list[MismatchErr] = []
    node = defn.defn
    selector = _bound_selector(node, scope)
    for target in listing:
        if not (found := _bind_linked(node, target, selector, scope, failures)):
            if fast and failures:
                return matches, failures
            continue
        safe_target, linked = found
        if is_mismatch(chosen := _first_layout(safe_target, defn.layouts, cache, fast=fast, scope=linked.kwargs)):
            if node.skip_mismatch:
                continue
            if fast:
                return matches, [chosen]
            failures.append(chosen)
            continue
        layout, children = chosen
        bound = OneDefn(node, layout)
        matches.append(_bound_dir_match_type(layout)(safe_target, linked, children, bound))
    return _bind_sort_matches(matches, node), failures


@overload
def _bind_matches(
    defn: File[_L], listing: Sequence[Path], cache: _FsCache, *, fast: bool = False, scope: CaptureMap | None = None,
) -> _MatchRes[FileMatch[_L]]: ...  # fmt: skip


@overload
def _bind_matches(
    defn: DirDefn, listing: Sequence[Path], cache: _FsCache, *, fast: bool = False, scope: CaptureMap | None = None,
) -> _MatchRes[DirMatch]: ...  # fmt: skip


def _bind_matches(
    defn: Defn, listing: Sequence[Path], cache: _FsCache, *, fast: bool = False, scope: CaptureMap | None = None
) -> tuple[Sequence[FileMatch[object] | DirMatch], list[MismatchErr]]:
    return _bind_matches_kind(defn, listing, cache, fast, scope)  # pyright: ignore[reportArgumentType]


@dispatch
def _bind_matches_kind(  # pyright: ignore[reportRedeclaration]
    defn: File, listing: Sequence[Path], cache: _SeqCache, fast: bool = False, scope: CaptureMap | None = None
) -> object:
    return _bind_file_matches(defn, listing, fast=fast, scope=scope)


@dispatch
def _bind_matches_kind(
    defn: DirDefn, listing: Sequence[Path], cache: _SeqCache, fast: bool = False, scope: CaptureMap | None = None
) -> _MatchRes[DirMatch]:
    return _bind_dir_matches(defn, listing, typing.cast(_FsCache, cache), fast=fast, scope=scope)
