# fs-schema

Python typed schema for filesystem layouts.

Not published yet.

```bash
./run.sh setup:install-pre-commit   # once, after sync
./run.sh uv:venv:sync
./run.sh pretty
./run.sh check
./run.sh tests
./run.sh help
```

Maintainer: same GitHub Actions workflows, locally via [act](https://github.com/nektos/act):

```bash
./run.sh ci              # test.yml
./run.sh docs:deploy     # docs.yml
./run.sh publish         # publish.yml --input target=testpypi
./run.sh docs:serve      # local preview
```
