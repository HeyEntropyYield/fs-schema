from dataclasses import dataclass
from pathlib import Path

from beartype import beartype

import fs_schema as fss


@dataclass
class Manifest:
    name: str


@beartype
def _read(node: fss.Loadable) -> Manifest | Exception:
    return node.load(Manifest)


def test_bound_file_is_loadable_and_a_directory_is_not(tmp_path: Path) -> None:
    class Layout(fss.Schema):
        schema = {
            "fixed": fss.File("manifest.json", schema=Manifest),
            fss.Dir("folder", alias="folder"): {"note": fss.File("note.txt", optional=True)},
        }

    (tmp_path / "folder").mkdir()
    root = Layout.relative_to(tmp_path)
    root.fixed.create(Manifest("fixed"))
    bound = fss.raise_mismatch(root.bind())
    assert isinstance(bound.fixed, fss.Loadable)
    assert not isinstance(bound.folder, fss.Loadable)
    assert _read(bound.fixed) == Manifest("fixed")
