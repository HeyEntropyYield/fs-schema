# Child access shapes. basedpyright checks this module; pytest does not call check().
# pyright: reportPrivateUsage=false
from pathlib import Path

from typing_extensions import assert_type

import fs_schema as fss
from fs_schema import _fmt, _schema


def check(box_path: Path) -> None:
    class Box(fss.Schema):
        schema = {
            "manifest": "manifest.json",
            "contents": fss.File("contents.json", optional=True),
            "images": fss.File(fmt="{stem}.png", min=0, max=1),
            "nested": {"note": fss.File("note.txt")},
        }

    class Sorted(fss.Schema):
        schema = {"parts": fss.File(
            fmt="part-{part:d}.parquet",
            min=0,
            sort=lambda m: m.kwargs["part"],
        )}  # fmt: skip

    box = Box.bind(box_path)
    if not isinstance(box, Box):
        return
    sorted_box = Sorted.bind(box_path)
    if not isinstance(sorted_box, Sorted):
        return

    assert_type(box.manifest, _schema._ChildView)
    assert_type(fss.exists_opt(box.manifest), Path | None)
    assert_type(fss.exists_opt(box.contents), Path | None)
    assert_type(fss.exists_opt(next(box.images, None)), Path | None)
    assert_type(fss.exists_opt(box.images.get()), Path | None)
    assert_type(box.images.format(stem="x").path, Path)
    assert_type(box.nested.note.path, Path)
    assert_type([item.name for item in box.images], list[str])
    assert_type(len(box.images), int)
    planned = Box.relative_to(box)
    assert_type(planned.images.format(stem="y").path, Path)
    assert_type(sorted_box.parts[-1].kwargs["part"], _fmt.CaptureField)
    assert_type(box.manifest.load(), object | Exception)

    if not (missing := Box.bind(box_path)):
        assert_type(missing, fss.MismatchErr)
    else:
        assert_type(missing, Box)

    class Note(fss.Schema):
        schema = {"body": "body.txt"}

    class Results(fss.Schema):
        schema = {fss.Dir(alias="runs", fmt="{n:d}", min=0): fss.xor(note=Note)}

    trained = Results.bind(box_path)
    if not isinstance(trained, Results):
        return
    notes = trained.runs.note
    assert_type(notes.get(-1), _schema._ChildView | None)
    assert_type(notes[0], _schema._ChildView)
    assert_type(len(notes), int)
