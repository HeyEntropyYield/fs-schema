# pyright: reportAttributeAccessIssue=false, reportCallIssue=false
# pyright: reportIndexIssue=false, reportGeneralTypeIssues=false
# pyright: reportArgumentType=false, reportAssignmentType=false
# pyright: reportUnknownMemberType=false, reportUnknownVariableType=false
# pyright: reportUnknownArgumentType=false

from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

import fs_schema as fss


@dataclass
class Manifest:
    delivery_id: str
    expected_parts: int


@dataclass
class CuratedManifest:
    delivery_id: str
    partitions: int


class Batch(fss.Schema):
    schema = {
        # Typed numeric captures make this collection sort numerically
        "parts": fss.File(
            fmt="part-{part:d}.jsonl",
            sort=lambda part: part.kwargs.part,
        ),
    }


class Delivery(fss.Schema):
    schema = {
        "manifest": fss.File("manifest.json", schema=Manifest),
        "batches": {
            # days names the repeated directory collection in Python
            fss.Dir(
                alias="days",
                fmt="{day:%Y-%m-%d}",
                sort=lambda day: day.kwargs.day,
            ): Batch,
        },
    }


class Curated(fss.Schema):
    schema = {
        "manifest": fss.File("manifest.json", schema=CuratedManifest),
        fss.Dir(alias="days", fmt="{day:%Y-%m-%d}"): {
            "parts": fss.File(fmt="part-{part:d}.parquet"),
        },
    }


def curate(source: Path, target: Path) -> Curated | fss.MismatchErr:
    # Bind proves the input layout before any child is used
    if fss.is_mismatch(delivery := Delivery.bind(source)):
        return delivery

    # The declared File schema supplies this dataclass loader
    manifest: Manifest = fss.raise_exn(delivery.manifest.load())
    # Templates are ordered collections; an item is one capture-bearing match
    latest = delivery.batches.days[-1]
    fs = Curated.relative_to(target)
    parquet = convert_parts([part.path for part in latest.parts])
    # One spec: exact files by alias, collection members as (captures, body) pairs.
    fs.create(
        manifest=CuratedManifest(manifest.delivery_id, partitions=1),
        days=[({"day": latest.kwargs.day}, {"parts": [({"part": 0}, parquet)]})],
    )
    return fs.bind()


def convert_parts(parts: Sequence[Path]) -> bytes:
    # Stand-in for an application converter; keeps this example executable.
    return b"\n".join(part.read_bytes() for part in parts)
