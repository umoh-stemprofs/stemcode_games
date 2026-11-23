"""Play-time accrual (P3-T05, D-26).

The rule is one sentence: *time is charged to the learner, not to the session.*
There is exactly one ``game_play_clock`` row per learner per school day, and
both heartbeats and real game actions advance it through the same function.
That is what makes all of these true at once:

- two tabs cannot consume the allowance twice;
- a heartbeat and an answer in the same interval do not double-count;
- a client that stops sending heartbeats but keeps playing is still charged
  through its actions;
- resuming from a pause never charges the idle gap.

The server never accepts a duration from the client. It measures the gap from
the last moment it counted, and never counts more than 30 seconds for one gap.
"""

from __future__ import annotations

import datetime as dt
import uuid
from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncSession

from app.games.domain.access import local_date
from app.games.repository import (
    add_usage,
    ensure_play_clock,
    lock_play_clock,
    used_seconds,
)

# The largest amount of time one gap may add. A heartbeat is sent every 15 s;
# 30 s is the plan's cap and stays correct through one lost heartbeat.
MAX_GAP_SECONDS = 30

# A gap this long means the tab stopped talking, not that the learner kept
# playing (P3-T04: automatic pause after 45 s of silence).
SILENCE_SECONDS = 45


@dataclass(frozen=True, slots=True)
class Accrual:
    """What one counted interval did, so callers can decide about pausing."""

    granted_seconds: int
    gap_seconds: float


def _aware(value: dt.datetime) -> dt.datetime:
    return value if value.tzinfo else value.replace(tzinfo=dt.UTC)


async def record_activity(
    session: AsyncSession,
    *,
    user_id: uuid.UUID,
    school_timezone: str,
    at: dt.datetime,
    source: str,
) -> Accrual:
    """Accrue the gap since this learner was last counted."""
    day = local_date(at, school_timezone)

    # Insert-then-lock (P3-T05): the insert cannot collide, so the row lock
    # below always serialises two tabs that act in the same instant.
    await ensure_play_clock(session, user_id=user_id, local_date=day, now=at)
    clock = await lock_play_clock(session, user_id=user_id, local_date=day)
    if clock is None:  # pragma: no cover - the insert above guarantees it
        return Accrual(0, 0.0)

    elapsed = (_aware(at) - _aware(clock.last_counted_at)).total_seconds()
    granted = int(min(max(elapsed, 0.0), MAX_GAP_SECONDS))

    await add_usage(session, user_id=user_id, local_date=day, source=source, seconds=granted)
    clock.last_counted_at = at
    await session.flush()
    return Accrual(granted_seconds=granted, gap_seconds=max(elapsed, 0.0))


async def reset_clock(
    session: AsyncSession, *, user_id: uuid.UUID, school_timezone: str, at: dt.datetime
) -> None:
    """Charge nothing for the gap, and continue from now.

    Used by both pause and resume (P3-T04): after either one, the next counted
    interval starts at this moment, so a learner who comes back to the tab is
    never billed 30 seconds for the minutes they were away.
    """
    day = local_date(at, school_timezone)
    await ensure_play_clock(session, user_id=user_id, local_date=day, now=at)
    clock = await lock_play_clock(session, user_id=user_id, local_date=day)
    if clock is not None:
        clock.last_counted_at = at
        await session.flush()


async def used_today(
    session: AsyncSession, *, user_id: uuid.UUID, school_timezone: str, at: dt.datetime
) -> int:
    return await used_seconds(session, user_id=user_id, local_date=local_date(at, school_timezone))
