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
| Result helpers | `MismatchErr`, `is_mismatch`, `raise_mismatch`, `raise_exn` |
| Writing | `put` |
| Package metadata | `__version__` |

All names in this table are available from `fs_schema`.

## Defining schemas

Subclass `Schema` and define a `schema` mapping. Nested mappings represent
nested directories. A Schema subclass has exactly one direct Schema base.
Schema subclasses are layout declarations; do not add methods, mixins, custom
metaclasses, or other behavior, as those uses are unsupported.

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
keyword-only. Every declaration requires `name`, `fmt`, or `match`. For a fixed
directory, an explicit `ChildSchema` is both the nested layout and its exact
runtime type. A fixed inline mapping receives one private `Schema` subtype with
stable identity, visible through recursive class-level navigation.

`Dir(..., schema=Required)` checks the right-hand-side layout when the
containing Schema is defined. It must contain the required declarations
recursively; extra declarations are fine. `Required` is not merged, and the
right-hand side still controls the directory's children and runtime type.

### Templates, matching, and allowed match counts

| Option | Meaning |
| --- | --- |
| `name` | Exact basename. It cannot be combined with `fmt`. |
| `fmt` | Full-basename parse and format template, validated when declared. |
| `match` | Regex selector on full basename with `re.fullmatch`, compiled when declared. |
| `min` | Minimum count; defaults to `1`. Use `0` for an optional `fmt`/`match` collection. |
| `max` | Maximum count. Exact names require `min=max=1`; templates are unbounded. |
| `alias` | Name used for child access in Python. |
| `sort` | Key function for template matches. |
| `sort_rev` | Reverse the match order when true. |
| `schema` | Loader for a file, or an extra schema contract for a directory. |

With `name`, `match` validates the exact basename. With `fmt`, it adds a filter without changing format captures. Used alone, `match` exposes unnamed groups in `args` and named groups in `kwargs`. Optional groups produce `None`.

Untyped format fields produce `str`, `:d` fields produce `int`, and datetime format fields produce `datetime`.

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

Ordinary inheritance starts with the direct base's effective layout. The
subclass may add declarations or replace inherited ones.

```python
class AuditedDelivery(Delivery):
    schema = {
        "audit": "audit.json",
    }
```

Within one directory, distinct children cannot collide by alias, exact name,
normalized name, or `fmt`; ambiguous layouts fail when the class is defined.
Aliases, names, and formats identify inherited declarations for whole-node
replacement. Match-only declarations without one of those identities append.

### Declaration API

```text
File(
    name: str = "",
    *,
    fmt: FmtLike | None = None,
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
    fmt: FmtLike | None = None,
    match: str | None = None,
    min: int = 1,
    max: int | None = None,
    alias: str | None = None,
    sort: Callable[[Match], str | int | float | datetime | Located] | None = None,
    sort_rev: bool = False,
    schema: type[S] | None = None,
) -> Dir[S]

dt(pattern: str) -> FmtLike
```

The mapping table above defines the valid `Layout` key-value pairings.

## Applying schemas

`bind` checks an existing directory tree. It returns an ordinary instance of the
exact requested schema class on success (`type(result) is Delivery` below), or a
`MismatchErr` value on failure. Fixed directories backed by explicit or inline
schemas have that exact Schema runtime type. Repeated directories bind to
collections whose elements are ordinary directory matches with captures and
child navigation.

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

Binding checks declared structure and allowed match counts at that moment. It
ignores undeclared entries, is not a filesystem lock, and returns the first
mismatch.

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
access for named captures. Optional regex captures can be `None`. Use mapping
lookup for names such as `"items"` that collide with mapping methods.

| Collection operation | Result |
| --- | --- |
| `collection[index]` | One `Match`; normal sequence indexing may raise `IndexError` |
| `collection[slice]` | Another collection of the same concrete type |
| `filter(predicate)` | Accepted matches as the same concrete collection type, in collection order |
| `find(predicate)` | The first accepted match, or `None` |
| `where(*args, **kwargs)` | Matches whose captures have the positional prefix and named subset |
| `get(index=0, default=...)` | Safely indexed match, or the supplied default when out of range |
| `format(*args, **kwargs)` | Planned fixed file or recursively navigable fixed directory (format-backed collections only) |

A predicate receives the pair `(match.args, match.kwargs)`. Filtering returns a
materialized result that keeps collection capabilities such as slicing and, for
format-backed collections, `format()`. Empty results are collections too.

`where` combines all supplied constraints. Positional values match a capture
prefix, with `None` acting as a wildcard for that position; named values match a
subset, where `None` matches an optional capture value. Unknown named capture
fields raise `KeyError`, even on an empty planned collection. More positional
values than a match has simply reject that match. Calling `where()` without
constraints returns an equivalent collection.

`get` accepts positive and negative indexes. With no explicit default, an
out-of-range index returns `None`; an explicit `None` or other default is
returned unchanged. Other errors are not hidden. This makes one-result queries
concise without changing ordinary sequence indexing.

```python
def is_selected_day(args, kwargs):
    return kwargs["day"] == datetime(2026, 9, 10)

selected_days = days.filter(is_selected_day)
selected_day = days.find(is_selected_day)
selected_by_capture = days.where(day=datetime(2026, 9, 10))
selected_by_capture_or_none = selected_by_capture.get()
```

```text
filter(predicate, /) -> Self
find(predicate, /) -> Match | None
where(*args: str | int | datetime | None,
      **kwargs: str | int | datetime | None) -> Self
get(index: int = 0) -> Match | None
get(index: int, default: T) -> Match | T
get(*, default: T) -> Match | T
```

Capture names are dynamic, so static checking does not try to narrow keyword
names passed to `where`.

Formatting a format-backed collection plans one concrete path without I/O or
captures. A formatted directory remains recursively navigable, and a formatted
file retains its read, load, and put methods. Regex-only collections and
individual matches are not formattable.

```python
planned_day = days.format(day=datetime(2026, 9, 11))
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
    def args(self) -> tuple[str | int | datetime | None, ...]: ...
    @property
    def kwargs(self) -> Mapping[str, str | int | datetime | None]: ...
```

The concrete `kwargs` mapping also supports capture access by attribute, as
shown above.

### Static typing of dynamic children

Dynamically resolved class children use the bare `type` boundary. This is broad
enough for direct recursive navigation such as `Root.inline.leaf`, but it cannot
preserve whether each dynamically named child is a file class, collection class,
or exact generated `Schema` subtype. Instance child access likewise returns a
union of possible child kinds. `Delivery.RootT` remains
`type[SchemaRoot[Schema]]`.

Use an explicit `fss.SchemaRoot[Delivery]` annotation when the schema parameter
must remain exact. Fixed Schema-backed values retain their exact classes; only
dynamic static lookup loses that precision.

## Creating with schemas

`relative_to` creates a planned layout without checking the filesystem. Fixed
children already have paths. Planned collections are empty until binding; a
format-backed collection can produce one concrete planned child, while a
regex-only collection cannot be concretized without matching the filesystem.
Writing and validation remain separate.

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

Every descendant of a rooted plan is also planned and derived from the same
canonical declarations. Only the top-level `SchemaRoot` retains the schema/root
token and exposes `bind()`; descendants do not independently bind or return to
the root. Keep the root plan when that transition is needed.

```python
reopened_plan: fss.SchemaRoot[Delivery] = delivery.root()
```

### Reading and writing

| Operation | Result |
| --- | --- |
| `file.read_bytes()` | `bytes` |
| `file.read_text()` | `str` |
| `file.put(data)` | Writes to the declared file |
| `file.load()` | Declared value or decoding exception |
| `fss.put(path, data)` | Lower-level direct-path helper; creates missing parent directories |

```python
manifest: Manifest = fss.raise_exn(delivery.manifest.load())


def load_manifest(path: Path) -> Manifest:
    return Manifest(path.stem, 0)


custom_manifest = fss.File(
    "manifest.custom",
    schema=load_manifest,
)
```

`put` creates the target parent, then writes bytes or text, copies a source
`Path`, or calls `save(Path)`. Other dataclass instances are encoded as JSON
with Mashumaro. Install `fs-schema[mashumaro]` for the standard backend or
`fs-schema[orjson]` to prefer its faster backend.
`load()` returns decoding failures as values, and `raise_exn` raises one while
preserving the successful result type.

```text
put(path, data) -> None
raise_exn(value: T | Exception) -> T
```
