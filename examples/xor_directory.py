# pyright: reportAttributeAccessIssue=false, reportCallIssue=false
# pyright: reportIndexIssue=false, reportGeneralTypeIssues=false
# pyright: reportArgumentType=false, reportAssignmentType=false
# pyright: reportUnknownMemberType=false, reportUnknownVariableType=false
# pyright: reportUnknownArgumentType=false

"""Write one branch of a directory, then read whichever branch bound."""

import tempfile
from pathlib import Path

import fs_schema as fss


class Letter(fss.Schema):
    schema = {"body": "body.txt"}


class Table(fss.Schema):
    schema = {"rows": "rows.json"}


class Box(fss.Schema):
    schema = {"slot": fss.xor(letter=Letter, table=Table)}


class Open(fss.Schema):
    schema = {"slot": fss.xor(Letter, Table)}


def write_open(root: Path, body: str) -> str:
    # Unnamed: body and rows sit on slot. The union itself cannot create.
    planned = Open.relative_to(root)
    planned.slot.body.create(body)
    bound = fss.raise_mismatch(planned.bind())
    return bound.slot.body.read_text()


def write_letter(root: Path, body: str) -> None:
    # Plan: every branch is still here. create() on the union itself raises.
    Box.relative_to(root).slot.letter.create(body=body)


def write_table(root: Path, rows: str) -> None:
    Box.relative_to(root).slot["table"].create(rows=rows)


def read_slot(root: Path) -> str:
    # Bind: slot is the winning schema. The branch name is gone.
    box = fss.raise_mismatch(Box.bind(root))
    if isinstance(box.slot, Letter):
        return box.slot.body.read_text()
    return box.slot.rows.read_text()


def main() -> None:
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        print(write_open(root / "open", "hello\n"), end="")
        write_letter(root / "note", "hello\n")
        print(read_slot(root / "note"), end="")
        write_table(root / "sheet", "{}\n")
        print(read_slot(root / "sheet"), end="")
