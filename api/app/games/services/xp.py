"""Awarding Game XP (P5-T02, P5-T03, D-13).

The only door to XP. No endpoint accepts an amount: a result is written by the
server, and this module turns that result into a ledger row, a daily total and a
leaderboard projection, inside the caller's transaction.

Three properties this file exists to guarantee:

- **Idempotent.** The ledger's unique key is ``(session_id, user_id, reason)``.
  A retried award finds the existing row and changes nothing — it does not add
  the daily total twice, and it does not touch the board again.
- **Capped.** The daily total row is inserted and then locked *before* it is
  read, so two concurrent awards on one learner cannot both see the old total
  and both take the last 5 points.
- **Auditable.** A below-minimum session still writes a row with
  ``reason='below_minimum'`` and ``awarded_amount=0``: deciding to pay nothing is
  recorded, not invisible (D-29).
"""

from __future__ import annotations

import datetime as dt
import uuid
from dataclasses import dataclass
from zoneinfo import ZoneInfo

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.games import repository as repo
from app.games.domain import xp_rules
from app.games.models import GameResult, GameSession, GameXpDailyTotal, GameXpEntry
from app.games.services import leaderboards
from app.identity.models import ClassMember, LearningXpEntry, School, User
from app.identity.service import Actor, get_age_band


@dataclass(frozen=True, slots=True)
class Award:
    """What one award did, for the caller and for the post-game summary."""

    awarded: int
    requested: int
    today: int
    daily_cap: int
    reason: str
    eligible: bool


def _now() -> dt.datetime:
    return dt.datetime.now(dt.UTC)


async def daily_cap(session: AsyncSession) -> int:
    """The cap is a setting, not a constant (D-13)."""
    from app.games.services.access import _setting_int

    return await _setting_int(session, "xp.daily_cap", xp_rules.DEFAULT_DAILY_CAP)


async def _school_timezone(session: AsyncSession, school_id: uuid.UUID) -> str:
    school = await session.get(School, school_id)
    return school.timezone if school is not None else "UTC"


async def _class_of(session: AsyncSession, user_id: uuid.UUID) -> uuid.UUID | None:
    """The class this learner was in when the XP was earned (D-23).

    A snapshot, so a later transfer does not move past XP to another class.
    """
    return (
        (
            await session.execute(
                select(ClassMember.class_id)
                .where(ClassMember.user_id == user_id)
                .order_by(ClassMember.class_id)
                .limit(1)
            )
        )
        .scalars()
        .first()
    )


async def _lock_daily_total(
    session: AsyncSession, *, user_id: uuid.UUID, local_date: dt.date, school_id: uuid.UUID
) -> GameXpDailyTotal:
    """Insert-then-lock: two first awards of the day must not collide."""
    await session.execute(
        pg_insert(GameXpDailyTotal)
        .values(user_id=user_id, local_date=local_date, school_id=school_id, xp_total=0)
        .on_conflict_do_nothing(index_elements=["user_id", "local_date"])
    )
    return (
        await session.execute(
            select(GameXpDailyTotal)
            .where(
                GameXpDailyTotal.user_id == user_id,
                GameXpDailyTotal.local_date == local_date,
            )
            .with_for_update()
        )
    ).scalar_one()


async def _existing_award(
    session: AsyncSession, *, session_id: uuid.UUID, user_id: uuid.UUID, reason: str
) -> GameXpEntry | None:
    stmt = select(GameXpEntry).where(
        GameXpEntry.session_id == session_id,
        GameXpEntry.user_id == user_id,
        GameXpEntry.reason == reason,
    )
    return (await session.execute(stmt)).scalars().first()


async def award_for_result(
    session: AsyncSession,
    *,
    result: GameResult,
    game_row: GameSession,
    user: User,
    now: dt.datetime | None = None,
    challenge_win: bool = False,
) -> Award:
    """Turn a stored result into XP. Call inside the writing transaction."""
    now = now or _now()
    tz = ZoneInfo(await _school_timezone(session, user.school_id))
    local_date = now.astimezone(tz).date()

    cap = await daily_cap(session)
    request = xp_rules.request_xp(
        game_id=game_row.game_id,
        outcome=result.outcome,
        score=result.score,
        details=dict(result.details or {}),
        challenge_win=challenge_win,
    )

    # Idempotency first: a retry must not consume cap room a second time.
    already = await _existing_award(
        session, session_id=game_row.id, user_id=user.id, reason=request.reason
    )
    today = await repo.xp_for_user_on_date(session, user_id=user.id, local_date=local_date)
    if already is not None:
        return Award(
            awarded=already.awarded_amount,
            requested=already.requested_amount,
            today=today,
            daily_cap=cap,
            reason=already.reason,
            eligible=already.leaderboard_eligible,
        )

    total = await _lock_daily_total(
        session, user_id=user.id, local_date=local_date, school_id=user.school_id
    )
    awarded = xp_rules.capped_award(request.requested, total.xp_total, cap)

    band = (
        await get_age_band(session, date_of_birth=user.date_of_birth, on_date=local_date)
        if user.date_of_birth
        else None
    )
    class_id = await _class_of(session, user.id)

    # Pair/day caps and fair-play exclusion land in later phases; until then
    # "eligible" is the result's own flag AND real play AND something paid.
    eligible = bool(result.leaderboard_eligible) and request.meets_minimum and awarded > 0

    session.add(
        GameXpEntry(
            user_id=user.id,
            game_id=game_row.game_id,
            session_id=game_row.id,
            reason=request.reason,
            requested_amount=request.requested,
            awarded_amount=awarded,
            local_date=local_date,
            school_id=user.school_id,
            class_id_snapshot=class_id,
            age_band_snapshot=band.id if band is not None else None,
            leaderboard_eligible=eligible,
        )
    )
    await session.flush()
    total.xp_total = total.xp_total + awarded

    if eligible:
        # sessions_count counts a *session*, not a row: a challenge writes two
        # rows for one attempt and must still count as one (P5-T07, D-14).
        first_for_session = (
            await repo.ledger_rows_for_session(session, session_id=game_row.id, user_id=user.id)
            == 1
        )
        await leaderboards.apply_award(
            session,
            school_id=user.school_id,
            user_id=user.id,
            game_id=game_row.game_id,
            class_id=class_id,
            age_band=band.id if band is not None else None,
            xp=awarded,
            sessions=1 if first_for_session else 0,
            at=now,
            timezone=tz.key,
        )

    return Award(
        awarded=awarded,
        requested=request.requested,
        today=total.xp_total,
        daily_cap=cap,
        reason=request.reason,
        eligible=eligible,
    )


async def learning_total(session: AsyncSession, *, user_id: uuid.UUID) -> int:
    """Learning XP belongs to the host platform; this is the local stub (D-01)."""
    value = (
        await session.execute(
            select(func.coalesce(func.sum(LearningXpEntry.amount), 0)).where(
                LearningXpEntry.user_id == user_id
            )
        )
    ).scalar_one()
    return int(value)


async def award_challenge_win(
    session: AsyncSession,
    *,
    game_row: GameSession,
    user: User,
    now: dt.datetime | None = None,
) -> int:
    """The +5 for winning a challenge, as its own ledger row (P7-T05).

    It cannot ride on the "played" row: that row is keyed
    ``(session_id, user_id, 'played')`` and already exists by the time the two
    attempts are compared, so the idempotent path would return the old award and
    the bonus would silently never pay. Its own reason makes it keyed
    ``(child_session, user_id, 'challenge_win')`` and therefore paid once.

    Returns what it actually paid, which may be 0 when the cap is already full.
    """
    now = now or _now()
    tz = ZoneInfo(await _school_timezone(session, user.school_id))
    local_date = now.astimezone(tz).date()
    cap = await daily_cap(session)

    already = await _existing_award(
        session, session_id=game_row.id, user_id=user.id, reason="challenge_win"
    )
    if already is not None:
        return 0

    total = await _lock_daily_total(
        session, user_id=user.id, local_date=local_date, school_id=user.school_id
    )
    awarded = xp_rules.capped_award(xp_rules.CHALLENGE_WIN_BONUS, total.xp_total, cap)
    band = (
        await get_age_band(session, date_of_birth=user.date_of_birth, on_date=local_date)
        if user.date_of_birth
        else None
    )
    class_id = await _class_of(session, user.id)

    # A bonus row is written even when it pays nothing, for the same reason a
    # below-minimum row is: the decision must be auditable (D-29).
    session.add(
        GameXpEntry(
            user_id=user.id,
            game_id=game_row.game_id,
            session_id=game_row.id,
            reason="challenge_win",
            requested_amount=xp_rules.CHALLENGE_WIN_BONUS,
            awarded_amount=awarded,
            local_date=local_date,
            school_id=user.school_id,
            class_id_snapshot=class_id,
            age_band_snapshot=band.id if band is not None else None,
            leaderboard_eligible=awarded > 0,
        )
    )
    await session.flush()
    total.xp_total = total.xp_total + awarded

    if awarded > 0:
        await leaderboards.apply_award(
            session,
            school_id=user.school_id,
            user_id=user.id,
            game_id=game_row.game_id,
            class_id=class_id,
            age_band=band.id if band is not None else None,
            xp=awarded,
            sessions=0,
            at=now,
            timezone=tz.key,
        )
    return awarded


async def award_quest_bonus(
    session: AsyncSession,
    *,
    game_row: GameSession,
    user: User,
    requested: int,
    now: dt.datetime | None = None,
) -> int:
    """Pay the daily quest bonus once per learner per day (P5-T02 rules apply).

    It rides the same cap as play, because it is XP like any other. Its ledger
    row carries the session that completed the quest, so the unique
    ``(session_id, user_id, reason)`` key is still meaningful; the *day* guard is
    a separate lookup, because a second session could otherwise pay twice.
    """
    now = now or _now()
    tz = ZoneInfo(await _school_timezone(session, user.school_id))
    local_date = now.astimezone(tz).date()

    paid_today = (
        await session.execute(
            select(GameXpEntry.id).where(
                GameXpEntry.user_id == user.id,
                GameXpEntry.reason == "daily_quest",
                GameXpEntry.local_date == local_date,
            )
        )
    ).first()
    if paid_today is not None:
        return 0

    cap = await daily_cap(session)
    total = await _lock_daily_total(
        session, user_id=user.id, local_date=local_date, school_id=user.school_id
    )
    awarded = xp_rules.capped_award(requested, total.xp_total, cap)
    band = (
        await get_age_band(session, date_of_birth=user.date_of_birth, on_date=local_date)
        if user.date_of_birth
        else None
    )
    class_id = await _class_of(session, user.id)

    session.add(
        GameXpEntry(
            user_id=user.id,
            game_id=game_row.game_id,
            session_id=game_row.id,
            reason="daily_quest",
            requested_amount=requested,
            awarded_amount=awarded,
            local_date=local_date,
            school_id=user.school_id,
            class_id_snapshot=class_id,
            age_band_snapshot=band.id if band is not None else None,
            leaderboard_eligible=awarded > 0,
        )
    )
    await session.flush()
    total.xp_total = total.xp_total + awarded

    if awarded > 0:
        await leaderboards.apply_award(
            session,
            school_id=user.school_id,
            user_id=user.id,
            game_id=game_row.game_id,
            class_id=class_id,
            age_band=band.id if band is not None else None,
            xp=awarded,
            sessions=0,
            at=now,
            timezone=tz.key,
        )
    return awarded


async def summary(session: AsyncSession, *, actor: Actor, now: dt.datetime | None = None) -> dict:
    """The XP chip: learning + game, today's game XP, and the cap (P5-T05)."""
    now = now or _now()
    local_date = now.astimezone(ZoneInfo(actor.school_timezone)).date()

    game_total = await repo.total_game_xp(session, user_id=actor.id)
    game_today = await repo.xp_for_user_on_date(session, user_id=actor.id, local_date=local_date)
    learning = await learning_total(session, user_id=actor.id)

    return {
        "learning_xp_total": learning,
        "game_xp_total": game_total,
        "profile_xp_total": learning + game_total,
        "game_xp_today": game_today,
        "daily_cap": await daily_cap(session),
    }
