from collections.abc import Callable
from pathlib import Path
from typing import TypeVar

from typing_extensions import TypeIs, assert_never

from ._types import DataclassInstance, HasSave, LoadT, PathIsh, Puttable

# The passthrough value is returned unchanged when it is not a mismatch.
_T = TypeVar("_T")


class MismatchErr(Exception):
    pass


def is_mismatch(x: object) -> TypeIs[MismatchErr]:
    return isinstance(x, MismatchErr)


def raise_mismatch(x: _T | MismatchErr) -> _T:
    if is_mismatch(x):
        raise x
    return x


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
            _ = target.write_bytes(data.read_bytes())
        case HasSave():
            data.save(target)
        case DataclassInstance():
            raise TypeError(f"no declared codec for {type(data).__name__}")
        case _:  # pragma: no cover - closed-union defense
            assert_never(data)


def load(path: PathIsh, decoder: Callable[[Path], LoadT]) -> LoadT | Exception:
    try:
        return decoder(Path(path))
    except Exception as error:
        return error
