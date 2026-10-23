from collections.abc import Callable, Mapping
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
    __slots__: Final = ("_kinds", "_parser")
    _kinds: dict[str, type[FmtFieldT]]
    _parser: Parser

    def __init__(self, pattern: Raw[FmtStr]) -> None:
        """Exception: raises on unsupported type"""
        self._parser = Parser(pattern, case_sensitive=True)
        self._kinds = _field_kinds_exn(self._parser)  # unsupported type

    @property
    def field_type(self) -> Mapping[str, type[FmtFieldT]]:
        return self._kinds

    def parse(self, text: Safe[Name]) -> _Parsed | None:
        """Exception: raises on unsupported type"""
        if not (result := _parselib_parse(self._parser, text)):
            return None
        return _Parsed.from_result_exn(result)


def spec_type_exn(spec: str) -> type[FmtFieldT]:
    # <name:spec>. One field, named x
    pattern = Raw[FmtStr]("{x}" if not spec else "{x:" + spec + "}")
    return Spec(pattern).field_type["x"]  # unsupported type


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


def _field_kinds_exn(parser: Parser) -> dict[str, type[FmtFieldT]]:
    # _sample_exn returns a value. type() of that value is the kind. No converter means str
    names = cast(Mapping[str, str], parser._name_types)  # pyright: ignore[reportAttributeAccessIssue]  # field_name -> field_spec
    groups = cast(Mapping[str, str], parser._name_to_group_map)  # pyright: ignore[reportAttributeAccessIssue]  # field_name -> group
    conversions = cast(Mapping[object, object], parser._type_conversions)  # pyright: ignore[reportAttributeAccessIssue]
    kinds: dict[str, type[FmtFieldT]] = {}
    for name in names:
        converter = conversions.get(groups[name])
        kinds[name] = str if converter is None else type(value_exn(_sample_exn(converter)))
    return kinds


def _sample_exn(converter: object) -> _Field:
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
