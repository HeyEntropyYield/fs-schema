# pyright: reportPrivateUsage=false
import re
from datetime import date, datetime, time
from decimal import Decimal
from functools import partial
from pathlib import Path
from typing import get_args

import pytest
from beartype.roar import BeartypeCallHintParamViolation
from pytest_params import params  # pyright: ignore[reportUnknownVariableType]

from fs_schema import _errmsg as em
from fs_schema import _fmt, _fmt_spec, _types


def _compile(pattern: str) -> _fmt.CompiledFormat:
    return _fmt.CompiledFormat(_types.Raw[_types.FmtStr](pattern))


def _name(text: str) -> _types.Safe[_types.Name]:
    safe_name = _fmt.safe(_types.Raw[_types.Name](text))
    assert safe_name is not None
    return safe_name


def test_capture_map_supports_keys_attributes_and_mapping_collisions() -> None:
    captures = _fmt.CaptureMap({"part": 2, "label": "ready", "items": "collision"})
    assert dict(captures) == {"part": 2, "label": "ready", "items": "collision"}
    assert captures.part == 2
    assert captures["items"] == "collision"
    assert callable(captures.items)
    with pytest.raises(KeyError, match="missing"):
        _ = captures["missing"]
    with pytest.raises(AttributeError, match="missing"):
        _ = captures.missing
    absent = _fmt.CaptureMap({"part": None})
    with pytest.raises(KeyError, match="missing"):
        absent.render_exn("missing")
    with pytest.raises(TypeError, match=re.escape(em.Schema.Body.unbound("part"))):
        absent.render_exn("part")


def test_compiled_format_round_trips_named_string_and_integer_fields() -> None:
    compiled = _compile("part-{part:d}-{label}.json")
    assert compiled.pattern == "part-{part:d}-{label}.json"
    assert compiled.fields == (
        _fmt.FormatField("part", 0, "d"),
        _fmt.FormatField("label", 1),
    )
    assert all(type(field) is _fmt.FormatField for field in compiled.fields)
    assert all(not field.positional for field in compiled.fields)
    basename = compiled.format(part=2, label="ready")
    assert basename == "part-2-ready.json"
    parsed = compiled.parse(_name(basename))
    assert isinstance(parsed, _fmt.ParsedCaptures)
    assert parsed.args == ()
    assert type(parsed.kwargs) is _fmt.CaptureMap
    assert parsed.kwargs == {"part": 2, "label": "ready"}


def test_compiled_format_round_trips_auto_and_numbered_positional_fields() -> None:
    automatic = _compile("{}-{:d}")
    assert automatic.fields == (
        _fmt.FormatField("", 0),
        _fmt.FormatField("", 1, "d"),
    )
    assert all(field.positional for field in automatic.fields)
    basename = automatic.format("name", 3)
    assert basename == "name-3"
    parsed = automatic.parse(_name(basename))
    assert parsed is not None
    assert parsed.args == ("name", 3)
    assert parsed.kwargs == {}

    numbered = _compile("{0}-{1:d}")
    assert all(field.positional for field in numbered.fields)
    assert numbered.format("item", 4) == "item-4"
    parsed_numbered = numbered.parse(_name("item-4"))
    assert parsed_numbered is not None
    assert parsed_numbered.args == ("item", 4)


def test_datetime_formats_round_trip_named_and_public_dt_fields() -> None:
    moment = datetime(2026, 9, 14, 19, 51)
    named = _compile("run-{moment:%Y%m%d-%H%M}")
    assert named.fields == (_fmt.FormatField("moment", 0, "%Y%m%d-%H%M"),)
    assert type(named.fields[0]) is _fmt.FormatField
    basename = named.format(moment=moment)
    assert basename == "run-20260914-1951"
    parsed = named.parse(_name(basename))
    assert parsed is not None
    assert parsed.kwargs == {"moment": moment}

    date_pattern: _types.Raw[_types.FmtStr] = _fmt.dt("%Y%m%d")
    date_only = _fmt.CompiledFormat(date_pattern)
    assert date_only.format(ts=moment) == "20260914"
    parsed_date = date_only.parse(_name("20260914"))
    assert parsed_date is not None
    assert parsed_date.kwargs == {"ts": datetime(2026, 9, 14)}

    positional = _fmt.CompiledFormat(_fmt.dt("%Y%m%d", ""))
    assert positional.format(moment) == "20260914"
    parsed_positional = positional.parse(_name("20260914"))
    assert parsed_positional is not None
    assert parsed_positional.args == (datetime(2026, 9, 14),)


def test_parser_requires_a_complete_case_sensitive_basename() -> None:
    compiled = _compile("Part-{part:d}.json")
    assert compiled.parse(_name("Part-1.json")) is not None
    assert compiled.parse(_name("part-1.json")) is None
    assert compiled.parse(_name("prefix-Part-1.json")) is None
    assert compiled.parse(_name("Part-1.json.bak")) is None


def test_malformed_pattern_surfaces_native_failure() -> None:
    with pytest.raises(ValueError):
        _compile("{unclosed")


@params("pattern", [("clock", "{value:%H:%M}"), ("named", "{value:tt}")])
def test_time_only_capture_fails_when_the_pattern_is_compiled(pattern: str) -> None:
    with pytest.raises(TypeError, match=em.Fmt.TIME):
        _compile(pattern)


def test_time_value_is_rejected_if_parse_yields_one() -> None:
    with pytest.raises(TypeError, match=em.Fmt.TIME):
        _fmt_spec.value_exn(time(19, 51))


@params(("pattern", "kind"), [
    ("float", "{value:f}", "float"),
    ("percent", "{value:%}", "float"),
    ("decimal", "{value:F}", "Decimal"),
])  # fmt: skip
def test_other_parsed_types_fail_when_the_pattern_is_compiled(pattern: str, kind: str) -> None:
    with pytest.raises(TypeError, match=em.Fmt.value(kind)):
        _compile(pattern)


def test_strftime_spec_with_a_bad_directive_fails() -> None:
    # Parser accepts this because it contains %Y. strptime rejects %Q
    with pytest.raises(TypeError, match=em.Fmt.value("%Y%Q")):
        _compile("{value:%Y%Q}")


def test_unknown_converter_is_rejected() -> None:
    def odd(_text: str, _match: object) -> str: ...

    with pytest.raises(TypeError, match=em.Fmt.value("function")):
        _fmt_spec._sample_exn(partial(odd))
    with pytest.raises(TypeError, match=em.Fmt.value("object")):
        _fmt_spec._sample_exn(object())


def test_named_date_spec_parses_datetime() -> None:
    compiled = _compile("{value:ti}")
    parsed = compiled.parse(_name("2001-02-03T04:05:06"))
    assert parsed is not None
    assert parsed.kwargs == {"value": datetime(2001, 2, 3, 4, 5, 6)}


def test_format_types_are_exact_and_atomic_inputs_are_beartyped() -> None:
    assert set(get_args(_types.FmtFieldT)) == {str, int, datetime}
    assert set(get_args(_fmt.CaptureField)) == {str, int, datetime, type(None)}
    assert set(get_args(_fmt_spec._Field)) == {str, int, float, Decimal, date, time, datetime}

    with pytest.raises(BeartypeCallHintParamViolation):
        _fmt.dt(1)  # pyright: ignore[reportArgumentType]
    with pytest.raises(BeartypeCallHintParamViolation):
        _fmt.CompiledFormat(1)  # pyright: ignore[reportArgumentType]
    with pytest.raises(BeartypeCallHintParamViolation):
        _compile("{value}").format(value=1.5)  # pyright: ignore[reportArgumentType]
    with pytest.raises(BeartypeCallHintParamViolation):
        _compile("{value}").format(value=None)  # pyright: ignore[reportArgumentType]


def test_refs_preview_and_escape_before_the_basename_check() -> None:
    assert _fmt.close_exn(_types.Raw[_types.Name]("plain.txt"), None) == "plain.txt"
    assert _fmt.close_exn(_types.Raw[_types.Name]("a/<b>.txt"), None) == "a<b>.txt"
    assert _fmt.safe(_types.Raw[_types.Name]("a/<b>.txt")) == "a<b>.txt"
    assert _fmt.safe(_types.Raw[_types.Name]("a<b>.txt")) is None
    assert _fmt.safe(_types.Raw[_types.Name]("<ts>.log")) is None
    opened = _fmt.open_str(_types.Raw[_types.Name]("a/<b>_<ts:%Y%m%d>.txt"))
    assert opened == "a/<b>_<ts:%Y%m%d>.txt"
    assert isinstance(opened, _types.Open) and not isinstance(opened, _types.Safe)
    assert _fmt.safe(_types.Raw[_types.Name]("a/b.txt")) is None
    _compile("a/<{n}")
    with pytest.raises(ValueError, match=re.escape(em.Fmt.literal("a\\b{n}"))):
        _compile("a\\b{n}")
    with pytest.raises(ValueError, match=re.escape(em.Schema.Body.unbound("ts"))):
        _fmt.close_exn(_types.Raw[_types.Name]("<ts>.log"), None)


@params(("pattern", "message"), [
    ("slash", "a/{x}", em.Fmt.literal("a/{x}")),
    ("backslash", "a\\{x}", em.Fmt.literal("a\\{x}")),
    ("nul", "a\0{x}", em.Fmt.literal("a\0{x}")),
    ("dot", ".", em.Fmt.basename(".")),
    ("dotdot", "..", em.Fmt.basename("..")),
    ("underscore", "{_n}", em.Fmt.field("_n")),
    ("digit_name", "{0d}", em.Fmt.field("0d")),
    ("space", "{ d}", em.Fmt.field(" d")),
    ("field", "{foo.bar}", em.Fmt.field("foo.bar")),
    ("index", "{foo[0]}", em.Fmt.field("foo[0]")),
    ("conversion", "{x!r}", em.Fmt.CONV),
])  # fmt: skip
def test_format_pattern_rejects_unsafe_literals_fields_and_conversions(pattern: str, message: str) -> None:
    with pytest.raises(ValueError, match=re.escape(message)):
        _compile(pattern)


def test_literal_basename_pattern_is_safe_and_a_dotted_field_pattern_stays() -> None:
    assert _compile("file.txt").format() == "file.txt"
    assert _compile("{stem}.json").format(stem="a") == "a.json"


def test_safe_path_accepts_an_anchor_and_rejects_a_bad_component() -> None:
    root = _fmt._safe_path(Path("/"))
    assert root is not None
    assert root == Path("/")
    assert _fmt.path_name_exn(root) == ""
    with pytest.raises(ValueError, match=re.escape(em.Fmt.basename("a/../b"))):
        _fmt.safe_path_exn(Path("a/../b"))


def test_filesystem_root_has_no_component_and_dot_paths_fail() -> None:
    root = _fmt.safe_path_exn(Path("/"))
    name = _fmt.path_name_exn(root)
    assert name == ""
    assert isinstance(name, _types.Safe)
    assert isinstance(name, _types.Open) and isinstance(name, _types.Resolved)
    assert _fmt.child_path_exn(root, name) == root
    assert _fmt.child_path_exn(root, _types.Safe[_types.Name](".")) == root
    assert _fmt.child_path_exn(root, _name("etc")) == Path("/etc")
    assert _fmt.path_name_exn(_fmt.safe_path_exn(Path("/etc"))) == "etc"
    assert _fmt.safe_path_exn(Path("/.")) == Path("/")
    assert _fmt.safe_path_exn(Path("//")) == Path("//")
    assert _fmt.path_name_exn(_fmt.safe_path_exn(Path("//"))) == ""
    assert _fmt.safe_path_exn(Path("///")) == Path("/")
    assert _fmt.child_path_exn(_fmt.safe_path_exn(Path("//")), _name("etc")) == Path("//") / "etc"
    relative = _fmt.safe_path_exn(Path("foo/bar"))
    assert relative.name == "bar" and _fmt.path_name_exn(relative) == "bar"
    assert _fmt.safe(_types.Raw[_types.Name]("")) is None
    assert _fmt.safe(_types.Raw[_types.Name](".")) is None
    assert _fmt.safe(_types.Raw[_types.Name]("..")) is None
    assert _fmt.safe(_types.Safe[_types.Name]("")) == ""
    assert _fmt.safe(_types.Safe[_types.Name](".")) == "."
    for text in (".", "", "..", "/..", "/foo/..", "foo/../bar", "a\\b", "a\0b"):
        with pytest.raises(ValueError, match=re.escape(em.Fmt.basename(Path(text).as_posix()))):
            _fmt.safe_path_exn(Path(text))


def test_format_spec_cannot_contain_a_capture() -> None:
    with pytest.raises(ValueError, match=re.escape(em.Fmt.spec("<ts>"))):
        _compile("{n:<ts>}")
    with pytest.raises(ValueError, match=re.escape(em.Fmt.spec("a<b"))):
        _compile("{n:a<b}")
    with pytest.raises(ValueError, match=re.escape("format spec '/' not recognised")):
        _compile("{n:/}")
    with pytest.raises(ValueError, match="format spec"):
        _compile("{n:\\}")
    dotted = _compile(".{n}")
    assert [(field.field_name, field.field_spec) for field in dotted.fields] == [("n", "")]
    empty_spec = _compile("{n:}")
    assert [(field.field_name, field.field_spec) for field in empty_spec.fields] == [("n", "")]
    compiled = _compile("file_<ts>_{n:d}.txt")
    assert [(field.field_name, field.field_spec) for field in compiled.fields] == [("n", "d")]
    assert isinstance(compiled.pattern, _types.Open)
    assert not isinstance(compiled.pattern, _types.Safe)
    assert _fmt.valid_fmt_exn("") is None
    assert _fmt.valid_fmt_exn(None) is None


def test_ref_stand_in_and_filled_text_must_be_one_component() -> None:
    assert _fmt.open_str(_types.Raw[_types.Name]("<a>/b.txt")) is None
    assert _fmt.open_str(_types.Raw[_types.Name]("<a>\\b")) is None
    assert _fmt.open_str(_types.Raw[_types.Name]("<a>\0b")) is None
    escaped = _fmt.open_str(_types.Raw[_types.Name]("../<a>"))
    assert escaped == "..<a>"
    assert isinstance(escaped, _types.Safe)
    assert _fmt._safe_ish(_types.Raw[_types.Name]("")) is None
    kept = _types.Safe[_types.Name]("")
    assert _fmt._resolve(kept) == ""
    assert _fmt._safe(kept) == ""
    with pytest.raises(ValueError, match=re.escape(em.Fmt.basename("a/b"))):
        _fmt.close_exn(_types.Raw[_types.Name]("<n>"), _fmt.CaptureMap({"n": "a/b"}))
    with pytest.raises(ValueError, match=re.escape(em.Fmt.basename("a<b>"))):
        _fmt.close_exn(_types.Raw[_types.Name]("<n>"), _fmt.CaptureMap({"n": "a<b>"}))
    with pytest.raises(ValueError, match=re.escape(em.Fmt.basename(""))):
        _fmt.close_exn(_types.Raw[_types.Name]("<n>"), _fmt.CaptureMap({"n": ""}))
    with pytest.raises(ValueError, match=re.escape(em.Fmt.basename(".."))):
        _fmt.close_exn(_types.Raw[_types.Name]("<n>"), _fmt.CaptureMap({"n": ".."}))
    with pytest.raises(ValueError, match=re.escape(em.Fmt.basename("."))):
        _fmt.close_exn(_types.Raw[_types.Name]("<n>"), _fmt.CaptureMap({"n": "."}))
