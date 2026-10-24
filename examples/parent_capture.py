# pyright: reportAttributeAccessIssue=false, reportCallIssue=false
# pyright: reportIndexIssue=false, reportGeneralTypeIssues=false
# pyright: reportArgumentType=false, reportAssignmentType=false
# pyright: reportUnknownMemberType=false, reportUnknownVariableType=false
# pyright: reportUnknownArgumentType=false, reportReturnType=false

"""Write a run whose names reuse the run's timestamp, then read them back."""

import tempfile
from datetime import datetime
from pathlib import Path

import fs_schema as fss


class Roll(fss.Schema):
    schema = {
        fss.Dir(alias="runs", fmt="run_{ts:%Y%m%d}", min=0): {  # or fmt=fss.dt("run_%Y%m%d")
            "log": "<ts>.log",
            "parts": fss.File(fmt="<ts>_{n:d}_<n:02d>.txt", min=0),  # <n:02d> is this file's n again
            fss.Dir(alias="extra", fmt="x_{n:d}_<ts>", min=0): {"body": "<ts>_<n>.txt"},
        }
    }


def write_run(root: Path, when: datetime, note: str, part: bytes) -> None:
    # parts repeats n as 1 and 01. extra's {n} is its own, and <ts> is the run
    run = Roll.relative_to(root).runs.format(ts=when)
    run.create(log=note, parts=[({"n": 1}, part)], extra=[({"n": 2}, {"body": "inside\n"})])


def read_run(root: Path) -> tuple[str, int, str, datetime, str]:
    # Bind: the log's ts is the run's ts. The part's two n's are one value. extra's body sees both
    run = fss.raise_mismatch(Roll.bind(root)).runs[0]
    extra = run.extra[0]
    part = run.parts[0]
    return run.log.read_text(), part.kwargs["n"], part.path.name, run.kwargs["ts"], extra.body.path.name


def main() -> None:
    when = datetime(1970, 1, 1)
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        write_run(root, when, "hello\n", b"part\n")
        note, number, part, stamp, body = read_run(root)
        print(note, end="")
        print(number)
        print(part)
        print(stamp.strftime("%Y%m%d"))
        print(body)
