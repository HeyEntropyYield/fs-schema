from collections.abc import Callable, Iterator, Mapping
from dataclasses import dataclass
from datetime import date, datetime, time
from decimal import Decimal
from functools import partial
from typing import Final, TypeAlias, cast

import parse as parse_lib
from beartype.typing import Protocol
from parse import Parser
from typing_extensions import Self, assert_never

import fs_schema._errmsg as em

from ._types import FmtFieldT, FmtStr, Name, Raw, Safe

# These types only exist for enforced typechecking
_Field: TypeAlias = str | int | float | Decimal | date | time | datetime


class _Result(Protocol):
    fixed: tuple[_Field, ...]
    named: dict[str, _Field]


def _parselib_parse(parser: Parser, text: Safe[Name]) -> _Result | None:
    if not (found := parser.parse(text)):
        return None
    return cast(_Result, found)


@dataclass(frozen=True, slots=True)
class _Parsed:
    args: tuple[FmtFieldT, ...]
    kwargs: Mapping[str, FmtFieldT]

    @classmethod
    def from_result_exn(cls, result: _Result) -> Self:
        return cls(
            tuple(value_exn(item) for item in result.fixed),  # unsupported type
            {name: value_exn(item) for name, item in result.named.items()},  # unsupported type
        )


class Spec:
    __slots__: Final = ("_parser",)
    _parser: Parser

    def __init__(self, pattern: Raw[FmtStr]) -> None:
        """Exception: raises on unsupported type"""
        self._parser = Parser(pattern, case_sensitive=True)
        for sample in _samples(self._parser):
            _ = value_exn(sample)  # unsupported type

    def parse(self, text: Safe[Name]) -> _Parsed | None:
        """Exception: raises on unsupported type"""
        if not (result := _parselib_parse(self._parser, text)):
            return None
        return _Parsed.from_result_exn(result)


def value_exn(parsed: _Field) -> FmtFieldT:
    match parsed:
        case datetime():
            return parsed
        case date():
            return datetime.combine(parsed, time.min)
        case str() | int():
            return parsed
        case time():
            raise TypeError(em.Fmt.TIME)
        case float() | Decimal():
            raise TypeError(em.Fmt.value(type(parsed).__name__))
        case _:
            assert_never(parsed)


class _Call:
    def __call__(self, text: str, match: object) -> object: ...


class _Converters(Protocol):
    int_convert: type[_Call]
    convert_first: type[_Call]
    percentage: Callable[[str, object], object]
    strf_date_convert: Callable[..., object]
    date_convert: Callable[..., object]


# parse stub exports Parser only
_LIB: Final = cast(_Converters, parse_lib)  # pyright: ignore[reportInvalidCast]
# date_convert returns datetime when any of these partial keywords is set, else time
_DATE_CONVERT_DATETIME: Final = ("ymd", "mdy", "dmy", "d_m_y", "mm")


def _samples(parser: Parser) -> Iterator[_Field]:
    # Parser records each converted field here. No public result type
    conversions = cast(Mapping[object, object], parser._type_conversions)  # pyright: ignore[reportAttributeAccessIssue]
    for converter in conversions.values():
        yield _sample(converter)


def _sample(converter: object) -> _Field:
    """Exception: raises on unsupported type"""
    match converter:
        case _LIB.int_convert() | _LIB.convert_first():
            return _call(converter, "1")
        case _ if converter is _LIB.percentage:
            return _call(converter, "50%")
        case partial(func=func, keywords=keys) if func is _LIB.strf_date_convert:
            # strf_date_convert parses one rendered spec into date, time, or datetime
            spec = cast(str, cast(Mapping[str, object], keys)["type"])
            try:
                return _call(cast(object, converter), datetime(2001, 2, 3, 4, 5, 6).strftime(spec))
            except ValueError as error:
                raise TypeError(em.Fmt.value(spec)) from error
        case partial(func=func, keywords=keys) if func is _LIB.date_convert:
            # date_convert needs a regex match. A date group selects datetime
            names = cast(Mapping[str, object], keys)
            if any(names.get(name) is not None for name in _DATE_CONVERT_DATETIME):
                return datetime(2001, 2, 3)
            return time.min
        case partial(func=func):
            raise TypeError(em.Fmt.value(type(func).__name__))
        case _:
            raise TypeError(em.Fmt.value(type(converter).__name__))


def _call(converter: object, text: str) -> _Field:
    return cast(_Field, cast(Callable[[str, object], object], converter)(text, None))
