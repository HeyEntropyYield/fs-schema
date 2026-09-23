# pyright: reportPrivateUsage=false, reportArgumentType=false, reportUnknownMemberType=false
# pyright: reportUnknownArgumentType=false, reportUnknownVariableType=false, reportUnknownLambdaType=false
from collections.abc import Iterator
from pathlib import Path
from typing import ClassVar

import pytest

from fs_schema import FILES, Dir, File, Schema
from fs_schema._schema import DirDefn, FixedFile, Matches, Template


def _define(layout: object) -> type[Schema]:
    return type("Invalid", (Schema,), {"schema": layout})


def test_reifies_each_raw_grammar_branch_and_stable_class_navigation() -> None:
    class Explicit(Schema):
        schema = {"leaf": "leaf.txt"}

    class LayoutSchema(Schema):
        schema = {
            FILES: ["loose.txt", File(fmt="part-{part:d}.txt", alias="parts")],
            "explicit": Explicit,
            Dir(alias="runs", fmt="run-{run:d}"): {"deep": {"leaf": "nested.txt"}},
            "named": File("named.txt"),
        }

    root = LayoutSchema._schema_defn
    assert [type(defn) for defn in root.defns] == [File, File, DirDefn, DirDefn, File]
    assert LayoutSchema.loose_txt is FixedFile
    assert LayoutSchema.parts is Template
    assert LayoutSchema.explicit is Explicit
    assert LayoutSchema.explicit.leaf is FixedFile
    assert LayoutSchema.runs is Template
    runs = root.defns[3]
    assert isinstance(runs, DirDefn)
    assert runs.child_type is not None
    assert runs.child_type.deep is runs.child_type.deep
    assert runs.child_type.deep.leaf is FixedFile
    assert LayoutSchema.named is FixedFile
    assert not hasattr(LayoutSchema, "unknown")
    assert not hasattr(LayoutSchema, "loose.txt")
    assert not hasattr(LayoutSchema, "__parameters__")


@pytest.mark.parametrize(
    "layout",
    [
        [],
        {FILES: "bad"},
        {FILES: [42]},
        {Dir("bad"): 42},
        {"bad": 42},
        {42: "bad"},
        {FILES: [File(".")]},
        {FILES: [File("nested/file")]},
        {FILES: [File("ok", alias="not-valid")]},
        {FILES: [File("ok", alias="class")]},
        {FILES: [File("ok", alias="_private")]},
    ],
)
def test_invalid_layouts_fail_at_class_creation_with_context(layout: object) -> None:
    with pytest.raises(TypeError, match=r"Invalid[.]schema"):
        _define(layout)


def test_invalid_dir_schema_is_reported_at_containing_class_creation() -> None:
    invalid = Dir("bad")
    object.__setattr__(invalid, "schema", object)
    with pytest.raises(TypeError, match=r"Invalid[.]schema declaration .* Dir[.]schema must be a Schema subclass"):
        _define({invalid: {}})


def test_files_is_list_only_uses_singleton_identity_and_reports_bad_member() -> None:
    with pytest.raises(TypeError, match=r"key FILES requires a list"):
        _define({FILES: ("bad",)})
    with pytest.raises(TypeError, match=r"key FILES member 42 must be a str or File"):
        _define({FILES: [42]})
    with pytest.raises(TypeError, match=r"invalid entry at key FILES"):
        _define({type(FILES)(): []})


def test_mapping_alias_reuses_or_replaces_file_without_wrapper() -> None:
    same = File("same.txt", alias="same")
    changed: File[int] = File("changed.txt", alias="old", schema=lambda _path: 1)

    class Aliased(Schema):
        schema = {"same": same, "new": changed}

    first, second = Aliased._schema_defn.defns
    assert first is same
    assert type(second) is File and second is not changed
    assert isinstance(second, File)
    assert second.alias == "new" and second.name == "changed.txt" and second.schema is changed.schema
    assert not hasattr(second, "source")


def test_single_inheritance_replaces_by_identity_without_local_metadata() -> None:
    class Base(Schema):
        schema = {
            "value": "base.txt",
            "other": "other.txt",
            FILES: [File("named.txt"), File(fmt="part-{part:d}.txt"), File(match="first")],
        }

    class Derived(Base):
        schema = {
            "value": {"child": "child.txt"},
            FILES: [
                File("named.txt", match=r"named[.]txt"),
                File(fmt="part-{part:d}.txt", min=0),
                File(match="second"),
            ],
        }

    class InheritedOnly(Derived):
        pass

    nodes = [defn.defn if isinstance(defn, DirDefn) else defn for defn in Derived._schema_defn.defns]
    assert [node.alias or node.name or node.fmt or None for node in nodes] == [
        "value",
        "other",
        "named.txt",
        "part-{part:d}.txt",
        None,
        None,
    ]
    assert isinstance(Derived._schema_defn.defns[0], DirDefn)
    assert isinstance(Derived._schema_defn.defns[3], File)
    assert Derived._schema_defn.defns[2].match == r"named[.]txt"  # pyright: ignore[reportAttributeAccessIssue]
    assert Derived._schema_defn.defns[3].min == 0
    assert [node.match for node in nodes if not (node.alias or node.name or node.fmt)] == ["first", "second"]
    assert InheritedOnly._schema_defn.defns == Derived._schema_defn.defns
    assert InheritedOnly.value is Derived.value

    class Append(Base):
        schema = {FILES: [File("new.txt")]}

    appended = Append._schema_defn.defns[-1]
    assert isinstance(appended, File) and appended.name == "new.txt"
    assert "_local_defns" not in Derived.__dict__
    assert "_schema_defn" in Derived.__dict__


def test_mapping_alias_identity_overrides_names_and_kinds() -> None:
    class Base(Schema):
        schema = {"value": "base.txt", "other": "other.txt"}

    class Renamed(Base):
        schema = {"value": File("renamed.txt", alias="ignored")}

    class CrossKind(Renamed):
        schema = {"value": {}}

    assert [defn.name for defn in Renamed._schema_defn.defns if isinstance(defn, File)] == [
        "renamed.txt",
        "other.txt",
    ]
    assert Renamed._schema_defn.defns[0].alias == "value"  # pyright: ignore[reportAttributeAccessIssue]
    assert isinstance(CrossKind._schema_defn.defns[0], DirDefn)
    assert CrossKind.value is not FixedFile


def test_empty_alias_and_match_only_declarations_are_anonymous() -> None:
    class Base(Schema):
        schema = {FILES: [File(match="first", alias="")]}

    class Derived(Base):
        schema = {FILES: [File(match="second", alias="")]}

    assert len(Derived._schema_defn.defns) == 2
    assert Derived._schema_defn.lookup == {}


def test_dir_schema_is_a_class_time_structural_requirement() -> None:
    class RequiredBase(Schema):
        schema = {"required": "required.txt", "nested": {"leaf": "leaf.txt"}}

    class Required(RequiredBase):
        pass

    class Independent(Schema):
        schema = {
            "required": "required.txt",
            "nested": {"leaf": "leaf.txt", "extra_nested": "extra-nested.txt"},
            "extra": "extra.txt",
        }

    class ViaInheritance(Independent):
        schema = {"more": "more.txt"}

    class Accepted(Schema):
        schema = {
            Dir("explicit", schema=Required): Independent,
            Dir("inherited", schema=Required): ViaInheritance,
            Dir("inline", schema=Required): {
                "required": "required.txt",
                "nested": {"leaf": "leaf.txt", "extra_nested": "extra-nested.txt"},
            },
        }

    assert Accepted.explicit is Independent
    assert Accepted.inherited is ViaInheritance
    assert issubclass(Accepted.inline, Schema)


@pytest.mark.parametrize(
    "rhs",
    [
        {"nested": {"leaf": "leaf.txt"}},
        {"required": File("different.txt"), "nested": {"leaf": "leaf.txt"}},
        {"required": "required.txt", "nested": {}},
        {"required": "required.txt", Dir("nested", match="nested"): {"leaf": "leaf.txt"}},
    ],
)
def test_dir_schema_rejects_missing_or_unequal_required_declarations(rhs: object) -> None:
    class Required(Schema):
        schema = {"required": "required.txt", "nested": {"leaf": "leaf.txt"}}

    with pytest.raises(TypeError, match=r"Invalid[.]schema declaration .* RHS does not satisfy Dir[.]schema"):
        _define({Dir("candidate", schema=Required): rhs})


def test_dir_schema_preserves_anonymous_requirement_multiplicity() -> None:
    class Required(Schema):
        schema = {FILES: [File(match="same"), File(match="same")]}

    class Candidate(Schema):
        schema = {FILES: [File(match="same")]}

    with pytest.raises(TypeError, match=r"Invalid[.]schema declaration .* RHS does not satisfy Dir[.]schema"):
        _define({Dir("candidate", schema=Required): Candidate})


def test_dir_schema_accepts_recursive_anonymous_requirements_with_extra_children() -> None:
    class Required(Schema):
        schema = {Dir(match=r"item-.+"): {"leaf": "leaf.txt"}}

    class Candidate(Schema):
        schema = {Dir(match=r"item-.+"): {"leaf": "leaf.txt", "extra": "extra.txt"}}

    class Root(Schema):
        schema = {Dir("candidate", schema=Required): Candidate}

    class EmptyRequired(Schema):
        pass

    class EmptyAccepted(Schema):
        schema = {Dir("empty", schema=EmptyRequired): {}}

    assert Root.candidate is Candidate
    assert issubclass(EmptyAccepted.empty, Schema)


def test_repeated_class_navigation_is_not_a_reusable_schema_declaration() -> None:
    class Parent(Schema):
        schema = {Dir(fmt="item-{n:d}", alias="items"): {}}

    assert Parent.items is Template
    with pytest.raises(TypeError, match=r"Invalid[.]schema invalid entry at key 'reused'"):
        _define({"reused": Parent.items})


def test_schema_declarations_compile_without_filesystem_io(monkeypatch: pytest.MonkeyPatch) -> None:
    def fail(_path: Path) -> Iterator[Path]:
        raise AssertionError("class definition performed filesystem I/O")

    monkeypatch.setattr(Path, "iterdir", fail)

    class NoIo(Schema):
        schema = {"nested": {FILES: [File(fmt="part-{n:d}", min=0)]}}

    assert issubclass(NoIo.nested, Schema)


def test_schema_policy_allows_passive_metadata_but_protects_critical_behavior() -> None:
    class Empty(Schema):
        """Passive declaration metadata."""

        note: ClassVar[int]
        constant = 42

    class Child(Empty):
        schema = {}

    assert Child.constant == 42 and Child._schema_defn.defns == ()

    critical = {
        "construction": {"__init__": lambda self: None},
        "storage": {"path": None},
        "binding": {"bind": lambda self: None},
        "navigation": {"__getitem__": lambda self, key: None},
    }
    for role, namespace in critical.items():
        with pytest.raises(TypeError, match=f"Bad_{role}"):
            type(f"Bad_{role}", (Schema,), {"__module__": __name__, **namespace})


@pytest.mark.parametrize("name", ["args", "kwargs"])
def test_schema_policy_reserves_match_members(name: str) -> None:
    with pytest.raises(TypeError, match=rf"CaptureMember Schema declaration cannot override '{name}'"):
        type("CaptureMember", (Schema,), {name: object()})


@pytest.mark.parametrize(
    "layout",
    [
        {FILES: [File("args")]},
        {FILES: [File("value", alias="kwargs")]},
        {"bind": "value"},
        {FILES: [File("path")]},
    ],
)
def test_schema_policy_rejects_reserved_navigation_names(layout: object) -> None:
    with pytest.raises(TypeError, match=r"Reserved[.]schema child .* shadows a Schema member"):
        type("Reserved", (Schema,), {"schema": layout})


def test_schema_policy_rejects_mixins_multiple_inheritance_and_custom_metaclass() -> None:
    events: list[str] = []

    class Mixin:
        def __init_subclass__(cls) -> None:
            events.append(cls.__name__)

    with pytest.raises(TypeError, match="exactly one direct Schema base"):
        type("BadLeft", (Mixin, Schema), {})
    with pytest.raises(TypeError, match="exactly one direct Schema base"):
        type("BadRight", (Schema, Mixin), {})

    class Left(Schema):
        pass

    class Right(Schema):
        pass

    with pytest.raises(TypeError, match="exactly one direct Schema base"):
        type("Diamond", (Left, Right), {})
    assert events == []

    class CustomMeta(type(Schema)):
        pass

    with pytest.raises(TypeError, match="exact Schema metaclass"):
        CustomMeta("BadMeta", (Schema,), {})


@pytest.mark.parametrize(
    ("first", "second", "collision"),
    [
        (File("same", alias="first"), File("same", alias="second"), "same"),
        (File("same"), File("other", alias="same"), "same"),
        (File("first", alias="shared"), File("second", alias="shared"), "shared"),
        (File("same_name", alias="first"), File("same-name", alias="second"), "same_name"),
        (File("first", alias="same_name"), File("same-name", alias="second"), "same_name"),
        (
            File(fmt="part-{n:d}", alias="first"),
            File(fmt="part-{n:d}", alias="second"),
            "part-{n:d}",
        ),
    ],
)
def test_name_alias_normalized_and_format_collisions_fail_at_class_creation(
    first: File[object], second: File[object], collision: str
) -> None:
    with pytest.raises(TypeError, match=rf"Invalid[.]schema duplicate child key: {collision!r}"):
        _define({FILES: [first, second]})


def test_inherited_identity_overrides_are_permissive_but_effective_collisions_fail() -> None:
    class Base(Schema):
        schema = {
            FILES: [
                File("named", match="base"),
                File("old", alias="aliased"),
                File(fmt="part-{n:d}"),
            ]
        }

    class Override(Base):
        schema = {
            FILES: [
                File("named", match="derived"),
                File("new", alias="aliased"),
                File(fmt="part-{n:d}", min=0),
            ]
        }

    assert [node.name for node in Override._schema_defn.defns if isinstance(node, File)] == ["named", "new", ""]
    assert Override._schema_defn.defns[0].match == "derived"  # pyright: ignore[reportAttributeAccessIssue]
    assert Override._schema_defn.defns[2].min == 0  # pyright: ignore[reportAttributeAccessIssue]

    with pytest.raises(TypeError, match="duplicate child key: 'aliased'"):
        type(
            "Collision",
            (Override,),
            {"schema": {FILES: [File("aliased", alias="fresh")]}},
        )


def test_coincident_identities_on_one_child_are_valid() -> None:
    class Coincident(Schema):
        schema = {FILES: [File("same", alias="same"), File(match="part-.+", alias="parts")]}

    assert Coincident.same is FixedFile
    assert Coincident.parts is Matches
