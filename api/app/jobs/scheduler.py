"""In-process sweeps for local development (D-34, P4-T08, P7-T10, P8-T11).

Production runs the jobs on the ARQ worker. Local development has no worker and
no Redis, so without this the ten-minute abandonment rule never fires: a learner
who closes the tab mid-round comes back hours later and the hub still says
"you have a game open somewhere else", because nothing ever closed that seat.

This is not a second implementation. It calls the same registered tasks, so the
rules cannot drift between the worker and the laptop. It runs only in `dev`;
staging and production refuse to start without Redis and always have a worker.
"""

from __future__ import annotations

import asyncio

from app.core.logging import get_logger
from app.jobs.registry import TASKS, run_task

log = get_logger(__name__)

# The sweeps that make the rules true on a timer. Order matters a little: a
# silent solo session is abandoned before invites and live matches are swept, so
# a freed seat can be reused in the same pass.
SWEEPS: tuple[str, ...] = ("sweep_sessions", "sweep_invites", "sweep_live")

INTERVAL_SECONDS = 60


async def _run_once() -> None:
    for name in SWEEPS:
        if name not in TASKS:
            continue
        try:
            await run_task(name)
        except asyncio.CancelledError:
            raise
        except Exception:  # noqa: BLE001 - one broken sweep must not stop the rest
            log.exception("job.inline_failed", extra={"route": name})


async def _loop() -> None:
    # Run once immediately: a server just started is exactly when a session
    # stranded by the previous run should be cleared, not a minute later.
    while True:
        await _run_once()
        await asyncio.sleep(INTERVAL_SECONDS)


def start() -> asyncio.Task[None]:
    """Start the sweep loop. Returns the task so shutdown can stop it."""
    log.info("jobs.inline_started", extra={"route": "startup", "status": 0})
    return asyncio.create_task(_loop(), name="inline-sweeps")


async def stop(task: asyncio.Task[None] | None) -> None:
    if task is None:
        return
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass
    log.info("jobs.inline_stopped", extra={"route": "shutdown", "status": 0})
