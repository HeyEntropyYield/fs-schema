import re
from pathlib import Path

import fs_schema


def test_version() -> None:
    semver_pattern = re.compile(r"^\d+\.\d+\.\d+(rc\d+(-.+)?)?$")
    assert bool(semver_pattern.match(fs_schema.__version__))


def test_imported_from_install() -> None:
    parts = Path(fs_schema.__file__).resolve().parts
    assert "tests" not in parts
    assert "src" in parts or "site-packages" in parts
