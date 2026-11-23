"""Session lifecycle as far as Phase 3 owns it (P3-T04, P3-T08).

Phase 4 creates sessions and scores them. Phase 3 owns the three moments that
spend time and nothing else:

- **start** — the access check, and the one active play per learner (D-26);
- **heartbeat** — the 15-second tick that accrues wall-clock time;
- **pause / resume** — the two places the clock must reset to zero charge.

The server never trusts a duration. A heartbeat carries only whether the tab
is visible; how long it has been is measured here, capped at 30 seconds, and
charged to the learner rather than the session.
"""

from __future__ import annotations

import datetime as dt
import uuid
from dataclasses import dataclass

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import AppError, ConflictError, NotFoundError
from app.games import repository as repo
from app.games.domain import access as rules
from app.games.models import GameSession
from app.games.services import access
from app.games.services import clock as play_clock
from app.identity.models import User


@dataclass(frozen=True, slots=True)
class PlayState:
    """What a heartbeat answers: enough to draw the meter and stop cleanly."""

    remaining_seconds: int
    used_seconds: int
    limit_minutes: int
    paused: bool
    ended: bool
    ended_reason: str | None


async def _load(
    session: AsyncSession, *, user: User, session_id: uuid.UUID
) -> tuple[GameSession, object]:
    row = await repo.get_session(session, session_id)
    if row is None or row.school_id != user.school_id:
        raise NotFoundError("That game was not found.")
    participant = await repo.get_participant(session, session_id, user.id)
    if participant is None:
        # A game you are not in is a game that does not exist, for you.
        raise NotFoundError("That game was not found.")
    return row, participant


async def start_play(
    session: AsyncSession, *, user: User, session_id: uuid.UUID, now: dt.datetime | None = None
) -> access.AccessState:
    now = now or dt.datetime.now(dt.UTC)
    row, participant = await _load(session, user=user, session_id=session_id)

    if row.mode == "challenge":
        raise AppError("That game cannot be started here.", code="not_startable", status_code=409)
    if row.status not in ("created", "active"):
        raise AppError("That game has ended.", code="session_ended", status_code=409)

    # D-27: a live match needs 15 minutes left *before* it starts.
    minimum = await access.live_minimum_seconds(session) if row.mode == "live" else 0
    state = await access.require_access(
        session, user=user, now=now, min_remaining_s=minimum, current_session_id=row.id
    )

    try:
        # A savepoint, so losing the race with another tab is a sentence and
        # not a broken transaction.
        async with session.begin_nested():
            participant.attempt_status = "in_progress"  # type: ignore[attr-defined]
            await session.flush()
    except IntegrityError as exc:
        raise ConflictError(
            "You have a game open somewhere else.", code="another_session_active"
        ) from exc

    # Starting is the first moment of the clock: set it to now without
    # charging, so the first real action is measured from the start.
    timezone = await access.school_timezone(session, user.school_id)
    await play_clock.reset_clock(session, user_id=user.id, school_timezone=timezone, at=now)

    row.status = "active"
    if row.started_at is None:
        row.started_at = now
    await session.commit()
    return state


async def heartbeat(
    session: AsyncSession,
    *,
    user: User,
    session_id: uuid.UUID,
    visible: bool,
    now: dt.datetime | None = None,
) -> PlayState:
    now = now or dt.datetime.now(dt.UTC)
    row, _participant = await _load(session, user=user, session_id=session_id)

    if row.status not in ("active", "paused", "created"):
        raise AppError("That game has ended.", code="session_ended", status_code=409)

    tz = await access.school_timezone(session, user.school_id)

    if not visible:
        # Hidden tab: charge nothing for the time it was hidden, and pause.
        await play_clock.reset_clock(session, user_id=user.id, school_timezone=tz, at=now)
        row.status = "paused"
        await session.commit()
        return await _state(session, user=user, row=row, now=now, paused=True)

    if row.status == "paused":
        # Resume: reset first, so the gap is never charged (P3-T04).
        await play_clock.reset_clock(session, user_id=user.id, school_timezone=tz, at=now)
        row.status = "active"
        await session.flush()
        return await _state(session, user=user, row=row, now=now, paused=False)

    accrual = await play_clock.record_activity(
        session, user_id=user.id, school_timezone=tz, at=now, source="heartbeat"
    )

    if accrual.gap_seconds > play_clock.SILENCE_SECONDS:
        # The tab stopped talking: treat it as paused rather than billing the
        # silence. Anything the learner actually did was charged as an action.
        await play_clock.reset_clock(session, user_id=user.id, school_timezone=tz, at=now)
        row.status = "paused"
        await session.commit()
        return await _state(session, user=user, row=row, now=now, paused=True)

    ended, reason = await _check_soft_limit(session, user=user, row=row, now=now)
    await session.commit()
    state = await _state(session, user=user, row=row, now=now, paused=False)
    if ended:
        return PlayState(
            remaining_seconds=0,
            used_seconds=state.used_seconds,
            limit_minutes=state.limit_minutes,
            paused=False,
            ended=True,
            ended_reason=reason,
        )
    return state


async def record_action(
    session: AsyncSession,
    *,
    user: User,
    session_id: uuid.UUID,
    now: dt.datetime | None = None,
) -> int:
    """A game action also proves the learner was playing (P3-T05).

    Called by every game's move endpoint from Phase 4 on. Returns the seconds
    accrued, so tests can prove a suppressed heartbeat still costs time.
    """
    now = now or dt.datetime.now(dt.UTC)
    await _load(session, user=user, session_id=session_id)
    tz = await access.school_timezone(session, user.school_id)
    accrual = await play_clock.record_activity(
        session, user_id=user.id, school_timezone=tz, at=now, source="action"
    )
    await session.commit()
    return accrual.granted_seconds


async def pause(
    session: AsyncSession, *, user: User, session_id: uuid.UUID, now: dt.datetime | None = None
) -> None:
    now = now or dt.datetime.now(dt.UTC)
    row, _participant = await _load(session, user=user, session_id=session_id)
    tz = await access.school_timezone(session, user.school_id)
    await play_clock.reset_clock(session, user_id=user.id, school_timezone=tz, at=now)
    if row.status == "active":
        row.status = "paused"
    await session.commit()


async def quit(
    session: AsyncSession, *, user: User, session_id: uuid.UUID, now: dt.datetime | None = None
) -> None:
    """Leave a game for good (P3-T04, and the close a live socket needs in P8).

    A quit is not a pause. The attempt ends here, produces no result, and frees
    the one-open-play seat (D-26), so the learner can start something else at
    once. The clock mark is cleared without inventing charges: time already
    played has been charged by heartbeats and actions as it happened.

    Quitting twice is not an error — the second call finds the game already
    over and says nothing, which is what a double tap on a slow phone gets.
    """
    now = now or dt.datetime.now(dt.UTC)
    row, participant = await _load(session, user=user, session_id=session_id)
    if row.status not in ("created", "active", "paused"):
        return

    participant.attempt_status = "expired"  # type: ignore[attr-defined]
    row.status = "abandoned"
    row.ended_at = now

    if row.parent_session_id is not None:
        # Local import: the challenge service uses this module for lifecycle, so
        # the dependency only exists in this one direction at call time.
        from app.games.services import challenge

        await challenge.close_after_quit(session, child=row, now=now)

    timezone = await access.school_timezone(session, user.school_id)
    await play_clock.reset_clock(session, user_id=user.id, school_timezone=timezone, at=now)
    await session.commit()


async def _check_soft_limit(
    session: AsyncSession, *, user: User, row: GameSession, now: dt.datetime
) -> tuple[bool, str | None]:
    """D-10: ten minutes past zero, then stop. Live matches are exempt (D-27)."""
    if row.mode == "live":
        return False, None

    state = await access.access_for(session, user=user, now=now, ignore_active_session=True)
    if state.remaining_seconds > 0:
        return False, None

    if row.allowance_grace_until is None:
        minutes = await access.grace_minutes(session)
        row.allowance_grace_until = rules.grace_deadline(now, minutes)
        await session.flush()
        return False, None

    if now >= row.allowance_grace_until:
        row.status = "timed_out_allowance"
        row.ended_at = now
        await session.flush()
        return True, rules.LIMIT_REACHED

    return False, None


async def _state(
    session: AsyncSession,
    *,
    user: User,
    row: GameSession,
    now: dt.datetime,
    paused: bool,
) -> PlayState:
    state = await access.access_for(session, user=user, now=now, ignore_active_session=True)
    ended = row.status == "timed_out_allowance"
    return PlayState(
        remaining_seconds=state.remaining_seconds,
        used_seconds=state.used_seconds,
        limit_minutes=state.limit_minutes,
        paused=paused,
        ended=ended,
        ended_reason=rules.LIMIT_REACHED if ended else None,
    )
