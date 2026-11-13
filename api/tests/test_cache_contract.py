"""One contract suite, run against both cache implementations (section 3A).

Semantics that other code depends on must be identical: TTL expiry, a single
winner for ``set_nx``, and fixed-window counting that resets.
"""

from __future__ import annotations

import asyncio
import os

import pytest
from app.core.cache import MemoryCache, RedisCache


@pytest.fixture(
    params=[
        pytest.param("memory", id="memory"),
        pytest.param("redis", id="redis", marks=pytest.mark.redis),
    ]
)
async def cache(request: pytest.FixtureRequest):
    if request.param == "memory":
        client = MemoryCache()
        yield client
        await client.aclose()
        return

    url = os.environ.get("REDIS_URL")
    if not url:
        pytest.skip("REDIS_URL not set: the redis contract runs in CI")
    client = RedisCache(url)
    await client.delete("test:contract:key", "test:contract:nx", "test:contract:window")
    yield client
    await client.aclose()


async def test_set_and_get(cache) -> None:
    assert await cache.get("test:contract:key") is None
    await cache.set("test:contract:key", "value")
    assert await cache.get("test:contract:key") == "value"
    await cache.delete("test:contract:key")
    assert await cache.get("test:contract:key") is None


async def test_ttl_expires(cache) -> None:
    await cache.set("test:contract:key", "value", ttl_s=1)
    assert await cache.get("test:contract:key") == "value"
    await asyncio.sleep(1.1)
    assert await cache.get("test:contract:key") is None


async def test_set_nx_has_one_winner(cache) -> None:
    first = await cache.set_nx("test:contract:nx", "one", ttl_s=30)
    second = await cache.set_nx("test:contract:nx", "two", ttl_s=30)
    assert (first, second) == (True, False)
    assert await cache.get("test:contract:nx") == "one"
    await cache.delete("test:contract:nx")


async def test_incr_window_counts_and_resets(cache) -> None:
    counts = [await cache.incr_window("test:contract:window", 1) for _ in range(3)]
    assert counts == [1, 2, 3]
    await asyncio.sleep(1.1)
    assert await cache.incr_window("test:contract:window", 1) == 1
    await cache.delete("test:contract:window")


async def test_pubsub_delivers(cache) -> None:
    received: list[str] = []

    async def listen() -> None:
        async for message in cache.subscribe("test:contract:chan"):
            received.append(message)
            return

    task = asyncio.create_task(listen())
    await asyncio.sleep(0.05)  # let the subscription register
    await cache.publish("test:contract:chan", "hello")
    await asyncio.wait_for(task, timeout=5)
    assert received == ["hello"]
