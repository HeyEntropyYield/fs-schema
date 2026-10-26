# pyright: reportAttributeAccessIssue=false, reportCallIssue=false
# pyright: reportIndexIssue=false, reportGeneralTypeIssues=false
# pyright: reportArgumentType=false, reportAssignmentType=false
# pyright: reportUnknownMemberType=false, reportUnknownVariableType=false
# pyright: reportUnknownArgumentType=false

"""A named class borrows <ts> from the dated directory that installs it."""

import tempfile
from datetime import datetime
from pathlib import Path

import fs_schema as fss


class Log(fss.Schema):
    capture_refs = True
    schema = {"body": "<ts>.log"}


class Day(fss.Schema):
    capture_refs = True
    schema = {"log": Log}


class Shelf(fss.Schema):
    schema = {fss.Dir(alias="days", fmt=fss.dt("%Y%m%d"), min=0): Day}


def main() -> None:
    when = datetime(1970, 1, 1)
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        day = Shelf.relative_to(root).days.format(ts=when)
        day.log.body.create("hello\n")
        print(Shelf.relative_to(root).days.parse(day.path.name).log.body.path.name)
        bound = fss.raise_mismatch(Shelf.bind(root))
        print(bound.days[0].log.body.read_text(), end="")
