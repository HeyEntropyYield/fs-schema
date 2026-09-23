import os
import tempfile
from collections.abc import Callable
from pathlib import Path
from shutil import copyfile
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


def put(path: PathIsh, data: Puttable | None = None) -> None:
    target = Path(path)
    _commit(target, lambda temporary: _write_puttable(temporary, data))


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


def _write_puttable(target: Path, data: Puttable | None) -> None:
    match data:
        case None:
            _ = target.write_bytes(b"")
        case bytes():
            _ = target.write_bytes(data)
        case str():
            _ = target.write_text(data)
        case Path():
            _ = copyfile(data, target)
        case HasSave():
            data.save(target)
        case DataclassInstance():
            encoded = encode_json(target, data)
            if isinstance(encoded, bytes):
                _ = target.write_bytes(encoded)
            else:
                _ = target.write_text(encoded)
        case _:  # pragma: no cover - closed-union defense
            assert_never(data)


def load(path: PathIsh, decoder: LoadSpec[LoadT]) -> LoadT | Exception:
    target = Path(path)
    try:
        if isinstance(decoder, type):
            return cast(LoadT, decode_json(target, decoder))
        return decoder(target)
    except Exception as error:
        return error
