"""Private compilation and parsing of fs-schema basename templates."""

import re
from collections.abc import Iterator, Mapping
from dataclasses import dataclass
from pathlib import Path
from string import Formatter
from typing import Final, TypeAlias, TypeVar, final

from typing_extensions import Self, override

import fs_schema._errmsg as em

from ._fmt_spec import Spec
from ._types import FieldSpecs, FmtFields, FmtFieldT, FmtStr, MatchPat, Name, Open, Raw, Resolved, Safe, SafePath

_K = TypeVar("_K")
# Regex optional groups can be absent; format fields cannot.
CaptureField: TypeAlias = FmtFieldT | None
_FORMATTER = Formatter()
_FIELD_NAME: Final = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")
# /< is a literal <. / is never a name character, so the escape is unambiguous
REF: Final = re.compile(r"(?<!/)<([A-Za-z_][A-Za-z0-9_]*)(?::([^>]*))?>")


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
    """Keys are field names, not basenames. Values are field values. A parent is the ancestor frame"""

    __slots__: Final = ("_parent", "_specs", "_values")
    _values: dict[str, CaptureField]
    _specs: FieldSpecs
    _parent: "CaptureMap | None"

    def __init__(
        self,
        values: Mapping[str, CaptureField],
        specs: FieldSpecs | None = None,
        parent: "CaptureMap | None" = None,
    ) -> None:
        self._values = dict(values)
        self._specs = dict(specs or {})
        self._parent = parent

    @override
    def __getitem__(self, key: str) -> CaptureField:
        found = self._stored(key)
        if found is None:
            raise KeyError(key)
        return found[0]

    @override
    def __iter__(self) -> Iterator[str]:
        # Local fields only. Lookup still walks the parent frame
        return iter(self._values)

    @override
    def __len__(self) -> int:
        return len(self._values)

    @override
    def __contains__(self, key: object) -> bool:
        return isinstance(key, str) and self._stored(key) is not None

    def __getattr__(self, name: str) -> CaptureField:
        try:
            return self[name]
        except KeyError as error:
            raise AttributeError(name) from error

    def render_exn(self, field_name: str, field_spec: str | None = None) -> str:
        found = self._stored(field_name)
        if found is None:
            raise KeyError(field_name)
        value, spec = found
        if value is None:
            raise TypeError(em.Schema.Body.unbound(field_name))
        # "" is a field_spec. None keeps the stored one
        return format(value, spec if field_spec is None else field_spec)

    def chain(self, parent: "CaptureMap | None") -> "CaptureMap":
        if parent is None:
            return self
        return CaptureMap(self._values, self._specs, parent)

    def _stored(self, name: str) -> tuple[CaptureField, str] | None:
        if name in self._values:
            return self._values[name], self._specs.get(name, "")
        if self._parent is not None:
            return self._parent._stored(name)
        return None


@dataclass(frozen=True, slots=True)
class FormatField:
    # field_name is an identifier. field_spec has no <
    field_name: str
    index: int
    field_spec: str = ""

    @property
    def positional(self) -> bool:
        return not self.field_name or (self.field_name.isascii() and self.field_name.isdecimal())


@final
@dataclass(frozen=True, slots=True)
class ParsedCaptures:
    args: tuple[CaptureField, ...]
    kwargs: CaptureMap

    def chain(self, parent: CaptureMap | None) -> Self:
        if parent is None:
            return self
        # ParsedCaptures(...) is not Self. type(self) is
        return type(self)(self.args, self.kwargs.chain(parent))


class CompiledFormat:
    __slots__: Final = ("_fields", "_pattern", "_spec")
    _fields: tuple[FormatField, ...]
    _pattern: Open[FmtStr]
    _spec: Spec

    def __init__(self, pattern: Raw[FmtStr]) -> None:
        self._pattern, self._fields, self._spec = _compile_fmt_exn(pattern)  # declaration error

    @property
    def pattern(self) -> Open[FmtStr]:
        return self._pattern

    @property
    def fields(self) -> tuple[FormatField, ...]:
        return self._fields

    def format(self, *args: FmtFieldT, **kwargs: FmtFieldT) -> Raw[Name]:
        # Can't prove the contents of args/kwargs are safe, treat as Raw
        return Raw[Name](_FORMATTER.vformat(self.pattern, args, kwargs))

    def parse(self, basename: Safe[Name]) -> ParsedCaptures | None:
        """Exception: raises on unsupported type"""
        if not (parsed := self._spec.parse(basename)):
            return None
        return ParsedCaptures(parsed.args, CaptureMap(parsed.kwargs))


## Exported fns
# safe, safe_exn, close_exn convert anything (Raw, Open) -> Safe
# open_str, valid_fmt_exn convert anything -> Open or better


def compile_match(pattern: Raw[MatchPat]) -> re.Pattern[str]:
    return re.compile(pattern)


def safe(text: Raw[_K]) -> Safe[_K] | None:
    # Safe("") is this path. A falsy check would drop it
    if isinstance(text, Safe):
        return text
    if (resolved := text if isinstance(text, Resolved) else _resolve(text)) is None:
        return None
    return _safe(resolved)


def safe_exn(text: Raw[_K]) -> Safe[_K]:
    if (safe_text := safe(text)) is None:
        raise ValueError(em.Fmt.basename(text))
    return safe_text


def close_exn(text: Raw[_K], scope: CaptureMap | None) -> Safe[_K]:
    if isinstance(text, Safe):
        return text
    return safe_exn(_refs_resolve_exn(text, scope))


def open_str(text: Raw[_K]) -> Open[_K] | None:
    # Declaration text. A ref stays Open when the x stand-in is one component
    if REF.search(text):
        if _safe_ish(text) is None:
            return None
        return Open[_K](text)
    return safe(text)


def valid_fmt_exn(fmt: str | None) -> Open[FmtStr] | None:
    if not fmt:
        return None
    opened, _, _ = _compile_fmt_exn(Raw[FmtStr](fmt))  # declaration error
    return opened


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
    # Filesystem root is an anchor with no component. safe rejects ""
    if path.anchor and not path.name:
        return Safe[Name]("")
    return safe_exn(Raw[Name](path.name))


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


def _resolve(text: Raw[_K]) -> Resolved[_K] | None:
    # Safe is already both. A ref fails here, before /< becomes <
    if isinstance(text, Safe):
        return text
    if REF.search(text):
        return None
    closed = text.replace("/<", "<")
    if _bad_text(closed):
        return None
    return Resolved[_K](closed)


def _safe(text: Resolved[_K]) -> Safe[_K] | None:
    if isinstance(text, Safe):
        return text
    if not _is_path_item(text) or _bad_text(text):
        return None
    return Safe[_K](text)


def _compile_fmt_exn(pattern: Raw[FmtStr]) -> tuple[Open[FmtStr], tuple[FormatField, ...], Spec]:
    # Literal, field, and conversion checks, then Spec. This return is the compiled pattern
    fields = _format_fields_exn(pattern)  # field_name is an identifier. field_spec has no <
    spec = Spec(pattern)  # unsupported type
    if REF.search(pattern):
        return Open[FmtStr](pattern), fields, spec
    return safe_exn(pattern), fields, spec


# This extracts and validates all the fields in the pattern
def _format_fields_exn(pattern: Raw[FmtStr]) -> tuple[FormatField, ...]:
    # Formatter owns the brace grammar. These checks are the pieces it returns.
    fields: list[FormatField] = []
    for index, (literal, field_name, field_spec, conversion) in enumerate(_FORMATTER.parse(pattern)):
        # A slice may be empty or ".". safe is a whole component
        if _refs_as_x(Raw[None](literal)) is None:
            raise ValueError(em.Fmt.literal(pattern))
        if field_name is None:
            continue
        if conversion is not None:
            raise ValueError(em.Fmt.CONV)
        if "<" in (field_spec or ""):
            raise ValueError(em.Fmt.spec(field_spec or ""))
        if (field_name
            and not (field_name.isascii() and field_name.isdecimal())
            and not _FIELD_NAME.fullmatch(field_name)
        ):  # fmt: skip
            raise ValueError(em.Fmt.field(field_name))
        fields.append(FormatField(field_name, index, field_spec or ""))
    if not fields and _safe_ish(Raw[None](pattern)) is None:
        raise ValueError(em.Fmt.basename(pattern))
    return tuple(fields)


def _safe_ish(text: Raw[_K]) -> Safe[None] | None:
    if not (resolved := _refs_as_x(text)):
        return None
    return _safe(resolved)


def _refs_as_x(text: Raw[_K]) -> Resolved[None] | None:
    # Formatter.parse yields a str slice
    substituted = text if "<" not in text else REF.sub("x", text)
    return _resolve(Raw[None](substituted))


def _refs_resolve_exn(text: Raw[_K], scope: CaptureMap | None) -> Resolved[_K]:
    # Ancestor frame only. This node's own fields are not in scope yet

    def replace(match: re.Match[str]) -> str:
        field_name = match.group(1)
        if scope is None or field_name not in scope:
            raise ValueError(em.Schema.Body.unbound(field_name))
        return scope.render_exn(field_name, match.group(2))

    substituted = text if "<" not in text else REF.sub(replace, text)
    if not (resolved := _resolve(Raw[_K](substituted))):
        raise ValueError(em.Fmt.basename(substituted))
    return resolved
