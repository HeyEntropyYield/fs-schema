# pyright: reportPrivateUsage=false, reportUnknownMemberType=false, reportUnknownArgumentType=false
# pyright: reportAttributeAccessIssue=false, reportIndexIssue=false, reportUnknownVariableType=false
"""A named class takes <refs> from the container that installs it"""

import re
from datetime import datetime
from pathlib import Path

import pytest

from fs_schema import Dir, Schema, dt, raise_mismatch
from fs_schema import _errmsg as em

WHEN = datetime(1970, 1, 1)
STAMP = "19700101"


class Log(Schema):
    capture_refs = True
    schema = {"body": "<ts>.log"}


class Roll(Schema):
    schema = {Dir(alias="runs", fmt=dt("%Y%m%d"), min=0): Log}


class Day(Schema):
    capture_refs = True
    schema = {"log": Log}


class Shelf(Schema):
    schema = {Dir(alias="days", fmt=dt("%Y%m%d"), min=0): Day}


def test_named_class_without_the_flag_still_fails_at_its_class_statement() -> None:
    detail = em.Schema.Body.decl("body", em.Schema.Body.unbound("ts"))
    with pytest.raises(TypeError, match=re.escape(em.Schema.text("Bare", detail))):

        class Bare(Schema):  # pyright: ignore[reportUnusedClass]
            schema = {"body": "<ts>.log"}


def test_container_without_the_ref_fails_at_its_class_statement() -> None:
    with pytest.raises(TypeError, match=re.escape(em.Schema.Body.unbound("ts"))):

        class Missing(Schema):  # pyright: ignore[reportUnusedClass]
            schema = {"kept": Log}


def test_sibling_field_does_not_satisfy_the_ref() -> None:
    with pytest.raises(TypeError, match=re.escape(em.Schema.Body.unbound("ts"))):

        class Beside(Schema):  # pyright: ignore[reportUnusedClass]
            schema = {
                Dir(alias="runs", fmt=dt("%Y%m%d"), min=0): {},
                "kept": Log,
            }


def test_ref_spec_must_match_the_container_field() -> None:
    class IntLog(Schema):
        capture_refs = True
        schema = {"body": "<ts:d>.log"}

    with pytest.raises(TypeError, match=re.escape(em.Schema.Body.spec("ts"))):

        class BadSpec(Schema):  # pyright: ignore[reportUnusedClass]
            schema = {Dir(alias="runs", fmt=dt("%Y%m%d"), min=0): IntLog}


def test_dropping_the_flag_on_an_empty_schema_compiles() -> None:
    class Open(Schema):
        capture_refs = True

    class Shut(Open):
        capture_refs = False

    assert Shut._schema_defn.defns == ()


def test_subclass_that_drops_the_flag_is_checked_against_its_own_scope() -> None:
    with pytest.raises(TypeError, match=re.escape(em.Schema.Body.unbound("ts"))):

        class Closed(Log):  # pyright: ignore[reportUnusedClass]
            capture_refs = False


def test_format_and_parse_use_the_container_capture(tmp_path: Path) -> None:
    planned = Roll.relative_to(tmp_path).runs.format(ts=WHEN)
    assert planned.body.path.name == f"{STAMP}.log"
    planned.body.create("z\n")
    assert (tmp_path / STAMP / f"{STAMP}.log").read_text() == "z\n"

    (tmp_path / "parsed" / STAMP).mkdir(parents=True)
    parsed = Roll.relative_to(tmp_path / "parsed").runs.parse(tmp_path / "parsed" / STAMP)
    assert parsed.body.path.name == f"{STAMP}.log"


def test_bind_reads_the_capture_from_the_directory_name(tmp_path: Path) -> None:
    day = tmp_path / STAMP
    day.mkdir()
    (day / f"{STAMP}.log").write_text("x\n")
    bound = raise_mismatch(Roll.bind(tmp_path))
    assert bound.runs[0].body.read_text() == "x\n"
    assert bound.runs[0].body.path.name == f"{STAMP}.log"


def test_middle_schema_passes_the_ref_to_its_container(tmp_path: Path) -> None:
    planned = Shelf.relative_to(tmp_path).days.format(ts=WHEN).log
    assert planned.body.path.name == f"{STAMP}.log"
    planned.body.create("y\n")
    assert (tmp_path / STAMP / "log" / f"{STAMP}.log").read_text() == "y\n"

    slot = tmp_path / "live" / STAMP / "log"
    slot.mkdir(parents=True)
    (slot / f"{STAMP}.log").write_text("q\n")
    bound = raise_mismatch(Shelf.bind(tmp_path / "live"))
    assert bound.days[0].log.body.read_text() == "q\n"


def test_subclass_keeps_the_flag(tmp_path: Path) -> None:
    class More(Log):
        schema = {"note": "note.txt"}

    class Held(Schema):
        schema = {Dir(alias="runs", fmt=dt("%Y%m%d"), min=0): More}

    planned = Held.relative_to(tmp_path).runs.format(ts=WHEN)
    assert planned.body.path.name == f"{STAMP}.log"
    assert planned.note.path.name == "note.txt"


def test_each_schema_keeps_its_own_unbound_refs() -> None:
    assert Log._unbound_refs == {"ts": None}
    assert Day._unbound_refs == {"ts": None}
    assert Roll._unbound_refs == {}
    assert Shelf._unbound_refs == {}

    class Open(Schema):
        capture_refs = True

    assert Open._unbound_refs == {}
    assert Open._unbound_refs is not Log._unbound_refs


def test_same_node_spec_still_fails_when_the_schema_captures() -> None:
    with pytest.raises(TypeError, match=re.escape(em.Schema.Body.spec("ts"))):

        class Mixed(Schema):  # pyright: ignore[reportUnusedClass]
            capture_refs = True
            schema = {Dir(alias="rows", fmt="{ts}_<ts:d>", min=0): {}}


def test_explicit_empty_spec_must_match_the_container_field() -> None:
    class TextLog(Schema):
        capture_refs = True
        schema = {"body": "<ts:>.log"}

    assert TextLog._unbound_refs == {"ts": ""}
    with pytest.raises(TypeError, match=re.escape(em.Schema.Body.spec("ts"))):

        class BadEmpty(Schema):  # pyright: ignore[reportUnusedClass]
            schema = {Dir(alias="runs", fmt=dt("%Y%m%d"), min=0): TextLog}


def test_member_planned_alone_has_no_container_scope(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match=re.escape(em.Schema.Body.unbound("ts"))):
        _ = Log.relative_to(tmp_path)
