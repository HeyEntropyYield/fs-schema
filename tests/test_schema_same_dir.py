from pathlib import Path

import pytest

import fs_schema as fss
from fs_schema._schema import DirDefn, File, Schema


class Notes(fss.Schema):
    schema = {
        "body": fss.File("body.txt"),
        "extra": fss.File("extra.txt", optional=True),
    }


class Metrics(fss.Schema):
    schema = {"score": fss.File("score.json")}


class Log(fss.Schema):
    schema = {"log": "log.txt"}


class Work(fss.Schema):
    schema = {
        fss.Dir(".", alias="notes"): Notes,
        fss.Dir(".", alias="metrics"): Metrics,
    }


class More(Work):
    schema = {fss.Dir(".", alias="log"): Log}


def test_alias_equal_to_normalized_name_is_one_child() -> None:
    class Same(Schema):
        schema = {fss.FILES: [File("a-b.txt", alias="a_b_txt")]}

    assert hasattr(Same, "a_b_txt")


def test_same_dir_requires_alias_and_rejects_match() -> None:
    with pytest.raises(TypeError, match=r"Dir\('\.'\) requires alias"):
        type("Bare", (fss.Schema,), {"schema": {fss.Dir("."): Notes}})
    with pytest.raises(ValueError, match="cannot take match"):
        fss.Dir(".", alias="notes", match=".*")


def test_same_dir_does_not_claim_underscore_name(tmp_path: Path) -> None:
    class Both(fss.Schema):
        schema = {
            fss.Dir(".", alias="notes"): Notes,
            fss.FILES: ["_"],
        }

    fss.put(tmp_path / "body.txt", "hi")
    fss.put(tmp_path / "_", "mark")
    bound = fss.raise_mismatch(Both.bind(tmp_path))
    assert type(bound.notes) is Notes
    assert bound.notes.path == tmp_path
    assert bound["_"].path == tmp_path / "_"


def test_same_dir_bind_create_and_subclass(tmp_path: Path) -> None:
    assert Work.notes is Notes
    fs = Work.relative_to(tmp_path)
    fs.create(notes={"body": "hi"}, metrics={"score": "{}"})
    bound = fss.raise_mismatch(fs.bind())
    assert type(bound) is Work
    assert type(bound.notes) is Notes
    assert bound.notes.path == bound.metrics.path == tmp_path
    assert (tmp_path / "body.txt").read_text() == "hi"

    missing = tmp_path / "empty"
    assert isinstance(Work.bind(missing), fss.MismatchErr)

    more = More.relative_to(tmp_path)
    more.create(log={"log": "ok"})
    bound_more = fss.raise_mismatch(more.bind())
    assert type(bound_more.log) is Log
    assert bound_more.log.path == tmp_path


def test_optional_same_dir_skips_a_mismatch(tmp_path: Path) -> None:
    class OptionalWork(fss.Schema):
        schema = {fss.Dir(".", alias="notes", optional=True): Notes}

    bare = fss.raise_mismatch(OptionalWork.bind(tmp_path))
    assert bare.notes is None
    fss.put(tmp_path / "body.txt", "hi")
    present = fss.raise_mismatch(OptionalWork.bind(tmp_path))
    assert type(present.notes) is Notes


def test_two_same_dirs_cannot_share_an_alias() -> None:
    with pytest.raises(TypeError, match="duplicate child key: 'notes'"):
        type(
            "Dup",
            (fss.Schema,),
            {"schema": {fss.Dir(".", alias="notes"): Notes, fss.Dir(".", alias="notes", optional=True): Metrics}},
        )


def test_dir_defn_same_dir_without_alias_raises() -> None:
    with pytest.raises(ValueError, match="requires alias"):
        DirDefn(fss.Dir("keep"), (DirDefn(fss.Dir(".")),))
