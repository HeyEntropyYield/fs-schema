# pyright: reportPrivateUsage=false
import pytest
from beartype.roar import BeartypeCallHintParamViolation

import fs_schema
from fs_schema import _schema


def test_declarations_are_frozen_slotted_values_with_contextual_defaults() -> None:
    fixed: _schema.File[object] = _schema.File("value.txt")
    assert fixed.name == "value.txt"
    assert fixed.min == 1
    assert fixed.max == 1
    assert _schema.Dir("values", min=0).max == 1
    assert _schema.File("many.txt", max=3).max == 3
    assert _schema.File(fmt="part-{part:d}.txt").max is None
    assert _schema.File(match=r"part-[0-9]+[.]txt").max is None
    assert _schema.File().max is None
    assert _schema.File(fmt="{value}", match=r".+") == _schema.File(fmt="{value}", match=r".+")
    assert not hasattr(fixed, "__dict__")
    equal: _schema.File[object] = _schema.File("value.txt")
    assert hash(fixed) == hash(equal)


def test_files_is_the_single_identity_token() -> None:
    assert fs_schema.FILES is _schema.FILES
    assert repr(_schema.FILES) == "FILES"


@pytest.mark.parametrize(
    ("kwargs", "message"),
    [
        ({"name": "value", "fmt": "{value}"}, "name cannot be combined"),
        ({"name": "value", "match": ".+"}, "name cannot be combined"),
        ({"min": -1}, "min must be at least zero"),
        ({"min": 2, "max": 1}, "max must be at least min"),
        ({"name": "value", "min": 2}, "max must be at least min"),
    ],
)
def test_declaration_semantic_failures(kwargs: dict[str, object], message: str) -> None:
    with pytest.raises(ValueError, match=message):
        _schema.File(**kwargs)  # pyright: ignore[reportArgumentType]


def test_beartype_rejects_invalid_declaration_atomic_inputs() -> None:
    with pytest.raises(BeartypeCallHintParamViolation):
        _schema.File(name=1)  # pyright: ignore[reportArgumentType]
    with pytest.raises(BeartypeCallHintParamViolation):
        _schema.Dir(min="1")  # pyright: ignore[reportArgumentType]
