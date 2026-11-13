"""Application settings.

Rules (P0-T04, P0-T11):
- Configuration comes from the environment (or a local ``.env`` file).
- No secret or connection string has a default in code.
- The in-memory cache/queue may only run in ``dev`` and ``test`` (D-34): startup
  refuses to boot in ``staging``/``prod`` without ``REDIS_URL``.
"""

from __future__ import annotations

from functools import lru_cache
from typing import Literal

from pydantic import Field, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

AppEnv = Literal["dev", "test", "staging", "prod"]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    app_env: AppEnv = "dev"

    # Required: there is no default database in code.
    database_url: str = Field(..., description="SQLAlchemy async database URL.")
    database_echo: bool = False

    # Optional in dev/test, mandatory in staging/prod (D-34).
    redis_url: str | None = None

    app_base_url: str = "http://localhost:3000"
    log_level: str = "INFO"
    rate_limit_enabled: bool = True

    # Signs short-lived access tokens (P1-T02, D-19). No default in code:
    # staging/prod must refuse to boot without it.
    secret_key: str = Field(..., min_length=32, description="HMAC key for access tokens.")
    access_token_ttl_s: int = 900  # 15 minutes
    refresh_token_ttl_s: int = 1_209_600  # 14 days
    cookie_secure: bool | None = None
    cookie_domain: str | None = None

    # Login protection: per-IP rate limit plus per-account lockout backoff.
    login_max_attempts: int = 10
    login_window_s: int = 300
    lockout_threshold: int = 5
    lockout_seconds: int = 900

    @field_validator("redis_url", mode="before")
    @classmethod
    def _blank_redis_url_is_none(cls, value: object) -> object:
        """Treat ``REDIS_URL=`` in a .env file as "not configured"."""
        if isinstance(value, str) and not value.strip():
            return None
        return value

    @property
    def is_production(self) -> bool:
        return self.app_env in ("staging", "prod")

    @property
    def use_secure_cookies(self) -> bool:
        """Secure cookies everywhere except plain-HTTP local development."""
        if self.cookie_secure is not None:
            return self.cookie_secure
        return self.is_production

    @property
    def uses_memory_cache(self) -> bool:
        """True when the in-memory cache/queue implementations are in use."""
        return not self.redis_url

    @model_validator(mode="after")
    def _refuse_memory_cache_outside_dev(self) -> Settings:
        if self.is_production and not self.redis_url:
            raise ValueError(
                "REDIS_URL is required when APP_ENV is 'staging' or 'prod'. "
                "The in-memory cache/queue is dev/test only (D-34)."
            )
        return self


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Cached settings accessor. Raises at import time when misconfigured."""
    return Settings()  # type: ignore[call-arg]
