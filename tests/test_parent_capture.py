# pyright: reportPrivateUsage=false, reportUnknownMemberType=false, reportUnknownArgumentType=false
# pyright: reportAttributeAccessIssue=false, reportIndexIssue=false, reportUnknownVariableType=false
import re
import sys
from datetime import datetime
from pathlib import Path

import pytest

from fs_schema import Dir, File, Schema, raise_mismatch
from fs_schema import _errmsg as em

WHEN = datetime(1970, 1, 1)
OTHER = datetime(1970, 1, 2)
STAMP = "19700101"
OTHER_STAMP = "19700102"


class Roll(Schema):
    schema = {
        Dir(alias="runs", fmt="run_{ts:%Y%m%d}", min=0): {
            "log": "<ts>.log",
            "parts": File(fmt="<ts>_{n:d}.txt", min=0),
            Dir(alias="extra", fmt="x_{n:d}_<ts>", min=0): {"body": "<ts>_<n>.txt"},
        }
    }


class Dated(Schema):
    schema = {Dir(alias="days", fmt="{ts:%Y%m%d_%H%M%S}", min=0): {"page": "<ts:%Y%m%d>.txt"}}


class Nested(Schema):
    schema = {
        Dir(alias="outer", fmt="{ts:%Y%m%d}", min=0): {
            Dir(alias="inner", fmt="{ts:%Y%m%d}", min=0): {"log": "<ts>.log"}
        }
    }


class Plain(Schema):
    schema = {"page": File(fmt="{ts:%Y%m%d}.txt", min=0)}


class Holder(Schema):
    schema = {Dir(alias="days", fmt="{ts:%Y%m%d}", min=0): Plain}


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)


def test_ref_without_an_ancestor_is_a_declaration_error() -> None:
    detail = em.Schema.Body.decl("log", em.Schema.Body.unbound("ts"))
    with pytest.raises(TypeError, match=re.escape(em.Schema.text("Alone", detail))):

        class Alone(Schema):  # pyright: ignore[reportUnusedClass]
            schema = {"log": "<ts>.log"}


def test_same_node_ref_is_a_declaration_error() -> None:
    with pytest.raises(TypeError, match=re.escape(em.Schema.Body.unbound("ts"))):

        class Same(Schema):  # pyright: ignore[reportUnusedClass]
            schema = {Dir(alias="runs", fmt="{ts:%Y%m%d}_<ts>", min=0): {}}


def test_override_spec_must_match_the_value_kind() -> None:
    with pytest.raises(TypeError, match=re.escape(em.Schema.Body.spec("n"))):

        class Mixed(Schema):  # pyright: ignore[reportUnusedClass]
            schema = {Dir(alias="rows", fmt="{n:d}", min=0): {"page": "<n:%Y%m%d>.txt"}}

    with pytest.raises(TypeError, match=re.escape(em.Schema.Body.spec("label"))):

        class Words(Schema):  # pyright: ignore[reportUnusedClass]
            schema = {Dir(alias="rows", fmt="{label}", min=0): {"page": "<label:d>.txt"}}


@pytest.mark.skipif(sys.platform == "win32", reason="Windows forbids < and > in file names")
def test_literal_brackets_escape(tmp_path: Path) -> None:
    class Bracket(Schema):
        schema = {"mark": "a/<b>.txt", "tail": "c>d.txt"}

    _write(tmp_path / "a<b>.txt", "ok\n")
    _write(tmp_path / "c>d.txt", "tail\n")
    bound = raise_mismatch(Bracket.bind(tmp_path))
    assert bound.mark.read_text() == "ok\n"
    assert bound.mark.path.name == "a<b>.txt"
    assert bound.tail.read_text() == "tail\n"
    assert bound.tail.path.name == "c>d.txt"


def test_bind_resolves_fixed_names_and_keeps_own_captures(tmp_path: Path) -> None:
    run = tmp_path / f"run_{STAMP}"
    _write(run / f"{STAMP}.log", "hello\n")
    _write(run / f"{STAMP}_1.txt", "one\n")
    _write(run / f"{OTHER_STAMP}_1.txt", "foreign\n")
    _write(run / f"x_2_{STAMP}" / f"{STAMP}_2.txt", "inside\n")

    bound = raise_mismatch(Roll.bind(tmp_path))
    got = bound.runs[0]
    assert got.kwargs["ts"] == WHEN
    assert got.log.path.name == f"{STAMP}.log"
    assert got.log.read_text() == "hello\n"
    assert got.log.kwargs["ts"] == WHEN
    assert [node.path.name for node in got.parts] == [f"{STAMP}_1.txt"]
    assert got.parts[0].kwargs["n"] == 1
    assert got.parts[0].kwargs["ts"] == WHEN
    extra = got.extra[0]
    assert extra.path.name == f"x_2_{STAMP}"
    assert extra.kwargs["n"] == 2
    assert extra.kwargs["ts"] == WHEN
    assert extra.body.path.name == f"{STAMP}_2.txt"
    assert extra.body.kwargs["n"] == 2
    assert extra.body.kwargs["ts"] == WHEN
    assert extra.body.read_text() == "inside\n"


def test_override_spec_renders_a_shorter_name(tmp_path: Path) -> None:
    day = tmp_path / f"{STAMP}_000000"
    _write(day / f"{STAMP}.txt", "page\n")
    _write(day / f"{STAMP}_000000.txt", "full\n")
    bound = raise_mismatch(Dated.bind(tmp_path))
    assert bound.days[0].page.path.name == f"{STAMP}.txt"
    assert bound.days[0].page.kwargs["ts"] == WHEN


def test_where_on_an_ancestor_keeps_every_sibling_or_none(tmp_path: Path) -> None:
    run = tmp_path / f"run_{STAMP}"
    _write(run / f"{STAMP}.log", "hello\n")
    _write(run / f"{STAMP}_1.txt", "one\n")
    _write(run / f"{STAMP}_2.txt", "two\n")
    parts = raise_mismatch(Roll.bind(tmp_path)).runs[0].parts
    assert [node.kwargs["n"] for node in parts.where(ts=WHEN)] == [1, 2]
    assert not parts.where(ts=OTHER)


def test_closest_capture_shadows_an_outer_one(tmp_path: Path) -> None:
    inner = tmp_path / STAMP / OTHER_STAMP
    _write(inner / f"{OTHER_STAMP}.log", "inner\n")
    _write(tmp_path / STAMP / OTHER_STAMP / f"{STAMP}.log", "outer\n")
    bound = raise_mismatch(Nested.bind(tmp_path))
    got = bound.outer[0].inner[0]
    assert got.kwargs["ts"] == OTHER
    assert got.log.path.name == f"{OTHER_STAMP}.log"
    assert got.log.kwargs["ts"] == OTHER


def test_named_schema_keeps_its_own_captures(tmp_path: Path) -> None:
    day = tmp_path / STAMP
    _write(day / f"{OTHER_STAMP}.txt", "other\n")
    bound = raise_mismatch(Holder.bind(tmp_path))
    assert bound.days[0].kwargs["ts"] == WHEN
    assert bound.days[0].page[0].kwargs["ts"] == OTHER
    assert bound.days[0].page[0].path.name == f"{OTHER_STAMP}.txt"


def test_create_resolves_refs_from_the_parent_frame(tmp_path: Path) -> None:
    Roll.relative_to(tmp_path).runs.format(ts=WHEN).create(
        log="hello\n",
        parts=[({"n": 1}, b"one\n")],
        extra=[({"n": 2}, {"body": "inside\n"})],
    )
    run = tmp_path / f"run_{STAMP}"
    assert (run / f"{STAMP}.log").read_text() == "hello\n"
    assert (run / f"{STAMP}_1.txt").read_bytes() == b"one\n"
    assert (run / f"x_2_{STAMP}" / f"{STAMP}_2.txt").read_text() == "inside\n"


def test_create_does_not_fill_a_child_field_from_the_parent(tmp_path: Path) -> None:
    with pytest.raises(TypeError, match=re.escape(em.Create.file("page", ["ts"], []))):
        Holder.relative_to(tmp_path).days.format(ts=WHEN).create(page=b"x\n")
    Holder.relative_to(tmp_path / "own").days.format(ts=WHEN).create(page=[({"ts": OTHER}, b"other\n")])
    assert (tmp_path / "own" / STAMP / f"{OTHER_STAMP}.txt").read_bytes() == b"other\n"


def test_ref_only_format_renders_the_ancestor_and_still_checks_the_regex(tmp_path: Path) -> None:
    class Logs(Schema):
        schema = {
            Dir(alias="runs", fmt="{ts:%Y%m%d}", min=0): {
                "log": File(fmt="<ts>.log", min=0),
                "bad": File(fmt="<ts>.txt", match="nope", min=0),
            }
        }

    made = Logs.relative_to(tmp_path).runs.format(ts=WHEN)
    assert made.log.format().path.name == f"{STAMP}.log"
    with pytest.raises(ValueError, match=re.escape(em.Fmt.pattern("nope", f"{STAMP}.txt"))):
        made.bad.format()
