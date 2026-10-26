from pathlib import Path

import pytest

import fs_schema as fss
from fs_schema._schema import DirDefn, File, Schema


class Letter(fss.Schema):
    schema = {
        "body": fss.File("body.txt"),
        "extra": fss.File("extra.txt", optional=True),
    }


class Table(fss.Schema):
    schema = {"rows": fss.File("rows.json")}


class Log(fss.Schema):
    schema = {"log": "download.log"}


class Bundle(fss.Schema):
    schema = {
        fss.Dir(".", alias="letter"): Letter,
        fss.Dir(".", alias="table"): Table,
    }


class More(Bundle):
    schema = {fss.Dir(".", alias="log"): Log}


def test_alias_equal_to_normalized_name_is_one_child() -> None:
    class Same(Schema):
        schema = {fss.FILES: [File("a-b.txt", alias="a_b_txt")]}

    assert hasattr(Same, "a_b_txt")


def test_same_dir_requires_alias_and_rejects_match() -> None:
    with pytest.raises(TypeError, match=r"Dir\('\.'\) requires alias"):
        type("Bare", (fss.Schema,), {"schema": {fss.Dir("."): Letter}})
    with pytest.raises(ValueError, match="cannot take match"):
        fss.Dir(".", alias="letter", match=".*")


def test_same_dir_does_not_claim_underscore_name(tmp_path: Path) -> None:
    class Both(fss.Schema):
        schema = {
            fss.Dir(".", alias="letter"): Letter,
            fss.FILES: ["_"],
        }

    fss.put(tmp_path / "body.txt", "hi")
    fss.put(tmp_path / "_", "mark")
    bound = fss.raise_mismatch(Both.bind(tmp_path))
    assert type(bound.letter) is Letter
    assert bound.letter.path == tmp_path
    assert bound["_"].path == tmp_path / "_"


def test_same_dir_bind_create_and_subclass(tmp_path: Path) -> None:
    assert Bundle.letter is Letter
    fs = Bundle.relative_to(tmp_path)
    fs.create(letter={"body": "hi"}, table={"rows": "{}"})
    bound = fss.raise_mismatch(fs.bind())
    assert type(bound) is Bundle
    assert type(bound.letter) is Letter
    assert bound.letter.path == bound.table.path == tmp_path
    assert (tmp_path / "body.txt").read_text() == "hi"

    missing = tmp_path / "empty"
    assert isinstance(Bundle.bind(missing), fss.MismatchErr)

    more = More.relative_to(tmp_path)
    more.create(log={"log": "ok"})
    bound_more = fss.raise_mismatch(more.bind())
    assert type(bound_more.log) is Log
    assert bound_more.log.path == tmp_path


def test_optional_same_dir_skips_a_mismatch(tmp_path: Path) -> None:
    class OptionalBundle(fss.Schema):
        schema = {fss.Dir(".", alias="letter", optional=True): Letter}

    bare = fss.raise_mismatch(OptionalBundle.bind(tmp_path))
    assert bare.letter is None
    fss.put(tmp_path / "body.txt", "hi")
    present = fss.raise_mismatch(OptionalBundle.bind(tmp_path))
    assert type(present.letter) is Letter


def test_two_same_dirs_cannot_share_an_alias() -> None:
    with pytest.raises(TypeError, match="duplicate child key: 'notes'"):
        type(
            "Dup",
            (fss.Schema,),
            {"schema": {fss.Dir(".", alias="letter"): Letter, fss.Dir(".", alias="letter", optional=True): Table}},
        )


def test_dir_defn_same_dir_without_alias_raises() -> None:
    with pytest.raises(ValueError, match="requires alias"):
        DirDefn(fss.Dir("keep"), (DirDefn(fss.Dir(".")),))
