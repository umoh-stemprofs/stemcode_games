"""ARQ worker entry point (P0-T03a container path).

Local development never needs this process: jobs run inline or through
``python -m app.cli job run <name>`` (D-34).

Every task goes through the registry, so a job behaves identically whether it
was enqueued in production, run inline in dev, or run by hand from the CLI.
"""

from __future__ import annotations

from typing import Any

from arq.connections import RedisSettings

from app.core.config import get_settings
from app.core.logging import configure_logging, get_logger
from app.jobs.registry import run_task

log = get_logger(__name__)


async def dispatch(ctx: dict[str, Any], name: str, payload: dict[str, Any]) -> dict[str, Any]:
    """Single entry point so the worker knows no task names of its own."""
    return await run_task(name, payload)


async def startup(ctx: dict[str, Any]) -> None:
    configure_logging(get_settings().log_level)
    log.info("worker.started", extra={"route": "startup"})


async def shutdown(ctx: dict[str, Any]) -> None:
    log.info("worker.stopped", extra={"route": "shutdown"})


class WorkerSettings:
    functions = [dispatch]
    on_startup = startup
    on_shutdown = shutdown
    max_jobs = 10
    job_timeout = 120

    @staticmethod
    def redis_settings() -> RedisSettings:  # pragma: no cover - worker only
        url = get_settings().redis_url
        if not url:
            raise RuntimeError("The worker requires REDIS_URL (D-34).")
        return RedisSettings.from_dsn(url)
