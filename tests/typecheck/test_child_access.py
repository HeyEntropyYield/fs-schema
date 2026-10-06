# DA child-access shapes. basedpyright checks this module; pytest does not call check().
# pyright: reportPrivateUsage=false
from pathlib import Path

from typing_extensions import assert_type

import fs_schema as fss
from fs_schema import _fmt, _schema


def check(box_path: Path) -> None:
    class Box(fss.Schema):
        schema = {
            "end2end": "end2end.onnx",
            "jetson": fss.File("end2end_jetson.onnx", optional=True),
            "bins": fss.File(fmt="bin_{slug}.bin", min=0, max=1),
            "nested": {"train": fss.File("train.json")},
        }

    class Sorted(fss.Schema):
        schema = {
            "best": fss.File(
                fmt="best_{epoch:d}.pth",
                min=0,
                sort=lambda m: m.kwargs["epoch"],
            ),
        }

    box = Box.bind(box_path)
    if not isinstance(box, Box):
        return
    sorted_box = Sorted.bind(box_path)
    if not isinstance(sorted_box, Sorted):
        return

    assert_type(box.end2end, _schema._ChildView)
    assert_type(fss.exists_opt(box.end2end), Path | None)
    assert_type(fss.exists_opt(box.jetson), Path | None)
    assert_type(fss.exists_opt(next(box.bins, None)), Path | None)
    assert_type(fss.exists_opt(box.bins.get()), Path | None)
    assert_type(box.bins.format(slug="x").path, Path)
    assert_type(box.nested.train.path, Path)
    assert_type([item.name for item in box.bins], list[str])
    assert_type(len(box.bins), int)
    planned = Box.relative_to(box)
    assert_type(planned.bins.format(slug="y").path, Path)
    assert_type(sorted_box.best[-1].kwargs["epoch"], _fmt.CaptureField)
    assert_type(box.end2end.load(), object | Exception)

    if not (missing := Box.bind(box_path)):
        assert_type(missing, fss.MismatchErr)
    else:
        assert_type(missing, Box)
