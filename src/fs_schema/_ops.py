from pathlib import Path
from shutil import copyfile
from typing import TypeVar, cast

from typing_extensions import TypeIs, assert_never

from ._mashumaro_json import decode_json, encode_json
from ._types import DataclassInstance, HasSave, LoadSpec, LoadT, PathIsh, Puttable

# The passthrough value is returned unchanged when it is not a mismatch.
_T = TypeVar("_T")


class MismatchErr(Exception):
    def __bool__(self) -> bool:
        return False


def is_mismatch(x: object) -> TypeIs[MismatchErr]:
    return isinstance(x, MismatchErr)


def raise_exn(x: _T | Exception) -> _T:
    if isinstance(x, Exception):
        raise x
    return x


def raise_mismatch(x: _T | MismatchErr) -> _T:
    return raise_exn(x)


def exists_opt(path: PathIsh) -> Path | None:
    candidate = Path(path)
    return candidate if candidate.exists() else None


def put(path: PathIsh, data: Puttable) -> None:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    match data:
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
