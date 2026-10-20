"""Private compilation and parsing of fs-schema basename templates."""

from collections.abc import Iterator, Mapping
from dataclasses import dataclass
from string import Formatter
from typing import Final, TypeAlias

from typing_extensions import override

from ._fmt_spec import Spec
from ._types import FmtFields, FmtFieldT

FmtLike: TypeAlias = str
# Regex optional groups can be absent; format fields cannot.
CaptureField: TypeAlias = FmtFieldT | None
_FORMATTER = Formatter()


class CaptureMap(Mapping[str, CaptureField]):
    __slots__: Final = ("_values",)
    _values: dict[str, CaptureField]

    def __init__(self, values: Mapping[str, CaptureField]) -> None:
        self._values = dict(values)

    @override
    def __getitem__(self, key: str) -> CaptureField:
        return self._values[key]

    @override
    def __iter__(self) -> Iterator[str]:
        return iter(self._values)

    @override
    def __len__(self) -> int:
        return len(self._values)

    def __getattr__(self, name: str) -> CaptureField:
        try:
            return self._values[name]
        except KeyError as error:
            raise AttributeError(name) from error


@dataclass(frozen=True, slots=True)
class FormatField:
    name: str
    index: int
    pattern: str = ""

    @property
    def positional(self) -> bool:
        return not self.name or (self.name.isascii() and self.name.isdecimal())


@dataclass(frozen=True, slots=True)
class ParsedCaptures:
    args: tuple[CaptureField, ...]
    kwargs: CaptureMap


class CompiledFormat:
    __slots__: Final = ("_fields", "_pattern", "_spec")
    _fields: tuple[FormatField, ...]
    _pattern: str
    _spec: Spec

    def __init__(self, pattern: str) -> None:
        self._fields = tuple(
            FormatField(name, index, spec or "")
            for index, (_, name, spec, _) in enumerate(_FORMATTER.parse(pattern))
            if name is not None
        )
        self._spec = Spec(pattern)  # unsupported type
        self._pattern = pattern

    @property
    def pattern(self) -> str:
        return self._pattern

    @property
    def fields(self) -> tuple[FormatField, ...]:
        return self._fields

    def format(self, *args: FmtFieldT, **kwargs: FmtFieldT) -> str:
        return _FORMATTER.vformat(self.pattern, args, kwargs)

    def parse(self, basename: str) -> ParsedCaptures | None:
        """Exception: raises on unsupported type"""
        if not (parsed := self._spec.parse(basename)):
            return None
        return ParsedCaptures(parsed.args, CaptureMap(parsed.kwargs))


@dataclass(frozen=True, slots=True)
class Captures:
    args: tuple[FmtFieldT, ...]
    kwargs: FmtFields


def captures(*args: FmtFieldT, **kwargs: FmtFieldT) -> Captures:
    return Captures(args, kwargs)


def dt(pattern: str, name: str = "ts") -> FmtLike:
    return f"{{{name}:{pattern}}}"
