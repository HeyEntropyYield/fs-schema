"""Import examples so coverage measures them. Docs stay typecheck+exec in test_docs."""

from pathlib import Path

import pytest

import data_delivery_after
import data_delivery_before
import fs_schema as fss
import quickstart
import smoke
import symlink_copy


def test_examples_import(tmp_path: Path) -> None:
    assert fss.is_mismatch(quickstart.curate(tmp_path / "missing", tmp_path / "out"))
    assert quickstart.curate
    assert data_delivery_before.pull
    assert data_delivery_after.DownloadedDelivery
    smoke.main()
    symlink_copy.main()


def _stage_download(target: Path, *, parts: int, expected: int) -> None:
    target.mkdir(parents=True, exist_ok=True)
    manifest = data_delivery_before.DeliveryManifest("d1", expected)
    (target / "manifest.json").write_text(manifest.to_json())
    transfer = target / "transfer"
    transfer.mkdir(exist_ok=True)
    (transfer / "download.log").write_text("ok\n")
    (transfer / "request.json").write_text("{}\n")
    day = target / "batches" / "2026-09-17"
    day.mkdir(parents=True, exist_ok=True)
    for index in range(parts):
        (day / f"part-{index}.jsonl").write_bytes(b"row\n")


def _download_one(source: str, target: Path) -> None:
    assert source == "src"
    _stage_download(target, parts=1, expected=1)


def _download_short(_source: str, target: Path) -> None:
    _stage_download(target, parts=1, expected=2)


def _download_nothing(_source: str, _target: Path) -> None:
    return None


def _convert_parts(parts: object) -> bytes:
    assert parts
    return b"parquet"


def _warehouse_load(parts: tuple[Path, ...]) -> str:
    assert parts
    return "load-1"


def _stop_curate(_delivery: object, _target: Path) -> fss.MismatchErr:
    return fss.MismatchErr("stopped")


def _install_delivery(monkeypatch: pytest.MonkeyPatch, download: object) -> None:
    for module in (data_delivery_before, data_delivery_after):
        monkeypatch.setattr(module, "download", download)
        monkeypatch.setattr(module, "convert_parts", _convert_parts)
        monkeypatch.setattr(module, "warehouse_load", _warehouse_load)


def test_delivery_before_ingest(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _install_delivery(monkeypatch, _download_one)
    curated = tmp_path / "curated"
    loaded = data_delivery_before.ingest("src", tmp_path / "staging", curated)
    assert (loaded / "load_receipt.json").is_file()
    parquet = curated / "partitions" / "event_date=2026-09-17" / "part-0000.parquet"
    assert parquet.read_bytes() == b"parquet"


def test_delivery_before_part_count(tmp_path: Path) -> None:
    short = tmp_path / "short"
    _stage_download(short, parts=1, expected=2)
    with pytest.raises(ValueError, match="expected 2 parts"):
        data_delivery_before.validate(short)
    _stage_download(short, parts=1, expected=1)
    checked = data_delivery_before.validate(short)
    (checked / "batches" / "2026-09-17" / "part-1.jsonl").write_bytes(b"extra\n")
    with pytest.raises(ValueError, match="changed after validation"):
        data_delivery_before.curate(checked, tmp_path / "drift")


def test_delivery_after_empty_pull(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _install_delivery(monkeypatch, _download_nothing)
    assert fss.is_mismatch(data_delivery_after.ingest("src", tmp_path / "empty", tmp_path / "empty-out"))
    assert fss.is_mismatch(data_delivery_after.pull("src", tmp_path / "empty-pull"))


def test_delivery_after_short_validate(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _install_delivery(monkeypatch, _download_short)
    pulled = data_delivery_after.pull("src", tmp_path / "bad")
    assert type(pulled) is data_delivery_after.DownloadedDelivery
    assert fss.is_mismatch(data_delivery_after.validate(pulled))
    rejected = data_delivery_after.ingest("src", tmp_path / "bad-ingest", tmp_path / "nowhere")
    assert fss.is_mismatch(rejected)


def test_delivery_after_ingest(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _install_delivery(monkeypatch, _download_one)
    loaded = data_delivery_after.ingest("src", tmp_path / "staging", tmp_path / "curated")
    assert type(loaded) is data_delivery_after.LoadedDataset
    receipt: data_delivery_after.LoadReceipt = fss.raise_exn(loaded.receipt.load())
    assert receipt.load_id == "load-1"


def test_delivery_after_curate_drift(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _install_delivery(monkeypatch, _download_one)
    staged = data_delivery_after.pull("src", tmp_path / "staging")
    assert type(staged) is data_delivery_after.DownloadedDelivery
    validated = data_delivery_after.validate(staged)
    assert type(validated) is data_delivery_after.ValidatedDelivery
    (validated.path / "batches" / "2026-09-17" / "part-1.jsonl").write_bytes(b"extra\n")
    rebound = data_delivery_after.ValidatedDelivery.bind(validated.path)
    assert type(rebound) is data_delivery_after.ValidatedDelivery
    assert fss.is_mismatch(data_delivery_after.curate(rebound, tmp_path / "drift"))


def test_delivery_after_curate_stopped(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _install_delivery(monkeypatch, _download_one)
    monkeypatch.setattr(data_delivery_after, "curate", _stop_curate)
    stopped = data_delivery_after.ingest("src", tmp_path / "staging", tmp_path / "curated")
    assert fss.is_mismatch(stopped)
