"""Queue abstraction (plan section 3A, D-34).

Production uses ARQ on Redis. Local development runs tasks inline or through
``python -m app.cli job run <name>`` so no worker process and no Redis are
needed. Nothing durable may live only in the queue.
"""

from __future__ import annotations

from typing import Any, Protocol

from app.core.config import Settings
from app.core.logging import get_logger
from app.jobs.registry import run_task

log = get_logger(__name__)


class QueueClient(Protocol):
    async def enqueue(self, task: str, payload: dict[str, Any], delay_s: int = 0) -> str: ...

    async def run_inline(self, task: str, payload: dict[str, Any]) -> None: ...

    async def aclose(self) -> None: ...


class InlineQueue:
    """Runs every task immediately in-process. Dev/test only."""

    backend = "inline"

    async def enqueue(self, task: str, payload: dict[str, Any], delay_s: int = 0) -> str:
        if delay_s:
            # Delayed work is not supported inline; run now and say so loudly.
            log.warning(
                "queue.delay_ignored_inline",
                extra={"route": task, "duration_ms": delay_s * 1000},
            )
        await run_task(task, payload)
        return f"inline:{task}"

    async def run_inline(self, task: str, payload: dict[str, Any]) -> None:
        await run_task(task, payload)

    async def aclose(self) -> None:
        return None


class ArqQueue:
    """ARQ-backed queue. Imports ARQ lazily so dev runs need no Redis."""

    backend = "arq"

    def __init__(self, url: str) -> None:
        self._url = url
        self._pool: Any = None

    async def _get_pool(self) -> Any:
        if self._pool is None:
            from arq.connections import RedisSettings, create_pool

            settings = RedisSettings.from_dsn(self._url)
            self._pool = await create_pool(settings)
        return self._pool

    async def enqueue(self, task: str, payload: dict[str, Any], delay_s: int = 0) -> str:
        pool = await self._get_pool()
        job = await pool.enqueue_job(task, payload, _defer_by=delay_s or None)
        return str(job.job_id if job else "")

    async def run_inline(self, task: str, payload: dict[str, Any]) -> None:
        # Deliberate: an operator asking for an inline run wants the real code
        # path, not a queue round-trip.
        await run_task(task, payload)

    async def aclose(self) -> None:
        if self._pool is not None:
            await self._pool.aclose()
            self._pool = None


def build_queue(settings: Settings) -> QueueClient:
    if settings.redis_url:
        return ArqQueue(settings.redis_url)
    if settings.is_production:
        raise RuntimeError("A real queue is required outside dev/test (D-34).")
    return InlineQueue()
