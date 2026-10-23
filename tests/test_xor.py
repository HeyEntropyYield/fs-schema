# pyright: reportPrivateUsage=false, reportUnknownMemberType=false, reportUnknownArgumentType=false
# pyright: reportAttributeAccessIssue=false, reportIndexIssue=false, reportUnknownVariableType=false
import re
from collections import UserList
from pathlib import Path

import pytest
from beartype.roar import BeartypeCallHintParamViolation

from fs_schema import Dir, Match, MismatchErr, Schema, is_mismatch, raise_mismatch, xor
from fs_schema import _errmsg as em
from fs_schema._compile import _dir_defn_exn
from fs_schema._decl import DirDefn, DirLayout
from fs_schema._schema import _schema_ctor_install_attrs


class Letter(Schema):
    schema = {"body": "body.txt"}


class Stamped(Letter):
    schema = {"stamp": "stamp.json"}


class Frame(Letter):
    schema = {"frame": "frame.png"}


class ArmA(Letter):
    schema = {"a": "a.txt"}


class ArmB(Letter):
    schema = {"b": "b.txt"}


class ArmC(Schema):
    schema = {"c": "c.txt"}


class NestedNeed(Schema):
    schema = {"nested": {"note": "note.txt"}}


class Payload(Schema):
    schema = {"payload": "payload.txt"}


class Slot(Schema):
    schema = {"slot": xor(stamp=Stamped, frame=Frame)}


class OneArm(Schema):
    schema = {"slot": xor(stamp=Stamped)}


class ZeroSkip(Schema):
    schema = {Dir(alias="items", fmt="{n:d}", min=0, skip_mismatch=True): xor()}


class ZeroStrict(Schema):
    schema = {"slot": xor()}


class Trio(Schema):
    schema = {
        Dir(alias="items", fmt="{n:d}", min=0, skip_mismatch=True): xor(a=ArmA, b=ArmB, c=ArmC),
    }


class GeneralFirst(Schema):
    schema = {
        Dir(alias="items", fmt="{n:d}", min=0, skip_mismatch=True): xor(payload=Payload, need=NestedNeed),
    }


class SpecificFirst(Schema):
    schema = {
        Dir(alias="items", fmt="{n:d}", min=0, skip_mismatch=True): xor(need=NestedNeed, payload=Payload),
    }


class StrictItems(Schema):
    schema = {Dir(alias="items", fmt="{n:d}", min=0): xor(c=ArmC, a=ArmA)}


def _file(root: Path, rel: str) -> None:
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(rel)


def test_xor_compile_rejects_a_non_schema_leaf() -> None:
    bad = xor()
    object.__setattr__(bad, "entries", ((None, 1),))
    with pytest.raises(TypeError, match=re.escape(em.Schema.text("Leaf", em.Schema.Body.schema_or_dict("slot", 1)))):
        _dir_defn_exn("Leaf", "tests", "slot", Dir(name="slot"), bad.entries, {}, origin=0, warn=False)


def test_xor_pairs_keep_definition_order_and_reject_non_schemas() -> None:
    got = xor(ArmC, stamp=Stamped, frame=Frame)
    assert got.entries == ((None, ArmC), ("stamp", Stamped), ("frame", Frame))
    with pytest.raises(BeartypeCallHintParamViolation):
        xor(Stamped, "frame")  # pyright: ignore[reportArgumentType]
    with pytest.raises(BeartypeCallHintParamViolation):
        xor(stamp="frame")  # pyright: ignore[reportArgumentType]
    with pytest.raises(
        TypeError, match=re.escape(em.Schema.text("BadSeq", em.Schema.Body.schema_or_dict("slot", "frame")))
    ):
        _ = type("BadSeq", (Schema,), {"schema": {"slot": (Stamped, "frame")}})


def test_xor_exact_dir_first_success_keeps_only_that_arm(tmp_path: Path) -> None:
    slot = tmp_path / "slot"
    _file(slot, "body.txt")
    _file(slot, "stamp.json")
    _file(slot, "frame.png")

    hit = raise_mismatch(Slot.bind(tmp_path)).slot
    assert isinstance(hit, Stamped)
    assert isinstance(hit, Letter)
    assert not isinstance(hit, Frame)
    assert type(hit) is Stamped
    assert hit.body.path.name == "body.txt"
    assert hit.stamp.path.name == "stamp.json"
    with pytest.raises(AttributeError):
        _ = hit.frame


def test_xor_tries_the_next_arm_after_the_first_fails(tmp_path: Path) -> None:
    slot = tmp_path / "slot"
    _file(slot, "body.txt")
    _file(slot, "frame.png")

    hit = raise_mismatch(Slot.bind(tmp_path)).slot
    assert isinstance(hit, Frame)
    assert not isinstance(hit, Stamped)
    assert hit.frame.path.name == "frame.png"


def test_xor_common_file_alone_matches_no_arm(tmp_path: Path) -> None:
    slot = tmp_path / "slot"
    _file(slot, "body.txt")

    err = Slot.bind(tmp_path)
    assert is_mismatch(err)
    assert isinstance(err, MismatchErr)
    text = str(err)
    assert "stamp.json" in text
    assert "frame.png" in text


def test_xor_three_arms_two_share_a_base_follow_definition_order(tmp_path: Path) -> None:
    both = tmp_path / "1"
    _file(both, "body.txt")
    _file(both, "a.txt")
    _file(both, "b.txt")
    only_b = tmp_path / "2"
    _file(only_b, "body.txt")
    _file(only_b, "b.txt")
    only_c = tmp_path / "3"
    _file(only_c, "c.txt")
    only_body = tmp_path / "4"
    _file(only_body, "body.txt")

    items = list(raise_mismatch(Trio.bind(tmp_path)).items)
    assert [type(hit).__name__ for hit in items] == ["ArmAMatch", "ArmBMatch", "ArmCMatch"]
    assert [hit.kwargs["n"] for hit in items] == [1, 2, 3]

    first, second, third = items
    assert isinstance(first, ArmA)
    assert isinstance(first, Letter)
    assert isinstance(first, Match)
    assert not isinstance(first, ArmB)
    assert first.a.path.name == "a.txt"
    with pytest.raises(AttributeError):
        _ = first.b
    assert isinstance(second, ArmB)
    assert not isinstance(second, ArmA)
    assert isinstance(third, ArmC)
    assert not isinstance(third, Letter)


def test_xor_earlier_general_arm_takes_a_directory_the_later_arm_also_matches(tmp_path: Path) -> None:
    stamp = tmp_path / "1"
    _file(stamp, "payload.txt")
    _file(stamp, "nested/note.txt")

    hit = raise_mismatch(GeneralFirst.bind(tmp_path)).items[0]
    assert isinstance(hit, Payload)
    assert not isinstance(hit, NestedNeed)


def test_xor_failed_earlier_arm_falls_through_to_a_later_arm(tmp_path: Path) -> None:
    broken = tmp_path / "1"
    _file(broken, "payload.txt")
    (broken / "nested").mkdir(parents=True)
    whole = tmp_path / "2"
    _file(whole, "nested/note.txt")

    items = list(raise_mismatch(SpecificFirst.bind(tmp_path)).items)
    assert [type(hit).__name__ for hit in items] == ["PayloadMatch", "NestedNeedMatch"]
    assert isinstance(items[0], Payload)
    assert not isinstance(items[0], NestedNeed)
    assert isinstance(items[1], NestedNeed)
    assert items[1].nested.note.path.name == "note.txt"


def test_xor_skip_mismatch_drops_a_directory_no_arm_binds(tmp_path: Path) -> None:
    _file(tmp_path / "1", "body.txt")
    _file(tmp_path / "2", "c.txt")

    items = list(raise_mismatch(Trio.bind(tmp_path)).items)
    assert [hit.path.name for hit in items] == ["2"]
    assert isinstance(items[0], ArmC)


def test_xor_matched_name_with_no_arm_is_a_mismatch(tmp_path: Path) -> None:
    _file(tmp_path / "8", "body.txt")
    _file(tmp_path / "3", "c.txt")
    assert is_mismatch(StrictItems.bind(tmp_path))


def test_xor_one_arm_binds_and_zero_arms_fail_unless_skipped(tmp_path: Path) -> None:
    slot = tmp_path / "one" / "slot"
    _file(slot, "body.txt")
    _file(slot, "stamp.json")
    hit = raise_mismatch(OneArm.bind(tmp_path / "one")).slot
    assert isinstance(hit, Stamped)

    _file(tmp_path / "skip" / "4", "body.txt")
    assert list(raise_mismatch(ZeroSkip.bind(tmp_path / "skip")).items) == []

    (tmp_path / "strict" / "slot").mkdir(parents=True)
    err = ZeroStrict.bind(tmp_path / "strict")
    assert is_mismatch(err)
    assert em.Xor.empty(tmp_path / "strict" / "slot") in str(err)


def test_xor_positional_and_sequence_rhs_share_first_success(tmp_path: Path) -> None:
    class ByPos(Schema):
        schema = {"slot": xor(Stamped, Frame)}

    assert ByPos.slot[0] is Stamped
    with pytest.raises(KeyError):
        _ = ByPos.slot[9]

    class BySeq(Schema):
        schema = {"slot": (Stamped, Frame)}

    class ByDir(Schema):
        schema = {Dir("slot"): (Stamped, Frame)}

    class _Arms(list[type[Schema]]):
        pass

    class BySubList(Schema):
        schema = {"slot": _Arms([Stamped, Frame])}

    class ByUserList(Schema):
        schema = {"slot": UserList[type[Schema]]([Stamped, Frame])}

    slot = tmp_path / "slot"
    _file(slot, "body.txt")
    _file(slot, "frame.png")
    for schema in (ByPos, BySeq, ByDir, BySubList, ByUserList):
        hit = raise_mismatch(schema.bind(tmp_path)).slot
        assert isinstance(hit, Frame)
        assert not isinstance(hit, Stamped)

    class ByDict(Schema):
        schema = {"slot": ({"stamp": "stamp.json"}, {"frame": "frame.png"})}

    dict_slot = tmp_path / "dicts" / "slot"
    _file(dict_slot, "frame.png")
    dictated = raise_mismatch(ByDict.bind(tmp_path / "dicts")).slot
    assert dictated.frame.path.name == "frame.png"
    with pytest.raises(AttributeError):
        _ = dictated.stamp


def test_xor_plan_keeps_every_arm(tmp_path: Path) -> None:
    slot = Slot._schema_defn.defns[0]
    assert isinstance(slot, DirDefn)
    assert [layout.name for layout in slot.layouts] == ["stamp", "frame"]
    assert Slot.slot.stamp is Stamped
    assert Slot.slot.frame is Frame
    assert Slot.slot["stamp"] is Stamped
    assert Slot.slot["frame"] is Frame
    assert OneArm.slot is not Stamped
    assert OneArm.slot.stamp is Stamped
    assert OneArm.slot["stamp"] is Stamped
    planned_one = OneArm.relative_to(tmp_path).slot
    assert planned_one["stamp"].body.path.name == "body.txt"
    with pytest.raises(TypeError, match=re.escape(em.Xor.single(tmp_path / "slot"))):
        planned_one.create()
    assert Trio.relative_to(tmp_path).path == tmp_path

    planned = Slot.relative_to(tmp_path).slot
    assert planned.stamp.stamp.path.name == "stamp.json"
    assert planned.frame.frame.path.name == "frame.png"
    with pytest.raises(TypeError, match=re.escape(em.Xor.single(tmp_path / "slot"))):
        planned.create()


def test_xor_one_named_branch_from_a_dict_stays_addressable(tmp_path: Path) -> None:
    branches = {"stamp": Stamped}

    class Dynamic(Schema):
        schema = {"slot": xor(**branches)}

    assert Dynamic.slot["stamp"] is Stamped
    planned = Dynamic.relative_to(tmp_path).slot
    assert planned["stamp"].stamp.path.name == "stamp.json"
    with pytest.raises(KeyError):
        _ = Dynamic.slot["missing"]
    with pytest.raises(KeyError):
        _ = planned["missing"]


def test_xor_class_index_skips_a_branch_with_no_class() -> None:
    class Bare(Schema):
        schema = {"recv": xor(stamp=Stamped)}

    child = Bare._schema_defn.defns[0]
    assert isinstance(child, DirDefn)
    nameless = DirLayout(child.layouts[0].defns, None, "anon")
    replaced = DirDefn(child.defn, layouts=(*child.layouts, nameless))
    type.__setattr__(Bare, "_schema_defn", DirLayout((replaced,)))
    _schema_ctor_install_attrs(Bare)
    assert Bare.recv["stamp"] is Stamped
    with pytest.raises(TypeError):
        _ = Stamped["nope"]  # pyright: ignore[reportInvalidTypeArguments]
    with pytest.raises(TypeError):
        _ = Stamped[0]  # pyright: ignore[reportInvalidTypeArguments]


def test_xor_fast_still_tries_the_next_arm(tmp_path: Path) -> None:
    _file(tmp_path / "1", "payload.txt")
    (tmp_path / "1" / "nested").mkdir()

    bound = SpecificFirst.bind(tmp_path, fast=True)
    assert not is_mismatch(bound)
    hit = bound.items[0]
    assert isinstance(hit, Payload)
