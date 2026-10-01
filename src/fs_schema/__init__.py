import warnings
from importlib.metadata import version as _version

from beartype.claw import beartype_this_package as _beartype_this_package
from beartype.roar import BeartypeDecorHintPep613DeprecationWarning as _Pep613Warning

__version__ = _version("fs-schema")

# TypeAlias until the minimum is 3.12.
warnings.filterwarnings("ignore", category=_Pep613Warning)

_beartype_this_package()

from ._fmt import captures as captures, dt as dt
from ._ops import (
    MismatchErr as MismatchErr,
    exists_opt as exists_opt,
    is_mismatch as is_mismatch,
    put as put,
    link_to as link_to,
    copy_to as copy_to,
    raise_exn as raise_exn,
    raise_mismatch as raise_mismatch,
)
from ._schema import (
    FILES as FILES,
    Dir as Dir,
    File as File,
    Layout as Layout,
    Match as Match,
    Schema as Schema,
    SchemaRoot as SchemaRoot,
)
from ._types import Loadable as Loadable, Located as Located

from . import _create as _create  # not on first create()
