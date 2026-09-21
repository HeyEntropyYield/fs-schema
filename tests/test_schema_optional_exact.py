# pyright: reportPrivateUsage=false, reportUnknownMemberType=false
# pyright: reportUnknownArgumentType=false, reportUnknownVariableType=false
# pyright: reportAttributeAccessIssue=false, reportCallIssue=false
# pyright: reportAssignmentType=false, reportOptionalMemberAccess=false
# pyright: reportIndexIssue=false
from pathlib import Path

from fs_schema import Dir, File, Match, MismatchErr, Schema, SchemaRoot
from fs_schema._schema import FixedFile, Template


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


def _write_required(root: Path) -> None:
    (root / "manifest.json").write_text("{}")


def test_exact_name_optional_defaults_max_to_one() -> None:
    file = File("receipt.json", optional=True)
    folder = Dir("notes", optional=True)
    assert file.name == "receipt.json" and file.min == 0 and file.max == 1
    assert folder.name == "notes" and folder.min == 0 and folder.max == 1


def test_planned_optional_scalar_has_the_candidate_path(tmp_path: Path) -> None:
    root = tmp_path / "delivery-42"
    placed = Delivery.relative_to(root)
    assert isinstance(placed, SchemaRoot)
    assert placed.receipt.path == root / "receipt.json"
    assert placed.notes.path == root / "notes"
    placed.manifest.put("{}")
    placed.receipt.put("{}")
    assert (root / "manifest.json").read_text() == "{}"
    assert (root / "receipt.json").read_text() == "{}"


def test_bind_optional_file_is_none_when_absent(tmp_path: Path) -> None:
    _write_required(tmp_path)
    bound = Delivery.bind(tmp_path)
    assert type(bound) is Delivery
    assert bound.receipt is None
    assert bound.notes is None


def test_bind_optional_file_is_the_same_type_as_required_when_present(tmp_path: Path) -> None:
    _write_required(tmp_path)
    (tmp_path / "receipt.json").write_text("{}")
    bound = Delivery.bind(tmp_path)
    assert type(bound) is Delivery
    assert type(bound.receipt) is type(bound.manifest) is FixedFile
    assert bound.receipt.path == tmp_path / "receipt.json"
    assert bound.receipt.read_text() == "{}"


def test_bind_optional_file_wrong_kind_is_mismatch(tmp_path: Path) -> None:
    _write_required(tmp_path)
    (tmp_path / "receipt.json").mkdir()
    assert isinstance(Delivery.bind(tmp_path), MismatchErr)


def test_optional_dir_schema_rhs_absent_present_and_invalid(tmp_path: Path) -> None:
    _write_required(tmp_path)
    absent = Delivery.bind(tmp_path)
    assert type(absent) is Delivery
    assert absent.notes is None

    notes = tmp_path / "notes"
    notes.mkdir()
    (notes / "README.md").write_text("ok")
    present = Delivery.bind(tmp_path)
    assert type(present) is Delivery
    assert type(present.notes) is Notes
    assert present.notes.readme.path.name == "README.md"

    (notes / "README.md").unlink()
    assert isinstance(Delivery.bind(tmp_path), MismatchErr)


def test_write_optional_after_bind_goes_through_root(tmp_path: Path) -> None:
    _write_required(tmp_path)
    bound = Delivery.bind(tmp_path)
    assert type(bound) is Delivery and bound.receipt is None
    bound.root().receipt.put("{}")
    rebound = Delivery.bind(bound)
    assert type(rebound) is Delivery
    assert rebound.receipt is not None
    assert rebound.receipt.read_text() == "{}"


def test_repeated_schema_elements_are_the_declared_class_with_captures(tmp_path: Path) -> None:
    _write_required(tmp_path)
    day = tmp_path / "2026-09-17"
    day.mkdir()
    (day / "part-1.jsonl").write_text("a")
    (day / "part-2.jsonl").write_text("b")
    bound = Delivery.bind(tmp_path)
    assert type(bound) is Delivery
    assert isinstance(bound.days, Template)
    first = bound.days[0]
    assert isinstance(first, Batch) and isinstance(first, Match)
    assert type(first) is not Batch
    assert issubclass(type(first), Batch)
    assert first.kwargs["day"].year == 2026
    assert first.parts[0].path.name == "part-1.jsonl"
