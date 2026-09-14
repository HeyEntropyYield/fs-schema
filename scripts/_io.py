import sys
from collections.abc import Sequence
from typing import TypeAlias

from typing_extensions import Protocol, runtime_checkable

Toml: TypeAlias = dict[str, "Toml"] | list["Toml"] | str | int | float | bool | None
TomlObj: TypeAlias = dict[str, Toml]


@runtime_checkable
class TextReader(Protocol):
    def read(self, n: int = -1, /) -> str: ...


@runtime_checkable
class TextWriter(Protocol):
    def write(self, s: str, /) -> int: ...


def argv_tail(argv: Sequence[str]) -> list[str]:
    return list(argv[1:] if argv is sys.argv else argv)
