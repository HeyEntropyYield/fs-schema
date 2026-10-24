import re
from typing import Final

from attrs import define

import fs_schema._errmsg as em

from ._fmt import REF, CaptureMap, CompiledFormat, ParsedCaptures, compile_match
from ._types import FieldSpecs, FmtFieldT, FmtStr, MatchPat, Name, Open, Raw, Safe

# Not a user field: positional reference indexing each repeated ref
_REPEAT: Final = "fss_ref_"


def _repeat_fields(pattern: Open[FmtStr]) -> tuple[Open[FmtStr], tuple[str, ...]]:
    # <n:spec> beside {n} becomes {fss_ref_0:spec}. Bare <n> keeps {n}'s spec. <parent> stays a ref
    specs = {field.field_name: field.field_spec for field in CompiledFormat(pattern).fields if not field.positional}

    if not specs or "<" not in pattern:
        return pattern, ()
    names: list[str] = []

    def repl(match: re.Match[str]) -> str:
        name, override = match.group(1), match.group(2)
        if name not in specs:  # if <ref> not in self {fields}
            return match.group(0)  # no change
        # note: don't pre-emptively fill <rep> and match, like parent matches
        # rewrite <rep> as {rep_n}, fmt capture {rep_n}, audit (captures) <rep_n> == {ref}
        token = _REPEAT + str(len(names))  # must go before names.append
        spec = specs[name] if override is None else override
        names.append(name)
        return "{" + token + ":" + spec + "}" if spec else "{" + token + "}"

    rewritten = REF.sub(repl, pattern)
    if not names:
        return pattern, ()
    return Open[FmtStr](rewritten), tuple(names)


@define(frozen=True, slots=True, init=False)
class Selector:
    """One declaration's compiled basename selector."""

    fmt: CompiledFormat | None
    match: re.Pattern[str] | None
    repeats: tuple[str, ...]

    def __init__(
        self,
        fmt: Open[FmtStr] | CompiledFormat | None,
        match: Raw[MatchPat] | re.Pattern[str] | None = None,
        repeats: tuple[str, ...] = (),
    ) -> None:
        if isinstance(fmt, Open):
            fmt, repeats = _repeat_fields(fmt)
            fmt = CompiledFormat(fmt)
        object.__setattr__(self, "fmt", fmt)
        if isinstance(match, Raw):
            match = compile_match(match)
        object.__setattr__(self, "match", match)
        object.__setattr__(self, "repeats", repeats)

    def captures(self, basename: Safe[Name]) -> ParsedCaptures | None:
        matched: re.Match[str] | None = None
        if self.match and (matched := self.match.fullmatch(basename)) is None:
            return None
        if self.fmt:
            if (parsed := self.fmt.parse(basename)) is None:
                return None
            values = dict(parsed.kwargs)
            for index, name in enumerate(self.repeats):
                key = _REPEAT + str(index)
                if (key not in values  # repeat's uniq id wasn't captured, mismatch
                    or name not in values  # original ref's id wasn't captured
                    or values.pop(key) != values[name]  # captures must be equal!
                ):  # fmt: skip
                    return None
            return ParsedCaptures(parsed.args, CaptureMap(values, self.field_specs()))
        if matched is None:
            return ParsedCaptures((), CaptureMap({}))
        named = set(matched.re.groupindex.values())
        return ParsedCaptures(
            tuple(value for index, value in enumerate(matched.groups(), 1) if index not in named),
            CaptureMap(matched.groupdict()),
        )

    def format(self, *args: FmtFieldT, **kwargs: FmtFieldT) -> Raw[Name]:
        """Exception: raises to support chaining"""
        if not self.fmt:
            raise TypeError(em.Fmt.NONE)
        if self.repeats:
            extra: dict[str, FmtFieldT] = {}
            for index, name in enumerate(self.repeats):
                if name not in kwargs:
                    raise KeyError(name)
                # mapped <rep> -> {rep_n}, let {rep_n} = {rep}
                extra[_REPEAT + str(index)] = kwargs[name]
            kwargs = {**kwargs, **extra}
        basename = self.fmt.format(*args, **kwargs)
        if self.match and self.match.fullmatch(basename) is None:
            raise ValueError(em.Fmt.pattern(self.match.pattern, basename))
        return basename

    def field_specs(self) -> FieldSpecs:
        if not self.fmt:
            return {}
        return {field.field_name: field.field_spec for field in self.fmt.fields if not field.positional
            and not field.field_name.startswith(_REPEAT)  # hide repeats
        }  # fmt: skip

    def capture_names(self) -> frozenset[str]:
        if self.fmt:
            return frozenset(field.field_name for field in self.fmt.fields if not field.positional
                and not field.field_name.startswith(_REPEAT)  # hide repeats
            )  # fmt: skip
        if self.match:
            return frozenset(self.match.groupindex)
        return frozenset()

    def match_failure(self, basename: Safe[Name]) -> str | None:
        if not self.fmt or not self.match or self.fmt.parse(basename) is None:
            return None
        if self.match.fullmatch(basename) is None:
            return self.match.pattern
        return None
