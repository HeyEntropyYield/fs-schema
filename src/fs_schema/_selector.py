import re
from typing import Final

from ._fmt import CaptureMap, CompiledFormat, FmtField, FmtLike, ParsedCaptures


class Selector:
    """One declaration's compiled basename selector."""

    __slots__: Final = ("_fmt", "_match")
    _fmt: CompiledFormat | None
    _match: re.Pattern[str] | None

    def __init__(self, fmt: FmtLike | None, match: str | None) -> None:
        self._fmt = CompiledFormat(fmt) if fmt is not None else None
        self._match = re.compile(match) if match is not None else None

    def captures(self, basename: str) -> ParsedCaptures | None:
        if self._fmt is not None:
            if (captures := self._fmt.parse(basename)) is None:
                return None
            return captures if self._match is None or self._match.fullmatch(basename) else None
        if self._match is None:
            return ParsedCaptures((), CaptureMap({}))
        if (matched := self._match.fullmatch(basename)) is None:
            return None
        named = set(matched.re.groupindex.values())
        return ParsedCaptures(
            tuple(value for index, value in enumerate(matched.groups(), 1) if index not in named),
            CaptureMap(matched.groupdict()),
        )

    def format(self, *args: FmtField, **kwargs: FmtField) -> str:
        if self._fmt is None:
            raise TypeError("declaration has no formatter")
        basename = self._fmt.format(*args, **kwargs)
        if self._match is not None and self._match.fullmatch(basename) is None:
            raise ValueError(f"formatted basename does not match {self._match.pattern!r}: {basename!r}")
        return basename

    def capture_names(self) -> frozenset[str]:
        if self._fmt is not None:
            return frozenset(field.name for field in self._fmt.fields if not field.positional)
        if self._match is not None:
            return frozenset(self._match.groupindex)
        return frozenset()

    def match_failure(self, basename: str) -> str | None:
        if self._fmt is None or self._match is None or self._fmt.parse(basename) is None:
            return None
        if self._match.fullmatch(basename) is None:
            return self._match.pattern
        return None
