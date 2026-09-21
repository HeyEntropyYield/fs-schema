# Docs coverage is typecheck + exec of fenced python (markdown has no coverage map).
# pyright: reportAttributeAccessIssue=false, reportCallIssue=false
# pyright: reportIndexIssue=false, reportUnknownMemberType=false
# pyright: reportUnknownVariableType=false, reportUnknownArgumentType=false
# pyright: reportAssignmentType=false

import io
import json
import re
import subprocess
import tempfile
from pathlib import Path

import pytest
from markdown import Markdown
from scripts.docs_inputs import DocsInputError, external_inputs, main, makeExtension, require_fresh, sync

import fs_schema as fss
from quickstart import CuratedManifest, Manifest, curate

PROJECT_ROOT = Path(__file__).parents[1]
DOCS = (PROJECT_ROOT / "README.md", *sorted((PROJECT_ROOT / "docs").rglob("*.md")))

# The locked API deliberately gives dynamic generated children a broad static
# fallback. Suppress only diagnostics caused at that boundary; basedpyright still
# checks names, assignments, return values, and ordinary Python around it.
DYNAMIC_CHILD_CHECKS = """# pyright: reportAttributeAccessIssue=false, reportCallIssue=false
# pyright: reportIndexIssue=false, reportGeneralTypeIssues=false
# pyright: reportArgumentType=false, reportAssignmentType=false
# pyright: reportUnknownMemberType=false
# pyright: reportUnknownVariableType=false, reportUnknownArgumentType=false
# pyright: reportRedeclaration=false
"""
PYRIGHT_CONFIG = {
    "typeCheckingMode": "standard",
    "pythonVersion": "3.10",
    "venvPath": str(PROJECT_ROOT),
    "venv": ".venv",
    "reportMissingTypeStubs": "none",
}


def _python_from(path: Path) -> str:
    chunks: list[str] = []
    for match in re.finditer(r"```python\n(.*?)\n```", path.read_text(), flags=re.DOTALL):
        source = match.group(1)
        include = re.fullmatch(r'--8<-- "([^"]+)"', source.strip())
        chunks.append((PROJECT_ROOT / include.group(1)).read_text() if include else source)
    return DYNAMIC_CHILD_CHECKS + "\n".join(chunks) + "\n"


def test_all_documented_python_typechecks() -> None:
    with tempfile.TemporaryDirectory() as directory:
        generated = Path(directory)
        config = generated / "pyrightconfig.json"
        config.write_text(json.dumps(PYRIGHT_CONFIG))
        modules: list[str] = []
        for path in DOCS:
            module = generated / f"{path.parent.name}-{path.stem}.py"
            module.write_text(_python_from(path))
            modules.append(str(module))

        result = subprocess.run(
            [str(PROJECT_ROOT / ".venv/bin/basedpyright"), "--project", str(config), *modules],
            cwd=PROJECT_ROOT,
            check=False,
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0, result.stdout + result.stderr


def test_readme_embeds_the_checked_quickstart() -> None:
    assert '--8<-- "examples/quickstart.py"' in (PROJECT_ROOT / "README.md").read_text()


def test_readme_schema_declarations_construct() -> None:
    source = _python_from(PROJECT_ROOT / "README.md")
    declaration = source[: source.index("download =")]
    namespace = {"__name__": "readme_smoke"}
    exec(compile(declaration, "README.md", "exec"), namespace)


def test_embedded_quickstart_runs_end_to_end(tmp_path: Path) -> None:
    source = tmp_path / "source"
    target = tmp_path / "target"
    source_day = source / "batches" / "2026-09-17"

    fss.put(source / "manifest.json", Manifest("delivery-1", expected_parts=2))
    fss.put(source_day / "part-1.jsonl", b"first")
    fss.put(source_day / "part-2.jsonl", b"second")

    curated = fss.raise_mismatch(curate(source, target))
    manifest: CuratedManifest = fss.raise_exn(curated.manifest.load())
    assert manifest == CuratedManifest("delivery-1", partitions=1)
    assert curated.days[0].parts[0].read_bytes() == b"first\nsecond"


def test_generate_directive_writes_missing_output(tmp_path: Path) -> None:
    docs = tmp_path / "docs"
    docs.mkdir()
    (tmp_path / "zensical.toml").write_text("[project]\nsite_name = 'x'\n")
    tool = tmp_path / "tool.sh"
    tool.write_text("#!/bin/sh\necho hello\n")
    tool.chmod(0o755)
    (docs / "index.md").write_text('<!-- generate: docs/out.txt from tool.sh -->\n--8<-- "docs/out.txt"\n')
    assert external_inputs(tmp_path) == ("tool.sh",)
    sync(tmp_path)
    assert (docs / "out.txt").read_text() == "hello\n"


def test_unknown_snippet_fails(tmp_path: Path) -> None:
    docs = tmp_path / "docs"
    docs.mkdir()
    (tmp_path / "zensical.toml").write_text("[project]\nsite_name = 'x'\n")
    (docs / "index.md").write_text('--8<-- "missing.md"\n')
    with pytest.raises(DocsInputError, match="snippet not found"):
        external_inputs(tmp_path)


def test_require_fresh_accepts_this_repo() -> None:
    require_fresh()
    assert main([]) == 0


def test_main_reports_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    def fail(_root: Path = PROJECT_ROOT) -> None:
        raise DocsInputError("stale")

    stderr = io.StringIO()
    monkeypatch.setattr("scripts.docs_inputs.require_fresh", fail)
    assert main([], stderr=stderr) == 1
    assert stderr.getvalue() == "error: stale\n"


def test_require_fresh_stops_on_stale_watch(tmp_path: Path) -> None:
    docs = tmp_path / "docs"
    docs.mkdir()
    (docs / "index.md").write_text('--8<-- "README.md"\n')
    (tmp_path / "README.md").write_text("hi\n")
    (tmp_path / "zensical.toml").write_text("[project]\nwatch = []\n")
    workflow = tmp_path / ".github/workflows"
    workflow.mkdir(parents=True)
    (workflow / "docs.yml").write_text("on:\n  push:\n    paths:\n      - docs/**\n")
    with pytest.raises(DocsInputError, match=r"zensical\.toml watch"):
        require_fresh(tmp_path)


def test_extension_regenerates_included_output() -> None:
    Markdown(extensions=[makeExtension()]).convert("page")
    test_readme_embeds_current_run_help()


def test_readme_embeds_current_run_help() -> None:
    result = subprocess.run(
        [str(PROJECT_ROOT / "run.sh"), "help"],
        cwd=PROJECT_ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    assert (PROJECT_ROOT / "docs/run-help.txt").read_text() == result.stdout + result.stderr
