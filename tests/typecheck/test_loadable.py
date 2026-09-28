# pyright: reportPrivateUsage=false
from typing_extensions import assert_type

from fs_schema import Loadable, _schema


def takes(node: Loadable) -> None:
    assert_type(node.load(bytes), bytes | Exception)


def accepts_child(node: _schema._ChildView) -> None:
    takes(node)
