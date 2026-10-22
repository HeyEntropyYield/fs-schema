import re
import warnings
from pathlib import Path

import pytest

from fs_schema import FILES, Dir, File, Schema, is_mismatch, raise_mismatch, xor
from fs_schema import _errmsg as em


class Base(Schema):
    schema = {"f": "file.json"}


class Child1(Base):
    schema = {"data": "data.json"}


class Child2(Base):
    schema = {"log": "log.txt"}


class Other(Schema):
    schema = {"f": "other.json", "log": "log.txt"}


class Root(Schema):
    schema = {"recv": xor(table=Child1, frame=Child2)}


class Open(Schema):
    schema = {"recv": xor(Child1, Child2)}


class Inline(Schema):
    schema = {
        "data": xor(
            {"f": "file.json", "data": "data.json"},
            stamp={"stamp": "stamp.json"},
        )
    }


class Boxed(Schema):
    schema = {Dir(alias="recv", fmt="{n:d}", min=0): xor(table=Child1, frame=Child2)}


class NeedOne(Schema):
    schema = {Dir(alias="recv", fmt="{n:d}", min=1): xor(table=Child1, frame=Child2)}


def test_named() -> None:
    assert Root.recv.table is Child1  # pyright: ignore[reportUnknownMemberType]
    assert Root.recv.frame is Child2  # pyright: ignore[reportUnknownMemberType]
    assert Root.recv.table.f is not None


def test_named_plan(tmp_path: Path) -> None:
    data = Root.relative_to(tmp_path).recv
    assert data.table.f.path == data.frame.f.path
    assert data.table.data.path.name == "data.json"
    assert data.frame.log.path.name == "log.txt"
    with pytest.raises(AttributeError):
        _ = data.f
    with pytest.raises(AttributeError):
        _ = data.data
    with pytest.raises(IndexError):
        _ = data[0]
    with pytest.raises(TypeError, match=em.Xor.single(tmp_path / "recv")):
        data.create()

    data.table.f.create("{}")
    data.table.data.create("{}")
    assert (tmp_path / "recv" / "file.json").read_text() == "{}"
    assert (tmp_path / "recv" / "data.json").read_text() == "{}"


def test_open(tmp_path: Path) -> None:
    data = Open.relative_to(tmp_path).recv
    assert data[0].data.path.name == "data.json"
    assert data[1].log.path.name == "log.txt"
    assert data.f.path.name == "file.json"
    with pytest.raises(AttributeError):
        _ = data.file_json
    assert data.data.path.name == "data.json"
    assert data.log.path.name == "log.txt"
    with pytest.raises(AttributeError):
        _ = data.table


def test_unnamed_fmt_without_alias_is_not_a_clash(tmp_path: Path) -> None:
    class Bare(Schema):
        schema = {"recv": xor({Dir(fmt="{n:d}", min=0): {"x": "x.txt"}})}

    assert Bare.relative_to(tmp_path).recv[0].path.name == "recv"


def test_open_clash(tmp_path: Path) -> None:
    with pytest.warns(UserWarning, match=re.escape(em.Xor.clash("f"))):

        class Local(Schema):
            schema = {"recv": xor(Child1, Other)}

    data = Local.relative_to(tmp_path).recv
    with pytest.raises(AttributeError, match=re.escape(em.Xor.clash("f"))):
        _ = data.f
    assert data[0].f.path.name == "file.json"
    assert data[1].f.path.name == "other.json"
    assert data.data.path.name == "data.json"
    assert data.log.path.name == "log.txt"


def test_unnamed_basename_without_alias_warns() -> None:
    with pytest.warns(UserWarning, match=re.escape(em.Xor.clash("notes_txt"))):

        class Local(Schema):
            schema = {"recv": xor({FILES: [File("notes.txt")]}, {FILES: [File("notes-txt")]})}

    assert Local.recv


def test_named_arms_do_not_clash() -> None:
    with warnings.catch_warnings():
        warnings.simplefilter("error", UserWarning)

        class Named(Schema):
            schema = {"recv": xor(table=Child1, frame=Other)}

    assert Named.recv.frame is Other  # pyright: ignore[reportUnknownMemberType]


def test_open_clash_quiet() -> None:
    with warnings.catch_warnings():
        warnings.simplefilter("error", UserWarning)

        class Quiet(Schema):
            warn = False
            schema = {"recv": xor(Child1, Other)}

    assert Quiet.recv is not None


def test_arm_key(tmp_path: Path) -> None:
    class Arm(Schema):
        schema = {"recv": xor(f=Child1, frame=Child2)}

    assert Arm.recv.f is Child1  # pyright: ignore[reportUnknownMemberType]
    data = Arm.relative_to(tmp_path).recv
    assert data.f.f.path.name == "file.json"
    assert data.f.data.path.name == "data.json"
    with pytest.raises(AttributeError):
        _ = data.data


def test_inline(tmp_path: Path) -> None:
    assert Inline.data.stamp.stamp is not None  # pyright: ignore[reportUnknownMemberType]
    data = Inline.relative_to(tmp_path).data
    assert data[0].data.path.name == "data.json"
    assert data.f.path.name == "file.json"
    assert data.stamp.stamp.path.name == "stamp.json"
    data.stamp.stamp.create("{}")
    assert (tmp_path / "data" / "stamp.json").read_text() == "{}"


def test_bind(tmp_path: Path) -> None:
    recv = tmp_path / "recv"
    recv.mkdir()
    (recv / "file.json").write_text("{}")
    (recv / "data.json").write_text("{}")

    hit = raise_mismatch(Root.bind(tmp_path)).recv
    assert isinstance(hit, Child1)
    assert isinstance(hit, Root.recv.table)  # pyright: ignore[reportUnknownMemberType]
    assert not isinstance(hit, Child2)
    assert hit.f.path.name == "file.json"
    assert hit.data.path.name == "data.json"
    with pytest.raises(AttributeError):
        _ = hit.table
    with pytest.raises(AttributeError):
        _ = hit.log


def test_fmt(tmp_path: Path) -> None:
    planned = Boxed.relative_to(tmp_path).recv.format(n=1)
    planned.frame.create(f="{}", log="log\n")
    assert (tmp_path / "1" / "log.txt").read_text() == "log\n"

    hit = raise_mismatch(Boxed.bind(tmp_path)).recv[0]
    assert isinstance(hit, Child2)
    assert hit.log.path.name == "log.txt"
    with pytest.raises(AttributeError):
        _ = hit.frame


def test_miss(tmp_path: Path) -> None:
    (tmp_path / "nope").mkdir()
    assert list(raise_mismatch(Boxed.bind(tmp_path)).recv) == []

    numbered = tmp_path / "4"
    numbered.mkdir()
    (numbered / "file.json").write_text("{}")
    (numbered / "data.json").write_text("{}")
    hit = raise_mismatch(Boxed.bind(tmp_path)).recv[0]
    assert isinstance(hit, Child1)

    (numbered / "file.json").unlink()
    (numbered / "data.json").unlink()
    assert is_mismatch(Boxed.bind(tmp_path))


def test_empty_arm(tmp_path: Path) -> None:
    class Empty(Schema):
        schema = {}

    class WithEmpty(Schema):
        schema = {Dir(alias="recv", fmt="{n:d}", min=0): xor(table=Child1, bare=Empty)}

    (tmp_path / "4").mkdir()
    hit = raise_mismatch(WithEmpty.bind(tmp_path)).recv[0]
    assert isinstance(hit, Empty)


def test_min(tmp_path: Path) -> None:
    (tmp_path / "1").mkdir()
    assert is_mismatch(NeedOne.bind(tmp_path))


class FixedOnly(Schema):
    schema = {"data": "data.json"}


class Frames(Schema):
    schema = {Dir(alias="frame", fmt="{n:d}", min=1): {"frame": "frame.png"}}


class Notes(Schema):
    schema = {Dir(alias="note", fmt="{n:d}", min=1): {"text": "text.txt"}}


class Mix(Schema):
    schema = {"recv": xor(fixed=FixedOnly, frames=Frames)}


class Pair(Schema):
    schema = {"recv": xor(frames=Frames, notes=Notes)}


class Over(Schema):
    schema = {Dir(".", alias="here"): xor(table=Child1, frame=Child2)}


def test_fmt_arm(tmp_path: Path) -> None:
    planned = Mix.relative_to(tmp_path).recv
    assert planned.fixed.data.path.name == "data.json"
    planned.frames.frame.format(n=3).create(frame="{}")
    assert (tmp_path / "recv" / "3" / "frame.png").read_text() == "{}"

    hit = raise_mismatch(Mix.bind(tmp_path)).recv
    assert isinstance(hit, Frames)
    assert not isinstance(hit, FixedOnly)
    assert hit.frame[0].frame.path.name == "frame.png"

    fixed = tmp_path / "fixed" / "recv"
    fixed.mkdir(parents=True)
    (fixed / "data.json").write_text("{}")
    assert isinstance(raise_mismatch(Mix.bind(tmp_path / "fixed")).recv, FixedOnly)


def test_fmt_arms(tmp_path: Path) -> None:
    planned = Pair.relative_to(tmp_path / "plan").recv
    planned.frames.frame.format(n=1).create(frame="{}")
    planned.notes.note.format(n=2).create(text="x\n")
    assert (tmp_path / "plan" / "recv" / "2" / "text.txt").read_text() == "x\n"

    live = tmp_path / "live" / "recv" / "2"
    live.mkdir(parents=True)
    (live / "text.txt").write_text("x\n")
    hit = raise_mismatch(Pair.bind(tmp_path / "live")).recv
    assert isinstance(hit, Notes)
    assert hit.note[0].kwargs["n"] == 2


def test_overlay(tmp_path: Path) -> None:
    here = Over.relative_to(tmp_path).here
    assert here.table.f.path == tmp_path / "file.json"
    here.frame.f.create("{}")
    here.frame.log.create("log\n")
    assert (tmp_path / "log.txt").read_text() == "log\n"

    hit = raise_mismatch(Over.bind(tmp_path)).here
    assert isinstance(hit, Child2)
    assert hit.log.path == tmp_path / "log.txt"


def test_overlay_optional(tmp_path: Path) -> None:
    class Opt(Schema):
        schema = {Dir(".", alias="here", optional=True): xor(table=Child1, frame=Child2)}

    assert raise_mismatch(Opt.bind(tmp_path)).here is None
