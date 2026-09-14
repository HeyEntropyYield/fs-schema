#!/usr/bin/env python3
"""Reject malformed release tags before they are pushed.

Usage:
  pre_push.py
"""

import sys
from collections.abc import Callable, Iterable, Sequence
from typing import NamedTuple

from docopt import docopt

from ._io import TextWriter, argv_tail
from .release import ZERO_SHA, ReleaseError, check_range, check_tag

RangeChecker = Callable[[str, str], object]
TagChecker = Callable[..., object]


class PushUpdate(NamedTuple):
    local_ref: str
    local_sha: str
    remote_ref: str
    remote_sha: str


def parse_update(line: str) -> PushUpdate:
    fields = line.split()
    if len(fields) != 4:
        raise ReleaseError(f"want 4 fields, got {len(fields)}")
    return PushUpdate(*fields)


def check_updates(
    lines: Iterable[str],
    *,
    range_checker: RangeChecker,
    tag_checker: TagChecker,
) -> None:
    for line in lines:
        stripped = line.strip()
        if not stripped:
            continue
        update = parse_update(stripped)
        match update:
            case PushUpdate(local_sha=sha) if sha == ZERO_SHA:
                continue
            case PushUpdate(local_ref=ref) if ref.startswith("refs/tags/"):
                tag_checker(ref.removeprefix("refs/tags/"), ref=f"{ref}^{{commit}}")
            case PushUpdate(local_ref=ref, local_sha=local, remote_sha=remote) if ref.startswith("refs/heads/"):
                range_checker(remote, local)
            case _:
                continue


def main(
    argv: Sequence[str] = sys.argv,
    *,
    stdin: Iterable[str] = sys.stdin,
    stderr: TextWriter = sys.stderr,
    range_checker: RangeChecker = check_range,
    tag_checker: TagChecker = check_tag,
) -> int:
    _ = docopt(__doc__, argv=argv_tail(argv))
    try:
        check_updates(stdin, range_checker=range_checker, tag_checker=tag_checker)
    except Exception as error:
        print(f"error: {error}", file=stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
