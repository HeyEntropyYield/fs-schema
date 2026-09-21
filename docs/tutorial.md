# Migrate a delivery pipeline from paths to states

A delivery pipeline is a sequence of filesystem states, even when its code says
only `Path`. This tutorial migrates a download → validation → curation →
warehouse-load pipeline so that every function accepts the state it really
requires.

The Python snippets share one page context. These functions stand in for the
application's downloader, partition converter, and warehouse client. They raise
because this page describes integration boundaries, not a runnable delivery
system.

```python
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import ClassVar

import fs_schema as fss


def download(source: str, target: Path) -> None:
    raise NotImplementedError(f"download {source} to {target}")


def convert_parts(parts: Sequence[Path]) -> bytes:
    raise NotImplementedError(f"convert {len(parts)} parts")


def warehouse_load(parts: tuple[Path, ...]) -> str:
    raise NotImplementedError(f"load {len(parts)} parts")
```

## Start with paths and implicit contracts

A conventional implementation passes roots between stages. Each stage repeats
layout knowledge with literals and globs:

```python
def pull_path(source: str, target: Path) -> Path:
    download(source, target)
    return target


def validate_path(root: Path) -> Path:
    parts = tuple(sorted((root / "batches").glob("*/*.jsonl")))
    if not (root / "manifest.json").is_file() or not parts:
        raise ValueError(f"incomplete delivery at {root}")
    return root


def curate_path(root: Path, output: Path) -> Path:
    parts = tuple(sorted((root / "batches").glob("*/*.jsonl")))
    target = output / "partitions" / "part-0000.parquet"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(convert_parts(parts))
    return output


def load_path(root: Path) -> Path:
    parts = tuple(sorted((root / "partitions").glob("*/*.parquet")))
    _ = warehouse_load(parts)
    return root


def incorrect_but_typechecks(source: str, staging: Path) -> Path:
    return load_path(pull_path(source, staging))
```

The last function skips validation and curation without a type error. The
migration should fix that system boundary, not merely replace one spelling of
path concatenation with another.

## Design roots and state transitions first

Choose when identity changes and what durable evidence marks a transition
before declaring schemas.

| State | Root | New guarantee | Produced by |
| --- | --- | --- | --- |
| `DownloadedDelivery` | staging root | manifest, transfer metadata, dated batches, and numbered parts exist | external download, then `bind()` |
| `ValidatedDelivery` | same staging root | downloaded guarantee plus a validation report | content checks, report write, then `bind()` |
| `CuratedDataset` | separate curated root | manifest and dated Parquet partitions exist | conversion into planned paths, then `bind()` |
| `LoadedDataset` | same curated root | curated guarantee plus a local warehouse receipt | remote load, receipt write, then `bind()` |

Validation and loading are additive same-root states: they strengthen what is
known about an existing directory. Curation creates a different dataset, so it
gets a different root.

Install the JSON model conversion used below with:

```bash
uv add "fs-schema[mashumaro,orjson]"
```

The models remain ordinary application dataclasses. File declarations attach
them to JSON locations; the `orjson` extra keeps the faster implementation.

```python
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


class DeliveryBatch(fss.Schema):
    schema: ClassVar[fss.Layout] = {
        "parts": fss.File(
            fmt="part-{part:d}.jsonl",
            min=1,
            sort=lambda part: part.kwargs.part,
        ),
    }


class DownloadedDelivery(fss.Schema):
    schema: ClassVar[fss.Layout] = {
        "manifest": fss.File("manifest.json", schema=DeliveryManifest),
        "transfer": {fss.FILES: ["download.log", "request.json"]},
        "batches": {
            fss.Dir(
                alias="days",
                fmt="{day:%Y-%m-%d}",
                sort=lambda day: day.kwargs.day,
            ): DeliveryBatch,
        },
    }


class ValidatedDelivery(DownloadedDelivery):
    schema: ClassVar[fss.Layout] = {
        "validation": fss.File("validation.json", schema=ValidationReport),
    }


class CuratedPartition(fss.Schema):
    schema: ClassVar[fss.Layout] = {
        "parts": fss.File(
            fmt="part-{part:d}.parquet",
            min=1,
            sort=lambda part: part.kwargs.part,
        ),
    }


class CuratedDataset(fss.Schema):
    schema: ClassVar[fss.Layout] = {
        "manifest": fss.File("manifest.json", schema=CuratedManifest),
        "partitions": {
            fss.Dir(
                alias="days",
                fmt="event_date={day:%Y-%m-%d}",
                sort=lambda day: day.kwargs.day,
            ): CuratedPartition,
        },
    }


class LoadedDataset(CuratedDataset):
    schema: ClassVar[fss.Layout] = {
        "receipt": fss.File("load_receipt.json", schema=LoadReceipt),
    }
```

Only `bind()` establishes a bound state token. `relative_to()` instead
returns a rooted plan: paths are known, but the filesystem has not been
validated.

## Bind the external download boundary

The downloader mutates the filesystem outside fs-schema. Plan its destination,
pass the path to that integration, and bind what it leaves behind:

```python
def pull(
    source: str,
    target: Path,
) -> DownloadedDelivery | fss.MismatchErr:
    fs = DownloadedDelivery.relative_to(target)
    download(source, fs.path)
    return fs.bind()
```

A mismatch is returned as a value. A successful result carries the downloaded
contract into later functions.

Natural child access now replaces repeated literals and globs:

```python
def delivery_parts(delivery: DownloadedDelivery) -> tuple[Path, ...]:
    return tuple(
        part.path
        for day in delivery.batches.days
        for part in day.parts
    )
```

The declared JSON model supplies a `DeliveryManifest`. `raise_exn` raises a
decoding error while preserving the successful model type.

## Strengthen the same root with validation

Structural binding cannot prove business facts such as an expected row-part
count. Validation checks that content contract, writes durable evidence to the
fixed report file, and binds the stronger schema at the same path.

```python
def validate(
    delivery: DownloadedDelivery,
) -> ValidatedDelivery | fss.MismatchErr:
    manifest: DeliveryManifest = fss.raise_exn(delivery.manifest.load())

    parts = delivery_parts(delivery)
    if len(parts) != manifest.expected_parts:
        message = f"expected {manifest.expected_parts} parts, got {len(parts)}"
        return fss.MismatchErr(message)

    fs = ValidatedDelivery.relative_to(delivery.path)
    fs.validation.create(ValidationReport(parts=len(parts)))
    return fs.bind()
```

The input object still denotes the downloaded state. Only the returned object
denotes the validated state, even though both have the same `.path`.

## Plan and materialize a separate output

Curation reads only a validated delivery and targets another root. It loads the
declared models and checks that the validated input has not changed.

```python
def curate(
    delivery: ValidatedDelivery,
    target: Path,
) -> CuratedDataset | fss.MismatchErr:
    manifest: DeliveryManifest = fss.raise_exn(delivery.manifest.load())
    validation: ValidationReport = fss.raise_exn(delivery.validation.load())

    if len(delivery_parts(delivery)) != validation.parts:
        return fss.MismatchErr("delivery changed after validation")

    fs = CuratedDataset.relative_to(target)
    days = [
        ({"day": source_day.kwargs.day}, {"parts": [({"part": 0}, convert_parts([part.path for part in source_day.parts]))]})
        for source_day in delivery.batches.days
    ]
    fs.create(partitions={"days": days}, manifest=CuratedManifest(delivery_id=manifest.delivery_id, partitions=len(days)))
    return fs.bind()
```

The list is the whole write. Each pair is one member: the captures, then the body that member would take. `part` is not the same capture as `day`, so the inner file still needs its own pair. A capture that an enclosing `format` already supplied is just the body. `bind()` checks the tree you wrote.

## Record loaded state and design retries first

Warehouse loading is an external side effect. Advance local state only after
recording its receipt:

```python
def curated_parts(dataset: CuratedDataset) -> tuple[Path, ...]:
    return tuple(
        part.path
        for day in dataset.partitions.days
        for part in day.parts
    )


def load(
    dataset: CuratedDataset,
) -> LoadedDataset | fss.MismatchErr:
    fs = LoadedDataset.relative_to(dataset.path)
    load_id = warehouse_load(curated_parts(dataset))
    fs.receipt.create(LoadReceipt(load_id=load_id))
    return fs.bind()
```

There is still a failure window: the warehouse may commit before the receipt
write succeeds. Production code should use a stable idempotency key, query an
existing job before retrying, or reconcile local receipts with remote state.
A schema cannot make those two systems transactional.

## Compose state transitions

The orchestrator handles mismatches while each stage advertises its required
input state:

```python
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
```

`load(downloaded)` is now a type error: the loader requires a
`CuratedDataset`. Download, validation, materialization, and remote loading
are explicit transitions rather than conventions attached to four `Path`
values.

## What these calls do not promise

`relative_to` and `format` only plan paths. `create` and `put` write. `put` replaces one file atomically and creates missing parents. `create` can leave a partial tree if a later write fails. `bind` checks names and shape. `load` checks file contents.

## Companion listings

The repository keeps the complete comparison behind this migration:

- [Path-based delivery listing](https://github.com/HeyEntropyYield/fs-schema/blob/master/examples/data_delivery_before.py)
- [State-based delivery listing](https://github.com/HeyEntropyYield/fs-schema/blob/master/examples/data_delivery_after.py)

Both retain placeholder integrations. Read them as before/after design
listings, not as a claim that a delivery runs without application-specific
network, conversion, and warehouse implementations.
