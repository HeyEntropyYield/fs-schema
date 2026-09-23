# pyright: reportAttributeAccessIssue=false, reportUnknownMemberType=false
# pyright: reportUnknownVariableType=false, reportUnknownArgumentType=false
# pyright: reportAssignmentType=false, reportAny=false
import json
from datetime import datetime
from pathlib import Path

from glom import Coalesce, T, glom

import fs_schema as fss


def load_note(path: Path) -> dict[str, object]:
    return json.loads(path.read_text())


class Day(fss.Schema):
    schema = {
        "body": fss.File("body.txt"),
        "note": fss.File("note.json", schema=load_note, optional=True),
    }


class Shelf(fss.Schema):
    schema = {fss.Dir(alias="days", fmt="{day:%Y-%m-%d}", min=0): Day}


class Library(fss.Schema):
    schema = {"shelf": Shelf}


def latest_body(bound: Library) -> Path | None:
    # Fixed dir, formatted template dir, last member, fixed file.
    return glom(bound, T.shelf.days[-1].body.path, default=None)


def latest_title(bound: Library) -> object:
    # Same chain, then an optional file and its loader. Missing note -> None.
    return glom(bound, Coalesce((T.shelf.days[-1].note.load(), "title"), default=None))


def body_on(bound: Library, day: datetime) -> Path | None:
    # Same chain, filtering days by kwarg datetime
    return glom(bound, T.shelf.days.where(day=day)[0].body.path, default=None)
