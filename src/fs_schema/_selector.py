import re

from attrs import define

import fs_schema._errmsg as em

from ._fmt import CaptureMap, CompiledFormat, ParsedCaptures, compile_match
from ._types import FieldSpecs, FmtFieldT, FmtStr, MatchPat, Name, Open, Raw, Safe


@define(frozen=True, slots=True, init=False)
class Selector:
    """One declaration's compiled basename selector."""

    fmt: CompiledFormat | None
    match: re.Pattern[str] | None

    def __init__(
        self,
        fmt: Open[FmtStr] | CompiledFormat | None,
        match: Raw[MatchPat] | re.Pattern[str] | None = None,
    ) -> None:
        if isinstance(fmt, Open):
            fmt = CompiledFormat(fmt)
        object.__setattr__(self, "fmt", fmt)
        if isinstance(match, Raw):
            match = compile_match(match)
        object.__setattr__(self, "match", match)

    def captures(self, basename: Safe[Name]) -> ParsedCaptures | None:
        if self.fmt:
            if (parsed := self.fmt.parse(basename)) is None:
                return None
            if self.match and self.match.fullmatch(basename) is None:
                return None
            return ParsedCaptures(parsed.args, CaptureMap(dict(parsed.kwargs), self.field_specs()))
        if not self.match:
            return ParsedCaptures((), CaptureMap({}))
        if (matched := self.match.fullmatch(basename)) is None:
            return None
        named = set(matched.re.groupindex.values())
        return ParsedCaptures(
            tuple(value for index, value in enumerate(matched.groups(), 1) if index not in named),
            CaptureMap(matched.groupdict()),
        )

    def format(self, *args: FmtFieldT, **kwargs: FmtFieldT) -> Raw[Name]:
        """Exception: raises to support chaining"""
        if not self.fmt:
            raise TypeError(em.Fmt.NONE)
        basename = self.fmt.format(*args, **kwargs)
        if self.match and self.match.fullmatch(basename) is None:
            raise ValueError(em.Fmt.pattern(self.match.pattern, basename))
        return basename

    def field_specs(self) -> FieldSpecs:
        if not self.fmt:
            return {}
        return {field.field_name: field.field_spec for field in self.fmt.fields if not field.positional}

    def capture_names(self) -> frozenset[str]:
        if self.fmt:
            return frozenset(field.field_name for field in self.fmt.fields if not field.positional)
        if self.match:
            return frozenset(self.match.groupindex)
        return frozenset()

    def match_failure(self, basename: Safe[Name]) -> str | None:
        if not self.fmt or not self.match or self.fmt.parse(basename) is None:
            return None
        if self.match.fullmatch(basename) is None:
            return self.match.pattern
        return None
