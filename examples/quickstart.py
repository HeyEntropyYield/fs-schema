# pyright: reportAttributeAccessIssue=false, reportCallIssue=false
# pyright: reportIndexIssue=false, reportGeneralTypeIssues=false
# pyright: reportArgumentType=false, reportAssignmentType=false
# pyright: reportUnknownMemberType=false, reportUnknownVariableType=false
# pyright: reportUnknownArgumentType=false

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
    manifest: Manifest = delivery.manifest.load()
    # Templates are ordered collections; an item is one capture-bearing match
    latest = delivery.batches.days[-1]
    source_parts = tuple(part.path for part in latest.parts)

    # A relative instance plans under the root; it does not claim the target exists.
    output = Curated.relative_to(target)
    # Finish conversion before writing, so conversion failure leaves no partial output.
    parquet = convert_parts(source_parts)
    output.manifest.put(CuratedManifest(manifest.delivery_id, partitions=1))
    # Formatting chooses a concrete path; put creates its missing parents.
    target_day = output.days.format(day=latest.kwargs.day)
    target_day.parts.format(part=0).put(parquet)
    # Bind validates the output tree after it has been written
    return output.bind()


def convert_parts(parts: tuple[Path, ...]) -> bytes:
    # Stand-in for an application converter; keeps this example executable.
    return b"\n".join(part.read_bytes() for part in parts)
