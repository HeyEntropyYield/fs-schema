# Typechecking

The runtime behavior is the API. A layout dict does not say whether a child name is a file, a directory, or a collection. Because of that, a type checker has to give every child the same type.

This page covers what you may run into with one checker, and what to do about it.

## basedpyright 1.39.10 (2026-09-25)

### Import root

This can happen if a directory you point the checker at contains a file named `fs_schema.py`.

basedpyright treats the root of each execution environment as its first import root. So the checker picks that local `fs_schema.py` over the installed package, and in the checker's view `import fs_schema` loads your file. Python does not resolve the import this way, and it still loads the installed package.

The checker gives no warning when this happens. It checks your code against the wrong module, and its results for `fss.` calls stop matching what actually runs.

You can't ignore this, because there is no diagnostic to ignore. The only fix is to rename your module.

### Unannotated `schema`

The usual way to write a layout is `schema = { ... }` on a subclass. basedpyright reports `reportUnannotatedClassAttribute` on that line, even though `Schema` already annotates `schema`.

Here is what you can do, most practical first.

Turn the rule off for the file that defines your schemas. Put this comment on the first line of that file, before the docstring:

```text
# pyright: reportUnannotatedClassAttribute=false
```

It only covers that one file. You could turn the rule off for a whole directory with an `executionEnvironments` setting, but then it also hides real mistakes in the other modules there.

Or annotate the assignment:

```python
import fs_schema as fss
from typing import ClassVar

class Annotated(fss.Schema):
    schema: ClassVar[fss.Layout] = {
        "parts": fss.File(fmt="part-{part:d}.parquet"),
    }
```

Or pass the dict on the class line:

```python
class Keyword(fss.Schema, schema={
    "parts": fss.File(fmt="part-{part:d}.parquet"),
}):
    pass
```

Pick one of these two forms. If you set `schema` both ways on the same class, you get a `TypeError`.

`@final` also makes the warning go away, but it isn't recommended. Schemas are meant to be subclassed, because subclassing is how a layout grows. Marking one `@final` says something that isn't true.

### Child access

Every child name has the same static type. So some calls pass the checker and then fail or return something unexpected when you run them:

- A name that is not in the schema raises `AttributeError`.
- A missing optional file is `None`.
- `format` or `len` on an exact file raises.
- `read_text` and `read_bytes` typecheck on every child. A directory does not have them at runtime.

basedpyright gives no diagnostic for any of these. The code typechecks, and the problem only shows up at runtime.

When you need the real type, annotate that one name where you use it. You could also write out a type for every child on the class, but that repeats the layout, and the package does not ask you to do it.

### Loading

`load()` on a child is `object | Exception` until you name the model. With no annotation, that is as specific as the type gets: the file's model is not on the child type. An ignore on `load` itself would not change the caller's error.

Write the type on the assignment. basedpyright fills the result in from that annotation, so there is no `reportAssignmentType` to ignore:

```text
loaded: Manifest | Exception = node.load()
manifest: Manifest = fss.raise_exn(node.load())
```

After `isinstance(loaded, Exception)`, the checker treats `loaded` as `Manifest`.

Or pass the model. Same result, and the annotation can sit on the call instead of the variable:

```text
loaded = node.load(Manifest)
```

`load()` with no argument is the runtime call. A runtime checker already sees the declared model, so it does not need the argument. Pass a model when you do not want to annotate the variable. If the file declares no loader, that argument is what gets used. If it declares a class, the class has to be that model or a subclass of it. Otherwise `load` raises `TypeError` and does not read the file. A callable loader has no class to compare, so call `load()` with no argument.

A helper that loads one file takes `Loadable` and calls `load(Manifest)`. A directory is not `Loadable`.

### Sort keys

`kwargs` is a mapping from a format name to a value. The name is a string, and it is known when the class is created, not in the type. Values for one name share a type. A different name can be an `int`, a `str`, or a `datetime`. There is no static map from those names to those types.

`m.kwargs["epoch"]` is typed as possibly `None`, because a regex group can be absent. A format field such as `{epoch:d}` is never `None` when the file matches. `format` still wants a value that is not `None`, so check a regex group before you pass it.

`lambda m: m.kwargs["epoch"]` typechecks either way. But if a `None` key does turn up next to other values, `list.sort` raises `TypeError`. The checker says nothing about this.

You can annotate the lambda as returning `int`, but that only changes what the checker sees. Sorting still gets the real value, so a real `None` still raises.

What actually helps is making sure the key can't be `None`. Use a format field when you can. If you use a regex group that might be absent, the key function needs to handle the `None` case itself.
