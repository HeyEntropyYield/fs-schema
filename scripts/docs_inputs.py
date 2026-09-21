"""Snippet closure for the docs build.

``main`` is ``require_fresh``. ``docs:build`` / ``docs:serve`` run it through
``scripts/beartype`` before zensical. The markdown extension runs
``<!-- generate: OUT from CMD -->`` before snippets read ``OUT``. Zensical
watches ``docs/`` only, so ``watch`` and ``docs.yml`` ``paths`` are static
copies of the files outside ``docs/``. They are not rewritten.
"""

import re
import shlex
import subprocess
import sys
from collections.abc import Sequence
from dataclasses import dataclass, field
from pathlib import Path

from markdown import Markdown
from markdown.extensions import Extension
from markdown.preprocessors import Preprocessor
from mashumaro.mixins.toml import DataClassTOMLMixin
from typing_extensions import override

from ._io import TextWriter

REPO = Path(__file__).resolve().parents[1]
_SNIPPET = re.compile(r'--8<-- "([^"]+)"')
_GENERATE = re.compile(r"<!-- generate: (\S+) from (.+?) -->")
_PATHS = re.compile(r"(?m)^(?P<indent>[ \t]*)paths:\n(?P<body>(?:(?P=indent)  - .+\n)+)")
# Globs and the workflow file itself are not snippet targets. The closure must
# still be listed beside them or a master push skips the deploy.
_ALWAYS = frozenset({"docs/**", "zensical.toml", ".github/workflows/docs.yml"})


class DocsInputError(RuntimeError):
    pass


@dataclass
class Snippets:
    base_path: list[str] = field(default_factory=lambda: ["."])


@dataclass
class Pymdownx:
    snippets: Snippets = field(default_factory=Snippets)


@dataclass
class MarkdownExtensions:
    pymdownx: Pymdownx = field(default_factory=Pymdownx)


@dataclass
class Project:
    watch: list[str] = field(default_factory=list)
    markdown_extensions: MarkdownExtensions = field(default_factory=MarkdownExtensions)


@dataclass
class Zensical(DataClassTOMLMixin):
    project: Project = field(default_factory=Project)


def _zensical(root: Path) -> Zensical:
    return Zensical.from_toml((root / "zensical.toml").read_text(encoding="utf-8"))


@dataclass(frozen=True)
class Generated:
    output: Path
    command: tuple[str, ...]


@dataclass(frozen=True)
class Page:
    generated: tuple[Generated, ...]
    includes: tuple[Path, ...]


@dataclass(frozen=True)
class Closure:
    files: set[Path]
    generated: tuple[Generated, ...]


def _locate(bases: tuple[Path, ...], name: str) -> Path:
    for base in bases:
        candidate = base.joinpath(name).resolve()
        if candidate.is_file():
            return candidate
    return bases[0].joinpath(name).resolve()


def _bases(root: Path) -> tuple[Path, ...]:
    names = _zensical(root).project.markdown_extensions.pymdownx.snippets.base_path
    return tuple((root / name).resolve() for name in names)


def _read_page(path: Path, bases: tuple[Path, ...]) -> Page:
    text = path.read_text(encoding="utf-8")
    generated: list[Generated] = []
    includes: list[Path] = []
    for match in _GENERATE.finditer(text):
        command = tuple(shlex.split(match.group(2)))
        if not command:
            raise DocsInputError(f"empty generate command in {path}")
        generated.append(Generated(_locate(bases, match.group(1)), command))
    for match in _SNIPPET.finditer(text):
        includes.append(_locate(bases, match.group(1)))
    return Page(tuple(generated), tuple(includes))


def _require_present(missing: Sequence[Path], generated: Sequence[Generated]) -> None:
    # A generate target may not exist yet; sync writes it. Any other missing include is an error.
    outputs = {item.output for item in generated}
    absent = [path for path in missing if path not in outputs]
    if absent:
        raise DocsInputError(f"snippet not found: {absent[0]}")


def _collect(root: Path) -> Closure:
    bases = _bases(root)
    seen: set[Path] = set()
    queue = sorted((root / "docs").rglob("*.md"))
    generated: list[Generated] = []
    missing: list[Path] = []
    while queue:
        path = queue.pop()
        if path in seen:
            continue
        if not path.is_file():
            missing.append(path)
            continue
        seen.add(path)
        page = _read_page(path, bases)
        generated.extend(page.generated)
        for included in page.includes:
            if included not in seen:
                queue.append(included)
    _require_present(missing, generated)
    return Closure(seen, tuple(generated))


def _outside_docs(root: Path, path: Path) -> bool:
    return not path.resolve().is_relative_to((root / "docs").resolve())


def external_inputs(root: Path = REPO) -> tuple[str, ...]:
    """Repo-relative files outside ``docs/`` that change the built site."""
    root = root.resolve()
    closure = _collect(root)
    paths = {path for path in closure.files if _outside_docs(root, path)}
    for item in closure.generated:
        if _outside_docs(root, item.output):
            paths.add(item.output)
        for token in item.command:
            candidate = (root / token).resolve()
            if candidate.is_file() and _outside_docs(root, candidate):
                paths.add(candidate)
    return tuple(sorted(path.relative_to(root).as_posix() for path in paths))


def _workflow_paths(root: Path) -> set[str]:
    text = (root / ".github/workflows/docs.yml").read_text(encoding="utf-8")
    block = _PATHS.search(text)
    if block is None:
        raise DocsInputError("docs.yml has no paths list")
    return {line.strip().removeprefix("-").strip() for line in block.group("body").splitlines()}


def require_fresh(root: Path = REPO) -> None:
    """Fail when ``watch`` or ``docs.yml`` paths drift from the snippet closure."""
    external = set(external_inputs(root))
    watch = set(_zensical(root).project.watch)
    if watch != external:
        raise DocsInputError(f"zensical.toml watch {sorted(watch)} != snippet closure {sorted(external)}")
    missing = sorted((external | _ALWAYS) - _workflow_paths(root))
    if missing:
        raise DocsInputError(f"docs.yml paths missing {missing}")


def sync(root: Path = REPO) -> None:
    """Regenerate files named by ``<!-- generate: OUT from CMD -->``."""
    root = root.resolve()
    for item in _collect(root).generated:
        executable = item.command[0]
        command = [executable if Path(executable).is_absolute() else str(root / executable), *item.command[1:]]
        result = subprocess.run(command, cwd=root, check=True, capture_output=True, text=True)
        body = result.stdout + result.stderr
        if not item.output.is_file() or item.output.read_text(encoding="utf-8") != body:
            item.output.write_text(body, encoding="utf-8")


def main(_argv: Sequence[str] = (), *, stderr: TextWriter = sys.stderr) -> int:
    try:
        require_fresh()
    except Exception as error:
        print(f"error: {error}", file=stderr)
        return 1
    return 0


class _Generate(Preprocessor):
    @override
    def run(self, lines: list[str]) -> list[str]:
        sync()
        return lines


class DocsInputsExtension(Extension):
    @override
    def extendMarkdown(self, md: Markdown) -> None:
        # SnippetPreprocessor is 32. Generate first so ``--8<--`` reads fresh output.
        md.preprocessors.register(_Generate(md), "docs_inputs", 35)


def makeExtension(**_kwargs: object) -> DocsInputsExtension:
    return DocsInputsExtension()
