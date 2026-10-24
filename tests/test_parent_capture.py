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


def test_same_node_ref_repeats_its_field(tmp_path: Path) -> None:
    class Twin(Schema):
        schema = {Dir(alias="runs", fmt="{ts:%Y%m%d}_<ts>", min=0): {}}

    class Outer(Schema):
        schema = {Dir(alias="days", fmt="{ts:%Y%m%d}", min=0): {Dir(alias="inner", fmt="{ts:%Y%m%d}_<ts>", min=0): {}}}

    match = tmp_path / "match"
    (match / f"{STAMP}_{STAMP}").mkdir(parents=True)
    (match / f"{STAMP}_{OTHER_STAMP}").mkdir()
    bound = raise_mismatch(Twin.bind(match))
    assert [node.path.name for node in bound.runs] == [f"{STAMP}_{STAMP}"]
    assert bound.runs[0].kwargs["ts"] == WHEN
    assert Twin.relative_to(tmp_path / "made").runs.format(ts=WHEN).path.name == f"{STAMP}_{STAMP}"
    with pytest.raises(KeyError, match="ts"):
        Twin.relative_to(tmp_path / "open").runs.format()

    shadow = tmp_path / "shadow" / STAMP / f"{OTHER_STAMP}_{OTHER_STAMP}"
    shadow.mkdir(parents=True)
    (tmp_path / "shadow" / STAMP / f"{OTHER_STAMP}_{STAMP}").mkdir()
    outer = raise_mismatch(Outer.bind(tmp_path / "shadow"))
    assert [node.path.name for node in outer.days[0].inner] == [f"{OTHER_STAMP}_{OTHER_STAMP}"]
    assert outer.days[0].inner[0].kwargs["ts"] == OTHER

    class Plain(Schema):
        schema = {Dir(alias="rows", fmt="{label}_<label>", min=0): {}}

    text = tmp_path / "text"
    (text / "ab_ab").mkdir(parents=True)
    (text / "ab_cd").mkdir()
    plain = raise_mismatch(Plain.bind(text))
    assert [node.path.name for node in plain.rows] == ["ab_ab"]
    assert plain.rows[0].kwargs["label"] == "ab"

    class Copied(Schema):
        schema = {Dir(alias="rows", fmt="{n:d}_<n:d>", min=0): {}}

    assert Copied.relative_to(tmp_path / "copy").rows.format(n=1).path.name == "1_1"

    with pytest.raises(TypeError, match=re.escape(em.Schema.Body.spec("n"))):

        class MixedSame(Schema):  # pyright: ignore[reportUnusedClass]
            schema = {Dir(alias="rows", fmt="{n:d}_<n:%Y%m%d>", min=0): {}}

    class Padded(Schema):
        schema = {Dir(alias="rows", fmt="{n:d}_<n:02d>", min=0): {}}

    assert Padded.relative_to(tmp_path / "pad").rows.format(n=1).path.name == "1_01"
    padded = tmp_path / "pad-bind"
    (padded / "1_01").mkdir(parents=True)
    (padded / "1_1").mkdir()
    bound = raise_mismatch(Padded.bind(padded))
    assert [node.path.name for node in bound.rows] == ["1_01", "1_1"]
    assert [node.kwargs["n"] for node in bound.rows] == [1, 1]

    class Iso(Schema):
        schema = {Dir(alias="days", fmt="{ts:%Y%m%d}_<ts:%Y-%m-%d>", min=0): {}}

    assert Iso.relative_to(tmp_path / "iso").days.format(ts=WHEN).path.name == f"{STAMP}_1970-01-01"


@pytest.mark.skipif(sys.platform == "win32", reason="Windows forbids < and > in file names")
def test_same_string_ref_keeps_a_literal_bracket(tmp_path: Path) -> None:
    class Bracketed(Schema):
        schema = {Dir(alias="rows", fmt="a/<{n:d}>_<n>", min=0): {}}

    assert Bracketed.relative_to(tmp_path / "br").rows.format(n=1).path.name == "a<1>_1"
    root = tmp_path / "br-bind"
    (root / "a<1>_1").mkdir(parents=True)
    (root / "a<1>_2").mkdir()
    bound = raise_mismatch(Bracketed.bind(root))
    assert [node.path.name for node in bound.rows] == ["a<1>_1"]

    class Escaped(Schema):
        schema = {Dir(alias="rows", fmt="pre/<_{n:d}_<n>", min=0): {}}

    assert Escaped.relative_to(tmp_path / "esc").rows.format(n=1).path.name == "pre<_1_1"
    esc = tmp_path / "esc-bind"
    (esc / "pre<_1_1").mkdir(parents=True)
    (esc / "pre<_1_2").mkdir()
    bound = raise_mismatch(Escaped.bind(esc))
    assert [node.path.name for node in bound.rows] == ["pre<_1_1"]
    assert bound.rows[0].kwargs["n"] == 1


def test_repeat_edges(tmp_path: Path) -> None:
    with pytest.raises(TypeError, match=re.escape(em.Schema.Body.spec("n"))):

        class EmptyOverride(Schema):  # pyright: ignore[reportUnusedClass]
            schema = {Dir(alias="rows", fmt="{n:d}_<n:>", min=0): {}}

    with pytest.raises(TypeError, match=re.escape(em.Schema.Body.unbound("n"))):

        class UnboundPair(Schema):  # pyright: ignore[reportUnusedClass]
            schema = {Dir(alias="rows", fmt="<n>_<n>", min=0): {}}

    class Inherit(Schema):
        schema = {Dir(alias="rows", fmt="{n:02d}_<n>", min=0): {}}

    assert Inherit.relative_to(tmp_path / "inh").rows.format(n=1).path.name == "01_01"
    inh = tmp_path / "inh-bind"
    for name in ("01_01", "01_1", "1_01", "1_1"):
        (inh / name).mkdir(parents=True)
    bound = raise_mismatch(Inherit.bind(inh))
    assert sorted(node.path.name for node in bound.rows) == ["01_01", "01_1", "1_01", "1_1"]
    assert [node.kwargs["n"] for node in bound.rows] == [1, 1, 1, 1]

    class Day(Schema):
        schema = {Dir(alias="rows", fmt="{ts:%m%d}_<ts>", min=0): {}}

    assert Day.relative_to(tmp_path / "day").rows.format(ts=WHEN).path.name == "0101_0101"
    (tmp_path / "day-bind" / "0101_0101").mkdir(parents=True)
    # %m%d has no year, so parse fills the current year and both sides still match
    assert raise_mismatch(Day.bind(tmp_path / "day-bind")).rows[0].kwargs["ts"] == datetime(datetime.now().year, 1, 1)

    class RefFirst(Schema):
        schema = {Dir(alias="rows", fmt="<n:02d>_{n:d}", min=0): {}}

    assert RefFirst.relative_to(tmp_path / "first").rows.format(n=1).path.name == "01_1"
    first = tmp_path / "first-bind"
    for name in ("01_1", "1_1", "01_01", "1_01"):
        (first / name).mkdir(parents=True)
    bound = raise_mismatch(RefFirst.bind(first))
    assert sorted(node.path.name for node in bound.rows) == ["01_01", "01_1", "1_01", "1_1"]

    class Twice(Schema):
        schema = {Dir(alias="rows", fmt="{n:d}_<n>_<n:02d>", min=0): {}}

    assert Twice.relative_to(tmp_path / "twice").rows.format(n=1).path.name == "1_1_01"
    twice = tmp_path / "twice-bind"
    for name in ("1_1_01", "1_1_1", "1_2_01"):
        (twice / name).mkdir(parents=True)
    bound = raise_mismatch(Twice.bind(twice))
    assert sorted(node.path.name for node in bound.rows) == ["1_1_01", "1_1_1"]
    assert [node.kwargs["n"] for node in bound.rows] == [1, 1]

    class Pair(Schema):
        schema = {Dir(alias="rows", fmt="{a:d}_{b}_<b>_<a:02d>", min=0): {}}

    assert Pair.relative_to(tmp_path / "pair").rows.format(a=1, b="x").path.name == "1_x_x_01"
    pair = tmp_path / "pair-bind"
    for name in ("1_x_x_01", "1_x_y_01", "1_x_x_1"):
        (pair / name).mkdir(parents=True)
    bound = raise_mismatch(Pair.bind(pair))
    assert sorted(node.path.name for node in bound.rows) == ["1_x_x_01", "1_x_x_1"]
    assert bound.rows[0].kwargs["a"] == 1 and bound.rows[0].kwargs["b"] == "x"

    class Positional(Schema):
        schema = {Dir(alias="rows", fmt="{}_{n:d}_<n>", min=0): {}}

    assert Positional.relative_to(tmp_path / "pos").rows.format("z", n=1).path.name == "z_1_1"
    pos = tmp_path / "pos-bind"
    (pos / "z_1_1").mkdir(parents=True)
    (pos / "z_1_2").mkdir()
    bound = raise_mismatch(Positional.bind(pos))
    assert [node.path.name for node in bound.rows] == ["z_1_1"]
    assert bound.rows[0].args == ("z",)
    assert bound.rows[0].kwargs["n"] == 1

    class Wide(Schema):
        schema = {Dir(alias="rows", fmt="{n:d}_<n:02d>", min=0): {}}

    wide = tmp_path / "wide"
    for name in ("1_001", "1_01", "1_1", "1_2"):
        (wide / name).mkdir(parents=True)
    bound = raise_mismatch(Wide.bind(wide))
    assert sorted(node.path.name for node in bound.rows) == ["1_01", "1_1"]

    class Glued(Schema):
        schema = {Dir(alias="rows", fmt="{n:d}<n:02d>", min=0): {}}

    assert Glued.relative_to(tmp_path / "glue").rows.format(n=1).path.name == "101"
    (tmp_path / "glue-bind" / "101").mkdir(parents=True)
    assert list(raise_mismatch(Glued.bind(tmp_path / "glue-bind")).rows) == []

    class Under(Schema):
        schema = {Dir(alias="rows", fmt="{_n}_<_n>", min=0): {}}

    # parse only names a field that starts with a letter, so {_n} formats and does not bind
    assert Under.relative_to(tmp_path / "under").rows.format(_n="ab").path.name == "ab_ab"
    (tmp_path / "under-bind" / "ab_ab").mkdir(parents=True)
    assert list(raise_mismatch(Under.bind(tmp_path / "under-bind")).rows) == []

    class Swapped(Schema):
        schema = {Dir(alias="rows", fmt="{ts:%m%d}_<ts:%d%m>", min=0): {}}

    assert Swapped.relative_to(tmp_path / "swap").rows.format(ts=OTHER).path.name == "0102_0201"
    (tmp_path / "swap-bind" / "0102_0201").mkdir(parents=True)
    swapped = raise_mismatch(Swapped.bind(tmp_path / "swap-bind")).rows[0]
    assert swapped.kwargs["ts"] == datetime(datetime.now().year, 1, 2)

    class YearOnly(Schema):
        schema = {Dir(alias="rows", fmt="{ts:%m%d}_<ts:%Y>", min=0): {}}

    assert YearOnly.relative_to(tmp_path / "year").rows.format(ts=WHEN).path.name == "0101_1970"
    (tmp_path / "year-bind" / "0101_1970").mkdir(parents=True)
    assert list(raise_mismatch(YearOnly.bind(tmp_path / "year-bind")).rows) == []

    class Ancestors(Schema):
        schema = {Dir(alias="outer", fmt="{n:d}", min=0): {Dir(alias="rows", fmt="<n>_<n>", min=0): {}}}

    assert Ancestors.relative_to(tmp_path / "anc").outer.format(n=1).rows.format().path.name == "1_1"
    anc = tmp_path / "anc-bind" / "1"
    (anc / "1_1").mkdir(parents=True)
    (anc / "1_2").mkdir()
    bound = raise_mismatch(Ancestors.bind(tmp_path / "anc-bind"))
    assert [node.path.name for node in bound.outer[0].rows] == ["1_1"]

    class Mixed(Schema):
        schema = {Dir(alias="outer", fmt="{tag}", min=0): {Dir(alias="rows", fmt="<tag>_{n:d}_<n:02d>", min=0): {}}}

    assert Mixed.relative_to(tmp_path / "mix").outer.format(tag="ab").rows.format(n=1).path.name == "ab_1_01"
    mix = tmp_path / "mix-bind" / "ab"
    for name in ("ab_1_01", "ab_1_1", "ab_1_2", "zz_1_01"):
        (mix / name).mkdir(parents=True)
    bound = raise_mismatch(Mixed.bind(tmp_path / "mix-bind"))
    assert sorted(node.path.name for node in bound.outer[0].rows) == ["ab_1_01", "ab_1_1"]

    class Foreign(Schema):
        schema = {Dir(alias="outer", fmt="{ts:%Y%m%d}", min=0): {Dir(alias="rows", fmt="<ts>_{n:d}", min=0): {}}}

    assert Foreign.relative_to(tmp_path / "for").outer.format(ts=WHEN).rows.format(n=1).path.name == f"{STAMP}_1"
    foreign = tmp_path / "for-bind" / STAMP
    for name in (f"{STAMP}_1", f"{OTHER_STAMP}_1", f"{STAMP}_2"):
        (foreign / name).mkdir(parents=True)
    bound = raise_mismatch(Foreign.bind(tmp_path / "for-bind"))
    assert sorted(node.path.name for node in bound.outer[0].rows) == [f"{STAMP}_1", f"{STAMP}_2"]
    assert [node.kwargs["n"] for node in bound.outer[0].rows] == [1, 2]


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
