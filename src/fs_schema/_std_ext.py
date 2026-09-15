from collections.abc import Callable, Sequence
from typing import Final, Generic, overload

from typing_extensions import TypeVar, override

_T_co = TypeVar("_T_co", covariant=True)


class CacheSeq(Sequence[_T_co], Generic[_T_co]):
    __slots__: Final = ("_data", "_fetch")
    _data: Sequence[_T_co] | None
    _fetch: Callable[[], Sequence[_T_co]]

    def __init__(self, fetch: Callable[[], Sequence[_T_co]]) -> None:
        self._fetch = fetch
        self._data = None

    def _load(self) -> Sequence[_T_co]:
        if self._data is None:
            self._data = self._fetch()
        return self._data

    @override
    def __len__(self) -> int:
        return len(self._load())

    @overload
    def __getitem__(self, index: int) -> _T_co: ...

    @overload
    def __getitem__(self, index: slice) -> Sequence[_T_co]: ...

    @override
    def __getitem__(self, index: int | slice) -> _T_co | Sequence[_T_co]:
        return self._load()[index]
