"""Cache abstraction (plan section 3A, D-34).

Application code must never import a Redis client directly; this module is the
only place allowed to do so (enforced by ``tests/test_layering.py``).

The two implementations must agree on semantics, not on storage:
TTL expiry, ``incr_window`` counting once per window, ``set_nx`` returning
False on the second caller, and single-use keys all behave the same. The only
permitted differences are durability and cross-instance sharing.
"""

from __future__ import annotations

import asyncio
import time
from collections.abc import AsyncIterator
from typing import Protocol, runtime_checkable

from app.core.config import Settings


@runtime_checkable
class CacheClient(Protocol):
    async def get(self, key: str) -> str | None: ...

    async def set(self, key: str, value: str, ttl_s: int | None = None) -> None: ...

    async def set_nx(self, key: str, value: str, ttl_s: int) -> bool:
        """Create ``key`` only if absent or expired. True when this caller won."""
        ...

    async def incr_window(self, key: str, window_s: int) -> int:
        """Increment a fixed-window counter and return the new count."""
        ...

    async def delete(self, *keys: str) -> None: ...

    async def publish(self, channel: str, message: str) -> None: ...

    def subscribe(self, channel: str) -> AsyncIterator[str]: ...

    async def ping(self) -> bool: ...

    async def aclose(self) -> None: ...


class MemoryCache:
    """In-memory cache. Dev/test only, single process only (D-34)."""

    backend = "memory"

    def __init__(self) -> None:
        self._store: dict[str, tuple[str, float | None]] = {}
        self._subs: dict[str, set[asyncio.Queue[str]]] = {}
        self._lock = asyncio.Lock()

    def _live(self, key: str, now: float) -> tuple[str, float | None] | None:
        item = self._store.get(key)
        if item is None:
            return None
        value, expires_at = item
        if expires_at is not None and expires_at <= now:
            self._store.pop(key, None)
            return None
        return item

    async def get(self, key: str) -> str | None:
        async with self._lock:
            item = self._live(key, time.monotonic())
            return None if item is None else item[0]

    async def set(self, key: str, value: str, ttl_s: int | None = None) -> None:
        async with self._lock:
            now = time.monotonic()
            self._store[key] = (value, None if ttl_s is None else now + ttl_s)

    async def set_nx(self, key: str, value: str, ttl_s: int) -> bool:
        async with self._lock:
            now = time.monotonic()
            if self._live(key, now) is not None:
                return False
            self._store[key] = (value, now + ttl_s)
            return True

    async def incr_window(self, key: str, window_s: int) -> int:
        async with self._lock:
            now = time.monotonic()
            item = self._live(key, now)
            if item is None:
                self._store[key] = ("1", now + window_s)
                return 1
            count = int(item[0]) + 1
            self._store[key] = (str(count), item[1])
            return count

    async def delete(self, *keys: str) -> None:
        async with self._lock:
            for key in keys:
                self._store.pop(key, None)

    async def publish(self, channel: str, message: str) -> None:
        for queue in tuple(self._subs.get(channel, ())):
            queue.put_nowait(message)

    async def subscribe(self, channel: str) -> AsyncIterator[str]:
        queue: asyncio.Queue[str] = asyncio.Queue()
        self._subs.setdefault(channel, set()).add(queue)
        try:
            while True:
                yield await queue.get()
        finally:
            self._subs.get(channel, set()).discard(queue)

    async def ping(self) -> bool:
        return True

    async def aclose(self) -> None:
        self._store.clear()
        self._subs.clear()


class RedisCache:
    """Redis-backed cache. Required in staging/prod, optional in dev."""

    backend = "redis"

    _INCR_LUA = """
local current = redis.call('INCR', KEYS[1])
if current == 1 then
  redis.call('EXPIRE', KEYS[1], ARGV[1])
end
return current
"""

    def __init__(self, url: str) -> None:
        import redis.asyncio as redis_asyncio  # local import: single allowed boundary

        self._client = redis_asyncio.from_url(url, decode_responses=True)
        self._incr_script = self._client.register_script(self._INCR_LUA)

    async def get(self, key: str) -> str | None:
        value = await self._client.get(key)
        return None if value is None else str(value)

    async def set(self, key: str, value: str, ttl_s: int | None = None) -> None:
        await self._client.set(key, value, ex=ttl_s)

    async def set_nx(self, key: str, value: str, ttl_s: int) -> bool:
        result = await self._client.set(key, value, nx=True, ex=ttl_s)
        return bool(result)

    async def incr_window(self, key: str, window_s: int) -> int:
        count = await self._incr_script(keys=[key], args=[window_s])
        return int(count)

    async def delete(self, *keys: str) -> None:
        if keys:
            await self._client.delete(*keys)

    async def publish(self, channel: str, message: str) -> None:
        await self._client.publish(channel, message)

    async def subscribe(self, channel: str) -> AsyncIterator[str]:
        pubsub = self._client.pubsub()
        await pubsub.subscribe(channel)
        try:
            async for message in pubsub.listen():
                if message.get("type") == "message":
                    yield str(message["data"])
        finally:
            await pubsub.unsubscribe(channel)
            await pubsub.aclose()

    async def ping(self) -> bool:
        try:
            return bool(await self._client.ping())
        except Exception:  # noqa: BLE001 - readiness probe must not raise
            return False

    async def aclose(self) -> None:
        await self._client.aclose()


def build_cache(settings: Settings) -> CacheClient:
    """Pick the cache implementation for this environment."""
    if settings.redis_url:
        return RedisCache(settings.redis_url)
    if settings.is_production:
        # Guarded already by Settings, repeated here so no path can bypass it.
        raise RuntimeError("Redis is required outside dev/test (D-34).")
    return MemoryCache()
