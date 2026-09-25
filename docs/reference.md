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
| Writing | `put`, `link_to`, `copy_to`, `create` |
| Package metadata | `__version__` |

All names in this table are available from `fs_schema`.

## Defining schemas

Subclass `Schema`. Put the layout in `schema`.
Nested mapping = nested directory.
One Schema base. No methods, mixins, or extra metaclasses.

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

`name` is the only positional arg. Need `name`, `fmt`, or `match`.
`Dir(...): Child` → child type is `Child`.
Inline `{...}` → private Schema with stable identity.
`Dir(schema=Required)` → class-time subset check. RHS still owns children.

### Templates, matching, and allowed match counts

| Option | Meaning |
| --- | --- |
| `name` | Exact basename. Not with `fmt`. |
| `fmt` | Full-basename parse/format template. |
| `match` | `re.fullmatch` on the basename. |
| `optional` | Exact: absent after bind is `None`. |
| `min` / `max` | Collection count. Default min 1, max unbounded. |
| `alias` | Python child name. |
| `sort` / `sort_rev` | Collection order. |
| `skip_mismatch` | Collection: drop a fmt hit that fails `match`, or a directory whose children mismatch. |
| `schema` | File loader, or extra Dir contract. |

`name` + `match` validates that basename.
`fmt` + `match` filters; captures stay from `fmt`.
`match` alone: unnamed groups → `args`, named → `kwargs`. Optional groups → `None`.

Untyped format fields → `str`. `:d` → `int`. Datetime fields → `datetime`.

```python
part_decl = fss.File(
    fmt="part-{part:d}.{ext}",
    match=r"(?i).+\.(?:json|yaml|toml)",
)
day_decl = fss.Dir(alias="days", fmt=fss.dt("%Y-%m-%d"), min=0)
```

`fss.dt("%Y-%m-%d")` → `"{ts:%Y-%m-%d}"`. Capture is `kwargs["ts"]`.
`fss.dt("%Y-%m-%d", "day")` names that capture. `fss.dt("%Y-%m-%d", "")` stays positional.

### Inheritance and replacement

Subclass layout starts from the base. Add or replace nodes.

```python
class AuditedDelivery(Delivery):
    schema = {
        "audit": "audit.json",
    }
```

Alias, name, or `fmt` collision fails at class creation.
Matching keys replace the inherited node.
Anonymous match-only decls append.

### One directory, several schemas

A schema has one base. There is no multiple inheritance.

`Dir(".", alias=...)` checks another schema against this same directory. The attribute is that schema. The parent is not.

Use this when one directory is several results, or several stages, and each result should stay its own type. A subclass adds another `Dir(".")`.

`optional=True` skips that schema when it does not match. The directory is still there.

```python
class Notes(fss.Schema):
    schema = {"body": "body.txt"}


class Metrics(fss.Schema):
    schema = {"score": "score.json"}


class Work(fss.Schema):
    schema = {
        fss.Dir(".", alias="notes"): Notes,
        fss.Dir(".", alias="metrics"): Metrics,
    }
```

`work.notes` is a `Notes`. Pass that where a `Notes` is required. `fmt` and `match` do not belong on this form. An alias is required.

### Declaration API

Exact basename:

```text
File(
    name: str,
    *,
    alias: str | None = None,
    match: str | None = None,
    optional: bool = False,
    schema: type[T] | Callable[[Path], T] | None = None,
) -> File[T]

Dir(
    ".",
    *,
    alias: str,
    optional: bool = False,
    schema: type[S] | None = None,
) -> Dir[S]

Dir(
    name: str,
    *,
    alias: str | None = None,
    match: str | None = None,
    optional: bool = False,
    schema: type[S] | None = None,
) -> Dir[S]
```

Collection (`fmt` and/or `match`, no `name`):

```text
File(
    *,
    fmt: FmtLike,
    match: str | None = None,
    min: int = 1,
    max: int | None = None,
    alias: str | None = None,
    sort: Callable[[Match], str | int | float | datetime | Located] | None = None,
    sort_rev: bool = False,
    skip_mismatch: bool = False,
    schema: type[T] | Callable[[Path], T] | None = None,
) -> File[T]

Dir(
    *,
    fmt: FmtLike,
    match: str | None = None,
    min: int = 1,
    max: int | None = None,
    alias: str | None = None,
    sort: Callable[[Match], str | int | float | datetime | Located] | None = None,
    sort_rev: bool = False,
    skip_mismatch: bool = False,
    schema: type[S] | None = None,
) -> Dir[S]
```

Regex-only collection omits `fmt` and supplies `match` instead.

```text
dt(pattern: str) -> FmtLike
```

The mapping table above defines the valid `Layout` key-value pairings.

## Applying schemas

`bind` checks the tree.
Success → that Schema class. Failure → `MismatchErr`.
Fixed `Dir(...): Child` → `Child`.
Repeated `Dir(...): Batch` → each item is a `Batch` with captures.
Exact `optional=True` → `None` if absent. Write after bind via `bound.root()`.

```python
result = Delivery.bind("/srv/incoming/delivery-42")
if not result:
    print(result)
else:
    delivery: Delivery = result
```

`MismatchErr` is falsy. Bound schemas are truthy.
`if not result` works when the type stays `S | MismatchErr`.
Cross-schema returns still need `is_mismatch`.

```python
delivery = fss.raise_mismatch(
    Delivery.bind("/srv/incoming/delivery-42")
)
```

`Schema.bind` takes a path. A string, a `Path`, and any value with `__fspath__` all work, including a schema node. A planned root binds itself.

```python
validated_again = Delivery.bind(delivery)
planned_delivery = Delivery.relative_to("/srv/incoming/delivery-42")
validated_from_plan = planned_delivery.bind()
```

Bind checks structure and counts now. Ignores extras. First mismatch wins.

```text
Schema.bind(root: str | os.PathLike[str]) -> Self | MismatchErr
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
have `exists()`. Fixed files add `read_bytes()`, `read_text()`, and `create()`.

Children support attribute access and exact item lookup. An explicit alias is
used unchanged. Otherwise, each run outside `[A-Za-z0-9_]` in the disk name
becomes `_`.

```python
log_file = delivery.transfer.download_log
same_request = delivery.transfer["request.json"]
```

Use `exists_opt(path)` when an absent optional node should become `None` rather
than a missing path. `exists_opt(None)` is `None`.

```text
exists_opt(path: str | os.PathLike[str] | None) -> Path | None
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
| `parse(source)` | Planned member named by `Path(source).name`. `source` may be a basename, a path, or any `__fspath__` value |

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

`relative_to` picks a root and fills in the paths. It does not write anything. `create` writes that plan and hands it back. `bind` reads the tree and checks that it matches the schema.

A file argument is whatever `put` accepts. A directory argument names child aliases. Leave an optional child out, or pass `None`, and it stays absent. An unknown alias raises `KeyError`. `create()` with no arguments creates that directory and every required child directory. It does not write files, and it does not create optional directories or collection members.

You do not `create` a collection as a whole.
`format(**captures)` names one member.
If that member is a directory, every template under it remembers the captures.
`parse(source)` names one member from a basename, a path, or another schema node.
A basename that does not fit raises `ValueError` there, not later at `bind`.
`create` on the member writes it.
A path-like body is copied.
A string body is text, even when it names a file that exists.

A list of members can go in the spec. Each item is a `(captures, payload)` pair: the captures are the `format` arguments, and the payload is what you would pass to `create` on that member. A mapping of filename to body writes those names as given. The keys are filenames. If a key is a capture name instead of a filename, the error says so.

If a file collection's captures were all remembered by an enclosing `format`, pass the file body by itself. A directory collection does not do that, because a mapping there already means filenames. A bare body that is still missing a capture raises `TypeError` and names the missing one. Two different values for the same capture raise `ValueError`.

```python
fs: fss.SchemaRoot[Delivery] = Delivery.relative_to("/srv/curated/delivery-42")
event_date = datetime(2026, 9, 10)
manifest = Manifest("delivery-42", 1_000)
parquet_bytes = b"parquet payload"
fs.create(
    manifest=manifest,
    batches={"days": [({"day": event_date}, {"parts": [({"part": 0}, parquet_bytes)]})]},
)
another = fs.batches.days.format(day=datetime(2026, 9, 11))
another.parts.format(part=0).create(b"next")
created = fs.bind()
```

`create` on a bound schema raises `TypeError`. Call `root()` and write on the plan. A bound file can still `create`; that is `put`.

`bind()` returns the schema when the tree matches, and `MismatchErr` when it does not. `root()` starts a fresh plan at the same path. That plan has not been checked. `bind()` lives on the plan from `relative_to` or `root()`. Keep that plan if you will bind after writing a child.

```python
fs: fss.SchemaRoot[Delivery] = delivery.root()
```

### Reading and writing

| Operation | Result |
| --- | --- |
| `file.read_bytes()` | `bytes` |
| `file.read_text()` | `str` |
| `file.create(data=None)` | Atomic write of one file. Creates missing parents |
| `dir.create(spec=None, **children)` | `mkdir` this directory and required child directories, then write the spec |
| `file.load()` | Declared value or decoding exception |
| `fss.put(path, data=None)` | Atomic file write. Creates missing parents |

```python
manifest: Manifest = fss.raise_exn(delivery.manifest.load())


def load_manifest(path: Path) -> Manifest:
    return Manifest(path.stem, 0)


custom_manifest = fss.File(
    "manifest.custom",
    schema=load_manifest,
)
```

`put` writes one file and creates any missing parent directories.
The new contents replace the old file in one step, so a reader sees either the old file or the new one.
Pass `None`, or omit the body, and the file is empty.
The body can be bytes, text, a path to copy, a schema node to copy, an object with `save`, or a dataclass stored as JSON.
A string is always text.
`Path("notes.txt")` copies that file.
The string `"notes.txt"` writes the text `notes.txt`, even when `notes.txt` exists in the same directory.
`save` is called on a file that then becomes the destination.
Install `fs-schema[mashumaro]` for dataclass JSON.
Install `fs-schema[orjson]` for a faster JSON encoder.
`load()` returns a decoding failure as a value.
`raise_exn` raises that failure and keeps the success type.

```text
put(path, data=None) -> None
link_to(path, target, *, hard=False) -> None
copy_to(source, dest, *, follow_symlinks=True, clean=False) -> None
raise_exn(value: T | Exception) -> T
```

`link_to` replaces the path with a link to `target`.
`hard=False` is a symlink and is not followed, so a link to a link stays pointed at that link.
`hard=True` is a hard link to the file inode. `os.link` raises `OSError` across filesystems.
A string target is a path.
The same atomic replace as `put`.

`copy_to` copies a file or directory onto another path.
Source and destination are paths, path strings, or schema nodes.
`follow_symlinks=True` writes regular files.
`follow_symlinks=False` keeps links.
`clean=False` copies onto what is already there. Extra names at the destination stay.
`clean=True` removes the destination first.
The same path, or one path inside the other, raises `ValueError`.

```text
node.link_to(target, *, hard=False) -> None
node.copy_to(dest, *, follow_symlinks=True, clean=False) -> None
```

```python
class Album(fss.Schema):
    schema = {"images": fss.File(fmt="{stem}.png", min=0)}


album = Album.relative_to(Path("album"))
album.images.parse("a.png").link_to(Path("camera/a.png"))
album.images.parse("a.png").link_to(Path("camera/a.png"), hard=True)
bound = fss.raise_mismatch(Album.bind(Path("album")))
publish = Album.relative_to(Path("publish"))
bound.copy_to(publish)
bound.copy_to(publish, follow_symlinks=False)
bound.copy_to(publish, clean=True)
fss.link_to("album/b.png", "camera/b.png")
fss.copy_to(bound, publish)
```

`examples/symlink_copy.py` links each frame, then publishes that tree as regular files.
