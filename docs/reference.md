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
| Declarations | `File`, `Dir`, `FILES`, `xor`, `dt` |
| Paths and matches | `Located`, `Match`, `exists_opt` |
| Result helpers | `MismatchErr`, `is_mismatch`, `raise_mismatch`, `raise_exn` |
| Writing | `put`, `link_to`, `copy_to`, `captures`, `create` |
| Package metadata | `__version__` |

All names in this table are available from `fs_schema`.

## Defining schemas

Subclass `Schema`. Put the layout in `schema`.
Nested mapping = nested directory.
One Schema base. No methods, mixins, or extra metaclasses.

The same name works on the class line.
Use that when a type checker warns that the body assignment needs an annotation.
Do not set both.

```python
class Batch(fss.Schema, schema={
    "parts": fss.File(fmt="part-{part:d}.parquet"),
}):
    pass
```

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
`Dir(...): Child` -> child type is `Child`.
Inline `{...}` -> private Schema with stable identity.
`Dir(schema=Required)` -> class-time subset check. RHS still owns children.

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
`match` alone: unnamed groups -> `args`, named -> `kwargs`. Optional groups -> `None`.

Untyped format fields -> `str`. `:d` -> `int`. Datetime fields -> `datetime`. A named field starts with a letter. A number is positional.

```python
part_decl = fss.File(
    fmt="part-{part:d}.{ext}",
    match=r"(?i).+\.(?:json|yaml|toml)",
)
day_decl = fss.Dir(alias="days", fmt=fss.dt("%Y-%m-%d"), min=0)
```

`fss.dt("%Y-%m-%d")` -> `"{ts:%Y-%m-%d}"`. Capture is `kwargs["ts"]`.
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
class Letter(fss.Schema):
    schema = {"body": "body.txt"}


class Table(fss.Schema):
    schema = {"rows": "rows.json"}


class Bundle(fss.Schema):
    schema = {
        fss.Dir(".", alias="letter"): Letter,
        fss.Dir(".", alias="table"): Table,
    }
```

`bundle.letter` is a `Letter`. Pass that where a `Letter` is required. `fmt` and `match` do not belong on this form. An alias is required.

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
    fmt: str,
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
    fmt: str,
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

`with_` copies one child and changes the copy. `optional=True` makes an exact name optional. Subclass the schema and put that copy in a `FILES` list. The other children stay. You do not retype the alias. A new alias on that same filename is rejected.

```python
class Loaded(fss.Schema):
    schema = {
        "receipt": fss.File("receipt.json", schema=Manifest),
        "note": "note.txt",
    }


class Staged(Loaded):
    schema = {fss.FILES: [Loaded.receipt.with_(optional=True)]}
```

```text
node.with_(**changes) -> Self
```

```text
dt(pattern: str, name: str = "ts") -> str
```

The mapping table above defines the valid `Layout` key-value pairings.

### Warnings

`Schema.warn` is `True`. `warn = False` on a subclass silences warnings from that class.

## Applying schemas

`bind` checks the tree.
Success -> that Schema class. Failure -> `MismatchErr`.
Fixed `Dir(...): Child` -> `Child`.
Repeated `Dir(...): Batch` -> each item is a `Batch` with captures.
Exact `optional=True` -> `None` if absent. Write after bind via `bound.root()`.

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

Bind checks structure and counts now. Ignores extras.

When several things are wrong, `bind` returns one `MismatchErr` with one line per problem, in declaration order, so `str(err).splitlines()` lists them all. A single problem is a single line. `fast=True` stops at the first and does not look at the rest.

```text
Schema.bind(root: str | os.PathLike[str], *, fast=False) -> Self | MismatchErr
SchemaRoot[S].bind(*, fast=False) -> S | MismatchErr
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

Children support attribute access and item lookup. An alias is an attribute.
So is the disk name, with characters outside `[A-Za-z0-9_]` replaced by `_`.
Item lookup also accepts the raw disk name.

A directory, schema, root, or bound directory iterates its children.
A collection iterates its matches.
`for` and comprehensions use that.

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

```python
days.where(day=datetime(2026, 9, 10))  # every named constraint
days.where(day=None)  # None matches an optional capture
days.where(None, 1)  # None wildcards that position; extra positions drop the match
days.where()  # same collection
days.where(no_such=1)  # KeyError, even on an empty plan
kept = days.filter(lambda args, kwargs: kwargs["day"] == datetime(2026, 9, 10))  # still a collection; empty stays one
days.get()  # first match, or None
days.get(-1, default=latest_day)  # negative index; that default, including None
_ = days[9]  # IndexError
```

`days.where(ts=when)` keeps every sibling or none when `ts` is an ancestor in scope.

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

@runtime_checkable
class Loadable(Protocol):
    def load(self, model: type[Model]) -> Model | Exception: ...
```

`Loadable` is a bound file or a file match a helper can take. The helper calls `load(Model)`. A directory does not have it.

The concrete `kwargs` mapping also supports capture access by attribute, as
shown above.

### Static typing of dynamic children

```python
annotated: fss.SchemaRoot[Delivery] = Delivery.relative_to("/srv/incoming/delivery-42")
_ = Delivery.RootT  # type[SchemaRoot[Schema]]; a dynamic child is bare type
_ = annotated.batches.days  # navigates; the static type is not the exact collection class
```

A fixed child keeps its class. A dynamic name does not. Instance access is a union of those child kinds.

## Creating with schemas

`relative_to` picks a root and fills in the paths. It does not write anything. `create` writes and returns that same node. A failure raises. The return is never a failure, so `if not node.create(...)` does not catch one.

`bind` returns `MismatchErr` instead of raising. `load` returns an `Exception` instead of raising. That value is true, so `if not load()` does not catch a failed load either.

<details markdown="block">
<summary>What create raises</summary>

The filesystem:

- `OSError` - the write failed
- `FileNotFoundError` - the body is a path to copy, and that path is not there

Bad arguments:

- `KeyError` - that name is not a child
- `TypeError` - the value has the wrong shape. One `(captures, payload)` pair was passed instead of a list. A collection was given one body. Captures are missing. Two names for the same child disagree.
- `ValueError` - a filename does not match that child
- `BeartypeCallHintParamViolation` - the value is the wrong Python type
- `NotFoundLookupError` - a file was given a mapping

</details>

```python
fs: fss.SchemaRoot[Delivery] = Delivery.relative_to("/srv/curated/delivery-42")
event_date = datetime(2026, 9, 10)
manifest = Manifest("delivery-42", 1_000)
parquet_bytes = b"parquet payload"
fs.create(
    manifest=manifest,
    batches={"days": [(  # directory collection: one pair per day
        {"day": event_date},  # dict of format names
        {"parts": [(fss.captures(part=0), parquet_bytes)]},  # same slot via captures
    )]},
)
another = fs.batches.days.format(day=datetime(2026, 9, 11))  # templates under that day remember day
another.parts.format(part=0).create(b"next")  # captures already set, so the body is the only argument
created = fs.bind()
fs.manifest.create("notes.txt")  # the file contains the text notes.txt
fs.manifest.create(Path("notes.txt"))  # a path is copied
fs.manifest.create()  # empty file
fs.create()  # required child directories; no files, no optional, no members
fs.create(manifest=None)  # omitted or None stays absent
fs.batches.days.parse("nope")  # a basename that does not fit is ValueError here
fs.batches.days.create([(fss.captures(0), b"x")])  # captures(0) fills {} or {0}, not {part}
```

```python
delivery.create()  # TypeError; a bound file's create is put
plan = delivery.root()  # fresh unchecked plan; keep it if you write a child and then bind
plan.bind()
```

`{"2026-09-10": b"..."}` keys are filenames. A capture name there says so. A directory mapping is child names, so it does not take that bare body. A missing `{name}` is `TypeError` and names it. Two values for one capture is `ValueError`.

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
| `file.load(Model)` | `Model` or an exception. For a static checker. No argument is the runtime call |
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

```python
fss.put(delivery.manifest, "notes.txt")  # text notes.txt, even when that path exists
fss.put(delivery.manifest, Path("notes.txt"))  # copies that file
fss.put(delivery.manifest, delivery.manifest)  # a schema node copies too
fss.put(delivery.manifest, None)  # empty file; missing parents are created
loaded: Manifest = fss.raise_exn(delivery.manifest.load())
delivery.manifest.load(Manifest)  # same call, typed Model | Exception


class Other:
    pass


delivery.manifest.load(Other)  # TypeError before the read; a callable loader does this too
```

`fs-schema[mashumaro]` stores a dataclass as JSON. `fs-schema[orjson]` is a faster encoder. A reader sees the old file or the new one. An object with `save` writes a file, then that file replaces the path. No declared loader ignores `load(Model)`.

```text
put(path, data=None) -> None
link_to(path, target, *, hard=False) -> None
copy_to(source, dest, *, follow_symlinks=True, clean=False) -> None
raise_exn(value: T | Exception) -> T
```

```text
node.link_to(target, *, hard=False) -> None
node.copy_to(dest, *, follow_symlinks=True, clean=False) -> None
```

```python
class Album(fss.Schema):
    schema = {"images": fss.File(fmt="{stem}.png", min=0)}


album = Album.relative_to(Path("album"))
album.images.parse("a.png").link_to(Path("camera/a.png"))  # symlink; a link to a link stays; same replace as put
album.images.parse("a.png").link_to(Path("camera/a.png"), hard=True)  # inode; OSError across filesystems
bound = fss.raise_mismatch(Album.bind(Path("album")))
publish = Album.relative_to(Path("publish"))
bound.copy_to(publish)  # regular files, including a link to a directory; extra names stay
bound.copy_to(publish, follow_symlinks=False)  # link text unchanged
bound.copy_to(publish, clean=True)  # destination removed first
fss.link_to("album/b.png", "camera/b.png")  # a string target is a path
fss.copy_to(bound, publish)  # source and dest are paths or schema nodes
album.copy_to(album)  # the same path, or one path inside the other, is ValueError
```

`examples/symlink_copy.py` links each frame, then publishes that tree as regular files.

### Symlinks

A link lets a tree match the schema while the bytes stay somewhere else. `examples/symlink_copy.py` links camera files into a roll, then `copy_to` writes regular files.

Raise an issue if one of these is a problem.

- `bind` and `load` follow a link. The bound path stays the link. A link of the wrong kind, or a dangling link, is `MismatchErr`. An optional dangling link counts as absent.
- `put` and `File.create` replace a link with a regular file. The file it pointed at is not changed.
- `Dir.create` writes inside a link to a directory. The link stays. A link to a file, or a dangling link, raises `FileExistsError`.
- `link_to` replaces a file or a link. It can point at a missing path. It does not replace a real directory.
- `copy_to(follow_symlinks=True)` writes regular files and directories, including a link that points at a directory. `False` copies the link text unchanged.
- A link at the destination is replaced, not written through. A dangling link is missing to `exists_opt`.

## Ancestor captures

A nested dict sees the ancestor. A named class does not. Closest wins. `<ts:spec>` overrides when both specs are the same type.

`<n>` on the same fmt as `{n}` is that field again. The name matches when the values are equal. `<n:02d>` is a second way to write it, so `1_01` and `1_1` are both `n=1`. A different type is a declaration error.

```python
class Roll(fss.Schema):
    schema = {
        fss.Dir(alias="runs", fmt="run_{ts:%Y%m%d}", min=0): {
            "log": "<ts>.log",  # the run's ts
            "mark": "a/<b>.txt",  # basename a<b>.txt
            "parts": fss.File(fmt="<ts>_{n:d}_<n:02d>.txt", min=0),  # <n:02d> is this file's n again
        }
    }


def write_run(root: Path, when: datetime) -> None:
    Roll.relative_to(root).runs.format(ts=when).create(
        log="hello\n",
        parts=[({"n": 1}, b"part\n")],  # 19700101_1_01.txt
    )
```

[Example](https://github.com/heyentropyyield/fs-schema/blob/master/examples/parent_capture.py)

## xor

Exclusive union. One branch binds, in definition order. The first success wins.

```text
xor(*branches: type[Schema] | dict, **named: type[Schema] | dict)
```

A directory value is one of:

```text
Schema
{"dict": "mapping.txt"}
{}
xor(UnnamedSchema, {"inline": "schema.txt"}, this_schema=ThisSchema)
xor(**branches)
(UnnamedSchema, AnotherSchema)
```

`Schema`, a dict, and `{}` are one schema. `xor(Letter)` with no keyword is that schema too. `xor(letter=Letter)` and `xor(**branches)` stay a union, so the name still works. A tuple is an unnamed union.

```python
class Letter(fss.Schema):
    schema = {"body": "body.txt", "stamp": "stamp.json"}


class Table(fss.Schema):
    schema = {"rows": "rows.json", "stamp": "stamp.json"}


class Open(fss.Schema):
    schema = {"slot": fss.xor(Letter, Table)}


class Box(fss.Schema):
    schema = {"slot": fss.xor(letter=Letter, table=Table)}


def publish_note(root: Path) -> str:
    planned = Open.relative_to(root)
    planned.slot.body.create("hello\n")  # unnamed: shared children sit on the xor
    planned.slot.stamp.create("{}\n")
    _ = planned.slot[0]  # that branch anyway
    bound = fss.raise_mismatch(planned.bind())  # Letter or Table
    return bound.slot.body.read_text()


def publish_letter(root: Path) -> str:
    _ = Box.slot.letter  # a keyword stays the Letter class
    planned = Box.relative_to(root)
    planned.slot.letter.create(body="hello\n", stamp="{}\n")
    bound = fss.raise_mismatch(planned.bind())
    _ = Box.bind(root, fast=True)  # still tries every branch
    return bound.slot.body.read_text()  # .letter is not on the bound value
```

`planned.slot.rows` warns, and reading it raises. `planned.slot.create()` on the union raises. A directory whose name matched, but no branch bound, is `MismatchErr`. `skip_mismatch` drops it.

[Example](https://github.com/heyentropyyield/fs-schema/blob/master/examples/xor_directory.py)
