"""Test configuration.

Tests run with ``APP_ENV=test`` and the in-memory cache unless ``REDIS_URL`` is
set. The Redis-specific tests are marked ``redis`` and are expected to run in
CI, where the service container provides a real server (section 3A, rule 3).

Each test runs inside one outer transaction that is rolled back at the end, so
tests may commit freely (the commits become savepoints) and the database is
left exactly as it was found.
"""

from __future__ import annotations

import os
from collections.abc import AsyncIterator

os.environ.setdefault("APP_ENV", "test")
os.environ.setdefault(
    "DATABASE_URL",
    "postgresql+asyncpg://postgres@127.0.0.1:5433/stem_games",
)
os.environ.setdefault("RATE_LIMIT_ENABLED", "true")
# Fixed key for tests only. CI sets its own; nothing here is a real secret.
os.environ.setdefault("SECRET_KEY", "test-only-secret-key-0123456789abcdefghij")

import httpx  # noqa: E402
import pytest  # noqa: E402
from sqlalchemy.ext.asyncio import AsyncSession  # noqa: E402


@pytest.fixture(autouse=True)
def _clear_settings_cache() -> None:
    """Settings are cached for the process; keep tests independent."""
    from app.core.config import get_settings

    get_settings.cache_clear()


@pytest.fixture
async def db_session() -> AsyncIterator[AsyncSession]:
    """A session bound to one transaction that is always rolled back."""
    from app.core.db import get_engine

    engine = get_engine()
    async with engine.connect() as connection:
        transaction = await connection.begin()
        session = AsyncSession(
            bind=connection,
            expire_on_commit=False,
            join_transaction_mode="create_savepoint",
        )
        try:
            yield session
        finally:
            await session.close()
            await transaction.rollback()


@pytest.fixture
async def client(db_session: AsyncSession) -> AsyncIterator[httpx.AsyncClient]:
    """HTTP client that talks to the real app, wired to the test transaction."""
    from app.core.cache import MemoryCache
    from app.core.db import get_session
    from app.main import create_app

    app = create_app()
    app.state.cache = MemoryCache()

    async def _override_session() -> AsyncIterator[AsyncSession]:
        yield db_session

    app.dependency_overrides[get_session] = _override_session

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(
        transport=transport, base_url="http://test", follow_redirects=False
    ) as http:
        yield http

    app.dependency_overrides.clear()
