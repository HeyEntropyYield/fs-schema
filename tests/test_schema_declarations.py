# pyright: reportPrivateUsage=false
import re
import warnings
from pathlib import Path
from unittest.mock import patch

import pytest
from beartype.roar import BeartypeCallHintParamViolation
from pytest_params import params  # pyright: ignore[reportUnknownVariableType]

import fs_schema
from fs_schema import MismatchErr, _compile, _decl, _fmt, _schema, _types
from fs_schema import _errmsg as em


def test_declarations_are_frozen_slotted_values_with_contextual_defaults() -> None:
    fixed: _decl.File[object] = _decl.File("value.txt")
    assert fixed.name == "value.txt"
    assert fixed.min == fixed.max == 1
    assert _decl.Dir("values").max == 1
    assert _decl.File("value.txt").max == 1
    assert _decl.File(fmt="many-{n}.txt", max=3).max == 3
    pattern: _types.Raw[_types.FmtStr] = _fmt.dt("%Y%m%d")
    templated: _decl.File[object] = _decl.File(fmt=pattern)
    assert templated.fmt == pattern
    assert templated.max is None
    assert _decl.File(match=r"part-[0-9]+[.]txt").max is None
    assert _decl.File(fmt="{value}", match=r".+") == _decl.File(fmt="{value}", match=r".+")
    assert not hasattr(fixed, "__dict__")
    equal: _decl.File[object] = _decl.File("value.txt")
    assert hash(fixed) == hash(equal)


def test_fixed_name_with_a_format_field_warns() -> None:
    with pytest.warns(UserWarning, match=re.escape(em.Node.NAME_FIELD)):

        class Dated(fs_schema.Schema):  # pyright: ignore[reportUnusedClass]
            schema = {"log": "{ts:%Y%m%d}.log"}

    with pytest.warns(UserWarning, match=re.escape(em.Node.NAME_FIELD)):

        class Broken(fs_schema.Schema):  # pyright: ignore[reportUnusedClass]
            schema = {"log": "{ts.log"}

    with warnings.catch_warnings():
        warnings.simplefilter("error", UserWarning)

        class Braces(fs_schema.Schema):  # pyright: ignore[reportUnusedClass]
            schema = {"log": "a{{b}}.txt"}

        class Quiet(fs_schema.Schema):  # pyright: ignore[reportUnusedClass]
            warn = False
            schema = {"log": "{n:d}.log"}


def test_name_and_match_are_valid_while_name_and_fmt_are_not() -> None:
    node: _decl.File[object] = _decl.File(name="value.txt", match=r"value[.]txt")
    assert node.name == "value.txt"
    assert node.match == r"value[.]txt"
    assert _decl.File(fmt="{value}", match=r".+").match == r".+"


def test_schema_keyword_is_the_schema_dict(tmp_path: Path) -> None:
    class Box(_schema.Schema, schema={"manifest": "manifest.json"}):
        pass

    (tmp_path / "manifest.json").write_bytes(b"x")
    bound = Box.bind(tmp_path)
    assert isinstance(bound, Box)
    assert bound.manifest.path.name == "manifest.json"

    with pytest.raises(TypeError, match=re.escape(em.Schema.twice("Both"))):

        class Both(_schema.Schema, schema={"a": "a.txt"}):  # pyright: ignore[reportUnusedClass]
            schema = {"b": "b.txt"}


def test_files_is_the_single_identity_token() -> None:
    assert fs_schema.FILES is _decl.FILES
    assert repr(_decl.FILES) == "FILES"


@params(("kwargs", "message"), [
    ("empty", {}, em.Node.NEEDS),
    ("unclosed", {"fmt": "{unclosed"}, "expected .}."),
    ("bad match", {"match": "("}, "unterminated subpattern"),
    ("name and fmt", {"name": "value", "fmt": "{value}"}, em.Node.NAME_FMT),
    ("negative min", {"name": "value", "min": -1}, em.Node.MIN),
    ("max below min", {"fmt": "{value}", "min": 2, "max": 1}, em.Node.MAX),
    ("exact max", {"name": "value", "max": 2}, em.Node.EXACT_MAX),
    ("exact min", {"name": "value", "min": 2}, em.Node.EXACT_MIN),
])  # fmt: skip
def test_declaration_semantic_failures(kwargs: dict[str, object], message: str) -> None:
    with pytest.raises(re.error if kwargs.get("match") == "(" else ValueError, match=message):
        _decl.File(**kwargs)  # pyright: ignore[reportArgumentType, reportCallIssue]


def test_beartype_rejects_invalid_declaration_atomic_inputs() -> None:
    with pytest.raises(BeartypeCallHintParamViolation):
        _decl.File(name=1)  # pyright: ignore[reportArgumentType]
    with pytest.raises(BeartypeCallHintParamViolation):
        _decl.Dir(min="1")  # pyright: ignore[reportCallIssue]


def test_with_copies_optional_exact_name() -> None:
    required = _decl.File("receipt.json", schema=str)
    optional = required.with_(optional=True)
    assert optional == _decl.File("receipt.json", schema=str, optional=True)
    assert required.min == 1
    assert _decl.Dir("notes").with_(optional=True).min == 0
    aliased = required.with_(alias="receipt")
    assert aliased.alias == "receipt" and aliased.schema is str
    with pytest.raises(ValueError, match=re.escape(em.Node.OPTIONAL)):
        _decl.File(fmt="{value}").with_(optional=True)


def test_exact_optional_sets_min_zero() -> None:
    file = _decl.File("receipt.json", optional=True)
    assert file.min == 0 and file.max == 1
    assert _decl.Dir("notes", optional=True).min == 0
    compat = _decl.File("receipt.json", min=0)  # pyright: ignore[reportCallIssue]
    assert compat == file


def test_skip_mismatch_drops_failed_file_matches_and_bad_directories(tmp_path: Path) -> None:
    (tmp_path / "part-1.txt").write_text("a")
    (tmp_path / "junk.txt").write_text("b")
    (tmp_path / "notes.md").write_text("c")

    class Parts(_schema.Schema):
        schema = {"parts": _decl.File(match=r"part-[0-9]+[.]txt", min=0)}

    class PartsSkip(_schema.Schema):
        schema = {"parts": _decl.File(match=r"part-[0-9]+[.]txt", min=0, skip_mismatch=True)}

    strict = Parts.bind(tmp_path)
    assert type(strict) is Parts
    assert [match.path.name for match in strict.parts] == ["part-1.txt"]
    skipped = PartsSkip.bind(tmp_path)
    assert type(skipped) is PartsSkip
    assert [match.path.name for match in skipped.parts] == ["part-1.txt"]

    shaped = tmp_path / "shaped"
    shaped.mkdir()
    (shaped / "2.txt").write_text("no")
    (shaped / "readme").write_text("ignore")

    class Shaped(_schema.Schema):
        schema = {"parts": _decl.File(fmt="{n:d}.txt", match=r"1[.]txt", min=0)}

    class ShapedSkip(_schema.Schema):
        schema = {"parts": _decl.File(fmt="{n:d}.txt", match=r"1[.]txt", min=0, skip_mismatch=True)}

    shaped_failed = Shaped.bind(shaped)
    assert isinstance(shaped_failed, MismatchErr)
    assert em.Bind.failed("1[.]txt", "2.txt") in str(shaped_failed)
    (shaped / "1.txt").write_text("yes")
    kept = ShapedSkip.bind(shaped)
    assert type(kept) is ShapedSkip
    assert [match.path.name for match in kept.parts] == ["1.txt"]

    class Dated(_schema.Schema):
        schema = {_decl.Dir(alias="days", fmt="{day:%Y%m%d}"): {"note": "note.json"}}

    class DatedSkip(_schema.Schema):
        schema = {_decl.Dir(alias="days", fmt="{day:%Y%m%d}", skip_mismatch=True): {"note": "note.json"}}

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
    assert len(hits) == 1
    assert hits[0].name == "20260102"

    class DatedStrict(_schema.Schema):
        schema = {
            _decl.Dir(alias="days", fmt="{day:%Y%m%d}", match=r"20260102"): {"note": "note.json"},
        }

    failed = DatedStrict.bind(root)
    assert isinstance(failed, MismatchErr)
    assert em.Bind.failed("20260102", "20260101") in str(failed)

    class DatedSkipMatch(_schema.Schema):
        schema = {
            _decl.Dir(alias="days", fmt="{day:%Y%m%d}", match=r"20260102", skip_mismatch=True): {
                "note": "note.json",
            },
        }

    skipped_match = DatedSkipMatch.bind(root)
    assert type(skipped_match) is DatedSkipMatch
    assert [hit.name for hit in skipped_match.days] == ["20260102"]


def test_match_only_format_rejected() -> None:
    declaration = _decl.File(match=r"part-.+", min=0)
    with pytest.raises(TypeError, match=re.escape(em.Fmt.NONE)):
        declaration.selector.format()


def test_exact_name_rejects_collection_only_flags() -> None:
    def sort_key(match: _decl.Match) -> str:
        return match.path.name  # pragma: no cover

    with pytest.raises(ValueError, match=re.escape(em.Node.SORT)):
        _decl.File("value", sort=sort_key)  # pyright: ignore[reportCallIssue]
    with pytest.raises(ValueError, match=re.escape(em.Node.SORT_REV)):
        _decl.File("value", sort_rev=True)  # pyright: ignore[reportCallIssue]
    with pytest.raises(ValueError, match=re.escape(em.Node.SKIP)):
        _decl.File("value", skip_mismatch=True)  # pyright: ignore[reportCallIssue]


def test_collection_rejects_optional_flag() -> None:
    with pytest.raises(ValueError, match=re.escape(em.Node.OPTIONAL)):
        _decl.File(fmt="{value}", optional=True)  # pyright: ignore[reportCallIssue]


def test_a_name_that_will_not_fold_is_a_basename_error() -> None:
    class Note(_schema.Schema):
        schema = {"note": "note.txt"}

    with (
        patch.object(_decl, "normalize_name", return_value=None),
        pytest.raises(ValueError, match=re.escape(em.Fmt.basename("note.txt"))),
    ):
        _decl._dir_defn_ctor_uniq_lookups_exn((_decl.File("note.txt"),))
    with patch.object(_compile, "normalize_name", return_value=None):
        error = _compile.schema_ctor_check_defn_shadows(Note)
    assert isinstance(error, ValueError)
    assert str(error) == em.Fmt.basename("note.txt")
