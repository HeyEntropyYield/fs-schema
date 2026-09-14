from beartype import BeartypeConf, BeartypeStrategy, FrozenDict
from beartype.claw import beartype_this_package

from ._io import TomlObj

beartype_this_package(
    conf=BeartypeConf(
        strategy=BeartypeStrategy.On,
        hint_overrides=FrozenDict({TomlObj: dict}),  # Fixed in py 3.12
    )
)
