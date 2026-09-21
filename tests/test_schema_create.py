# pyright: reportPrivateUsage=false, reportUnknownMemberType=false
# pyright: reportUnknownArgumentType=false, reportUnknownVariableType=false
# pyright: reportAttributeAccessIssue=false, reportCallIssue=false
# pyright: reportArgumentType=false, reportAssignmentType=false
# pyright: reportOptionalMemberAccess=false, reportIndexIssue=false
from datetime import datetime
from pathlib import Path

import pytest
from beartype.roar import BeartypeCallHintParamViolation
from plum import NotFoundLookupError

from fs_schema import Dir, File, Schema


class Batch(Schema):
    schema = {"parts": File(fmt="part-{part:d}.jsonl")}


class Notes(Schema):
    schema = {"readme": "README.md"}


class Delivery(Schema):
    schema = {
        "manifest": "manifest.json",
        "receipt": File("receipt.json", optional=True),
        Dir("notes", optional=True): Notes,
        Dir(alias="days", fmt="{day:%Y-%m-%d}", min=0): Batch,
    }


class Export(Schema):
    schema = {"jetson": File(fmt="end2end_jetson.onnx", min=0, max=1)}


def test_create_then_bind_omits_unwritten_optionals(tmp_path: Path) -> None:
    bound = Delivery.relative_to(tmp_path).create(manifest="{}").bind()
    assert type(bound) is Delivery
    assert bound.receipt is None and bound.notes is None
    assert bound.manifest.read_text() == "{}"


def test_create_writes_exact_children_and_one_formatted_member(tmp_path: Path) -> None:
    fs = Delivery.relative_to(tmp_path)
    fs.create(manifest="{}", receipt="{}", notes={"readme": "ok"})
    day = fs.days.format(day=datetime(2026, 9, 17))
    _ = day.create().parts.format(part=1).create("a")
    bound = fs.bind()
    assert type(bound) is Delivery
    assert bound.receipt is not None and bound.receipt.read_text() == "{}"
    assert bound.notes is not None and bound.notes.readme.read_text() == "ok"
    assert bound.days[0].parts[0].read_text() == "a"


def test_create_without_data_touches_a_file(tmp_path: Path) -> None:
    fs = Delivery.relative_to(tmp_path)
    fs.manifest.create()
    assert fs.manifest.read_bytes() == b""


def test_bound_schema_create_requires_root(tmp_path: Path) -> None:
    bound = Delivery.relative_to(tmp_path).create(manifest="{}").bind()
    assert type(bound) is Delivery
    with pytest.raises(TypeError, match="use root"):
        bound.create()
    bound.root().receipt.create("{}")
    rebound = Delivery.bind(bound)
    assert type(rebound) is Delivery and rebound.receipt is not None
    assert rebound.receipt.read_text() == "{}"


def test_create_rejects_unknown_collection_and_duplicate_keys(tmp_path: Path) -> None:
    fs = Delivery.relative_to(tmp_path)
    with pytest.raises(KeyError, match="unknown create key"):
        fs.create(missing="x")
    with pytest.raises(ValueError, match="does not match"):
        fs.create(days={"nope": {}})
    with pytest.raises(TypeError, match="duplicate create keys"):
        fs.create({"manifest": "{}"}, manifest="{}")
    with pytest.raises(NotFoundLookupError):
        fs.create(manifest={"nope": 1})
    with pytest.raises(BeartypeCallHintParamViolation):
        fs.create(manifest=1)


def test_none_omits_an_optional(tmp_path: Path) -> None:
    bound = Delivery.relative_to(tmp_path).create(manifest="{}", receipt=None).bind()
    assert type(bound) is Delivery and bound.receipt is None


def test_captureless_collection_create_returns_the_file(tmp_path: Path) -> None:
    fs = Export.relative_to(tmp_path)
    _ = fs.jetson.format().create(b"onnx")
    bare = Export.relative_to(tmp_path / "bare")
    bare.create(jetson=b"onnx")
    bound = fs.bind()
    assert type(bound) is Export
    assert bound.jetson[0].read_bytes() == b"onnx"
    assert (tmp_path / "bare" / "end2end_jetson.onnx").read_bytes() == b"onnx"


class _Inner(Schema):
    schema = {"leaf": "leaf.txt"}


class _Bucket(Schema):
    schema = {"inner": _Inner}


class _Tree(Schema):
    schema = {"bucket": _Bucket, Dir("skip", optional=True): {}}


class _Pics(Schema):
    schema = {"images": File(fmt="{stem}.{ext}", match=r".+\.png")}


def test_create_mkdirs_required_directories_only(tmp_path: Path) -> None:
    _Tree.relative_to(tmp_path).create()
    assert (tmp_path / "bucket" / "inner").is_dir()
    assert not (tmp_path / "bucket" / "inner" / "leaf.txt").exists()
    assert not (tmp_path / "skip").exists()
    bare = tmp_path / "omitted"
    _Tree.relative_to(bare).create(bucket=None)
    assert bare.is_dir() and not (bare / "bucket").exists()


def test_create_fills_collections_from_pairs_and_basenames(tmp_path: Path) -> None:
    when = datetime(2026, 9, 17)
    bound = (
        Delivery
        .relative_to(tmp_path)
        .create(
            manifest="{}",
            days=[({"day": when}, {"parts": [({"part": 1}, "a")]})],
        )
        .bind()
    )
    assert type(bound) is Delivery
    assert bound.days[0].parts[0].read_text() == "a"
    with pytest.raises(BeartypeCallHintParamViolation):
        Delivery.relative_to(tmp_path).create(days=[{"day": when}])
    with pytest.raises(TypeError, match="is a collection"):
        Delivery.relative_to(tmp_path).create(days=tmp_path)

    pics = _Pics.relative_to(tmp_path / "pics")
    pics.create(images={"a.png": b"img"})
    assert (tmp_path / "pics" / "a.png").read_bytes() == b"img"
    with pytest.raises(ValueError, match="does not match"):
        pics.images.parse("nope")
    _ = pics.images.parse("b.png").create(b"z")
    assert (tmp_path / "pics" / "b.png").read_bytes() == b"z"


class _Shelf(Schema):
    schema = {
        Dir(alias="days", fmt="{day:%Y-%m-%d}", min=0): {
            "note": File(fmt="{day:%Y-%m-%d}.txt", min=0),
            "extra": {
                "readme": File("README.txt", optional=True),
                "body": File(fmt="{day:%Y-%m-%d}.txt"),
            },
        },
        "ranked": File(fmt="{label}_{n:d}.txt", min=0),
    }


class _Groups(Schema):
    schema = {Dir(alias="groups", fmt="n-{n:d}", min=0): {"files": File(fmt="{label}-{n:d}.txt")}}


def test_stamped_file_collections_take_a_body(tmp_path: Path) -> None:
    when = datetime(2026, 9, 17)
    row = "row\n"
    bound = (
        _Shelf
        .relative_to(tmp_path)
        .create(
            days=[({"day": when}, {"note": row, "extra": {"readme": "#\n", "body": row}})],
            ranked=[({"label": "alpha", "n": 1}, b"rank")],
        )
        .bind()
    )
    assert type(bound) is _Shelf
    assert bound.days[0].note[0].read_text() == row
    assert bound.days[0].extra.readme is not None
    assert bound.days[0].extra.body[0].read_text() == row
    assert bound.ranked[0].read_bytes() == b"rank"

    planned = _Shelf.relative_to(tmp_path / "again")
    planned.days.format(day=when).create(extra={"body": row})
    assert (tmp_path / "again" / "2026-09-17" / "extra" / "2026-09-17.txt").read_text() == row

    with pytest.raises(ValueError, match="disagrees"):
        _Shelf.relative_to(tmp_path / "clash").create(
            days=[({"day": when}, {"note": [({"day": datetime(2026, 9, 18)}, row)]})]
        )
    with pytest.raises(TypeError, match="label"):
        _Groups.relative_to(tmp_path / "partial").create(groups=[({"n": 1}, {"files": b"rank"})])
    with pytest.raises(ValueError, match="filenames"):
        _Shelf.relative_to(tmp_path / "names").create(days={"day": {}})


def test_stamp_failure_modes(tmp_path: Path) -> None:
    when = datetime(2026, 9, 17)
    later = datetime(2026, 9, 18)
    row = "row\n"

    same = _Shelf.relative_to(tmp_path / "same")
    same.create(days=[({"day": when}, {"note": [({"day": when}, row)]})])
    assert (tmp_path / "same" / "2026-09-17" / "2026-09-17.txt").read_text() == row

    with pytest.raises(ValueError, match="disagrees with the enclosing stamp"):
        _Shelf.relative_to(tmp_path / "clash").create(days=[({"day": when}, {"note": [({"day": later}, row)]})])

    with pytest.raises(TypeError, match=r"missing captures \['label', 'n'\]"):
        _Shelf.relative_to(tmp_path / "open").create(ranked=b"rank")

    with pytest.raises(TypeError, match=r"missing captures \['label'\]; already stamped \['n'\]"):
        _Groups.relative_to(tmp_path / "partial").create(groups=[({"n": 1}, {"files": b"rank"})])

    with pytest.raises(ValueError, match="filenames, not captures"):
        _Shelf.relative_to(tmp_path / "names").create(days={"day": {}})

    for body in ("nope", b"nope", tmp_path):
        with pytest.raises(TypeError, match="is a collection"):
            _Shelf.relative_to(tmp_path / "plain").create(days=body)
