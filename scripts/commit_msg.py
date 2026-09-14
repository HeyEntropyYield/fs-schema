#!/usr/bin/env python3
"""Enforce one ASCII subject and release-version commit provenance.

Usage:
  commit_msg.py COMMIT_MSG_FILE
"""

import sys
from collections.abc import Callable, Sequence
from pathlib import Path

from docopt import docopt

from ._io import TextWriter, argv_tail
from .release import ReleaseError, check_commit

CommitChecker = Callable[[str], object]


def first_subject(content: str) -> str:
    for line in content.splitlines():
        candidate = line.strip()
        if not candidate or candidate.startswith("#") or candidate.lower().startswith("co-authored-by:"):
            continue
        return candidate
    return ""


def normalize_commit_message(path: Path, checker: CommitChecker) -> None:
    try:
        subject = first_subject(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError) as error:
        raise ReleaseError(str(error)) from error
    if not subject:
        raise ReleaseError("empty commit subject")
    if not subject.isascii():
        raise ReleaseError("commit subject must be ASCII")
    checked = checker(subject)
    if isinstance(checked, Exception):
        raise checked
    path.write_text(subject + "\n", encoding="ascii")


def main(
    argv: Sequence[str] = sys.argv,
    *,
    stderr: TextWriter = sys.stderr,
    checker: CommitChecker = check_commit,
) -> int:
    try:
        normalize_commit_message(
            Path(str(docopt(__doc__, argv=argv_tail(argv))["COMMIT_MSG_FILE"])),
            checker,
        )
    except Exception as error:
        print(f"error: {error}", file=stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
