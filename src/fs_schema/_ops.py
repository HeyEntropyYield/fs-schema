import os
import tempfile
from collections.abc import Callable
from pathlib import Path
from shutil import copyfile, copytree, rmtree
from typing import Literal, TypeVar, cast

from typing_extensions import TypeIs, assert_never

from ._mashumaro_json import decode_json, encode_json
from ._types import DataclassInstance, HasSave, LoadSpec, LoadT, PathIsh, Puttable

# The passthrough value is returned unchanged when it is not a mismatch.
_T = TypeVar("_T")


class MismatchErr(Exception):
    def __bool__(self) -> Literal[False]:
        return False


def is_mismatch(x: object) -> TypeIs[MismatchErr]:
    return isinstance(x, MismatchErr)


def raise_exn(x: _T | Exception) -> _T:
    if isinstance(x, Exception):
        raise x
    return x


def raise_mismatch(x: _T | MismatchErr) -> _T:
    return raise_exn(x)


def exists_opt(path: PathIsh | None) -> Path | None:
    if path is None:
        return None
    candidate = Path(path)
    return candidate if candidate.exists() else None


def put(path: PathIsh, data: Puttable | PathIsh | None = None) -> None:
    target = Path(path)
    _commit(target, lambda temporary: _write_puttable(temporary, data))


def link_to(path: PathIsh, target: PathIsh, *, hard: bool = False) -> None:
    _commit(Path(path), lambda temporary: _link(temporary, target, hard=hard))


def copy_to(
    source: PathIsh,
    dest: PathIsh,
    *,
    follow_symlinks: bool = True,
    clean: bool = False,
) -> None:
    src = Path(source)
    target = Path(dest)
    if _overlaps(src, target):
        raise ValueError(f"refusing to copy onto itself: {target}")
    if clean and (target.exists() or target.is_symlink()):
        if target.is_dir() and not target.is_symlink():
            rmtree(target)
        else:
            target.unlink()
    # A symlink at dest is the path being replaced. Do not write through it.
    if target.is_symlink():
        target.unlink()
    if src.is_dir() and not src.is_symlink():
        _ = copytree(src, target, symlinks=not follow_symlinks, dirs_exist_ok=not clean)
        return
    target.parent.mkdir(parents=True, exist_ok=True)
    if follow_symlinks or not src.is_symlink():
        _ = copyfile(src, target)
        return
    if target.exists() or target.is_symlink():
        target.unlink()
    os.symlink(src.readlink(), target)


def _overlaps(source: Path, dest: Path) -> bool:
    src, dst = source.resolve(), dest.resolve()
    return src == dst or src in dst.parents or dst in src.parents


def _commit(target: Path, write: Callable[[Path], None]) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    descriptor, name = tempfile.mkstemp(dir=target.parent, prefix=".", suffix=target.suffix)
    os.close(descriptor)
    temporary = Path(name)
    try:
        write(temporary)
        os.replace(temporary, target)
    except BaseException:
        temporary.unlink(missing_ok=True)
        raise


def _write_puttable(target: Path, data: Puttable | PathIsh | None) -> None:
    match data:
        case None:
            _ = target.write_bytes(b"")
        case bytes():
            _ = target.write_bytes(data)
        case str():
            _ = target.write_text(data)
        case HasSave():
            data.save(target)
        case DataclassInstance():
            encoded = encode_json(target, data)
            match encoded:
                case bytes():
                    _ = target.write_bytes(encoded)
                case str():
                    _ = target.write_text(encoded)
                case _:
                    assert_never(encoded)
        case os.PathLike():
            _ = copyfile(Path(data), target)
        case _:
            assert_never(data)


def _link(temporary: Path, source: PathIsh, *, hard: bool) -> None:
    temporary.unlink()
    match hard:
        case True:
            os.link(source, temporary)
        case False:
            os.symlink(source, temporary)


def load(path: PathIsh, decoder: LoadSpec[LoadT]) -> LoadT | Exception:
    target = Path(path)
    try:
        if isinstance(decoder, type):
            return cast(LoadT, decode_json(target, decoder))
        return decoder(target)
    except Exception as error:
        return error
