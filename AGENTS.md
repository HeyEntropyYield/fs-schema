# fs-schema

`./run.sh help` is the project API. After `./run.sh uv:venv:sync`, cmds use `.venv/bin` (no `uv run`).

## Commits

One line. No body. ASCII only. No names, task ids, or commit hashes.

## Layout

`src/fs_schema` is the installable package. Tests import that install (`--import-mode=importlib`). Do not put `src/` on `pythonpath`.

`examples/` is a pytest `pythonpath` entry (the directory itself, not the repo root).

## Code

ASCII in source and comments. `run.sh` is the task entry (portable; not make-only).

## Docs

Site config is `zensical.toml`. Zensical does not read pyproject.
