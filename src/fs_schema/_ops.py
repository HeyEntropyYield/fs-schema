from collections.abc import Callable
from pathlib import Path
from typing import TypeVar

from typing_extensions import TypeIs

from ._types import LoadT, PathIsh, Puttable

# The passthrough value is returned unchanged when it is not a mismatch.
_T = TypeVar("_T")


class MismatchErr(Exception):
    pass


def is_mismatch(x: object) -> TypeIs[MismatchErr]:
    raise NotImplementedError


def raise_mismatch(x: _T | MismatchErr) -> _T:
    raise NotImplementedError


def exists_opt(path: PathIsh) -> Path | None:
    raise NotImplementedError


def put(path: PathIsh, data: Puttable) -> None:
    # Creates missing parent directories.
    raise NotImplementedError


def load(path: PathIsh, decoder: Callable[[Path], LoadT]) -> LoadT | Exception:
    raise NotImplementedError
