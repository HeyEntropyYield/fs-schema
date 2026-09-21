# pyright: reportPrivateUsage=false
import re
from pathlib import Path

import pytest
from beartype.roar import BeartypeCallHintParamViolation

import fs_schema
from fs_schema import _fmt, _schema


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


def test_collection_skip_mismatch_is_stored_without_binding_change(tmp_path: Path) -> None:
    declaration = _schema.File(match=r"part-[0-9]+[.]txt", skip_mismatch=True, min=0)
    assert declaration.skip_mismatch is True
    (tmp_path / "part-1.txt").write_text("a")
    (tmp_path / "junk.txt").write_text("b")
    bound = _schema._bind_file_matches(declaration, list(tmp_path.iterdir()))
    assert [match.path.name for match in bound] == ["part-1.txt"]


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
