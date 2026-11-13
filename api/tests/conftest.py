"""Test configuration.

Tests run with ``APP_ENV=test`` and the in-memory cache unless ``REDIS_URL`` is
set. The Redis-specific tests are marked ``redis`` and are expected to run in
CI, where the service container provides a real server (section 3A, rule 3).
"""

from __future__ import annotations

import os

os.environ.setdefault("APP_ENV", "test")
os.environ.setdefault(
    "DATABASE_URL",
    "postgresql+asyncpg://postgres@127.0.0.1:5433/stem_games",
)
os.environ.setdefault("RATE_LIMIT_ENABLED", "true")

import pytest  # noqa: E402


@pytest.fixture(autouse=True)
def _clear_settings_cache() -> None:
    """Settings are cached for the process; keep tests independent."""
    from app.core.config import get_settings

    get_settings.cache_clear()
