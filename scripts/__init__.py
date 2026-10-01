import warnings

from beartype import BeartypeConf, FrozenDict
from beartype.claw import beartype_this_package
from beartype.roar import BeartypeDecorHintPep613DeprecationWarning as _Pep613Warning

from ._io import TomlObj

# TypeAlias until the minimum is 3.12.
warnings.filterwarnings("ignore", category=_Pep613Warning)

beartype_this_package(
    conf=BeartypeConf(
        hint_overrides=FrozenDict({TomlObj: dict}),  # Fixed in py 3.12
    )
)
