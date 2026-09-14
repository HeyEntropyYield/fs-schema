"""Private compilation and parsing of fs-schema basename templates."""

from collections.abc import Iterator, Mapping
from dataclasses import dataclass, replace
from datetime import date, datetime, time
from enum import Enum
from string import Formatter
from typing import Final, TypeAlias

from beartype.typing import Protocol
from parse import Parser
from typing_extensions import override

# A parsed template field: {n:d} -> int, {stem} -> str, dt() -> datetime.
FmtField: TypeAlias = str | int | datetime
_FORMATTER = Formatter()
_DIRECTIVES = frozenset("aAwdbBmyYHIpMSfzZjUWcxX%")
_INTEGER_TYPES = frozenset("bcdoxXn")


class CaptureMap(Mapping[str, FmtField]):
    __slots__: Final = ("_values",)
    _values: dict[str, FmtField]

    def __init__(self, values: Mapping[str, FmtField]) -> None:
        self._values = dict(values)

    @override
    def __getitem__(self, key: str) -> FmtField:
        return self._values[key]

    @override
    def __iter__(self) -> Iterator[str]:
        return iter(self._values)

    @override
    def __len__(self) -> int:
        return len(self._values)

    def __getattr__(self, name: str) -> FmtField:
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


class _FormatFieldTemplate(Enum):
    STRING = FormatField("", 0)
    INTEGER = FormatField("", 0, "d")
    DATETIME = FormatField("", 0, "%Y")


@dataclass(frozen=True, slots=True)
class ParsedCaptures:
    args: tuple[FmtField, ...]
    kwargs: CaptureMap


class CompiledFormat:
    __slots__: Final = ("_fields", "_parser", "_pattern")
    _fields: tuple[FormatField, ...]
    _parser: Parser
    _pattern: str

    def __init__(self, pattern: str) -> None:
        self._fields = tuple(
            _compile_field(name, spec or "", index)
            for index, (_, name, spec, _) in enumerate(_FORMATTER.parse(pattern))
            if name is not None
        )
        self._parser = Parser(pattern, case_sensitive=True)
        self._pattern = pattern

    @property
    def pattern(self) -> str:
        return self._pattern

    @property
    def fields(self) -> tuple[FormatField, ...]:
        return self._fields

    def format(self, *args: FmtField, **kwargs: FmtField) -> str:
        return _FORMATTER.vformat(self.pattern, args, kwargs)

    def parse(self, basename: str) -> ParsedCaptures | None:
        if (parsed := _parse(self._parser, basename)) is None:
            return None
        return ParsedCaptures(
            tuple(_capture_value(value) for value in parsed.fixed),
            CaptureMap({name: _capture_value(value) for name, value in parsed.named.items()}),
        )


# These types only exist for enforced typechecking
_ParserField: TypeAlias = str | int | date | time | datetime


class _ParseResult(Protocol):
    fixed: tuple[_ParserField, ...]
    named: dict[str, _ParserField]


def _parse(parser: Parser, basename: str) -> _ParseResult | None:
    return parser.parse(basename)


def _capture_value(value: _ParserField) -> FmtField:
    match value:
        case datetime():
            return value
        case date():
            return datetime.combine(value, time.min)
        case str() | int():
            return value
        case time():
            raise TypeError("time captures are unsupported")
        case _:  # pyright: ignore[reportUnnecessaryComparison]
            raise TypeError("unexpected capture type")  # pyright: ignore[reportUnreachable]


def _is_strftime_spec(spec: str) -> bool:
    found = False
    index = 0
    while index < len(spec):
        if spec[index] != "%":
            index += 1
            continue
        if index + 1 >= len(spec) or spec[index + 1] not in _DIRECTIVES:
            return False
        found |= spec[index + 1] != "%"
        index += 2
    return found


def _field_template(spec: str) -> _FormatFieldTemplate:
    if _is_strftime_spec(spec):
        return _FormatFieldTemplate.DATETIME
    if spec[-1:] in _INTEGER_TYPES:
        return _FormatFieldTemplate.INTEGER
    return _FormatFieldTemplate.STRING


def _compile_field(name: str, spec: str, index: int) -> FormatField:
    return replace(_field_template(spec).value, name=name, index=index, pattern=spec)


def dt(pattern: str) -> str:
    return f"{{:{pattern}}}"
