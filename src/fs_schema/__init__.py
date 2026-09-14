from importlib.metadata import version as _version

from beartype import (
    BeartypeConf as _BeartypeConf,
    BeartypeStrategy as _BeartypeStrategy,
)
from beartype.claw import beartype_this_package as _beartype_this_package

__version__ = _version("fs-schema")

_beartype_this_package(conf=_BeartypeConf(strategy=_BeartypeStrategy.On))

from ._fmt import dt as dt
from ._ops import (
    MismatchErr as MismatchErr,
    exists_opt as exists_opt,
    is_mismatch as is_mismatch,
    put as put,
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
from ._types import Located as Located
