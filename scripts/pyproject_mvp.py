#!/usr/bin/env python3
"""Extract dependency-related pyproject tables for Docker layer caching.

Usage:
  pyproject_mvp.py [-i FILE] [-o FILE]

Options:
  -i FILE  Input TOML file, or - for stdin [default: ./pyproject.toml].
  -o FILE  Output TOML file, or - for stdout [default: -].
"""

import sys
from collections.abc import Mapping, Sequence
from pathlib import Path

import tomli
import tomli_w
from docopt import docopt
from typing_extensions import Protocol, runtime_checkable

KEEP = ("name", "version", "requires-python", "dependencies")


class PyprojectError(Exception):
    def __bool__(self) -> bool:
        return False


@runtime_checkable
class TextReader(Protocol):
    def read(self, n: int = -1, /) -> str: ...


@runtime_checkable
class TextWriter(Protocol):
    def write(self, s: str, /) -> int: ...


def _mapping(value: object) -> Mapping[str, object]:
    return value if isinstance(value, Mapping) else {}


def extract(config: Mapping[str, object]) -> dict[str, object]:
    project = _mapping(config.get("project"))
    tool = _mapping(config.get("tool"))
    return {
        "project": {key: project[key] for key in KEEP if key in project},
        "dependency-groups": dict(_mapping(config.get("dependency-groups"))),
        "build-system": dict(_mapping(config.get("build-system"))),
        "tool": {"uv": dict(_mapping(tool.get("uv")))},
    }


def main(
    argv: Sequence[str] = sys.argv,
    *,
    stdin: TextReader = sys.stdin,
    stdout: TextWriter = sys.stdout,
    stderr: TextWriter = sys.stderr,
) -> int:
    args = docopt(__doc__, argv=list(argv[1:] if argv is sys.argv else argv))
    src, dst = str(args["-i"]), str(args["-o"])
    try:
        raw = stdin.read() if src == "-" else Path(src).read_text(encoding="utf-8")
        out = tomli_w.dumps(extract(tomli.loads(raw)))
        if dst == "-":
            _ = stdout.write(out)
        else:
            Path(dst).write_text(out, encoding="utf-8")
    except Exception as error:
        print(f"error: {error}", file=stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
