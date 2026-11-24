"""Leaderboard periods, projection and reads (P5-T06, P5-T07, D-33, D-35).

The projection is the whole design: on every eligible award, two rows are added
to **every open period** of the school — one under the game, one under
``game_id IS NULL`` ("all games"). A board then reads exactly one of those two
row sets and a window function ranks it. Nothing is ever recomputed on read, and
no board can double-count by summing the two.

Periods are school-local windows (D-07). ``all_time`` is one row per school with
no end, created when the school's first eligible award lands, so it can never be
rebuilt from "the last period" and never resets.
"""

from __future__ import annotations

import datetime as dt
import uuid
from dataclasses import dataclass
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import AppError, NotFoundError
from app.games import repository as repo
from app.games.domain import periods as period_rules
from app.games.domain import xp_rules
from app.games.models import LeaderboardPeriod, SchoolTerm
from app.identity.models import Role, School, User
from app.identity.service import Actor, visible_class, visible_classes

DEFAULT_MIN_SESSIONS = xp_rules.DEFAULT_MIN_SESSIONS


@dataclass(frozen=True, slots=True)
class BoardEntry:
    rank: int
    user_id: uuid.UUID
    preferred_name: str
    avatar_key: str
    xp_total: int
    sessions_count: int
    is_me: bool


@dataclass(frozen=True, slots=True)
class BoardChase:
    """The row just above the learner — the one worth catching today."""

    preferred_name: str
    xp_gap: int


@dataclass(frozen=True, slots=True)
class Board:
    period_type: str
    starts_at: dt.datetime
    ends_at: dt.datetime | None
    entries: list[BoardEntry]
    me: BoardEntry | None
    me_eligible: bool
    min_sessions: int
    # Near-miss nudges. Both are ``None`` for staff and for the top of the board.
    chase: BoardChase | None = None
    to_join: int | None = None


@dataclass(frozen=True, slots=True)
class StudentGameXp:
    game_id: str
    xp_total: int
    sessions_count: int


@dataclass(frozen=True, slots=True)
class StudentXp:
    preferred_name: str
    avatar_key: str
    xp_total: int
    sessions_count: int
    games: list[StudentGameXp]


@dataclass(frozen=True, slots=True)
class CoachBoard:
    period_type: str
    starts_at: dt.datetime
    ends_at: dt.datetime | None
    students: list[StudentXp]


def _now() -> dt.datetime:
    return dt.datetime.now(dt.UTC)


async def _term_for(
    session: AsyncSession, *, school_id: uuid.UUID, local_date: dt.date
) -> tuple[dt.date, dt.date] | None:
    """The school's current term, or ``None`` when its calendar says nothing."""
    row = (
        (
            await session.execute(
                select(SchoolTerm)
                .where(
                    SchoolTerm.school_id == school_id,
                    SchoolTerm.starts_on <= local_date,
                    SchoolTerm.ends_on >= local_date,
                )
                .order_by(SchoolTerm.starts_on.desc())
                .limit(1)
            )
        )
        .scalars()
        .first()
    )
    return None if row is None else (row.starts_on, row.ends_on)


async def _monthly_enabled(session: AsyncSession) -> bool:
    value = await repo.get_platform_setting(session, "leaderboards.monthly_enabled")
    return bool(value)


async def ensure_period(
    session: AsyncSession,
    *,
    school_id: uuid.UUID,
    period_type: str,
    now: dt.datetime,
    timezone: str,
) -> LeaderboardPeriod | None:
    """The current period, created on demand. ``None`` means "cannot exist"."""
    tz = ZoneInfo(timezone)
    local = now.astimezone(tz)
    term = await _term_for(session, school_id=school_id, local_date=local.date())
    first_award = None
    if period_type == "all_time":
        # The all-time board never rolls over, so an open one is always right:
        # comparing its start against "the first award" would close the board
        # the moment the first award existed and throw its rows away.
        existing_all_time = await repo.open_period(
            session, school_id=school_id, period_type="all_time"
        )
        if existing_all_time is not None:
            return existing_all_time
        first_award = await repo.first_award_at(session, school_id=school_id)
        if first_award is None:
            # Reachable and empty before its first award, so an admin can see
            # the board exists (the DoD asks for it to be reachable).
            first_award = now

    window = period_rules.window(
        period_type, now_local=local, tz=tz, term=term, first_award=first_award
    )
    if window is None:
        return None

    existing = await repo.open_period(session, school_id=school_id, period_type=period_type)
    if existing is not None:
        if existing.starts_at == window.starts_at:
            return existing
        # The window rolled over while nobody was looking. Close it here, on
        # first read, which is one of the three places the plan generates
        # periods (P5-T06); the nightly job is another.
        existing.status = "closed"
        await session.flush()

    return await repo.ensure_period(
        session,
        school_id=school_id,
        period_type=period_type,
        starts_at=window.starts_at,
        ends_at=window.ends_at,
    )


async def open_periods(
    session: AsyncSession, *, school_id: uuid.UUID, now: dt.datetime, timezone: str
) -> dict[str, LeaderboardPeriod]:
    """Every period an award must land in: today, this week, this term, all time."""
    wanted = list(period_rules.SHIPPED_PERIODS)
    if await _monthly_enabled(session):
        wanted.append("monthly")

    out: dict[str, LeaderboardPeriod] = {}
    for period_type in wanted:
        row = await ensure_period(
            session, school_id=school_id, period_type=period_type, now=now, timezone=timezone
        )
        if row is not None:
            out[period_type] = row
    return out


async def apply_award(
    session: AsyncSession,
    *,
    school_id: uuid.UUID,
    user_id: uuid.UUID,
    game_id: str,
    class_id: uuid.UUID | None,
    age_band: str | None,
    xp: int,
    sessions: int,
    at: dt.datetime,
    timezone: str,
) -> None:
    """Add one eligible award to every open period, twice (game and all games)."""
    periods = await open_periods(session, school_id=school_id, now=at, timezone=timezone)
    for period in periods.values():
        for row_game in (game_id, None):
            await repo.add_to_entry(
                session,
                period_id=period.id,
                school_id=school_id,
                user_id=user_id,
                game_id=row_game,
                class_id=class_id,
                age_band=age_band,
                xp=xp,
                sessions=sessions,
                at=at,
            )


async def _min_sessions(session: AsyncSession) -> int:
    from app.games.services.access import _setting_int

    return await _setting_int(session, "leaderboards.min_sessions", DEFAULT_MIN_SESSIONS)


async def board(
    session: AsyncSession,
    *,
    actor: Actor,
    period_type: str,
    game_id: str | None = None,
    class_id: uuid.UUID | None = None,
    age_band: str | None = None,
    now: dt.datetime | None = None,
) -> Board:
    """One board under the D-33 read rules, for one caller."""
    if period_type not in period_rules.PERIOD_TYPES:
        raise NotFoundError("That board was not found.")

    # All-time is the school's own board, shown with masked identity to every
    # role in that school, so it needs no extra gate (D-35). ``monthly`` stays
    # behind its flag.
    if period_type == "monthly" and not await _monthly_enabled(session):
        raise NotFoundError("That board was not found.")

    school = await session.get(School, actor.school_id)
    if school is not None and not school.leaderboards_enabled:
        raise NotFoundError("That board was not found.")

    if class_id is not None:
        # A class board is only readable for a class the caller may see.
        await visible_class(session, actor=actor, class_id=class_id)

    now = now or _now()
    period = await ensure_period(
        session,
        school_id=actor.school_id,
        period_type=period_type,
        now=now,
        timezone=actor.school_timezone,
    )
    if period is None:
        raise AppError(
            "That board is not open yet.",
            code="period_unavailable",
            status_code=404,
        )

    minimum = await _min_sessions(session)
    rows = await repo.board_rows(
        session,
        period_id=period.id,
        game_id=game_id,
        class_id=class_id,
        age_band=age_band,
        min_sessions=minimum,
        limit=10,
    )
    entries = [
        BoardEntry(
            rank=int(row.rank),
            user_id=row.user_id,
            preferred_name=row.preferred_name,
            avatar_key=row.avatar_key,
            xp_total=int(row.xp_total),
            sessions_count=int(row.sessions_count),
            is_me=row.user_id == actor.id,
        )
        for row in rows
    ]

    own = await repo.user_board_total(
        session,
        period_id=period.id,
        game_id=game_id,
        class_id=class_id,
        age_band=age_band,
        user_id=actor.id,
    )
    me: BoardEntry | None = None
    me_eligible = False
    chase: BoardChase | None = None
    to_join: int | None = None
    if own is not None:
        sessions_count = int(own.sessions_count or 0)
        me_eligible = sessions_count >= minimum
        if me_eligible:
            rank = await repo.user_rank(
                session,
                period_id=period.id,
                game_id=game_id,
                class_id=class_id,
                age_band=age_band,
                min_sessions=minimum,
                user_id=actor.id,
            )
            user = await session.get(User, actor.id)
            me = BoardEntry(
                rank=rank or 0,
                user_id=actor.id,
                preferred_name=user.preferred_name if user else actor.preferred_name,
                avatar_key=user.avatar_key if user else actor.avatar_key,
                xp_total=int(own.xp_total or 0),
                sessions_count=sessions_count,
                is_me=True,
            )
    if actor.role is Role.learner:
        if me is not None and me.rank > 1:
            # The next place up, priced in exactly the currency the board uses.
            above = await repo.ranked_row(
                session,
                period_id=period.id,
                game_id=game_id,
                class_id=class_id,
                age_band=age_band,
                min_sessions=minimum,
                rank=me.rank - 1,
            )
            if above is not None:
                chase = BoardChase(
                    preferred_name=above.preferred_name,
                    xp_gap=max(0, int(above.xp_total) - me.xp_total),
                )
        elif not me_eligible:
            # Not ranked yet: the useful number is how many games are missing.
            to_join = max(0, minimum - (int(own.sessions_count or 0) if own else 0))

    return Board(
        period_type=period_type,
        starts_at=period.starts_at,
        ends_at=period.ends_at,
        entries=entries,
        me=me,
        me_eligible=me_eligible,
        min_sessions=minimum,
        chase=chase,
        to_join=to_join,
    )


async def coach_breakdown(
    session: AsyncSession,
    *,
    actor: Actor,
    period_type: str,
    class_id: uuid.UUID | None = None,
    age_band: str | None = None,
    now: dt.datetime | None = None,
) -> CoachBoard:
    """A coach's class, with each learner's XP split by game (P5-T11).

    Staff only, and scoped twice: a coach sees the classes assigned to them, an
    admin sees the school. Every number here is a per-game row of the same
    projection the board reads, so it can be checked against the ledger without
    a second source of truth (D-33).
    """
    if period_type not in period_rules.PERIOD_TYPES:
        raise NotFoundError("That board was not found.")
    if period_type == "monthly" and not await _monthly_enabled(session):
        raise NotFoundError("That board was not found.")

    school = await session.get(School, actor.school_id)
    if school is not None and not school.leaderboards_enabled:
        raise NotFoundError("That board was not found.")

    if class_id is not None:
        await visible_class(session, actor=actor, class_id=class_id)
        scoped_class = class_id
        class_ids = [class_id]
    elif actor.is_admin:
        scoped_class = None
        class_ids = []
    else:
        # A coach without an explicit class gets their first one; the screen
        # always sends the class the coach picked.
        classes = await visible_classes(session, actor=actor)
        if not classes:
            return CoachBoard(period_type=period_type, starts_at=_now(), ends_at=None, students=[])
        scoped_class = classes[0].id
        class_ids = [scoped_class]

    now = now or _now()
    period = await ensure_period(
        session,
        school_id=actor.school_id,
        period_type=period_type,
        now=now,
        timezone=actor.school_timezone,
    )
    if period is None:
        raise AppError(
            "That board is not open yet.",
            code="period_unavailable",
            status_code=404,
        )

    rows = await repo.board_rows(
        session,
        period_id=period.id,
        game_id=None,
        class_id=scoped_class,
        age_band=age_band,
        # Staff see every learner who has played, not just those past the
        # learner-facing minimum: a coach needs the small numbers too.
        min_sessions=0,
        limit=100,
    )
    user_ids = [row.user_id for row in rows]
    per_game = (
        await repo.per_game_entries(
            session,
            period_id=period.id,
            class_ids=class_ids,
            age_band=age_band,
            user_ids=user_ids,
        )
        if user_ids
        else []
    )

    by_user: dict[uuid.UUID, list[StudentGameXp]] = {}
    for row in per_game:
        by_user.setdefault(row.user_id, []).append(
            StudentGameXp(
                game_id=row.game_id,
                xp_total=int(row.xp_total),
                sessions_count=int(row.sessions_count),
            )
        )

    students = [
        StudentXp(
            preferred_name=row.preferred_name,
            avatar_key=row.avatar_key,
            xp_total=int(row.xp_total),
            sessions_count=int(row.sessions_count),
            games=sorted(by_user.get(row.user_id, []), key=lambda g: -g.xp_total),
        )
        for row in rows
    ]

    return CoachBoard(
        period_type=period_type,
        starts_at=period.starts_at,
        ends_at=period.ends_at,
        students=students,
    )
