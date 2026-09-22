# Changelog

API by git tag. Signatures: [reference](https://heyentropyyield.github.io/fs-schema/reference/).

## v0.5.0

Exact names and collections are different constructors. `MismatchErr` is falsy. Bound nodes are truthy.

- **Declare** — exact `File`/`Dir` take a positional `name`. Collections are keyword-only `fmt` and/or `match`. `optional=True` on an exact name is `min=0`. `sort`, `sort_rev`, and `skip_mismatch` raise `ValueError` on an exact name. `dt(pattern)` captures `ts`. `skip_mismatch` drops a fmt hit that fails `match`, or a directory member whose children mismatch.
  `File`, `Dir`, `dt`
  [Defining schemas](https://heyentropyyield.github.io/fs-schema/reference/#defining-schemas)
- **Bind** — `MismatchErr` is falsy. A nested `Schema` binds as that schema.
  `MismatchErr`, `Schema`, `Schema.bind`
  [Applying schemas](https://heyentropyyield.github.io/fs-schema/reference/#applying-schemas)

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
