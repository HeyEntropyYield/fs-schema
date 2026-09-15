from collections.abc import Sequence

import pytest

from fs_schema._std_ext import CacheSeq


def test_cache_seq_is_lazy_and_fetches_once_including_empty() -> None:
    calls = 0

    def fetch() -> Sequence[int]:
        nonlocal calls
        calls += 1
        return ()

    cached = CacheSeq(fetch)
    assert calls == 0
    assert len(cached) == 0
    assert tuple(cached) == ()
    assert calls == 1


def test_cache_seq_supports_index_slice_and_iteration() -> None:
    cached = CacheSeq(lambda: (1, 2, 3))
    assert cached[1] == 2
    assert cached[1:] == (2, 3)
    assert list(cached) == [1, 2, 3]


def test_cache_seq_retries_after_fetch_exception() -> None:
    attempts = 0

    def fetch() -> Sequence[int]:
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise RuntimeError("transient")
        return (4,)

    cached = CacheSeq(fetch)
    with pytest.raises(RuntimeError, match="transient"):
        _ = len(cached)
    assert tuple(cached) == (4,)
    assert attempts == 2
