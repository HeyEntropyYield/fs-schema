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
    assert _ops.exists_opt(None) is None

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
    assert copied_from[0][0] == source
    assert Path(copied_from[0][1]).parent == copied.parent
    assert copied_from[0][1] != copied

    saver = Saver()
    saved = tmp_path / "saved" / "value.txt"
    _ops.put(saved, saver)
    assert saved.read_text() == "saved"

    model = tmp_path / "model" / "value.json"
    _ops.put(model, Model(1))
    assert model.read_text() == '{"value":1}'

    empty = tmp_path / "empty" / "value.txt"
    _ops.put(empty)
    assert empty.is_file() and empty.read_bytes() == b""


def test_put_string_writes_the_name_not_the_local_file(tmp_path: Path) -> None:
    source = tmp_path / "local.txt"
    _ = source.write_text("inside")
    dest = tmp_path / "out.txt"
    _ops.put(dest, source.name)
    assert dest.read_text() == "local.txt"
    assert dest.read_text() != source.read_text()


def test_load_returns_values_and_caught_exceptions(tmp_path: Path) -> None:
    path = tmp_path / "value.txt"
    _ = path.write_text("3")
    assert _ops.load(path, lambda candidate: int(candidate.read_text())) == 3

    def broken(_: Path) -> int:
        raise ValueError("bad data")

    result = _ops.load(path, broken)
    assert type(result) is ValueError
    assert str(result) == "bad data"


def test_put_leaves_the_previous_file_when_the_write_fails(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    target = tmp_path / "value.txt"
    target.write_text("old")

    def fail(*_args: object, **_kwargs: object) -> int:
        raise OSError("disk")

    monkeypatch.setattr(Path, "write_text", fail)
    with pytest.raises(OSError, match="disk"):
        _ops.put(target, "new")
    assert target.read_text() == "old"
    assert not any(path.name.startswith(".") for path in tmp_path.iterdir())


def test_link_to_replaces_with_a_soft_or_hard_link(tmp_path: Path) -> None:
    real = tmp_path / "real.txt"
    _ = real.write_text("body")
    via = tmp_path / "via.txt"
    via.symlink_to(real)
    soft = tmp_path / "out" / "soft.txt"
    _ops.link_to(soft, via)
    assert soft.is_symlink()
    assert soft.readlink() == via
    _ops.link_to(str(soft), str(real), hard=True)
    assert soft.is_file() and not soft.is_symlink()
    assert soft.stat().st_ino == real.stat().st_ino
    named = tmp_path / "named.txt"
    _ops.link_to(named, "real.txt")
    assert named.is_symlink()
    assert named.readlink() == Path("real.txt")


def test_link_to_leaves_the_previous_file_when_the_link_fails(tmp_path: Path) -> None:
    target = tmp_path / "value.txt"
    _ = target.write_text("old")
    missing = tmp_path / "missing.txt"
    with pytest.raises(FileNotFoundError):
        _ops.link_to(target, missing, hard=True)
    assert target.read_text() == "old"
    assert not any(path.name.startswith(".") for path in tmp_path.iterdir())


@pytest.mark.parametrize(
    ("follow", "clean"),
    [(True, False), (True, True), (False, False), (False, True)],
)
def test_copy_to_file_follow_and_clean(tmp_path: Path, follow: bool, clean: bool) -> None:
    real = tmp_path / "real.txt"
    _ = real.write_text("body")
    src = tmp_path / "src.txt"
    src.symlink_to(real)
    dest = tmp_path / "nested" / "dest.txt"
    if clean:
        dest.parent.mkdir()
        _ = dest.write_text("old")
    _ops.copy_to(src, dest, follow_symlinks=follow, clean=clean)
    if follow:
        assert dest.is_file() and not dest.is_symlink()
        assert dest.read_text() == "body"
    else:
        assert dest.is_symlink()
        assert dest.readlink() == real


def test_copy_to_directory_merges_or_cleans(tmp_path: Path) -> None:
    src = tmp_path / "src"
    (src / "sub").mkdir(parents=True)
    _ = (src / "keep.txt").write_text("keep")
    _ = (src / "sub" / "link.txt").symlink_to(src / "keep.txt")
    dest = tmp_path / "dest"
    dest.mkdir()
    _ = (dest / "extra.txt").write_text("extra")
    _ = (dest / "keep.txt").write_text("old")
    _ops.copy_to(src, dest, follow_symlinks=True, clean=False)
    assert (dest / "extra.txt").read_text() == "extra"
    assert (dest / "keep.txt").read_text() == "keep"
    assert (dest / "sub" / "link.txt").is_file() and not (dest / "sub" / "link.txt").is_symlink()
    _ops.copy_to(src, dest, follow_symlinks=False, clean=True)
    assert not (dest / "extra.txt").exists()
    kept = dest / "sub" / "link.txt"
    assert kept.is_symlink()
    assert kept.readlink() == src / "keep.txt"


def test_copy_to_replaces_a_symlink_instead_of_writing_through_it(tmp_path: Path) -> None:
    src = tmp_path / "src.txt"
    _ = src.write_text("body")
    other = tmp_path / "other.txt"
    _ = other.write_text("other")
    dest = tmp_path / "dest.txt"
    dest.symlink_to(other)
    _ops.copy_to(src, dest)
    assert dest.is_file() and not dest.is_symlink()
    assert dest.read_text() == "body"
    assert other.read_text() == "other"


def test_copy_to_clean_unlinks_a_file_or_symlink(tmp_path: Path) -> None:
    src = tmp_path / "src.txt"
    _ = src.write_text("body")
    victim = tmp_path / "real-dir"
    victim.mkdir()
    _ = (victim / "inside.txt").write_text("inside")
    dest = tmp_path / "dest"
    dest.symlink_to(victim)
    _ops.copy_to(src, dest, clean=True)
    assert dest.is_file() and not dest.is_symlink()
    assert dest.read_text() == "body"
    assert (victim / "inside.txt").read_text() == "inside"


@pytest.mark.parametrize(
    "layout",
    ["same", "dest-inside-source", "source-inside-dest"],
)
def test_copy_to_refuses_overlapping_paths(tmp_path: Path, layout: str) -> None:
    src = tmp_path / "src"
    src.mkdir()
    _ = (src / "file.txt").write_text("body")
    match layout:
        case "same":
            dest = src
        case "dest-inside-source":
            dest = src / "nested"
        case "source-inside-dest":
            dest = tmp_path
        case _:
            raise AssertionError(layout)
    with pytest.raises(ValueError, match="onto itself"):
        _ops.copy_to(src, dest)


def test_copy_to_recreates_a_symlink_to_a_directory(tmp_path: Path) -> None:
    real = tmp_path / "real"
    real.mkdir()
    src = tmp_path / "src"
    src.symlink_to(real)
    dest = tmp_path / "dest"
    _ops.copy_to(src, dest, follow_symlinks=False)
    assert dest.is_symlink()
    assert dest.readlink() == real
    with pytest.raises(IsADirectoryError):
        _ops.copy_to(src, tmp_path / "followed", follow_symlinks=True)


def test_beartype_rejects_invalid_operation_inputs(tmp_path: Path) -> None:
    with pytest.raises(BeartypeCallHintParamViolation):
        _ops.exists_opt(1)  # pyright: ignore[reportArgumentType]
    with pytest.raises(BeartypeCallHintParamViolation):
        _ops.put(tmp_path / "value", [])  # pyright: ignore[reportArgumentType]
    with pytest.raises(BeartypeCallHintParamViolation):
        _ops.load(tmp_path / "value", "decoder")  # pyright: ignore[reportArgumentType]
