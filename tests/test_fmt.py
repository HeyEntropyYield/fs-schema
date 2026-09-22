# pyright: reportPrivateUsage=false
from datetime import date, datetime, time
from typing import get_args

import pytest
from beartype.roar import BeartypeCallHintParamViolation

from fs_schema import _fmt


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


def test_compiled_format_round_trips_named_string_and_integer_fields() -> None:
    compiled = _fmt.CompiledFormat("part-{part:d}-{label}.json")
    assert compiled.pattern == "part-{part:d}-{label}.json"
    assert compiled.fields == (
        _fmt.FormatField("part", 0, "d"),
        _fmt.FormatField("label", 1),
    )
    assert all(type(field) is _fmt.FormatField for field in compiled.fields)
    assert all(not field.positional for field in compiled.fields)
    basename = compiled.format(part=2, label="ready")
    assert basename == "part-2-ready.json"
    parsed = compiled.parse(basename)
    assert isinstance(parsed, _fmt.ParsedCaptures)
    assert parsed.args == ()
    assert type(parsed.kwargs) is _fmt.CaptureMap
    assert parsed.kwargs == {"part": 2, "label": "ready"}


def test_compiled_format_round_trips_auto_and_numbered_positional_fields() -> None:
    automatic = _fmt.CompiledFormat("{}-{:d}")
    assert automatic.fields == (
        _fmt.FormatField("", 0),
        _fmt.FormatField("", 1, "d"),
    )
    assert all(field.positional for field in automatic.fields)
    basename = automatic.format("name", 3)
    assert basename == "name-3"
    parsed = automatic.parse(basename)
    assert parsed is not None
    assert parsed.args == ("name", 3)
    assert parsed.kwargs == {}

    numbered = _fmt.CompiledFormat("{0}-{1:d}")
    assert all(field.positional for field in numbered.fields)
    assert numbered.format("item", 4) == "item-4"
    parsed_numbered = numbered.parse("item-4")
    assert parsed_numbered is not None
    assert parsed_numbered.args == ("item", 4)


def test_datetime_formats_round_trip_named_and_public_dt_fields() -> None:
    moment = datetime(2026, 9, 14, 19, 51)
    named = _fmt.CompiledFormat("run-{moment:%Y%m%d-%H%M}")
    assert named.fields == (_fmt.FormatField("moment", 0, "%Y%m%d-%H%M"),)
    assert type(named.fields[0]) is _fmt.FormatField
    basename = named.format(moment=moment)
    assert basename == "run-20260914-1951"
    parsed = named.parse(basename)
    assert parsed is not None
    assert parsed.kwargs == {"moment": moment}

    date_pattern: _fmt.FmtLike = _fmt.dt("%Y%m%d")
    date_only = _fmt.CompiledFormat(date_pattern)
    assert date_only.format(ts=moment) == "20260914"
    parsed_date = date_only.parse("20260914")
    assert parsed_date is not None
    assert parsed_date.kwargs == {"ts": datetime(2026, 9, 14)}

    positional = _fmt.CompiledFormat(_fmt.dt("%Y%m%d", ""))
    assert positional.format(moment) == "20260914"
    parsed_positional = positional.parse("20260914")
    assert parsed_positional is not None
    assert parsed_positional.args == (datetime(2026, 9, 14),)


def test_parser_requires_a_complete_case_sensitive_basename() -> None:
    compiled = _fmt.CompiledFormat("Part-{part:d}.json")
    assert compiled.parse("Part-1.json") is not None
    assert compiled.parse("part-1.json") is None
    assert compiled.parse("prefix-Part-1.json") is None
    assert compiled.parse("Part-1.json.bak") is None


def test_malformed_pattern_surfaces_native_failure() -> None:
    with pytest.raises(ValueError):
        _fmt.CompiledFormat("{unclosed")


def test_invalid_strftime_directives_are_plain_string_formats() -> None:
    assert not _fmt._is_strftime_spec("%")
    assert not _fmt._is_strftime_spec("%Q")


def test_time_only_capture_fails_at_parse_boundary() -> None:
    compiled = _fmt.CompiledFormat("{value:%H:%M}")
    with pytest.raises(TypeError, match="time captures"):
        compiled.parse("19:51")


def test_field_enum_values_are_format_field_prototypes() -> None:
    assert tuple(_fmt._FormatFieldTemplate) == (
        _fmt._FormatFieldTemplate.STRING,
        _fmt._FormatFieldTemplate.INTEGER,
        _fmt._FormatFieldTemplate.DATETIME,
    )
    assert tuple(member.value for member in _fmt._FormatFieldTemplate) == (
        _fmt.FormatField("", 0),
        _fmt.FormatField("", 0, "d"),
        _fmt.FormatField("", 0, "%Y"),
    )
    assert all(type(member.value) is _fmt.FormatField for member in _fmt._FormatFieldTemplate)


def test_format_types_are_exact_and_atomic_inputs_are_beartyped() -> None:
    assert set(get_args(_fmt._ParserField)) == {str, int, date, time, datetime}
    assert set(get_args(_fmt.FmtField)) == {str, int, datetime}
    assert set(get_args(_fmt.CaptureField)) == {str, int, datetime, type(None)}

    with pytest.raises(BeartypeCallHintParamViolation):
        _fmt.dt(1)  # pyright: ignore[reportArgumentType]
    with pytest.raises(BeartypeCallHintParamViolation):
        _fmt.CompiledFormat(1)  # pyright: ignore[reportArgumentType]
    with pytest.raises(BeartypeCallHintParamViolation):
        _fmt.CompiledFormat("{value}").format(value=1.5)  # pyright: ignore[reportArgumentType]
    with pytest.raises(BeartypeCallHintParamViolation):
        _fmt.CompiledFormat("{value}").format(value=None)  # pyright: ignore[reportArgumentType]
