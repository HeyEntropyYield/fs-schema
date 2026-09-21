# pyright: reportAttributeAccessIssue=false, reportCallIssue=false
# pyright: reportIndexIssue=false, reportGeneralTypeIssues=false
# pyright: reportArgumentType=false, reportAssignmentType=false
# pyright: reportUnknownMemberType=false, reportUnknownVariableType=false
# pyright: reportUnknownArgumentType=false

"""Public-API smoke used by scripts/release.py after a clean install."""

import tempfile
from pathlib import Path

import fs_schema as fss


class Box(fss.Schema):
    schema = {
        "required": "required.txt",
        "items": fss.File(fmt="item-{number:d}.txt", min=0),
    }


def main() -> None:
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        fss.put(root / "required.txt", "required")
        fss.put(root / "item-2.txt", "item")
        bound = fss.raise_mismatch(Box.bind(root))
        assert bound.required.read_text() == "required"
        assert bound.items[0].kwargs.number == 2
        fs = Box.relative_to(root / "new")
        fs.items.format(number=3).create("planned")
        assert (root / "new" / "item-3.txt").read_text() == "planned"
    print(fss.__version__)


if __name__ == "__main__":
    main()
