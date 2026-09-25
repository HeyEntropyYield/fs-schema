# Changelog

API by git tag. Signatures: [reference](https://heyentropyyield.github.io/fs-schema/reference/).

## Unreleased

- **Write**
  `link_to`, `copy_to`
  [Reading and writing](https://heyentropyyield.github.io/fs-schema/reference/#reading-and-writing)
  - `link_to` replaces a path with a symlink. `hard=True` hardlinks that file's inode. A string target is a path. The symlink is not followed.
  - `copy_to` copies a file or directory onto a path, a path string, or a schema node.
    `clean=False` keeps names that exist only at the destination. `clean=True` removes the destination first.
    The same path, or one path inside the other, raises `ValueError`.
    A symlink at the destination is replaced. The copy does not write through it.
    [camera roll](https://github.com/heyentropyyield/fs-schema/blob/master/examples/symlink_copy.py)

## v0.6.0

`create` writes a plan. Nested directory overrides merge. `exists_opt(None)` is `None`.

- **Write**
  `relative_to`, `create`, `root`, `format`, `parse`, `put`
  [Creating with schemas](https://heyentropyyield.github.io/fs-schema/reference/#creating-with-schemas)
  - `relative_to` fills paths. `create` writes that plan and does not check the tree.
    [quickstart](https://github.com/heyentropyyield/fs-schema/blob/master/examples/quickstart.py#L68-L71)
  - `create` on a bound schema raises `TypeError`: `use root()`.
  - `dir.create()` makes that directory and required child directories. No files, no optional directories, no collection members.
  - `None` leaves an optional child absent. An unknown alias raises `KeyError`.
  - A collection takes a filename-to-body map, or a list of `(captures, payload)` pairs. Keys that are capture names are rejected.
    [delivery](https://github.com/heyentropyyield/fs-schema/blob/master/examples/data_delivery_after.py#L140-L154)
  - A file collection whose captures were set by `format` takes the body alone. A directory collection does not.
    [one member](https://github.com/heyentropyyield/fs-schema/blob/master/examples/smoke.py#L30-L31)
  - A missing capture raises `TypeError` and names it. Two values for one capture raise `ValueError`.
  - `put` replaces the path in one step. No body writes an empty file. Body: bytes, text, a file to copy, `save`, or a dataclass as JSON.
    [Reading and writing](https://heyentropyyield.github.io/fs-schema/reference/#reading-and-writing)

- **Declare**
  `Schema`, `File`, `Dir`
  [Inheritance and replacement](https://heyentropyyield.github.io/fs-schema/reference/#inheritance-and-replacement)
  - A nested directory override merges children with the base. A file override replaces that file.
  - On the class, a file or a collection exposes `alias`, `fmt`, `match`, `min`, `max`. `Coincident.parts.match`.
  - An exact directory with a schema class is that class. `Parent.child.file.match`.
  - A directory collection exposes `fmt` and `match` on the collection, not the child schema's fields.

- **Bind**
  `Schema.bind`, `exists_opt`, `MismatchErr`
  [Applying schemas](https://heyentropyyield.github.io/fs-schema/reference/#applying-schemas)
  - `bind` takes a string, a `Path`, or any `__fspath__` value, including a schema node. A planned root binds itself.
  - `exists_opt(None)` returns `None`.
    [Fixed directories and files](https://heyentropyyield.github.io/fs-schema/reference/#fixed-directories-and-files)
  - A wrong collection count names dangling symlinks that matched: `(dangling: gone.png)`.
  - Read follows a live symlink. `put` replaces a symlink at that path and does not write through it.

- **Read**
  [Integrations](https://heyentropyyield.github.io/fs-schema/integrations/)
  - `glom` is no longer installed with the package. Navigation examples are in the docs.

## v0.5.0

Exact names and collections use different constructors. `MismatchErr` is falsy.

- **Declare**
  `File`, `Dir`, `dt`, `optional`, `skip_mismatch`
  [Defining schemas](https://heyentropyyield.github.io/fs-schema/reference/#defining-schemas)
  - Exact `File` and `Dir` take a positional name. A collection is keyword-only: `fmt`, `match`, or both.
  - `optional=True` on an exact name is `min=0`.
    [optional file](https://github.com/heyentropyyield/fs-schema/blob/master/examples/glom_navigation.py#L20)
  - `sort`, `sort_rev`, and `skip_mismatch` on an exact name raise `ValueError`.
  - `dt("%Y-%m-%d")` captures `ts`. `dt("%Y-%m-%d", "day")` names it. `dt("%Y-%m-%d", "")` stays positional.
  - `skip_mismatch` drops a formatted name that fails `match`, and a directory member whose children do not match.

- **Bind**
  `Schema.bind`, `MismatchErr`, `is_mismatch`
  [Applying schemas](https://heyentropyyield.github.io/fs-schema/reference/#applying-schemas)
  - `MismatchErr` is falsy. A bound schema is truthy. `if not result` works for `Schema | MismatchErr`.
  - A result that might be another schema still needs `is_mismatch`.
  - A nested schema binds as that class. An optional exact child is `None` when absent.

## v0.4.6

First public. Alpha. `import fs_schema as fss`. Python 3.10–3.14.

- **Declare** — mapping; `name` | `fmt` | `match`; counts, alias, sort; one-base inherit/replace.
  `Schema`, `Layout`, `File`, `Dir`, `FILES`, `dt`
  [Defining schemas](https://heyentropyyield.github.io/fs-schema/reference/#defining-schemas)
- **Bind** — first failure; extras ignored.
  `Schema.bind`, `SchemaRoot.bind`, `MismatchErr`, `is_mismatch`, `raise_mismatch`
  [Applying schemas](https://heyentropyyield.github.io/fs-schema/reference/#applying-schemas)
- **Read** — attr/item access; `PathLike`.
  `Located`, `Match`, `exists_opt`, `.path`, `__fspath__`, `.exists`, `.read_bytes`, `.read_text`, `.args`, `.kwargs`, `.filter`, `.find`, `.where`, `.get`
  [Using schemas](https://heyentropyyield.github.io/fs-schema/reference/#using-schemas)
- **Write** — plan then bind; JSON dataclasses via extras `mashumaro`, `orjson`.
  `Schema.relative_to`, `SchemaRoot`, `.format`, `.root`, `.put`, `.load`, `put`, `raise_exn`
  [Creating with schemas](https://heyentropyyield.github.io/fs-schema/reference/#creating-with-schemas)
- **Types** — generated child attrs; dynamic names stay a union.
  `SchemaRoot[S]`, `__version__`
  [Static typing](https://heyentropyyield.github.io/fs-schema/reference/#static-typing-of-dynamic-children)
