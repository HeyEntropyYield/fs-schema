# pyright: reportPrivateUsage=false
import ast
import inspect
from pathlib import Path

from fs_schema._schema import FixedDir, FixedFile, Matches, Template, _DirMatch, _FileMatch

# Includes Sequence mixin names (index, count, __contains__, __reversed__).
_RUNTIME = (FixedFile, FixedDir, Matches, Template, _FileMatch, _DirMatch)
_DUNDERS = frozenset({
    "__bool__",
    "__contains__",
    "__fspath__",
    "__getattr__",
    "__getitem__",
    "__iter__",
    "__len__",
    "__lt__",
    "__next__",
    "__reversed__",
    "__str__",
})
_TYPECHECK = Path(__file__).parent / "typecheck" / "test_child_view.py"


def _runtime_names() -> set[str]:
    names: set[str] = set()
    for cls in _RUNTIME:
        for name in dir(cls):
            if name.startswith("_") and name not in _DUNDERS:
                continue
            names.add(name)
    return names


def _class_member_names(tree: ast.AST, class_name: str) -> set[str]:
    for node in ast.walk(tree):
        if not isinstance(node, ast.ClassDef) or node.name != class_name:
            continue
        names: set[str] = set()
        for stmt in node.body:
            if isinstance(stmt, ast.FunctionDef):
                names.add(stmt.name)
            elif isinstance(stmt, ast.AnnAssign) and isinstance(stmt.target, ast.Name):
                names.add(stmt.target.id)
        return names
    raise AssertionError(f"{class_name} is missing")


def _touched_names(tree: ast.AST) -> set[str]:
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Attribute):
            names.add(node.attr)
    return names


def test_child_view_matches_runtime_members() -> None:
    source = Path(inspect.getfile(FixedFile)).read_text()
    view = _class_member_names(ast.parse(source), "_ChildView")
    runtime = _runtime_names()
    assert view == runtime


def test_typecheck_mentions_every_child_view_member() -> None:
    source = Path(inspect.getfile(FixedFile)).read_text()
    view = _class_member_names(ast.parse(source), "_ChildView")
    touched = _touched_names(ast.parse(_TYPECHECK.read_text()))
    missing = view - touched
    assert not missing
