# Each _ChildView member is named here. basedpyright checks the signatures.
# pytest does not call check(). tests/test_child_view_members.py fails if a member is absent.
# pyright: reportPrivateUsage=false
from collections.abc import Iterator
from pathlib import Path

from typing_extensions import assert_type

from fs_schema import _fmt, _schema


def _pred(args: tuple[_fmt.CaptureField, ...], kwargs: _fmt.CaptureMap) -> bool:
    return bool(args or kwargs)


def check(node: _schema._ChildView) -> None:
    assert_type(node.path, Path)
    assert_type(node.name, str)
    assert_type(node.stem, str)
    assert_type(node.suffix, str)
    assert_type(node.args, tuple[_fmt.CaptureField, ...])
    assert_type(node.kwargs, _fmt.CaptureMap)
    assert_type(node.__bool__(), bool)
    assert_type(node.__contains__(node), bool)
    assert_type(node.__fspath__(), str)
    assert_type(node.__lt__(node), bool)
    assert_type(node.__str__(), str)
    assert_type(node.__getattr__("train"), _schema._ChildView)
    assert_type(node.__len__(), int)
    assert_type(node.__iter__(), Iterator[_schema._ChildView])
    assert_type(node.__next__(), _schema._ChildView)
    assert_type(node.__reversed__(), Iterator[_schema._ChildView])
    assert_type(node.__getitem__(0), _schema._ChildView)
    assert_type(node.count(node), int)
    assert_type(node.index(node), int)
    assert_type(node.exists(), bool)
    assert_type(node.read_bytes(), bytes)
    assert_type(node.read_text(), str)
    assert_type(node.format(), _schema._ChildView)
    assert_type(node.get(), _schema._ChildView | None)
    assert_type(node.filter(_pred), _schema._ChildView)
    assert_type(node.find(_pred), _schema._ChildView | None)
    assert_type(node.where(), _schema._ChildView)
    assert_type(node.parse(Path("x")), _schema._ChildView)
    assert_type(node.load(), object | Exception)
    assert_type(node.create(), _schema._ChildView)
    assert_type(node.link_to(Path("t")), None)
    assert_type(node.copy_to(Path("d")), None)
