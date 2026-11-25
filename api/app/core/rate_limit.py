"""Rate limiting on top of ``CacheClient.incr_window`` (P0-T05).

The limiter is a fixed-window counter. Both cache implementations provide the
same semantics, so the same tests pass against memory and Redis.

Usage:
    limited = rate_limit(lambda request: f"login:{client_ip(request)}", 10, 60)

    @router.post("/login", dependencies=[Depends(limited)])
    async def login(...): ...
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Annotated

from fastapi import Depends, Request

from app.core.cache import CacheClient
from app.core.config import Settings, get_settings
from app.core.errors import RateLimitedError


def get_cache(request: Request) -> CacheClient:
    cache: CacheClient = request.app.state.cache
    return cache


async def check_rate_limit(
    cache: CacheClient,
    key: str,
    limit: int,
    window_seconds: int,
) -> int:
    """Increment the window and raise ``RateLimitedError`` when over the limit.

    Returns the current count so callers (and tests) can assert on it.
    """
    count = await cache.incr_window(f"ratelimit:{key}", window_seconds)
    if count > limit:
        raise RateLimitedError(
            "Too many attempts. Please wait a moment and try again.",
            details={"limit": limit, "window_seconds": window_seconds},
            # Fixed-window limiter: the window may reset at any point inside it,
            # so advertise the full window rather than a wrong smaller number.
            headers={"Retry-After": str(window_seconds)},
        )
    return count


async def check_user_limit(
    cache: CacheClient,
    *,
    key: str,
    user_id: object,
    limit: int,
    window_seconds: int,
) -> int:
    """A counter per learner, for actions a person takes rather than a browser.

    ``rate_limit`` keys on the request, which is right for sign-in. Inviting and
    reporting belong to an account: a learner with two devices must not get two
    allowances, and a shared tablet must not spend one child's on another.

    Honours ``RATE_LIMIT_ENABLED`` like the dependency does, so a test or a
    local run can turn limits off in one place.
    """
    if not get_settings().rate_limit_enabled:
        return 0
    return await check_rate_limit(cache, f"{key}:{user_id}", limit, window_seconds)


def rate_limit(
    key_fn: Callable[[Request], str],
    limit: int,
    window_seconds: int,
) -> Callable[..., object]:
    """Build a FastAPI dependency. Disabled by ``RATE_LIMIT_ENABLED=false``."""

    async def dependency(
        request: Request,
        cache: Annotated[CacheClient, Depends(get_cache)],
        settings: Annotated[Settings, Depends(get_settings)],
    ) -> None:
        if not settings.rate_limit_enabled:
            return
        await check_rate_limit(cache, key_fn(request), limit, window_seconds)

    return dependency


def client_ip(request: Request) -> str:
    """Best-effort client address.

    Behind the reverse proxy this comes from the proxy-set header. Never used
    for authorization, only for rate limiting (P8-T01 explains why tickets are
    not IP-bound).
    """
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else "unknown"
