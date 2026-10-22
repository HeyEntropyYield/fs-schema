"""Private compilation and parsing of fs-schema basename templates."""

import re
from collections.abc import Iterator, Mapping
from dataclasses import dataclass
from pathlib import Path
from string import Formatter
from typing import Final, TypeAlias

from typing_extensions import override

import fs_schema._errmsg as em

from ._fmt_spec import Spec
from ._types import FmtFields, FmtFieldT, FmtStr, MatchPat, Name, Raw, Safe, SafePath

# Regex optional groups can be absent; format fields cannot.
CaptureField: TypeAlias = FmtFieldT | None
_FORMATTER = Formatter()
_FIELD_NAME: Final = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")


## Public


@dataclass(frozen=True, slots=True)
class Captures:
    args: tuple[FmtFieldT, ...]
    kwargs: FmtFields


def captures(*args: FmtFieldT, **kwargs: FmtFieldT) -> Captures:
    return Captures(args, kwargs)


def dt(pattern: str, name: str = "ts") -> Raw[FmtStr]:
    return Raw[FmtStr](f"{{{name}:{pattern}}}")


## Intl Types


class CaptureMap(Mapping[str, CaptureField]):
    """Keys are field names, not basenames. Values are types"""

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
    # field_name is an identifier
    field_name: str
    index: int
    field_spec: str = ""

    @property
    def positional(self) -> bool:
        return not self.field_name or (self.field_name.isascii() and self.field_name.isdecimal())


@dataclass(frozen=True, slots=True)
class ParsedCaptures:
    args: tuple[CaptureField, ...]
    kwargs: CaptureMap


class CompiledFormat:
    __slots__: Final = ("_fields", "_pattern", "_spec")
    _fields: tuple[FormatField, ...]
    _pattern: Safe[FmtStr]
    _spec: Spec

    def __init__(self, pattern: Raw[FmtStr]) -> None:
        self._pattern, self._fields, self._spec = compile_fmt_exn(pattern)  # declaration error

    @property
    def pattern(self) -> Safe[FmtStr]:
        return self._pattern

    @property
    def fields(self) -> tuple[FormatField, ...]:
        return self._fields

    def format(self, *args: FmtFieldT, **kwargs: FmtFieldT) -> Raw[Name]:
        return Raw[Name](_FORMATTER.vformat(self.pattern, args, kwargs))

    def parse(self, basename: Safe[Name]) -> ParsedCaptures | None:
        """Exception: raises on unsupported type"""
        if not (parsed := self._spec.parse(basename)):
            return None
        return ParsedCaptures(parsed.args, CaptureMap(parsed.kwargs))


## Exported fns


def compile_match(pattern: Raw[MatchPat]) -> re.Pattern[str]:
    return re.compile(pattern)


def safe(name: Raw[Name]) -> Safe[Name] | None:
    if _bad_text(name) or not _is_path_item(name):
        return None
    return Safe[Name](name)


def safe_exn(name: Raw[Name]) -> Safe[Name]:
    if (safe_text := safe(name)) is None:
        raise ValueError(em.Fmt.basename(name))
    return safe_text


def safe_path_exn(path: Path) -> SafePath:
    if not (found := _safe_path(path)):
        raise ValueError(em.Fmt.basename(path.as_posix()))
    return found


def child_path_exn(parent: SafePath, name: Safe[Name]) -> SafePath:
    # "" is no component. "." is this directory. Both keep the parent.
    if not name or name == ".":
        return parent
    return safe_path_exn(parent / name)


def path_name_exn(path: SafePath) -> Safe[Name]:
    if not path.name:
        return Safe[Name]("")
    return safe_exn(Raw[Name](path.name))  # caller error


## Intl Helpers


def _bad_text(text: str) -> bool:
    # all invalid chars
    return "\0" in text or "/" in text or "\\" in text


def _is_path_item(text: str) -> bool:
    # that is, an item that goes down the tree
    return bool(text) and text not in {".", ".."}


def _safe_path(path: Path) -> SafePath | None:
    parts = path.parts[1:] if path.anchor else path.parts
    # Anchor alone is the filesystem root. Path("/") and Path("//"). Path(".") has neither
    if path.anchor and not parts:
        return SafePath(path)
    if parts and all(not _bad_text(part) and _is_path_item(part) for part in parts):
        return SafePath(path)
    return None


def compile_fmt_exn(pattern: Raw[FmtStr]) -> tuple[Safe[FmtStr], tuple[FormatField, ...], Spec]:
    # Literal, field, and conversion checks, then Spec. This return is the compiled pattern
    fields = _format_fields_exn(pattern)
    spec = Spec(pattern)  # unsupported type
    return Safe[FmtStr](pattern), fields, spec


# This extracts and validates all the fields in the pattern
def _format_fields_exn(pattern: Raw[FmtStr]) -> tuple[FormatField, ...]:
    # Formatter owns the brace grammar. These checks are the pieces it returns.
    fields: list[FormatField] = []
    for index, (literal, field_name, field_spec, conversion) in enumerate(_FORMATTER.parse(pattern)):
        if _bad_text(literal):
            raise ValueError(em.Fmt.literal(pattern))
        if field_name is None:
            continue
        if conversion is not None:
            raise ValueError(em.Fmt.CONV)
        if (
            field_name
            and not (field_name.isascii() and field_name.isdecimal())
            and not _FIELD_NAME.fullmatch(field_name)
        ):
            raise ValueError(em.Fmt.field(field_name))
        fields.append(FormatField(field_name, index, field_spec or ""))
    if not fields and (_bad_text(pattern) or not _is_path_item(pattern)):
        raise ValueError(em.Fmt.basename(pattern))
    return tuple(fields)
