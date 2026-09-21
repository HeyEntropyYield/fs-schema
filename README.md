# fs-schema

[![PyPI](https://img.shields.io/pypi/v/fs-schema)](https://pypi.org/project/fs-schema/)
[![Python](https://img.shields.io/pypi/pyversions/fs-schema)](https://pypi.org/project/fs-schema/)
[![License](https://img.shields.io/pypi/l/fs-schema)](https://github.com/HeyEntropyYield/fs-schema/blob/master/LICENSE)

[![tests](https://github.com/HeyEntropyYield/fs-schema/actions/workflows/test.yml/badge.svg?branch=master)](https://github.com/HeyEntropyYield/fs-schema/actions/workflows/test.yml)
[![coverage](https://img.shields.io/badge/dynamic/json?url=https%3A%2F%2Fgithub.com%2FHeyEntropyYield%2Ffs-schema%2Freleases%2Flatest%2Fdownload%2Fcoverage.json&query=%24.message&label=coverage&color=brightgreen)](https://github.com/HeyEntropyYield/fs-schema/releases/latest)
[![Typed](https://img.shields.io/badge/typing-typed-informational)](https://pypi.org/project/fs-schema/)
[![docs](https://github.com/HeyEntropyYield/fs-schema/actions/workflows/docs.yml/badge.svg?branch=master)](https://heyentropyyield.github.io/fs-schema/)

[![Status](https://img.shields.io/pypi/status/fs-schema)](https://pypi.org/project/fs-schema/)
[![releases](https://img.shields.io/badge/dynamic/json?url=https%3A%2F%2Fapi.github.com%2Frepos%2FHeyEntropyYield%2Ffs-schema%2Freleases%3Fper_page%3D100&query=%24.length&label=releases)](https://github.com/HeyEntropyYield/fs-schema/releases)
<!-- [![Downloads](https://img.shields.io/pypi/dm/fs-schema)](https://pypistats.org/packages/fs-schema) -->
<!-- [![stars](https://img.shields.io/github/stars/HeyEntropyYield/fs-schema)](https://github.com/HeyEntropyYield/fs-schema/stargazers) -->

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
[Changelog](https://heyentropyyield.github.io/fs-schema/changelog/) ·
[Source](https://github.com/HeyEntropyYield/fs-schema) ·
[MIT LICENSE](https://heyentropyyield.github.io/fs-schema/LICENSE)

<details markdown="1">
<summary>Changelog</summary>

--8<-- "CHANGELOG.md"

</details>
