"""Thin persistence layer for the games schema (P2-T06).

Rules for everything here:

- **No business logic.** No scoring, no eligibility, no clocks, no permission
  checks. If a function needs to decide something, it belongs in a service.
- **No commits.** The caller owns the transaction, so a session plus its
  participants plus its first move land together or not at all.
- **No ``seed`` output.** ``get_session`` returns the row, and only a service
  that needs the number may read it. Nothing here serialises it (D-25).
"""

from __future__ import annotations

import datetime as dt
import uuid
from collections.abc import Sequence
from typing import Any

from sqlalchemy import and_, func, or_, select, text, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.games.models import (
    AccessPolicy,
    AuditEntry,
    BlockedWord,
    ContentItem,
    ContentPack,
    FairplayFlag,
    Game,
    GameBlock,
    GameInvitation,
    GameLockout,
    GameMove,
    GameNotification,
    GamePairDailyCount,
    GameParticipant,
    GamePlayClock,
    GameReport,
    GameResult,
    GameSession,
    GameTimeUsage,
    GameXpEntry,
    LeaderboardEntry,
    LeaderboardPeriod,
    PlatformSetting,
)
from app.identity.models import ClassMember, Role, User, UserStatus


# --------------------------------------------------------------------- catalog
async def list_games(session: AsyncSession, *, enabled_only: bool = True) -> list[Game]:
    stmt = select(Game).order_by(Game.name)
    if enabled_only:
        stmt = stmt.where(Game.enabled.is_(True))
    return list((await session.execute(stmt)).scalars().all())


async def get_game(session: AsyncSession, game_id: str) -> Game | None:
    return (await session.execute(select(Game).where(Game.id == game_id))).scalars().first()


# -------------------------------------------------------------------- sessions
async def create_session(session: AsyncSession, **fields: object) -> GameSession:
    row = GameSession(**fields)  # type: ignore[arg-type]
    session.add(row)
    await session.flush()
    return row


async def get_session(
    session: AsyncSession, session_id: uuid.UUID, *, for_update: bool = False
) -> GameSession | None:
    """One session row, optionally locked for the rest of the transaction.

    A live match is a read-modify-write on a JSONB document, and two requests can
    arrive at once: a move and the retry of that same move, or a move and a
    reconnect. Without ``for_update`` the second one reads the document before
    the first has committed, decides the move is still needed, and writes it
    again — which either loses an update or breaches a unique constraint. The
    lock makes the second request wait and then see the truth.
    """
    statement = select(GameSession).where(GameSession.id == session_id)
    if for_update:
        statement = statement.with_for_update()
    return (await session.execute(statement)).scalars().first()


async def list_sessions_for_user(
    session: AsyncSession, user_id: uuid.UUID, *, limit: int = 20
) -> list[GameSession]:
    stmt = (
        select(GameSession)
        .join(GameParticipant, GameParticipant.session_id == GameSession.id)
        .where(GameParticipant.user_id == user_id)
        .order_by(GameSession.created_at.desc())
        .limit(limit)
    )
    return list((await session.execute(stmt)).scalars().all())


async def active_session_for_user(session: AsyncSession, user_id: uuid.UUID) -> GameSession | None:
    """The one session this learner may have open (D-26).

    Reads the same participant row the unique index guards, so the check and
    the constraint can never disagree. A challenge parent never matches: its
    participant rows carry ``counts_as_active = false`` (D-28).
    """
    stmt = (
        select(GameSession)
        .join(GameParticipant, GameParticipant.session_id == GameSession.id)
        .where(
            GameParticipant.user_id == user_id,
            GameParticipant.counts_as_active.is_(True),
            GameParticipant.attempt_status == "in_progress",
        )
        .order_by(GameParticipant.joined_at.desc())
        .limit(1)
    )
    return (await session.execute(stmt)).scalars().first()


async def set_session_status(
    session: AsyncSession,
    session_id: uuid.UUID,
    *,
    status: str,
    ended_at: dt.datetime | None = None,
) -> None:
    row = await get_session(session, session_id)
    if row is None:
        return
    row.status = status
    if ended_at is not None:
        row.ended_at = ended_at


# ---------------------------------------------------------------- participants
async def add_participant(session: AsyncSession, **fields: object) -> GameParticipant:
    row = GameParticipant(**fields)  # type: ignore[arg-type]
    session.add(row)
    await session.flush()
    return row


async def list_participants(session: AsyncSession, session_id: uuid.UUID) -> list[GameParticipant]:
    stmt = (
        select(GameParticipant)
        .where(GameParticipant.session_id == session_id)
        .order_by(GameParticipant.seat)
    )
    return list((await session.execute(stmt)).scalars().all())


async def set_attempt_status(
    session: AsyncSession, session_id: uuid.UUID, user_id: uuid.UUID, *, status: str
) -> None:
    """Move one player's attempt between states (Appendix A).

    Starting an attempt is the insert-shaped step: ``in_progress`` is what the
    D-26 index counts, so this raises ``IntegrityError`` if the learner already
    has an open play.
    """
    row = await session.get(GameParticipant, (session_id, user_id))
    if row is None:
        return
    row.attempt_status = status
    await session.flush()


# ----------------------------------------------------------------------- moves
async def append_move(session: AsyncSession, **fields: object) -> GameMove:
    """Insert one move. ``client_move_id`` makes a retry a no-op upstream."""
    row = GameMove(**fields)  # type: ignore[arg-type]
    session.add(row)
    await session.flush()
    return row


async def list_moves(session: AsyncSession, session_id: uuid.UUID) -> Sequence[GameMove]:
    stmt = select(GameMove).where(GameMove.session_id == session_id).order_by(GameMove.move_number)
    return (await session.execute(stmt)).scalars().all()


async def next_move_number(session: AsyncSession, session_id: uuid.UUID) -> int:
    current = (
        await session.execute(
            select(func.max(GameMove.move_number)).where(GameMove.session_id == session_id)
        )
    ).scalar_one_or_none()
    return int(current or 0) + 1


# --------------------------------------------------------------------- results
async def append_result(session: AsyncSession, **fields: object) -> GameResult:
    row = GameResult(**fields)  # type: ignore[arg-type]
    session.add(row)
    await session.flush()
    return row


async def live_result(
    session: AsyncSession, *, session_id: uuid.UUID, user_id: uuid.UUID
) -> GameResult | None:
    stmt = select(GameResult).where(
        GameResult.session_id == session_id,
        GameResult.user_id == user_id,
        GameResult.superseded_by.is_(None),
    )
    return (await session.execute(stmt)).scalars().first()


async def supersede_result(
    session: AsyncSession, *, old_result_id: uuid.UUID, new_result: GameResult
) -> None:
    """Retire the old row, then write its replacement.

    The order matters: the live-result index allows only one row with
    ``superseded_by IS NULL`` per player per session, so the old row must be
    retired first. The self-referencing foreign keys are deferrable, which is
    what lets the old row point at a row that is flushed a moment later — the
    whole swap is still one transaction.
    """
    old = (
        (await session.execute(select(GameResult).where(GameResult.id == old_result_id)))
        .scalars()
        .first()
    )
    if old is None:
        return

    if new_result.id is None:
        new_result.id = uuid.uuid4()
    old.superseded_by = new_result.id
    await session.flush()

    new_result.supersedes_id = old.id
    session.add(new_result)
    await session.flush()


# -------------------------------------------------------------------------- XP
async def append_xp(session: AsyncSession, **fields: object) -> GameXpEntry:
    row = GameXpEntry(**fields)  # type: ignore[arg-type]
    session.add(row)
    await session.flush()
    return row


async def xp_for_user_on_date(
    session: AsyncSession, *, user_id: uuid.UUID, local_date: dt.date
) -> int:
    total = (
        await session.execute(
            select(func.coalesce(func.sum(GameXpEntry.awarded_amount), 0)).where(
                GameXpEntry.user_id == user_id,
                GameXpEntry.local_date == local_date,
            )
        )
    ).scalar_one()
    return int(total)


# ------------------------------------------------------------- leaderboards
async def open_period(
    session: AsyncSession, *, school_id: uuid.UUID, period_type: str
) -> LeaderboardPeriod | None:
    stmt = (
        select(LeaderboardPeriod)
        .where(
            LeaderboardPeriod.school_id == school_id,
            LeaderboardPeriod.period_type == period_type,
            LeaderboardPeriod.status == "open",
        )
        .order_by(LeaderboardPeriod.starts_at.desc())
        .limit(1)
    )
    return (await session.execute(stmt)).scalars().first()


async def ensure_period(
    session: AsyncSession,
    *,
    school_id: uuid.UUID,
    period_type: str,
    starts_at: dt.datetime,
    ends_at: dt.datetime | None,
) -> LeaderboardPeriod:
    """The open period, or a new one. Two readers may race; the unique key wins.

    ``ON CONFLICT DO NOTHING`` then re-read: whichever transaction inserted the
    row first, both end up with the same period object.
    """
    existing = await open_period(session, school_id=school_id, period_type=period_type)
    if existing is not None:
        return existing

    stmt = (
        pg_insert(LeaderboardPeriod)
        .values(
            id=uuid.uuid4(),
            school_id=school_id,
            period_type=period_type,
            starts_at=starts_at,
            ends_at=ends_at,
            status="open",
        )
        .on_conflict_do_nothing(constraint="ux_periods_identity")
    )
    await session.execute(stmt)
    await session.flush()

    again = await open_period(session, school_id=school_id, period_type=period_type)
    if again is None:  # pragma: no cover - only if the row was closed between the two reads
        raise RuntimeError("leaderboard period could not be created")
    return again


async def add_to_entry(
    session: AsyncSession,
    *,
    period_id: uuid.UUID,
    school_id: uuid.UUID,
    user_id: uuid.UUID,
    game_id: str | None,
    class_id: uuid.UUID | None,
    age_band: str | None,
    xp: int,
    sessions: int,
    at: dt.datetime,
) -> None:
    """Add this award to one row, creating it if needed (P5-T07).

    The conflict target repeats the expression index from the migration, because
    ``game_id IS NULL`` is a real row (the all-games board) and a plain unique
    constraint would let it be inserted twice.
    """
    stmt = (
        pg_insert(LeaderboardEntry)
        .values(
            id=uuid.uuid4(),
            period_id=period_id,
            school_id=school_id,
            user_id=user_id,
            game_id=game_id,
            class_id=class_id,
            age_band=age_band,
            xp_total=xp,
            sessions_count=sessions,
            last_award_at=at,
        )
        .on_conflict_do_update(
            # Literal expressions, matching the index definition exactly: a bind
            # parameter inside COALESCE would not match the index expression and
            # Postgres would refuse the statement.
            index_elements=[
                text("period_id"),
                text("user_id"),
                text("COALESCE(game_id, '')"),
                text("COALESCE(class_id, '00000000-0000-0000-0000-000000000000'::uuid)"),
                text("COALESCE(age_band, '')"),
            ],
            set_={
                "xp_total": LeaderboardEntry.__table__.c.xp_total + xp,
                "sessions_count": LeaderboardEntry.__table__.c.sessions_count + sessions,
                "last_award_at": at,
                "updated_at": func.now(),
            },
        )
    )
    await session.execute(stmt)
    await session.flush()


async def first_award_at(session: AsyncSession, *, school_id: uuid.UUID) -> dt.datetime | None:
    """When the school's all-time board began: its first eligible award."""
    return (
        await session.execute(
            select(func.min(GameXpEntry.created_at)).where(
                GameXpEntry.school_id == school_id,
                GameXpEntry.leaderboard_eligible.is_(True),
                GameXpEntry.awarded_amount > 0,
            )
        )
    ).scalar_one_or_none()


async def ledger_rows_for_session(
    session: AsyncSession, *, session_id: uuid.UUID, user_id: uuid.UUID
) -> int:
    """How many awards this player already has from this session.

    Used to count ``sessions_count`` once per session rather than once per
    ledger row: a challenge can write two rows for one attempt (P5-T07).
    """
    if session_id is None:  # pragma: no cover - defensive
        return 0
    count = (
        await session.execute(
            select(func.count())
            .select_from(GameXpEntry)
            .where(
                GameXpEntry.session_id == session_id,
                GameXpEntry.user_id == user_id,
            )
        )
    ).scalar_one()
    return int(count)


def _totals_query(
    *, period_id: uuid.UUID, game_id: str | None, class_id: uuid.UUID | None, age_band: str | None
) -> Any:
    """Sum one row set into one total per learner (D-33).

    A caller either asks for one game (``game_id = x``) or for all games
    (``game_id IS NULL``) — never both, because the two row sets overlap.
    """
    stmt = (
        select(
            LeaderboardEntry.user_id.label("user_id"),
            func.sum(LeaderboardEntry.xp_total).label("xp_total"),
            func.sum(LeaderboardEntry.sessions_count).label("sessions_count"),
            func.max(LeaderboardEntry.last_award_at).label("last_award_at"),
        )
        .where(LeaderboardEntry.period_id == period_id)
        .group_by(LeaderboardEntry.user_id)
    )
    if game_id is None:
        stmt = stmt.where(LeaderboardEntry.game_id.is_(None))
    else:
        stmt = stmt.where(LeaderboardEntry.game_id == game_id)
    if class_id is not None:
        stmt = stmt.where(LeaderboardEntry.class_id == class_id)
    if age_band is not None:
        stmt = stmt.where(LeaderboardEntry.age_band == age_band)
    return stmt


async def board_rows(
    session: AsyncSession,
    *,
    period_id: uuid.UUID,
    game_id: str | None,
    class_id: uuid.UUID | None,
    age_band: str | None,
    min_sessions: int,
    limit: int,
) -> list[Any]:
    """The ranked board, top ``limit`` only, below-minimum rows excluded.

    Ranking happens in the database, after the D-14 minimum is applied: a
    learner with two sessions must not hold a rank that a hidden row would
    otherwise have taken.
    """
    totals = _totals_query(
        period_id=period_id, game_id=game_id, class_id=class_id, age_band=age_band
    )
    totals = totals.having(func.sum(LeaderboardEntry.sessions_count) >= min_sessions).subquery()

    ranked = select(
        totals.c.user_id,
        totals.c.xp_total,
        totals.c.sessions_count,
        totals.c.last_award_at,
        func.row_number()
        .over(
            order_by=(
                totals.c.xp_total.desc(),
                totals.c.last_award_at.asc().nulls_last(),
                totals.c.user_id,
            )
        )
        .label("rank"),
    ).subquery()

    stmt = (
        select(
            ranked.c.user_id,
            ranked.c.xp_total,
            ranked.c.sessions_count,
            ranked.c.rank,
            User.preferred_name,
            User.avatar_key,
        )
        .join(User, User.id == ranked.c.user_id)
        .where(ranked.c.rank <= limit)
        .order_by(ranked.c.rank)
    )
    return list((await session.execute(stmt)).all())


async def user_rank(
    session: AsyncSession,
    *,
    period_id: uuid.UUID,
    game_id: str | None,
    class_id: uuid.UUID | None,
    age_band: str | None,
    min_sessions: int,
    user_id: uuid.UUID,
) -> int | None:
    """This learner's true rank, including when it is outside the top ten."""
    totals = _totals_query(
        period_id=period_id, game_id=game_id, class_id=class_id, age_band=age_band
    )
    totals = totals.having(func.sum(LeaderboardEntry.sessions_count) >= min_sessions).subquery()
    ranked = select(
        totals.c.user_id,
        func.row_number()
        .over(
            order_by=(
                totals.c.xp_total.desc(),
                totals.c.last_award_at.asc().nulls_last(),
                totals.c.user_id,
            )
        )
        .label("rank"),
    ).subquery()
    value = (
        await session.execute(select(ranked.c.rank).where(ranked.c.user_id == user_id))
    ).scalar_one_or_none()
    return None if value is None else int(value)


async def ranked_row(
    session: AsyncSession,
    *,
    period_id: uuid.UUID,
    game_id: str | None,
    class_id: uuid.UUID | None,
    age_band: str | None,
    min_sessions: int,
    rank: int,
) -> Any:
    """One row by its rank, using the same ordering the board used.

    The near-miss line asks for the row *above* the caller; computing it from
    the same window keeps the gap honest even when two learners are tied.
    """
    totals = _totals_query(
        period_id=period_id, game_id=game_id, class_id=class_id, age_band=age_band
    )
    totals = totals.having(func.sum(LeaderboardEntry.sessions_count) >= min_sessions).subquery()
    ranked = select(
        totals.c.user_id,
        totals.c.xp_total,
        func.row_number()
        .over(
            order_by=(
                totals.c.xp_total.desc(),
                totals.c.last_award_at.asc().nulls_last(),
                totals.c.user_id,
            )
        )
        .label("rank"),
    ).subquery()
    return (
        await session.execute(
            select(
                ranked.c.user_id,
                ranked.c.xp_total,
                ranked.c.rank,
                User.preferred_name,
            )
            .join(User, User.id == ranked.c.user_id)
            .where(ranked.c.rank == rank)
        )
    ).first()


async def user_board_total(
    session: AsyncSession,
    *,
    period_id: uuid.UUID,
    game_id: str | None,
    class_id: uuid.UUID | None,
    age_band: str | None,
    user_id: uuid.UUID,
) -> Any:
    """One learner's row in the same row set the board used."""
    totals = _totals_query(
        period_id=period_id, game_id=game_id, class_id=class_id, age_band=age_band
    )
    totals = totals.where(LeaderboardEntry.user_id == user_id).subquery()
    return (await session.execute(select(totals))).first()


async def total_game_xp(session: AsyncSession, *, user_id: uuid.UUID) -> int:
    total = (
        await session.execute(
            select(func.coalesce(func.sum(GameXpEntry.awarded_amount), 0)).where(
                GameXpEntry.user_id == user_id
            )
        )
    ).scalar_one()
    return int(total)


# ------------------------------------------------------------------ reconcile
async def all_open_periods(session: AsyncSession) -> list[LeaderboardPeriod]:
    """Every board that is still collecting awards, across all schools."""
    stmt = select(LeaderboardPeriod).where(LeaderboardPeriod.status == "open")
    return list((await session.execute(stmt)).scalars().all())


async def flagged_session_ids(session: AsyncSession, *, school_id: uuid.UUID) -> list[uuid.UUID]:
    """Sessions a fair-play flag keeps off this school's boards (P5-T04, P10-T02).

    A ``cleared`` flag has been reviewed and dismissed, so its session counts
    again. Everything else — open, under review, or actioned — stays off until
    someone clears it.
    """
    stmt = (
        select(FairplayFlag.session_id)
        .join(GameSession, GameSession.id == FairplayFlag.session_id)
        .where(
            GameSession.school_id == school_id,
            FairplayFlag.session_id.is_not(None),
            FairplayFlag.status != "cleared",
        )
    )
    return [row for row in (await session.execute(stmt)).scalars().all() if row is not None]


def _eligible_ledger(
    *,
    school_id: uuid.UUID,
    starts_at: dt.datetime,
    ends_at: dt.datetime | None,
    flagged: Sequence[uuid.UUID],
) -> Any:
    """The ledger rows a board may count: eligible, paid, in window, unflagged."""
    stmt = select(GameXpEntry).where(
        GameXpEntry.school_id == school_id,
        GameXpEntry.leaderboard_eligible.is_(True),
        GameXpEntry.awarded_amount > 0,
        GameXpEntry.created_at >= starts_at,
    )
    if ends_at is not None:
        stmt = stmt.where(GameXpEntry.created_at < ends_at)
    if flagged:
        # A NULL session_id on the ledger row cannot be flagged by session.
        stmt = stmt.where(
            or_(GameXpEntry.session_id.is_(None), GameXpEntry.session_id.not_in(flagged))
        )
    return stmt.subquery()


async def ledger_totals(
    session: AsyncSession,
    *,
    school_id: uuid.UUID,
    starts_at: dt.datetime,
    ends_at: dt.datetime | None,
    flagged: Sequence[uuid.UUID],
) -> list[Any]:
    """Expected per-game rows for one period, straight from the ledger (P5-T07).

    ``sessions`` counts distinct sessions, not rows: a challenge writes two
    ledger rows for one attempt and must still count as one game.
    """
    rows = _eligible_ledger(
        school_id=school_id, starts_at=starts_at, ends_at=ends_at, flagged=flagged
    )
    stmt = select(
        rows.c.user_id,
        rows.c.game_id,
        rows.c.class_id_snapshot,
        rows.c.age_band_snapshot,
        func.sum(rows.c.awarded_amount).label("xp_total"),
        func.count(func.distinct(rows.c.session_id)).label("sessions_count"),
        func.max(rows.c.created_at).label("last_award_at"),
    ).group_by(
        rows.c.user_id,
        rows.c.game_id,
        rows.c.class_id_snapshot,
        rows.c.age_band_snapshot,
    )
    return list((await session.execute(stmt)).all())


async def ledger_totals_all_games(
    session: AsyncSession,
    *,
    school_id: uuid.UUID,
    starts_at: dt.datetime,
    ends_at: dt.datetime | None,
    flagged: Sequence[uuid.UUID],
) -> list[Any]:
    """Expected ``game_id IS NULL`` rows: the same awards, summed across games."""
    rows = _eligible_ledger(
        school_id=school_id, starts_at=starts_at, ends_at=ends_at, flagged=flagged
    )
    stmt = select(
        rows.c.user_id,
        rows.c.class_id_snapshot,
        rows.c.age_band_snapshot,
        func.sum(rows.c.awarded_amount).label("xp_total"),
        func.count(func.distinct(rows.c.session_id)).label("sessions_count"),
        func.max(rows.c.created_at).label("last_award_at"),
    ).group_by(rows.c.user_id, rows.c.class_id_snapshot, rows.c.age_band_snapshot)
    return list((await session.execute(stmt)).all())


async def period_entries(session: AsyncSession, *, period_id: uuid.UUID) -> list[LeaderboardEntry]:
    stmt = select(LeaderboardEntry).where(LeaderboardEntry.period_id == period_id)
    return list((await session.execute(stmt)).scalars().all())


async def per_game_entries(
    session: AsyncSession,
    *,
    period_id: uuid.UUID,
    class_ids: Sequence[uuid.UUID],
    age_band: str | None,
    user_ids: Sequence[uuid.UUID],
) -> list[Any]:
    """The per-game breakdown for a set of learners (P5-T11).

    Reads the ``game_id = <game>`` rows only: summing those together with the
    all-games row would double every total (D-33).
    """
    stmt = (
        select(
            LeaderboardEntry.user_id,
            LeaderboardEntry.game_id,
            func.sum(LeaderboardEntry.xp_total).label("xp_total"),
            func.sum(LeaderboardEntry.sessions_count).label("sessions_count"),
        )
        .where(
            LeaderboardEntry.period_id == period_id,
            LeaderboardEntry.game_id.is_not(None),
            LeaderboardEntry.user_id.in_(user_ids),
        )
        .group_by(LeaderboardEntry.user_id, LeaderboardEntry.game_id)
    )
    if class_ids:
        stmt = stmt.where(LeaderboardEntry.class_id.in_(class_ids))
    if age_band is not None:
        stmt = stmt.where(LeaderboardEntry.age_band == age_band)
    return list((await session.execute(stmt)).all())


# --------------------------------------------------------------------- settings
async def get_platform_setting(session: AsyncSession, key: str) -> Any:
    row = (
        (await session.execute(select(PlatformSetting).where(PlatformSetting.key == key)))
        .scalars()
        .first()
    )
    return None if row is None else row.value


# --------------------------------------------------------------------- access
async def list_policies(
    session: AsyncSession, *, scope_types: Sequence[str] | None = None
) -> list[AccessPolicy]:
    stmt = select(AccessPolicy).order_by(AccessPolicy.valid_from.desc())
    if scope_types is not None:
        stmt = stmt.where(AccessPolicy.scope_type.in_(scope_types))
    return list((await session.execute(stmt)).scalars().all())


async def candidate_policies(
    session: AsyncSession,
    *,
    user_id: uuid.UUID,
    school_id: uuid.UUID,
    class_ids: Sequence[uuid.UUID],
    at: dt.datetime,
) -> list[AccessPolicy]:
    """Every policy that could apply to this learner right now (P3-T02).

    Deliberately unfiltered by specificity: the winner is chosen by the pure
    resolver, so precedence lives in one place instead of in SQL.
    """
    stmt = select(AccessPolicy).where(
        AccessPolicy.valid_from <= at,
        or_(AccessPolicy.valid_until.is_(None), AccessPolicy.valid_until > at),
        or_(
            AccessPolicy.scope_type == "platform",
            and_(AccessPolicy.scope_type == "school", AccessPolicy.scope_id == school_id),
            and_(AccessPolicy.scope_type == "class", AccessPolicy.scope_id.in_(class_ids)),
            and_(AccessPolicy.scope_type == "student", AccessPolicy.scope_id == user_id),
        ),
    )
    return list((await session.execute(stmt)).scalars().all())


async def create_policy(session: AsyncSession, **fields: object) -> AccessPolicy:
    row = AccessPolicy(**fields)  # type: ignore[arg-type]
    session.add(row)
    await session.flush()
    return row


async def list_lockouts(
    session: AsyncSession, *, include_revoked: bool = False
) -> list[GameLockout]:
    stmt = select(GameLockout).order_by(GameLockout.created_at.desc())
    if not include_revoked:
        stmt = stmt.where(GameLockout.revoked_at.is_(None))
    return list((await session.execute(stmt)).scalars().all())


async def lockouts_for(
    session: AsyncSession,
    *,
    user_id: uuid.UUID,
    class_ids: Sequence[uuid.UUID],
    at: dt.datetime,
) -> list[GameLockout]:
    """Live lockouts covering this learner: their own, or any of their classes."""
    stmt = select(GameLockout).where(
        GameLockout.revoked_at.is_(None),
        GameLockout.starts_at <= at,
        GameLockout.expires_at > at,
        or_(
            and_(GameLockout.scope_type == "student", GameLockout.scope_id == user_id),
            and_(GameLockout.scope_type == "class", GameLockout.scope_id.in_(class_ids)),
        ),
    )
    return list((await session.execute(stmt)).scalars().all())


async def get_lockout(session: AsyncSession, lockout_id: uuid.UUID) -> GameLockout | None:
    return (
        (await session.execute(select(GameLockout).where(GameLockout.id == lockout_id)))
        .scalars()
        .first()
    )


async def create_lockout(session: AsyncSession, **fields: object) -> GameLockout:
    row = GameLockout(**fields)  # type: ignore[arg-type]
    session.add(row)
    await session.flush()
    return row


# ---------------------------------------------------------------------- clock
async def ensure_play_clock(
    session: AsyncSession, *, user_id: uuid.UUID, local_date: dt.date, now: dt.datetime
) -> None:
    """Insert the day's clock row if it is missing, then let the caller lock it.

    Insert-then-lock (P3-T05) is what makes two simultaneous first actions of
    the day safe: the insert cannot collide (ON CONFLICT DO NOTHING), so the
    following ``FOR UPDATE`` always finds exactly one row to serialise on.
    """
    await session.execute(
        pg_insert(GamePlayClock)
        .values(user_id=user_id, local_date=local_date, last_counted_at=now)
        .on_conflict_do_nothing(index_elements=["user_id", "local_date"])
    )


async def lock_play_clock(
    session: AsyncSession, *, user_id: uuid.UUID, local_date: dt.date
) -> GamePlayClock | None:
    stmt = (
        select(GamePlayClock)
        .where(GamePlayClock.user_id == user_id, GamePlayClock.local_date == local_date)
        .with_for_update()
    )
    return (await session.execute(stmt)).scalars().first()


async def add_usage(
    session: AsyncSession,
    *,
    user_id: uuid.UUID,
    local_date: dt.date,
    source: str,
    seconds: int,
) -> None:
    if seconds <= 0:
        return
    stmt = pg_insert(GameTimeUsage).values(
        user_id=user_id,
        local_date=local_date,
        source=source,
        active_seconds=seconds,
        updated_at=dt.datetime.now(dt.UTC),
    )
    stmt = stmt.on_conflict_do_update(
        index_elements=["user_id", "local_date", "source"],
        set_={
            "active_seconds": GameTimeUsage.__table__.c.active_seconds
            + stmt.excluded.active_seconds,
            "updated_at": dt.datetime.now(dt.UTC),
        },
    )
    await session.execute(stmt)


async def used_seconds(session: AsyncSession, *, user_id: uuid.UUID, local_date: dt.date) -> int:
    stmt = select(func.coalesce(func.sum(GameTimeUsage.active_seconds), 0)).where(
        GameTimeUsage.user_id == user_id, GameTimeUsage.local_date == local_date
    )
    return int((await session.execute(stmt)).scalar_one())


# ---------------------------------------------------------------------- audit
async def blocked_words(session: AsyncSession) -> list[BlockedWord]:
    """The words a school admin has added, newest first."""
    stmt = select(BlockedWord).order_by(BlockedWord.created_at.desc(), BlockedWord.word)
    return list((await session.execute(stmt)).scalars().all())


async def blocked_word_values(session: AsyncSession) -> frozenset[str]:
    """Just the words, for the validator: one small query per operation."""
    stmt = select(BlockedWord.word)
    return frozenset((await session.execute(stmt)).scalars().all())


async def add_blocked_word(session: AsyncSession, *, word: str, actor_id: uuid.UUID) -> BlockedWord:
    row = BlockedWord(word=word, added_by=actor_id)
    session.add(row)
    await session.flush()
    return row


async def get_blocked_word(session: AsyncSession, word: str) -> BlockedWord | None:
    return await session.get(BlockedWord, word)


async def delete_blocked_word(session: AsyncSession, word: str) -> None:
    row = await session.get(BlockedWord, word)
    if row is not None:
        await session.delete(row)
        await session.flush()


async def audit(
    session: AsyncSession,
    *,
    actor_id: uuid.UUID | None,
    action: str,
    target_type: str | None,
    target_id: str | None,
    details: dict[str, object] | None = None,
) -> None:
    session.add(
        AuditEntry(
            actor_id=actor_id,
            action=action,
            target_type=target_type,
            target_id=target_id,
            details=details or {},
        )
    )
    await session.flush()


# ------------------------------------------------------------------ sessions
async def get_participant(
    session: AsyncSession, session_id: uuid.UUID, user_id: uuid.UUID
) -> GameParticipant | None:
    return await session.get(GameParticipant, (session_id, user_id))


# -------------------------------------------------------------------- content
async def list_content_packs(session: AsyncSession, *, game_id: str) -> list[ContentPack]:
    """Every version, newest first — the workflow view, not the play view."""
    stmt = (
        select(ContentPack)
        .where(ContentPack.game_id == game_id)
        .order_by(ContentPack.age_band, ContentPack.version.desc())
    )
    return list((await session.execute(stmt)).scalars().all())


async def next_content_version(
    session: AsyncSession, *, game_id: str, locale: str, age_band: str
) -> int:
    stmt = select(func.max(ContentPack.version)).where(
        ContentPack.game_id == game_id,
        ContentPack.locale == locale,
        ContentPack.age_band == age_band,
    )
    current = (await session.execute(stmt)).scalar_one_or_none()
    return int(current or 0) + 1


async def create_content_pack(session: AsyncSession, **fields: object) -> ContentPack:
    row = ContentPack(**fields)  # type: ignore[arg-type]
    session.add(row)
    await session.flush()
    return row


async def add_content_item(
    session: AsyncSession,
    *,
    pack_id: uuid.UUID,
    payload: dict[str, object],
    difficulty: int,
    sort_order: int = 0,
) -> ContentItem:
    row = ContentItem(
        pack_id=pack_id, payload=payload, difficulty=difficulty, sort_order=sort_order
    )
    session.add(row)
    await session.flush()
    return row


async def count_content_items(session: AsyncSession, pack_id: uuid.UUID) -> int:
    stmt = select(func.count()).select_from(ContentItem).where(ContentItem.pack_id == pack_id)
    return int((await session.execute(stmt)).scalar_one())


async def content_answers(session: AsyncSession, pack_id: uuid.UUID) -> set[str]:
    """Lowercased answers already in the pack, for duplicate checks."""
    rows = await pack_items(session, pack_id)
    return {str(row.payload.get("answer", "")).strip().lower() for row in rows}


async def content_answer_exists(session: AsyncSession, *, pack_id: uuid.UUID, answer: str) -> bool:
    return answer.strip().lower() in await content_answers(session, pack_id)


async def live_content_answers(
    session: AsyncSession, *, game_id: str, locale: str, age_band: str
) -> set[str]:
    """Answers already in play for one band, so a word cannot go live twice."""
    rows = await live_items(session, game_id=game_id, locale=locale, age_band=age_band)
    return {str(row.payload.get("answer", "")).strip().lower() for row in rows}


async def content_answer_is_live(
    session: AsyncSession,
    *,
    game_id: str,
    locale: str,
    age_band: str,
    answer: str,
    exclude_item: uuid.UUID | None = None,
) -> bool:
    rows = await live_items(session, game_id=game_id, locale=locale, age_band=age_band)
    wanted = answer.strip().lower()
    return any(
        str(row.payload.get("answer", "")).strip().lower() == wanted
        and (exclude_item is None or row.id != exclude_item)
        for row in rows
    )


async def copy_content_items(
    session: AsyncSession, *, from_pack: uuid.UUID, to_pack: uuid.UUID
) -> int:
    """Copy every word into a fresh draft, preserving order and level."""
    source = await pack_items(session, from_pack)
    for index, row in enumerate(source):
        session.add(
            ContentItem(
                pack_id=to_pack,
                payload=dict(row.payload),
                difficulty=row.difficulty,
                sort_order=index,
            )
        )
    await session.flush()
    return len(source)


async def retire_published_packs(
    session: AsyncSession,
    *,
    game_id: str,
    locale: str,
    age_band: str,
    keep: uuid.UUID,
) -> int:
    """One served version per (game, locale, band): retire the rest."""
    stmt = select(ContentPack).where(
        ContentPack.game_id == game_id,
        ContentPack.locale == locale,
        ContentPack.age_band == age_band,
        ContentPack.status == "published",
        ContentPack.id != keep,
    )
    rows = list((await session.execute(stmt)).scalars().all())
    for row in rows:
        row.status = "retired"
    await session.flush()
    return len(rows)


def utcnow() -> dt.datetime:
    return dt.datetime.now(dt.UTC)


async def serving_pack(
    session: AsyncSession, *, game_id: str, locale: str, age_band: str
) -> ContentPack | None:
    """The newest pack of this band that has not been retired.

    Not a gate any more (D-38): a word is playable because the **word** is
    live, not because its bucket is. This only gives the session a pack to
    point at, so a result can be traced back to the words it was built from.
    """
    stmt = (
        select(ContentPack)
        .where(
            ContentPack.game_id == game_id,
            ContentPack.locale == locale,
            ContentPack.age_band == age_band,
            ContentPack.status != "retired",
        )
        .order_by(ContentPack.version.desc())
        .limit(1)
    )
    return (await session.execute(stmt)).scalars().first()


async def live_items(
    session: AsyncSession, *, game_id: str, locale: str, age_band: str
) -> list[ContentItem]:
    """Every word a learner of this band may be given right now.

    One word cannot appear twice even if two packs hold it: the answer is the
    identity of a round, so the oldest live copy wins and the rest are dropped.
    """
    stmt = (
        select(ContentItem)
        .join(ContentPack, ContentPack.id == ContentItem.pack_id)
        .where(
            ContentPack.game_id == game_id,
            ContentPack.locale == locale,
            ContentPack.age_band == age_band,
            ContentPack.status != "retired",
            ContentItem.status == "live",
        )
        .order_by(ContentItem.created_at, ContentItem.sort_order)
    )
    seen: set[str] = set()
    out: list[ContentItem] = []
    for row in (await session.execute(stmt)).scalars().all():
        answer = str(row.payload.get("answer", "")).strip().lower()
        if answer in seen:
            continue
        seen.add(answer)
        out.append(row)
    return out


async def pack_items(session: AsyncSession, pack_id: uuid.UUID) -> list[ContentItem]:
    stmt = (
        select(ContentItem).where(ContentItem.pack_id == pack_id).order_by(ContentItem.sort_order)
    )
    return list((await session.execute(stmt)).scalars().all())


async def items_by_id(
    session: AsyncSession, item_ids: Sequence[uuid.UUID]
) -> dict[uuid.UUID, ContentItem]:
    if not item_ids:
        return {}
    stmt = select(ContentItem).where(ContentItem.id.in_(item_ids))
    return {row.id: row for row in (await session.execute(stmt)).scalars().all()}


# --------------------------------------------------------------------- moves
async def move_by_client_id(
    session: AsyncSession, *, session_id: uuid.UUID, client_move_id: str
) -> GameMove | None:
    stmt = select(GameMove).where(
        GameMove.session_id == session_id, GameMove.client_move_id == client_move_id
    )
    return (await session.execute(stmt)).scalars().first()


# ---------------------------------------------------------------- invitations
async def create_invitation(session: AsyncSession, **fields: object) -> GameInvitation:
    row = GameInvitation(**fields)  # type: ignore[arg-type]
    session.add(row)
    await session.flush()
    return row


async def get_invitation(session: AsyncSession, invitation_id: uuid.UUID) -> GameInvitation | None:
    return (
        (await session.execute(select(GameInvitation).where(GameInvitation.id == invitation_id)))
        .scalars()
        .first()
    )


async def invitation_by_code_hash(
    session: AsyncSession, *, code_hash: str
) -> GameInvitation | None:
    return (
        (await session.execute(select(GameInvitation).where(GameInvitation.code_hash == code_hash)))
        .scalars()
        .first()
    )


async def invitation_by_token_hash(
    session: AsyncSession, *, token_hash: str
) -> GameInvitation | None:
    return (
        (
            await session.execute(
                select(GameInvitation).where(GameInvitation.token_hash == token_hash)
            )
        )
        .scalars()
        .first()
    )


async def invitations_for_invitee(
    session: AsyncSession, *, user_id: uuid.UUID, now: dt.datetime
) -> list[GameInvitation]:
    """Pending invitations addressed to this learner (a roster tap, not a code)."""
    stmt = (
        select(GameInvitation)
        .where(
            GameInvitation.invitee_id == user_id,
            GameInvitation.status == "pending",
            GameInvitation.expires_at > now,
        )
        .order_by(GameInvitation.created_at.desc())
    )
    return list((await session.execute(stmt)).scalars().all())


async def invitations_for_session(
    session: AsyncSession, *, session_id: uuid.UUID
) -> list[GameInvitation]:
    stmt = select(GameInvitation).where(GameInvitation.session_id == session_id)
    return list((await session.execute(stmt)).scalars().all())


async def accept_invitation(
    session: AsyncSession,
    *,
    invitation_id: uuid.UUID,
    user_id: uuid.UUID,
    now: dt.datetime,
) -> bool:
    """Claim a pending invitation in one statement (P7-T03).

    ``WHERE status = 'pending' AND expires_at > now`` is what makes two learners
    racing for one seat safe: the row lock inside the UPDATE decides, and exactly
    one caller sees a returned id.
    """
    stmt = (
        update(GameInvitation)
        .where(
            GameInvitation.id == invitation_id,
            GameInvitation.status == "pending",
            GameInvitation.expires_at > now,
        )
        .values(status="accepted", redeemed_by=user_id, redeemed_at=now)
        .returning(GameInvitation.id)
    )
    return (await session.execute(stmt)).first() is not None


async def set_invitation_status(
    session: AsyncSession, *, invitation_id: uuid.UUID, status: str
) -> None:
    await session.execute(
        update(GameInvitation).where(GameInvitation.id == invitation_id).values(status=status)
    )


async def expire_overdue_invitations(session: AsyncSession, *, now: dt.datetime) -> int:
    result = await session.execute(
        update(GameInvitation)
        .where(GameInvitation.status == "pending", GameInvitation.expires_at <= now)
        .values(status="expired")
    )
    return int(result.rowcount or 0)  # type: ignore[attr-defined]


# ------------------------------------------------------------- notifications
async def add_notification(session: AsyncSession, **fields: object) -> GameNotification:
    row = GameNotification(**fields)  # type: ignore[arg-type]
    session.add(row)
    await session.flush()
    return row


async def notifications_for(
    session: AsyncSession, *, user_id: uuid.UUID, limit: int = 20
) -> list[GameNotification]:
    stmt = (
        select(GameNotification)
        .where(GameNotification.user_id == user_id)
        .order_by(GameNotification.created_at.desc())
        .limit(limit)
    )
    return list((await session.execute(stmt)).scalars().all())


async def unread_notifications(session: AsyncSession, *, user_id: uuid.UUID) -> int:
    stmt = (
        select(func.count())
        .select_from(GameNotification)
        .where(GameNotification.user_id == user_id, GameNotification.read_at.is_(None))
    )
    return int((await session.execute(stmt)).scalar_one())


async def mark_notifications_read(
    session: AsyncSession, *, user_id: uuid.UUID, now: dt.datetime
) -> int:
    result = await session.execute(
        update(GameNotification)
        .where(GameNotification.user_id == user_id, GameNotification.read_at.is_(None))
        .values(read_at=now)
    )
    return int(result.rowcount or 0)  # type: ignore[attr-defined]


# ------------------------------------------------------------------- blocking
async def block_exists_between(session: AsyncSession, *, a: uuid.UUID, b: uuid.UUID) -> bool:
    """True when either side blocked the other (P7-T08).

    Checked in both directions on purpose: a block stops invites both ways, so
    the blocked learner cannot invite the blocker either.
    """
    stmt = (
        select(func.count())
        .select_from(GameBlock)
        .where(
            GameBlock.type == "block",
            or_(
                and_(GameBlock.blocker_id == a, GameBlock.blocked_id == b),
                and_(GameBlock.blocker_id == b, GameBlock.blocked_id == a),
            ),
        )
    )
    return int((await session.execute(stmt)).scalar_one()) > 0


async def blocked_user_ids(session: AsyncSession, *, user_id: uuid.UUID) -> set[uuid.UUID]:
    """Ids this learner blocked, in either direction.

    A block removes both people from each other's roster, not just the blocker's
    (P7-T08) — otherwise the blocked learner keeps inviting into silence.
    """
    stmt = select(GameBlock.blocked_id).where(GameBlock.blocker_id == user_id)
    forward = {row for row in (await session.execute(stmt)).scalars().all()}
    back_stmt = select(GameBlock.blocker_id).where(GameBlock.blocked_id == user_id)
    return forward | {row for row in (await session.execute(back_stmt)).scalars().all()}


async def add_block(
    session: AsyncSession, *, blocker_id: uuid.UUID, blocked_id: uuid.UUID, type_: str
) -> None:
    session.add(GameBlock(blocker_id=blocker_id, blocked_id=blocked_id, type=type_))
    await session.flush()


async def remove_block(
    session: AsyncSession, *, blocker_id: uuid.UUID, blocked_id: uuid.UUID
) -> None:
    from sqlalchemy import delete

    await session.execute(
        delete(GameBlock).where(
            GameBlock.blocker_id == blocker_id, GameBlock.blocked_id == blocked_id
        )
    )


# --------------------------------------------------------------------- roster
async def classmates(
    session: AsyncSession, *, user_id: uuid.UUID, school_id: uuid.UUID, limit: int = 30
) -> list[User]:
    """Learners in the same class as this one (P7-T06: avatars come first)."""
    my_classes = select(ClassMember.class_id).where(ClassMember.user_id == user_id)
    stmt = (
        select(User)
        .join(ClassMember, ClassMember.user_id == User.id)
        .where(
            ClassMember.class_id.in_(my_classes),
            User.id != user_id,
            User.school_id == school_id,
            User.role == Role.learner,
            User.status == UserStatus.active,
        )
        .distinct()
        .order_by(User.preferred_name)
        .limit(limit)
    )
    return list((await session.execute(stmt)).scalars().all())


# -------------------------------------------------------------------- reports
async def add_report(session: AsyncSession, **fields: object) -> GameReport:
    row = GameReport(**fields)  # type: ignore[arg-type]
    session.add(row)
    await session.flush()
    return row


async def reports_for_school(
    session: AsyncSession, *, school_id: uuid.UUID, status: str = "open"
) -> list[GameReport]:
    """Reports about learners of one school, for the admin's minimum list."""
    reported = select(User.id).where(User.school_id == school_id)
    stmt = (
        select(GameReport)
        .where(GameReport.reported_id.in_(reported), GameReport.status == status)
        .order_by(GameReport.created_at.desc())
        .limit(50)
    )
    return list((await session.execute(stmt)).scalars().all())


# ------------------------------------------------------- challenge pair counts
async def pair_count(
    session: AsyncSession, *, user_id: uuid.UUID, other_user_id: uuid.UUID, local_date: dt.date
) -> int:
    """How many challenges this pair has played today, one direction.

    Stored one way only: the service always orders the two ids, so a pair has
    one row per day rather than two rows that could disagree.
    """
    stmt = select(GamePairDailyCount.count).where(
        GamePairDailyCount.user_id == user_id,
        GamePairDailyCount.other_user_id == other_user_id,
        GamePairDailyCount.local_date == local_date,
    )
    return int((await session.execute(stmt)).scalars().first() or 0)


async def bump_pair_count(
    session: AsyncSession, *, user_id: uuid.UUID, other_user_id: uuid.UUID, local_date: dt.date
) -> int:
    """Insert-or-increment one pair's count for the day (P7-T05)."""
    stmt = (
        pg_insert(GamePairDailyCount)
        .values(
            user_id=user_id,
            other_user_id=other_user_id,
            local_date=local_date,
            count=1,
        )
        .on_conflict_do_update(
            index_elements=["user_id", "other_user_id", "local_date"],
            set_={"count": GamePairDailyCount.count + 1},
        )
        .returning(GamePairDailyCount.count)
    )
    return int((await session.execute(stmt)).scalar_one())


# --------------------------------------------------------------- challenges
async def child_sessions(session: AsyncSession, *, parent_id: uuid.UUID) -> list[GameSession]:
    """The two attempts of one challenge (D-28). Never returns the parent."""
    stmt = (
        select(GameSession)
        .where(GameSession.parent_session_id == parent_id)
        .order_by(GameSession.created_at)
    )
    return list((await session.execute(stmt)).scalars().all())


async def open_challenges(session: AsyncSession) -> list[GameSession]:
    """Challenge parents that have not settled yet, for the sweep (P7-T10)."""
    stmt = select(GameSession).where(
        GameSession.mode == "challenge",
        GameSession.status.in_(("created", "active", "paused")),
    )
    return list((await session.execute(stmt)).scalars().all())


async def live_invitation_result(
    session: AsyncSession, *, invitation_id: uuid.UUID
) -> GameInvitation | None:
    return (
        (await session.execute(select(GameInvitation).where(GameInvitation.id == invitation_id)))
        .scalars()
        .first()
    )


async def open_challenge_children(
    session: AsyncSession, *, user_id: uuid.UUID
) -> list[GameSession]:
    """Challenge attempts this learner still owes a turn (P7-T06).

    Without this list the inviter's own attempt is only reachable from the sheet
    that created it: reload the page and the challenge is lost. A learner's turn
    has to be findable later, so it is asked for directly.
    """
    stmt = (
        select(GameSession)
        .join(GameParticipant, GameParticipant.session_id == GameSession.id)
        .where(
            GameParticipant.user_id == user_id,
            GameParticipant.counts_as_active.is_(True),
            GameSession.parent_session_id.is_not(None),
            GameSession.status.in_(("created", "active", "paused")),
        )
        .order_by(GameSession.created_at)
    )
    return list((await session.execute(stmt)).scalars().all())


# ------------------------------------------------------------- live matches
async def live_matches(session: AsyncSession) -> list[GameSession]:
    """Matches that could still end: the sweeper's worklist (P8-T11)."""
    stmt = (
        select(GameSession)
        .where(
            GameSession.mode == "live",
            GameSession.status.in_(("created", "ready", "active")),
        )
        .order_by(GameSession.created_at)
    )
    return list((await session.execute(stmt)).scalars().all())


async def invitation_for_session(
    session: AsyncSession, *, session_id: uuid.UUID
) -> GameInvitation | None:
    """The newest invitation for one session, used for invite age-out."""
    stmt = (
        select(GameInvitation)
        .where(GameInvitation.session_id == session_id)
        .order_by(GameInvitation.created_at.desc())
        .limit(1)
    )
    return (await session.execute(stmt)).scalars().first()
