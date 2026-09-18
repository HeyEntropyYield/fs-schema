# fs-schema

Typed schemas for filesystem layouts. Dataclass-like declarations turn directory
contracts into validated, navigable Python values.

```bash
uv add "fs-schema[mashumaro,orjson]"
```

```python
from dataclasses import dataclass

import fs_schema as fss

@dataclass
class Contents:
    title: str

class DataDownload(fss.Schema):
    schema = {
        "packs": {
            fss.FILES: ["upload.log", "request.log"],
            fss.Dir(alias="days", fmt="{day:%Y-%m-%d}"): {
                "parts": fss.File(fmt="{stem}.{ext}", max=4),
            },
        },
        "contents": fss.File("contents.json", schema=Contents),
    }

download = fss.raise_mismatch(DataDownload.bind("."))
with open(download.packs.upload_log, encoding="utf-8") as stream:
    print(stream.read())
part = download.packs.days[-1].parts[-1]
print(part.kwargs.stem, part.path.stat().st_size)
contents: Contents = fss.raise_exn(download.contents.load())
print(contents.title)
```

Binding validates an existing layout. Templates are collections; indexing selects
a concrete match whose parsed captures are available through `.args` and
`.kwargs`. `relative_to()` plans output paths without claiming they exist.
Format-backed collections plan concrete files or recursively navigable
directories; only the top-level plan binds the whole schema. Dataclass schemas
use Mashumaro for JSON; install the `mashumaro` or faster `orjson` extra.

<details>
<summary>Expanded quickstart</summary>

```python
--8<-- "examples/quickstart.py"
```

</details>

<details>
<summary>Development</summary>

```text
--8<-- "docs/run-help.txt"
```

</details>

[API reference](https://heyentropyyield.github.io/fs-schema/reference/) ·
[Tutorial](https://heyentropyyield.github.io/fs-schema/tutorial/) ·
[Source](https://github.com/HeyEntropyYield/fs-schema) ·
[MIT LICENSE](https://heyentropyyield.github.io/fs-schema/LICENSE)
