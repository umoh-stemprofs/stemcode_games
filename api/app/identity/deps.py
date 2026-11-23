"""Shared FastAPI dependencies: session, settings, caller, role gates (P1-T03).

Routers must not dig through cookies or the database themselves. They declare
``ActorDep`` (any signed-in caller) or one of the role gates, and that is the
whole authorization story. If a route needs a school or class scope, it calls
the guard in ``app.identity.service`` with that actor.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Annotated

from app.core.cache import CacheClient
from app.core.config import Settings, get_settings
from app.core.db import get_session
from app.core.errors import ForbiddenError, UnauthorizedError
from app.core.rate_limit import check_rate_limit, client_ip, get_cache
from app.identity.models import Role
from app.identity.security import ACCESS_COOKIE
from app.identity.service import Actor, actor_from_access_token
from fastapi import Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

SessionDep = Annotated[AsyncSession, Depends(get_session)]
SettingsDep = Annotated[Settings, Depends(get_settings)]
CacheDep = Annotated[CacheClient, Depends(get_cache)]


async def current_actor(
    request: Request,
    session: SessionDep,
    settings: SettingsDep,
) -> Actor:
    token = request.cookies.get(ACCESS_COOKIE)
    if not token:
        raise UnauthorizedError("Please sign in.")
    return await actor_from_access_token(session, token, settings)


ActorDep = Annotated[Actor, Depends(current_actor)]


def require_roles(*roles: Role) -> Callable[..., Awaitable[Actor]]:
    """Build a dependency that only lets the listed roles through.

    Deliberately a 403 and a plain sentence: the caller is already known, so
    there is nothing to hide — unlike a cross-school id, which is a 404.
    """

    async def guard(actor: ActorDep) -> Actor:
        if actor.role not in roles:
            raise ForbiddenError("You do not have access to this.")
        return actor

    return guard


async def login_rate_limit(
    request: Request,
    cache: CacheDep,
    settings: SettingsDep,
) -> None:
    """Per-IP brute-force limit on login (P1-T02).

    Separate from the per-account lockout: the IP limit stops a spray across
    many accounts, the account lockout stops a focused guess at one.
    """
    if not settings.rate_limit_enabled:
        return
    await check_rate_limit(
        cache,
        f"auth:login:{client_ip(request)}",
        settings.login_max_attempts,
        settings.login_window_s,
    )
