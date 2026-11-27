"""Application settings.

Rules (P0-T04, P0-T11):
- Configuration comes from the environment (or a local ``.env`` file).
- No secret or connection string has a default in code.
- The in-memory cache/queue may only run in ``dev`` and ``test`` (D-34): startup
  refuses to boot in ``staging``/``prod`` without ``REDIS_URL``.
- ``APP_BASE_URL`` is required in ``staging``/``prod`` (P11-T08): it is the only
  non-loopback origin the CSRF check and the WebSocket handshake accept, and the
  base of every invite link.
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

    # The public origin of the web app. Optional in dev/test (the dev server and
    # its rewrite are loopback); mandatory in staging/prod, where a loopback
    # default would silently refuse every real write instead of failing loudly
    # at boot.
    app_base_url: str | None = None
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

    @field_validator("app_base_url", mode="after")
    @classmethod
    def _base_url_is_absolute(cls, value: str | None) -> str | None:
        """A relative base URL cannot be compared with an ``Origin`` header."""
        if value is None or not value.strip():
            return None
        base = value.strip().rstrip("/")
        if not base.startswith(("http://", "https://")):
            raise ValueError(
                "APP_BASE_URL must be an absolute http(s) URL, "
                "for example https://games.example.org."
            )
        return base

    @model_validator(mode="after")
    def _refuse_dev_only_settings(self) -> Settings:
        if self.is_production and not self.redis_url:
            raise ValueError(
                "REDIS_URL is required when APP_ENV is 'staging' or 'prod'. "
                "The in-memory cache/queue is dev/test only (D-34)."
            )
        if self.is_production and not self.app_base_url:
            raise ValueError(
                "APP_BASE_URL is required when APP_ENV is 'staging' or 'prod'. "
                "Without it the accepted origins are loopback only, so every "
                "write from the real site is refused and invite links point at "
                "localhost."
            )
        return self


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Cached settings accessor. Raises at import time when misconfigured."""
    return Settings()  # type: ignore[call-arg]
