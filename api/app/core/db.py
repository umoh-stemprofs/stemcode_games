"""Database engine and session plumbing (P0-T04, P1-T01).

The engine is created lazily so importing the app never opens a connection and
so tests can run without a database when they do not need one.
"""

from __future__ import annotations

from collections.abc import AsyncIterator

from sqlalchemy import text
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase

from app.core.config import Settings, get_settings


class Base(DeclarativeBase):
    """Declarative base shared by every ORM model.

    Tables themselves are only ever created by an Alembic migration
    (AGENTS.md): the models describe the schema, they do not own it.
    """

_engines: dict[str, AsyncEngine] = {}
_sessionmakers: dict[str, async_sessionmaker[AsyncSession]] = {}


def get_engine(settings: Settings | None = None) -> AsyncEngine:
    settings = settings or get_settings()
    engine = _engines.get(settings.database_url)
    if engine is None:
        engine = create_async_engine(
            settings.database_url,
            echo=settings.database_echo,
            pool_pre_ping=True,
        )
        _engines[settings.database_url] = engine
    return engine


def get_sessionmaker(settings: Settings | None = None) -> async_sessionmaker[AsyncSession]:
    settings = settings or get_settings()
    maker = _sessionmakers.get(settings.database_url)
    if maker is None:
        maker = async_sessionmaker(get_engine(settings), expire_on_commit=False)
        _sessionmakers[settings.database_url] = maker
    return maker


async def get_session() -> AsyncIterator[AsyncSession]:
    async with get_sessionmaker()() as session:
        yield session


async def ping_db(settings: Settings | None = None) -> bool:
    """Readiness probe. Returns False instead of raising."""
    try:
        async with get_engine(settings).connect() as conn:
            await conn.execute(text("SELECT 1"))
        return True
    except Exception:  # noqa: BLE001 - readiness must never raise
        return False


async def dispose_engines() -> None:
    for engine in _engines.values():
        await engine.dispose()
    _engines.clear()
    _sessionmakers.clear()
