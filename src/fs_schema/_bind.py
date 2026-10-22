# pyright: reportImportCycles=false
import typing
from collections.abc import Callable, Sequence
from datetime import datetime
from pathlib import Path
from typing import TypeAlias, overload

from plum import dispatch
from typing_extensions import TypeIs, TypeVar

import fs_schema._errmsg as em

from ._decl import Defn, DirDefn, File, Match, Node, defn_node
from ._ops import MismatchErr, is_mismatch
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
from ._std_ext import CacheSeq

_L = TypeVar("_L")
_MatchT = TypeVar("_MatchT")
_MatchRes: TypeAlias = tuple[list[_MatchT], list[MismatchErr]]


def _is_bound_dir_match_type(value: object, schema_type: type) -> TypeIs[type[DirMatch]]:
    return isinstance(value, type) and issubclass(value, schema_type) and issubclass(value, DirMatch)


def _bound_dir_match_type(defn: DirDefn) -> type[DirMatch]:
    schema_type = defn.child_type
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


_FsCache: TypeAlias = dict[Path, CacheSeq[Path]]
_MatchValue = TypeVar("_MatchValue", bound=Match)


## Bind


def _bind_is_kind(path: Path, defn: Defn) -> bool:
    return path.is_file() if isinstance(defn, File) else path.is_dir()


def _bind_dangling_names(defn: Defn, listing: Sequence[Path]) -> list[str]:
    node = defn_node(defn)
    names: list[str] = []
    for target in listing:
        if _bind_is_kind(target, defn) or not target.is_symlink() or target.exists():
            continue
        if node.select(target.name) is not None:
            names.append(target.name)
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


def bind_children(
    path: Path, dir_defn: DirDefn, cache: _FsCache, *, fast: bool = False
) -> tuple[BoundChild, ...] | MismatchErr:
    if not path.is_dir():
        return _mismatch(f"expected directory: {path}")

    children: list[BoundChild] = []
    failures: list[MismatchErr] = []
    for position, defn in enumerate(dir_defn.defns):
        if is_mismatch(child := _bind_dir_defn(path, position, defn, cache, fast=fast)):
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
    path: Path, position: int, defn: Defn, cache: _FsCache, *, fast: bool = False
) -> BoundChild | MismatchErr:
    node = defn_node(defn)
    if node.name:
        target = path / node.name
        if node.min == 0 and node.name != "." and not target.exists():
            return None
        if node.select(target.name) is None:
            return _mismatch(em.Bind.fixed(node.match, target))
        if not _bind_is_kind(target, defn):
            message = em.Bind.file(target) if isinstance(defn, File) else em.Bind.directory(target)
            return _mismatch(message)
        bound = _bind_fixed(target, defn, cache, fast=fast)
        if node.name == "." and node.min == 0 and is_mismatch(bound):
            return None
        return bound

    listing = _bind_listing(path, cache)
    matches, failures = _bind_matches(defn, listing, cache, fast=fast)
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
    return Template(path, matches, defn) if node.fmt is not None else Matches(path, matches, defn)


@overload
def _bind_fixed(path: Path, defn: File[_L], cache: _FsCache, *, fast: bool = False) -> FixedFile[_L]: ...


@overload
def _bind_fixed(path: Path, defn: DirDefn, cache: _FsCache, *, fast: bool = False) -> FixedDir | MismatchErr: ...


def _bind_fixed(
    path: Path, defn: Defn, cache: _FsCache, *, fast: bool = False
) -> FixedFile[object] | FixedDir | MismatchErr:
    return _bind_fixed_kind(path, defn, cache, fast)  # pyright: ignore[reportArgumentType]


@dispatch
def _bind_fixed_kind(path: Path, defn: File, cache: _FsCache, fast: bool = False) -> FixedFile:  # pyright: ignore[reportRedeclaration]
    return FixedFile(path, defn)


@dispatch
def _bind_fixed_kind(path: Path, defn: DirDefn, cache: _FsCache, fast: bool = False) -> FixedDir | MismatchErr:
    if is_mismatch(children := bind_children(path, defn, cache, fast=fast)):
        return children
    return (defn.child_type or FixedDir)(path, children, defn)


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


def _bind_failed_match(node: Node, basename: str) -> MismatchErr | None:
    pattern = node.selector.match_failure(basename)
    if pattern is None:
        return None
    return _mismatch(em.Bind.failed(pattern, basename))


def _bind_file_matches(defn: File[_L], listing: Sequence[Path], *, fast: bool = False) -> _MatchRes[FileMatch[_L]]:
    matches: list[FileMatch[_L]] = []
    failures: list[MismatchErr] = []
    for target in listing:
        if not _bind_is_kind(target, defn):
            continue
        if is_mismatch(failed := _bind_failed_match(defn, target.name)):
            if defn.skip_mismatch:
                continue
            if fast:
                return matches, [failed]
            failures.append(failed)
            continue
        if (captures := defn.select(target.name)) is None:
            continue
        matches.append(FileMatch(target, captures, defn))
    return _bind_sort_matches(matches, defn), failures


def _bind_dir_matches(
    defn: DirDefn, listing: Sequence[Path], cache: _FsCache, *, fast: bool = False
) -> _MatchRes[DirMatch]:
    matches: list[DirMatch] = []
    failures: list[MismatchErr] = []
    match_type = _bound_dir_match_type(defn)
    node = defn.defn
    for target in listing:
        if not _bind_is_kind(target, defn):
            continue
        if is_mismatch(failed := _bind_failed_match(node, target.name)):
            if node.skip_mismatch:
                continue
            if fast:
                return matches, [failed]
            failures.append(failed)
            continue
        if (captures := node.select(target.name)) is None:
            continue
        if is_mismatch(children := bind_children(target, defn, cache, fast=fast)):
            if node.skip_mismatch:
                continue
            if fast:
                return matches, [children]
            failures.append(children)
            continue
        matches.append(match_type(target, captures, children, defn))
    return _bind_sort_matches(matches, defn.defn), failures


@overload
def _bind_matches(
    defn: File[_L], listing: Sequence[Path], cache: _FsCache, *, fast: bool = False
) -> _MatchRes[FileMatch[_L]]: ...


@overload
def _bind_matches(
    defn: DirDefn, listing: Sequence[Path], cache: _FsCache, *, fast: bool = False
) -> _MatchRes[DirMatch]: ...


def _bind_matches(
    defn: Defn, listing: Sequence[Path], cache: _FsCache, *, fast: bool = False
) -> tuple[Sequence[FileMatch[object] | DirMatch], list[MismatchErr]]:
    return _bind_matches_kind(defn, listing, cache, fast)  # pyright: ignore[reportArgumentType]


@dispatch
def _bind_matches_kind(  # pyright: ignore[reportRedeclaration]
    defn: File, listing: Sequence[Path], cache: _FsCache, fast: bool = False
) -> object:
    return _bind_file_matches(defn, listing, fast=fast)


@dispatch
def _bind_matches_kind(
    defn: DirDefn, listing: Sequence[Path], cache: _FsCache, fast: bool = False
) -> _MatchRes[DirMatch]:
    return _bind_dir_matches(defn, listing, cache, fast=fast)
