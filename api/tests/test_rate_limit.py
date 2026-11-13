"""P0-T05 / Phase 0 DoD: allows N, blocks N+1, and resets after the window."""

from __future__ import annotations

import asyncio

import pytest
from app.core.cache import MemoryCache
from app.core.errors import RateLimitedError
from app.core.rate_limit import check_rate_limit


async def test_allows_up_to_limit() -> None:
    cache = MemoryCache()
    for expected in (1, 2, 3):
        count = await check_rate_limit(cache, "login:1.2.3.4", limit=3, window_seconds=60)
        assert count == expected


async def test_blocks_one_over_limit() -> None:
    cache = MemoryCache()
    for _ in range(3):
        await check_rate_limit(cache, "login:1.2.3.4", limit=3, window_seconds=60)

    with pytest.raises(RateLimitedError) as excinfo:
        await check_rate_limit(cache, "login:1.2.3.4", limit=3, window_seconds=60)

    error = excinfo.value
    assert error.status_code == 429
    assert error.code == "rate_limited"
    assert error.headers["Retry-After"] == "60"


async def test_separate_keys_do_not_share_a_window() -> None:
    cache = MemoryCache()
    await check_rate_limit(cache, "invite:a", limit=1, window_seconds=60)
    assert await check_rate_limit(cache, "invite:b", limit=1, window_seconds=60) == 1


async def test_resets_after_window() -> None:
    cache = MemoryCache()
    await check_rate_limit(cache, "code:abc", limit=1, window_seconds=1)
    with pytest.raises(RateLimitedError):
        await check_rate_limit(cache, "code:abc", limit=1, window_seconds=1)

    await asyncio.sleep(1.1)
    assert await check_rate_limit(cache, "code:abc", limit=1, window_seconds=1) == 1
