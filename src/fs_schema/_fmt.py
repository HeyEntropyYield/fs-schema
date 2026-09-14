from collections.abc import Iterator, Mapping
from datetime import datetime
from typing import TypeAlias

from typing_extensions import override

# TODO: namefmt.Fmt (parse + format). A str pattern is the handle today.
FmtLike: TypeAlias = str

# A parsed template field: {n:d} -> int, {stem} -> str, dt() -> datetime.
FmtField: TypeAlias = str | int | datetime


class CaptureMap(Mapping[str, FmtField]):
    @override
    def __getitem__(self, key: str) -> FmtField:
        raise NotImplementedError

    @override
    def __iter__(self) -> Iterator[str]:
        raise NotImplementedError

    @override
    def __len__(self) -> int:
        raise NotImplementedError

    def __getattr__(self, name: str) -> FmtField:
        raise NotImplementedError


def dt(pattern: str) -> FmtLike:
    return f"{{:{pattern}}}"
