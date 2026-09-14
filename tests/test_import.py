import re
import subprocess
import sys
from pathlib import Path

import fs_schema
from fs_schema import (
    FILES,
    Dir,
    File,
    Layout,
    Located,
    Match,
    MismatchErr,
    Schema,
    SchemaRoot,
    __version__,
    dt,
    exists_opt,
    is_mismatch,
    put,
    raise_mismatch,
)


def test_public_exports_are_explicit_end_user_api() -> None:
    explicit_exports = {
        "FILES": FILES,
        "Dir": Dir,
        "File": File,
        "Layout": Layout,
        "Located": Located,
        "Match": Match,
        "MismatchErr": MismatchErr,
        "Schema": Schema,
        "SchemaRoot": SchemaRoot,
        "__version__": __version__,
        "dt": dt,
        "exists_opt": exists_opt,
        "is_mismatch": is_mismatch,
        "put": put,
        "raise_mismatch": raise_mismatch,
    }
    assert all(value is vars(fs_schema)[name] for name, value in explicit_exports.items())
    assert "__all__" not in vars(fs_schema)


def test_private_runtime_names_are_not_reexported() -> None:
    private_names = (
        "_DirMatch",
        "_FileMatch",
        "_Fixed",
        "_FixedDir",
        "_FixedFile",
        "_LoadableFile",
        "_LoadableFileMatch",
        "_TemplateCollection",
        "load",
    )
    assert not any(hasattr(fs_schema, name) for name in private_names)


def test_bootstrap_helpers_are_private_aliases() -> None:
    private_aliases = (
        "_BeartypeConf",
        "_BeartypeStrategy",
        "_beartype_this_package",
        "_version",
    )
    public_spellings = (
        "BeartypeConf",
        "BeartypeStrategy",
        "beartype_this_package",
        "version",
    )
    assert all(hasattr(fs_schema, name) for name in private_aliases)
    assert not any(hasattr(fs_schema, name) for name in public_spellings)


def test_version() -> None:
    semver_pattern = re.compile(r"^\d+\.\d+\.\d+(rc\d+(-.+)?)?$")
    assert bool(semver_pattern.match(__version__))


def test_imported_from_install() -> None:
    parts = Path(fs_schema.__file__).resolve().parts
    assert "tests" not in parts
    assert "src" in parts or "site-packages" in parts


def test_dt_wraps_unnamed_datetime_field() -> None:
    assert fs_schema.dt("%Y-%m-%d") == "{:%Y-%m-%d}"


PACKAGE_HOOK_PROBE = """
import sys

from beartype.roar import BeartypeCallHintParamViolation

assert "fs_schema._api_stubs" not in sys.modules
import fs_schema

assert fs_schema.dt.__module__ == "fs_schema._api_stubs"
try:
    fs_schema.dt(1)
except BeartypeCallHintParamViolation:
    pass
else:
    raise AssertionError("fs_schema._api_stubs was not instrumented")
"""


def test_ordinary_import_installs_package_hook_before_api_stubs() -> None:
    result = subprocess.run(
        [sys.executable, "-I", "-c", PACKAGE_HOOK_PROBE],
        check=False,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stdout + result.stderr
