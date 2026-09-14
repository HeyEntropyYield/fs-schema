# API reference

Examples on this page build on these imports and definitions:

```python
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

import fs_schema as fss
```

## Public API at a glance

| Area | Names |
| --- | --- |
| Schemas | `Schema`, `SchemaRoot`, `Layout` |
| Declarations | `File`, `Dir`, `FILES`, `dt` |
| Paths and matches | `Located`, `Match`, `exists_opt` |
| Mismatches | `MismatchErr`, `is_mismatch`, `raise_mismatch` |
| Writing | `put` |
| Package metadata | `__version__` |

All names in this table are available from `fs_schema`.

## Defining schemas

Subclass `Schema` and define a `schema` mapping. Nested mappings represent
nested directories.

```python
@dataclass
class Manifest:
    delivery_id: str
    rows: int


class Batch(fss.Schema):
    schema = {
        "parts": fss.File(fmt="part-{part:d}.parquet"),
    }


class Delivery(fss.Schema):
    schema = {
        "transfer": {
            fss.FILES: ["download.log", "request.json"],
        },
        "manifest": fss.File("manifest.json", schema=Manifest),
        "batches": {
            fss.Dir(
                alias="days",
                fmt="{day:%Y-%m-%d}",
                sort=lambda match: match.kwargs["day"],
            ): Batch,
        },
    }
```

### Mapping forms

| Entry | Declares |
| --- | --- |
| `"dir": {...}` or `"dir": ChildSchema` | A fixed directory |
| `Dir(...): {...}` or `Dir(...): ChildSchema` | A configured directory |
| `"alias": "file.ext"` or `"alias": File(...)` | One file |
| `FILES: ["file.ext", File(...)]` | Files in the current directory |

Only `name` is positional in `File` and `Dir`. All other options are
keyword-only.

### Templates, matching, and cardinality

| Option | Meaning |
| --- | --- |
| `name` | Exact basename. It cannot be combined with `fmt` or `match`. |
| `fmt` | Full-basename parse and format template. |
| `match` | Regular expression applied to the full basename with `re.fullmatch`. |
| `min` | Minimum count; defaults to `1`. Use `0` for an optional declaration. |
| `max` | Maximum count. Exact names default to one; templates are unbounded. |
| `alias` | Name used for child access in Python. |
| `sort` | Key function for template matches. |
| `sort_rev` | Reverse the match order when true. |
| `schema` | Loader for a file, or an extra schema contract for a directory. |

When `fmt` and `match` are both set, an existing basename must satisfy both.
Untyped format fields produce `str`, `:d` fields produce `int`, and datetime
format fields produce `datetime`.

```python
part_decl = fss.File(
    fmt="part-{part:d}.{ext}",
    match=r"(?i).+\.(?:json|yaml|toml)",
)
day_decl = fss.Dir(alias="days", fmt=fss.dt("%Y-%m-%d"), min=0)
```

`fss.dt("%Y-%m-%d")` returns `"{:%Y-%m-%d}"`. Its datetime is capture
`args[0]`. A named field such as `{day:%Y-%m-%d}` is capture `kwargs["day"]`.

### Inheritance and replacement

Inheritance merges layouts at the same root. Base layouts are merged in Python
MRO order, followed by the subclass layout.

```python
class AuditedDelivery(Delivery):
    schema = {
        "audit": "audit.json",
    }
```

Within one parent, a declaration's identity is its exact `name`, then its
`alias`, then its `fmt`. Both the identity kind and value matter. A later entry
with the same identity replaces the whole earlier entry, even if its node type
changes.

### Declaration API

```text
File(
    name: str = "",
    *,
    fmt: str | None = None,
    match: str | None = None,
    min: int = 1,
    max: int | None = None,
    alias: str | None = None,
    sort: Callable[[Match], str | int | float | datetime | Located] | None = None,
    sort_rev: bool = False,
    schema: type[T] | Callable[[Path], T] | None = None,
) -> File[T]

Dir(
    name: str = "",
    *,
    fmt: str | None = None,
    match: str | None = None,
    min: int = 1,
    max: int | None = None,
    alias: str | None = None,
    sort: Callable[[Match], str | int | float | datetime | Located] | None = None,
    sort_rev: bool = False,
    schema: type[S] | None = None,
) -> Dir[S]

dt(pattern: str) -> str
```

The mapping table above defines the valid `Layout` key-value pairings.

## Applying schemas

`bind` checks an existing tree. It returns the requested schema on success or a
`MismatchErr` value on failure.

```python
result = Delivery.bind("/srv/incoming/delivery-42")
if fss.is_mismatch(result):
    print(result)
else:
    delivery: Delivery = result
```

Use `raise_mismatch` when a mismatch should be raised:

```python
delivery = fss.raise_mismatch(
    Delivery.bind("/srv/incoming/delivery-42")
)
```

`Schema.bind` also accepts a `Located` value. A planned root binds itself.

```python
validated_again = Delivery.bind(delivery)
planned_delivery = Delivery.relative_to("/srv/incoming/delivery-42")
validated_from_plan = planned_delivery.bind()
```

Binding checks declared structure and cardinality at that moment. It ignores
undeclared entries, is not a filesystem lock, and returns the first mismatch.

```text
Schema.bind(root: str | os.PathLike[str] | Located) -> Self | MismatchErr
SchemaRoot[S].bind() -> S | MismatchErr
is_mismatch(x: object) -> TypeIs[MismatchErr]
raise_mismatch(x: T | MismatchErr) -> T
```

## Using schemas

### Fixed directories and files

A bound `Schema`, planned `SchemaRoot`, fixed directory, or fixed file
represents one path and satisfies `Located`. Each works with `os.fspath` and
APIs that accept `os.PathLike[str]`.

```python
root_path = delivery.path
manifest_path = Path(delivery.manifest)
request_text = delivery.transfer.request_json.read_text()
request_exists = delivery.transfer.request_json.exists()
```

`Located` promises only `.path` and `__fspath__`. Concrete fixed values also
have `exists()`. Fixed files add `read_bytes()`, `read_text()`, and `put()`.

Children support attribute access and exact item lookup. An explicit alias is
used unchanged. Otherwise, each run outside `[A-Za-z0-9_]` in the disk name
becomes `_`.

```python
log_file = delivery.transfer.download_log
same_request = delivery.transfer["request.json"]
```

Use `exists_opt(path)` when an absent optional node should become `None` rather
than a missing path:

```text
exists_opt(path: str | os.PathLike[str]) -> Path | None
```

### Template collections and matches

A template declaration provides a sequence of its current matches. The sequence
has the parent directory in `.path`, but it is not `Located`. Indexing or
iteration returns a concrete `Match`, which is `Located` and contains parsed
captures.

```python
days = delivery.batches.days
parent_directory = days.path
latest_day = days[-1]
day_value = latest_day.kwargs["day"]

for day in days:
    for part in day.parts:
        part_number = part.kwargs.part
        part_path = part.path
```

`args` contains unnamed captures. `kwargs` supports mapping and attribute
access for named captures. Use mapping lookup for names such as `"items"` that
collide with mapping methods.

| Collection operation | Result |
| --- | --- |
| `collection[index]` | One `Match` |
| `collection[slice]` | Another collection |
| `filter(*args, **kwargs)` | Matching items, in collection order |
| `find(*args, **kwargs)` | The sole item, or `MismatchErr` |
| `format(*args, **kwargs)` | A planned `SchemaRoot[Schema]` |

```python
selected_days = days.filter(day=datetime(2026, 9, 10))
selected_day = fss.raise_mismatch(
    days.find(day=datetime(2026, 9, 10))
)
```

Formatting a collection or a concrete match plans a path without I/O. Its
return type is `SchemaRoot[Schema]`: it neither preserves the generated child
type nor claims that the path exists.

```python
planned_day = days.format(day=datetime(2026, 9, 11))
replanned_day = latest_day.format(day=datetime(2026, 9, 11))
```

### Public path and match protocols

```text
@runtime_checkable
class Located(Protocol):
    @property
    def path(self) -> Path: ...
    def __fspath__(self) -> str: ...

@runtime_checkable
class Match(Located, Protocol):
    @property
    def args(self) -> tuple[str | int | datetime, ...]: ...
    @property
    def kwargs(self) -> Mapping[str, str | int | datetime]: ...
    def format(
        self,
        *args: str | int | datetime,
        **kwargs: str | int | datetime,
    ) -> SchemaRoot[Schema]: ...
```

The concrete `kwargs` mapping also supports capture access by attribute, as
shown above.

### Static typing of generated children

Generated child names are available at runtime, but static types remain broad:

- Class-level child access returns `type[Schema]`.
- Instance child access returns a union of possible child kinds.
- `Delivery.RootT` is `type[SchemaRoot[Schema]]`.

Use an explicit `fss.SchemaRoot[Delivery]` annotation when the schema parameter
must remain exact. Do not expect a type checker to infer exact generated child
or loader-result types from attribute names.

## Creating with schemas

`relative_to` creates a planned layout without checking the filesystem. Fixed
children already have paths. `format` turns a template into a concrete planned
root. Writing and validation remain separate.

```python
planned: fss.SchemaRoot[Delivery] = Delivery.relative_to(
    "/srv/curated/delivery-42"
)
event_date = datetime(2026, 9, 10)
planned_day = planned.batches.days.format(day=event_date)
planned_part = planned_day.parts.format(part=0)

manifest = Manifest("delivery-42", 1_000)
parquet_bytes = b"parquet payload"
planned.manifest.put(manifest)
planned_part.put(parquet_bytes)

created = planned.bind()
```

`SchemaRoot[Delivery]` keeps the schema parameter, so `bind()` returns
`Delivery | MismatchErr`. Calling `root()` on a bound schema creates a plan at
the same path and intentionally drops the validation guarantee.

```python
reopened_plan: fss.SchemaRoot[Delivery] = delivery.root()
```

### Reading and writing

| Operation | Result |
| --- | --- |
| `file.read_bytes()` | `bytes` |
| `file.read_text()` | `str` |
| `file.put(data)` | Writes to the declared file |
| `file.load()` | Decoded value; annotate it with the declared model type |
| `fss.put(path, data)` | Lower-level direct-path helper; creates missing parent directories |

```python
manifest: Manifest = delivery.manifest.load()


def load_manifest(path: Path) -> Manifest:
    return Manifest(path.stem, 0)


custom_manifest = fss.File(
    "manifest.custom",
    schema=load_manifest,
)
```

`put` accepts `bytes`, text, a source `Path`, an object with `save(Path)`, or a
dataclass instance. Codec selection and serialization details are outside this
API reference.

```text
put(path, data) -> None
```
