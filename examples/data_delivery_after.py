# pyright: reportAttributeAccessIssue=false, reportCallIssue=false
# pyright: reportIndexIssue=false, reportGeneralTypeIssues=false
# pyright: reportArgumentType=false, reportAssignmentType=false
# pyright: reportUnknownMemberType=false, reportUnknownVariableType=false
# pyright: reportUnknownArgumentType=false

# uv add "fs-schema[mashumaro,orjson]"

from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

import fs_schema as fss


## Real application:
# from delivery_platform import convert_parts, download, warehouse_load
def download(source: str, target: Path) -> None:
    raise NotImplementedError(f"download {source} to {target}")


def convert_parts(parts: Sequence[Path]) -> bytes:
    raise NotImplementedError(f"convert {len(parts)} parts")


def warehouse_load(parts: tuple[Path, ...]) -> str:
    raise NotImplementedError(f"load {len(parts)} parts")


## Internal datatypes


@dataclass
class DeliveryManifest:
    delivery_id: str
    expected_parts: int


@dataclass
class ValidationReport:
    parts: int


@dataclass
class CuratedManifest:
    delivery_id: str
    partitions: int


@dataclass
class LoadReceipt:
    load_id: str


## fs-schema encoding mental/comment description of filesystem


class DeliveryBatch(fss.Schema):
    schema = {
        "parts": fss.File(fmt="part-{part:d}.jsonl", sort=lambda part: part.kwargs["part"]),
    }


class DownloadedDelivery(fss.Schema):
    schema = {
        "manifest": fss.File("manifest.json", schema=DeliveryManifest),
        "transfer": {
            fss.FILES: ["download.log", "request.json"],
        },
        "batches": {
            fss.Dir(
                alias="days",
                fmt="{day:%Y-%m-%d}",
                sort=lambda day: day.kwargs["day"],
            ): DeliveryBatch,
        },
    }


class ValidatedDelivery(DownloadedDelivery):
    schema = {
        "validation": fss.File("validation.json", schema=ValidationReport),
    }


class CuratedPartition(fss.Schema):
    schema = {
        "parts": fss.File(fmt="part-{part:d}.parquet", sort=lambda part: part.kwargs["part"]),
    }


class CuratedDataset(fss.Schema):
    schema = {
        "manifest": fss.File("manifest.json", schema=CuratedManifest),
        "partitions": {
            fss.Dir(
                alias="days",
                fmt="event_date={day:%Y-%m-%d}",
                sort=lambda day: day.kwargs["day"],
            ): CuratedPartition,
        },
    }


class LoadedDataset(CuratedDataset):
    schema = {
        "receipt": fss.File("load_receipt.json", schema=LoadReceipt),
    }


## Main impl after:


def pull(
    source: str,
    target: Path,
) -> DownloadedDelivery | fss.MismatchErr:
    fs = DownloadedDelivery.relative_to(target)
    download(source, fs.path)
    return fs.bind()


def validate(
    delivery: DownloadedDelivery,
) -> ValidatedDelivery | fss.MismatchErr:
    fs = ValidatedDelivery.relative_to(delivery.path)
    manifest: DeliveryManifest = fss.raise_exn(delivery.manifest.load())
    parts = sum(len(day.parts) for day in delivery.batches.days)
    if parts != manifest.expected_parts:
        return fss.MismatchErr(f"expected {manifest.expected_parts} parts, got {parts}")

    fs.validation.create(ValidationReport(parts=parts))
    return fs.bind()


def curate(
    delivery: ValidatedDelivery,
    target: Path,
) -> CuratedDataset | fss.MismatchErr:
    fs = CuratedDataset.relative_to(target)
    manifest: DeliveryManifest = fss.raise_exn(delivery.manifest.load())
    validation: ValidationReport = fss.raise_exn(delivery.validation.load())
    parts = sum(len(day.parts) for day in delivery.batches.days)
    if parts != validation.parts:
        return fss.MismatchErr("delivery changed after validation")

    days = [
        (
            {"day": source_day.kwargs.day},
            {"parts": [({"part": 0}, convert_parts([part.path for part in source_day.parts]))]},
        )
        for source_day in delivery.batches.days
    ]
    fs.create(
        partitions={"days": days}, manifest=CuratedManifest(delivery_id=manifest.delivery_id, partitions=len(days))
    )
    return fs.bind()


def load(
    dataset: CuratedDataset,
) -> LoadedDataset | fss.MismatchErr:
    fs = LoadedDataset.relative_to(dataset.path)
    parts = tuple(part.path for day in dataset.partitions.days for part in day.parts)
    fs.receipt.create(LoadReceipt(load_id=warehouse_load(parts)))
    return fs.bind()


def ingest(
    source: str,
    staging: Path,
    curated: Path,
) -> LoadedDataset | fss.MismatchErr:
    if fss.is_mismatch(downloaded := pull(source, staging)):
        return downloaded

    if fss.is_mismatch(validated := validate(downloaded)):
        return validated

    if fss.is_mismatch(dataset := curate(validated, curated)):
        return dataset

    return load(dataset)
