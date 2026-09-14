# fs-schema

`./run.sh help` is the project API. Sync first: `./run.sh uv:venv:sync`. After that, cmds use `.venv/bin` (no `uv run`).

## Commits

One line. No body. ASCII only. No names, task ids, or commit hashes.

## Layout

`src/fs_schema` is the package. Tests import the installed package (`--import-mode=importlib`). Do not add repo-root or `src/` to `pythonpath`.

## Code

ASCII in source and comments. `run.sh` is the task entry (portable; not make-only).

## Docs

Site config is `zensical.toml`. Zensical does not read pyproject.
