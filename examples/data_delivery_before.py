"""
Every function below accepts and returns Path. Its real contract lives here:

downloaded/
  manifest.json                    DeliveryManifest
  transfer/
    download.log
    request.json
  batches/
    YYYY-MM-DD/
      part-NNNN.jsonl              one or more

validated/                         same downloaded root, plus:
  validation.json                 ValidationReport

curated/
  manifest.json                    CuratedManifest
  partitions/
    event_date=YYYY-MM-DD/
      part-0000.parquet

loaded/                            same curated root, plus:
  load_receipt.json                LoadReceipt

Callers and type checkers cannot see these states. Each function repeats
paths, globs, ordering, and existence assumptions.
"""

# uv add "mashumaro[orjson]"

from dataclasses import dataclass
from pathlib import Path

from mashumaro.mixins.orjson import DataClassORJSONMixin


## Real application:
# from delivery_platform import convert_parts, download, warehouse_load
def download(source: str, target: Path) -> None:
    raise NotImplementedError(f"download {source} to {target}")


def convert_parts(parts: tuple[Path, ...]) -> bytes:
    raise NotImplementedError(f"convert {len(parts)} parts")


def warehouse_load(parts: tuple[Path, ...]) -> str:
    raise NotImplementedError(f"load {len(parts)} parts")


## Internal datatypes


@dataclass
class DeliveryManifest(DataClassORJSONMixin):
    delivery_id: str
    expected_parts: int


@dataclass
class ValidationReport(DataClassORJSONMixin):
    parts: int


@dataclass
class CuratedManifest(DataClassORJSONMixin):
    delivery_id: str
    partitions: int


@dataclass
class LoadReceipt(DataClassORJSONMixin):
    load_id: str


## Main impl before:


def pull(source: str, target: Path) -> Path:
    download(source, target)
    return target


def validate(root: Path) -> Path:
    manifest = DeliveryManifest.from_json((root / "manifest.json").read_bytes())
    parts = tuple(sorted((root / "batches").glob("*/*.jsonl")))
    if len(parts) != manifest.expected_parts:
        raise ValueError(f"expected {manifest.expected_parts} parts, got {len(parts)}")

    (root / "validation.json").write_text(ValidationReport(parts=len(parts)).to_json())
    return root


def curate(
    root: Path,
    output: Path,
) -> Path:
    validation = ValidationReport.from_json((root / "validation.json").read_bytes())
    manifest = DeliveryManifest.from_json((root / "manifest.json").read_bytes())
    input_parts = tuple(sorted((root / "batches").glob("*/*.jsonl")))
    if len(input_parts) != validation.parts:
        raise ValueError("delivery changed after validation")

    partitions = 0
    for source_day in sorted((root / "batches").iterdir()):
        target = output / "partitions" / f"event_date={source_day.name}"
        target.mkdir(parents=True, exist_ok=True)
        parts = tuple(sorted(source_day.glob("part-*.jsonl")))
        (target / "part-0000.parquet").write_bytes(convert_parts(parts))
        partitions += 1

    output.mkdir(parents=True, exist_ok=True)
    (output / "manifest.json").write_text(
        CuratedManifest(
            delivery_id=manifest.delivery_id,
            partitions=partitions,
        ).to_json()
    )
    return output


def load(root: Path) -> Path:
    parts = tuple(sorted((root / "partitions").glob("*/*.parquet")))
    load_id = warehouse_load(parts)
    (root / "load_receipt.json").write_text(LoadReceipt(load_id=load_id).to_json())
    return root


def ingest(
    source: str,
    staging: Path,
    curated: Path,
) -> Path:
    downloaded = pull(source, staging)
    validated = validate(downloaded)
    dataset = curate(validated, curated)
    return load(dataset)


# This also typechecks, despite skipping validation and curation:
# load(pull(source, staging))
