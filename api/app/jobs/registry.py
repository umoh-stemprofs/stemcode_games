"""Background task registry (P0-T12).

Every job is registered by name so it can be run three ways:
  1. by the ARQ worker in production,
  2. inline in local development,
  3. by hand: ``python -m app.cli job run <name>``.

Phase 0 ships the registry and the four launch jobs as stubs. A stub says so in
its result instead of pretending to do work; each is replaced by the phase that
owns it.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

from app.core.logging import get_logger

log = get_logger(__name__)

Task = Callable[[dict[str, Any]], Awaitable[dict[str, Any]]]

TASKS: dict[str, Task] = {}


def task(name: str) -> Callable[[Task], Task]:
    def register(func: Task) -> Task:
        if name in TASKS:
            raise RuntimeError(f"duplicate task name: {name}")
        TASKS[name] = func
        return func

    return register


async def run_task(name: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
    func = TASKS.get(name)
    if func is None:
        raise KeyError(f"unknown task: {name}")
    log.info("job.start", extra={"route": name})
    result = await func(payload or {})
    log.info("job.finish", extra={"route": name})
    return result


_STUB = {"status": "not_implemented_yet"}


@task("roll_periods")
async def roll_periods(payload: dict[str, Any]) -> dict[str, Any]:
    """Close ended leaderboard periods and open the next (P5-T06)."""
    return {**_STUB, "owner": "P5-T06"}


@task("reconcile")
async def reconcile(payload: dict[str, Any]) -> dict[str, Any]:
    """Recompute leaderboard totals from the XP ledger and report drift (P5-T07)."""
    return {**_STUB, "owner": "P5-T07", "drift": 0}


@task("sweep_invites")
async def sweep_invites(payload: dict[str, Any]) -> dict[str, Any]:
    """Expire overdue invites and close challenges whose window ended (P7-T10)."""
    return {**_STUB, "owner": "P7-T10"}


@task("anomaly_scan")
async def anomaly_scan(payload: dict[str, Any]) -> dict[str, Any]:
    """Nightly fair-play scan writing ``fairplay_flags`` (P10-T02)."""
    return {**_STUB, "owner": "P10-T02"}
