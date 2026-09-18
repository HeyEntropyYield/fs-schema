# pyright: reportPrivateUsage=false
from dataclasses import dataclass
from pathlib import Path

import pytest
from beartype.roar import BeartypeCallHintParamViolation

from fs_schema import _ops


class Saver:
    saved_to: Path | None = None

    def save(self, path: Path) -> None:
        self.saved_to = path
        _ = path.write_text("saved")


@dataclass
class Model:
    value: int


def test_exists_and_mismatch_helpers(tmp_path: Path) -> None:
    present = tmp_path / "present.txt"
    _ = present.write_text("present")
    assert _ops.exists_opt(present) == present
    assert _ops.exists_opt(str(present)) == present
    assert _ops.exists_opt(tmp_path / "missing.txt") is None

    mismatch = _ops.MismatchErr("missing")
    assert _ops.is_mismatch(mismatch)
    assert not mismatch
    assert not _ops.is_mismatch("value")
    assert _ops.raise_exn("value") == "value"
    assert _ops.raise_mismatch("value") == "value"
    with pytest.raises(ValueError, match="bad value"):
        _ops.raise_exn(ValueError("bad value"))
    with pytest.raises(_ops.MismatchErr, match="missing"):
        _ops.raise_mismatch(mismatch)


def test_put_covers_supported_bodies_and_dataclass_without_codec(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    binary = tmp_path / "binary" / "value.bin"
    _ops.put(binary, b"bytes")
    assert binary.read_bytes() == b"bytes"

    text = tmp_path / "text" / "value.txt"
    _ops.put(text, "text")
    assert text.read_text() == "text"

    source = tmp_path / "source.txt"
    _ = source.write_text("copied")
    copied = tmp_path / "copied" / "value.txt"
    copied_from: list[tuple[str | Path, str | Path]] = []

    def record_copy(source_path: str | Path, target_path: str | Path) -> str:
        copied_from.append((source_path, target_path))
        return str(target_path)

    with monkeypatch.context() as copy_patch:
        copy_patch.setattr(_ops, "copyfile", record_copy)
        _ops.put(copied, source)
    assert copied_from == [(source, copied)]

    saver = Saver()
    saved = tmp_path / "saved" / "value.txt"
    _ops.put(saved, saver)
    assert saver.saved_to == saved
    assert saved.read_text() == "saved"

    model = tmp_path / "model" / "value.json"
    _ops.put(model, Model(1))
    assert model.read_text() == '{"value":1}'


def test_load_returns_values_and_caught_exceptions(tmp_path: Path) -> None:
    path = tmp_path / "value.txt"
    _ = path.write_text("3")
    assert _ops.load(path, lambda candidate: int(candidate.read_text())) == 3

    def broken(_: Path) -> int:
        raise ValueError("bad data")

    result = _ops.load(path, broken)
    assert type(result) is ValueError
    assert str(result) == "bad data"


def test_beartype_rejects_invalid_operation_inputs(tmp_path: Path) -> None:
    with pytest.raises(BeartypeCallHintParamViolation):
        _ops.exists_opt(1)  # pyright: ignore[reportArgumentType]
    with pytest.raises(BeartypeCallHintParamViolation):
        _ops.put(tmp_path / "value", [])  # pyright: ignore[reportArgumentType]
    with pytest.raises(BeartypeCallHintParamViolation):
        _ops.load(tmp_path / "value", "decoder")  # pyright: ignore[reportArgumentType]
