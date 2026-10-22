import re
from typing import Final

import fs_schema._errmsg as em

from ._fmt import CaptureMap, CompiledFormat, ParsedCaptures, compile_match
from ._types import FmtFieldT, FmtStr, MatchPat, Name, Raw, Safe


class Selector:
    """One declaration's compiled basename selector."""

    __slots__: Final = ("_fmt", "_match")
    _fmt: CompiledFormat | None
    _match: re.Pattern[str] | None

    def __init__(self, fmt: Safe[FmtStr] | None, match: Raw[MatchPat] | None) -> None:
        self._fmt = CompiledFormat(fmt) if fmt else None
        self._match = compile_match(match) if match else None

    def captures(self, basename: Safe[Name]) -> ParsedCaptures | None:
        if self._fmt:
            if (captures := self._fmt.parse(basename)) is None:
                return None
            return captures if not self._match or self._match.fullmatch(basename) else None
        if not self._match:
            return ParsedCaptures((), CaptureMap({}))
        if (matched := self._match.fullmatch(basename)) is None:
            return None
        named = set(matched.re.groupindex.values())
        return ParsedCaptures(
            tuple(value for index, value in enumerate(matched.groups(), 1) if index not in named),
            CaptureMap(matched.groupdict()),
        )

    def format(self, *args: FmtFieldT, **kwargs: FmtFieldT) -> Raw[Name]:
        """Exception: raises to support chaining"""
        if not self._fmt:
            raise TypeError(em.Fmt.NONE)
        basename = self._fmt.format(*args, **kwargs)
        if self._match and self._match.fullmatch(basename) is None:
            raise ValueError(em.Fmt.pattern(self._match.pattern, basename))
        return basename

    def capture_names(self) -> frozenset[str]:
        if self._fmt:
            return frozenset(field.field_name for field in self._fmt.fields if not field.positional)
        if self._match:
            return frozenset(self._match.groupindex)
        return frozenset()

    def match_failure(self, basename: Safe[Name]) -> str | None:
        if not self._fmt or not self._match or self._fmt.parse(basename) is None:
            return None
        if self._match.fullmatch(basename) is None:
            return self._match.pattern
        return None
