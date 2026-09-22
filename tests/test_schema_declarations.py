# pyright: reportPrivateUsage=false
import re
from pathlib import Path

import pytest
from beartype.roar import BeartypeCallHintParamViolation

import fs_schema
from fs_schema import MismatchErr, _fmt, _schema


def test_declarations_are_frozen_slotted_values_with_contextual_defaults() -> None:
    fixed: _schema.File[object] = _schema.File("value.txt")
    assert fixed.name == "value.txt"
    assert fixed.min == fixed.max == 1
    assert _schema.Dir("values").max == 1
    assert _schema.File("value.txt").max == 1
    assert _schema.File(fmt="many-{n}.txt", max=3).max == 3
    pattern: _fmt.FmtLike = _fmt.dt("%Y%m%d")
    templated: _schema.File[object] = _schema.File(fmt=pattern)
    assert templated.fmt == pattern
    assert templated.max is None
    assert _schema.File(match=r"part-[0-9]+[.]txt").max is None
    assert _schema.File(fmt="{value}", match=r".+") == _schema.File(fmt="{value}", match=r".+")
    assert not hasattr(fixed, "__dict__")
    equal: _schema.File[object] = _schema.File("value.txt")
    assert hash(fixed) == hash(equal)


def test_name_and_match_are_valid_while_name_and_fmt_are_not() -> None:
    node: _schema.File[object] = _schema.File(name="value.txt", match=r"value[.]txt")
    assert node.name == "value.txt"
    assert node.match == r"value[.]txt"
    assert _schema.File(fmt="{value}", match=r".+").match == r".+"


def test_files_is_the_single_identity_token() -> None:
    assert fs_schema.FILES is _schema.FILES
    assert repr(_schema.FILES) == "FILES"


@pytest.mark.parametrize(
    ("kwargs", "message"),
    [
        ({}, "declaration requires name, fmt, or match"),
        ({"fmt": "{unclosed"}, "expected .}."),
        ({"match": "("}, "unterminated subpattern"),
        ({"name": "value", "fmt": "{value}"}, "name cannot be combined"),
        ({"name": "value", "min": -1}, "min must be at least zero"),
        ({"fmt": "{value}", "min": 2, "max": 1}, "max must be at least min"),
        ({"name": "value", "max": 2}, "exact-name max is implicit"),
        ({"name": "value", "min": 2}, "exact-name min must be 0 or 1"),
    ],
)
def test_declaration_semantic_failures(kwargs: dict[str, object], message: str) -> None:
    with pytest.raises(re.error if kwargs.get("match") == "(" else ValueError, match=message):
        _schema.File(**kwargs)  # pyright: ignore[reportArgumentType, reportCallIssue]


def test_beartype_rejects_invalid_declaration_atomic_inputs() -> None:
    with pytest.raises(BeartypeCallHintParamViolation):
        _schema.File(name=1)  # pyright: ignore[reportArgumentType]
    with pytest.raises(BeartypeCallHintParamViolation):
        _schema.Dir(min="1")  # pyright: ignore[reportCallIssue]


def test_exact_optional_sets_min_zero() -> None:
    file = _schema.File("receipt.json", optional=True)
    assert file.min == 0 and file.max == 1
    assert _schema.Dir("notes", optional=True).min == 0
    compat = _schema.File("receipt.json", min=0)  # pyright: ignore[reportCallIssue]
    assert compat == file


def test_skip_mismatch_drops_failed_file_matches_and_bad_directories(tmp_path: Path) -> None:
    (tmp_path / "part-1.txt").write_text("a")
    (tmp_path / "junk.txt").write_text("b")
    (tmp_path / "notes.md").write_text("c")
    strict = _schema.File(match=r"part-[0-9]+[.]txt", min=0)
    ignored = _schema._bind_file_matches(strict, list(tmp_path.iterdir()))
    assert not isinstance(ignored, MismatchErr)
    assert [match.path.name for match in ignored] == ["part-1.txt"]
    skipped = _schema.File(match=r"part-[0-9]+[.]txt", min=0, skip_mismatch=True)
    bound = _schema._bind_file_matches(skipped, list(tmp_path.iterdir()))
    assert not isinstance(bound, MismatchErr)
    assert [match.path.name for match in bound] == ["part-1.txt"]

    shaped = tmp_path / "shaped"
    shaped.mkdir()
    (shaped / "2.txt").write_text("no")
    (shaped / "readme").write_text("ignore")
    fmt_and_match = _schema.File(fmt="{n:d}.txt", match=r"1[.]txt", min=0)
    assert isinstance(_schema._bind_file_matches(fmt_and_match, list(shaped.iterdir())), MismatchErr)
    (shaped / "1.txt").write_text("yes")
    kept = _schema._bind_file_matches(
        _schema.File(fmt="{n:d}.txt", match=r"1[.]txt", min=0, skip_mismatch=True),
        list(shaped.iterdir()),
    )
    assert not isinstance(kept, MismatchErr)
    assert [match.path.name for match in kept] == ["1.txt"]

    class Dated(_schema.Schema):
        schema = {_schema.Dir(alias="days", fmt="{day:%Y%m%d}"): {"note": "note.json"}}

    class DatedSkip(_schema.Schema):
        schema = {_schema.Dir(alias="days", fmt="{day:%Y%m%d}", skip_mismatch=True): {"note": "note.json"}}

    root = tmp_path / "dirs"
    root.mkdir()
    (root / "20260101").mkdir()
    good = root / "20260102"
    good.mkdir()
    (good / "note.json").write_text("{}")
    assert isinstance(Dated.bind(root), MismatchErr)
    skipped_dirs = DatedSkip.bind(root)
    assert type(skipped_dirs) is DatedSkip
    hits = skipped_dirs.days
    assert len(hits) == 1  # pyright: ignore[reportArgumentType]
    assert hits[0].name == "20260102"  # pyright: ignore[reportIndexIssue, reportUnknownMemberType, reportAttributeAccessIssue]


def test_exact_name_rejects_collection_only_flags() -> None:
    def sort_key(match: _schema.Match) -> str:
        return match.path.name

    with pytest.raises(ValueError, match="sort is only valid"):
        _schema.File("value", sort=sort_key)  # pyright: ignore[reportCallIssue]
    with pytest.raises(ValueError, match="sort_rev is only valid"):
        _schema.File("value", sort_rev=True)  # pyright: ignore[reportCallIssue]
    with pytest.raises(ValueError, match="skip_mismatch is only valid"):
        _schema.File("value", skip_mismatch=True)  # pyright: ignore[reportCallIssue]


def test_collection_rejects_optional_flag() -> None:
    with pytest.raises(ValueError, match="optional is only valid"):
        _schema.File(fmt="{value}", optional=True)  # pyright: ignore[reportCallIssue]
