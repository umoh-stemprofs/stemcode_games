"""Streaks, badges, the daily quest and personal bests.

The three things that bring a learner back — *don't break the run*, *finish
today's quest*, *collect the badge* — are decided here, on the server, from
results the server already wrote. Nothing in this module trusts a number from a
browser, and nothing here reads Game XP to decide a badge (P5-T05).

Where each piece lives:

- **Streak** — one row per learner (``learner_streaks``), advanced by the first
  finished game of a school-local day.
- **Quest** — one row per learner per day (``learner_daily_quests``). Completing
  it pays a small capped bonus through ``services/xp``; the row is the receipt.
- **Badges** — definitions in ``domain/badges.py``, earned facts in
  ``learner_badges``. Awarded when a game ends *and* lazily on read, so a learner
  who predates this feature still gets the badges they already earned.
- **Bests** — read straight from ``game_results``; nothing is stored twice.
"""

from __future__ import annotations

import datetime as dt
import uuid
from zoneinfo import ZoneInfo

from sqlalchemy import Integer, func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.games.domain import badges as badge_rules
from app.games.domain import engagement as rules
from app.games.models import (
    Game,
    GameResult,
    GameSession,
    LearnerBadge,
    LearnerDailyQuest,
    LearnerStreak,
)
from app.games.services import xp
from app.identity.models import Role, School, User
from app.identity.service import Actor


def _now() -> dt.datetime:
    return dt.datetime.now(dt.UTC)


async def _school_tz(session: AsyncSession, school_id: uuid.UUID) -> ZoneInfo:
    school = await session.get(School, school_id)
    return ZoneInfo(school.timezone if school is not None else "UTC")


async def _local_date(session: AsyncSession, user: User, now: dt.datetime) -> dt.date:
    return now.astimezone(await _school_tz(session, user.school_id)).date()


# --------------------------------------------------------------------- streak
async def touch_streak(
    session: AsyncSession, *, user: User, now: dt.datetime | None = None
) -> LearnerStreak:
    """Advance today's streak once. Safe to call from every finish path.

    Missing yesterday means the run is over and today starts a new one. A
    learner who has not played today keeps the number they had: the run is
    broken only when the *next* play finds a gap, not at midnight.
    """
    now = now or _now()
    today = await _local_date(session, user, now)

    await session.execute(
        pg_insert(LearnerStreak)
        .values(
            user_id=user.id,
            school_id=user.school_id,
            current_days=0,
            longest_days=0,
        )
        .on_conflict_do_nothing(index_elements=["user_id"])
    )
    row = (
        await session.execute(
            select(LearnerStreak).where(LearnerStreak.user_id == user.id).with_for_update()
        )
    ).scalar_one()

    if row.last_played_on == today:
        return row

    if row.last_played_on == today - dt.timedelta(days=1):
        row.current_days = row.current_days + 1
    else:
        row.current_days = 1
    row.last_played_on = today
    row.longest_days = max(row.longest_days, row.current_days)
    row.updated_at = now
    await session.flush()
    return row


# ----------------------------------------------------------------------- quest
async def advance_quest(
    session: AsyncSession,
    *,
    user: User,
    game_row: GameSession,
    now: dt.datetime | None = None,
) -> int:
    """Count this finished game towards today's quest; pay the bonus once.

    Returns the XP the bonus actually paid (0 when it was already paid, when the
    quest is not finished yet, or when the daily cap left no room).
    """
    if user.role is not Role.learner:
        return 0

    now = now or _now()
    today = await _local_date(session, user, now)
    quest = rules.DAILY_QUEST

    await session.execute(
        pg_insert(LearnerDailyQuest)
        .values(
            user_id=user.id,
            local_date=today,
            quest_id=quest.id,
            progress=0,
            target=quest.target,
        )
        .on_conflict_do_nothing(index_elements=["user_id", "local_date", "quest_id"])
    )
    row = (
        await session.execute(
            select(LearnerDailyQuest)
            .where(
                LearnerDailyQuest.user_id == user.id,
                LearnerDailyQuest.local_date == today,
                LearnerDailyQuest.quest_id == quest.id,
            )
            .with_for_update()
        )
    ).scalar_one()

    if row.completed_at is not None:
        return 0

    row.progress = row.progress + 1
    if row.progress < row.target:
        await session.flush()
        return 0

    row.completed_at = now
    paid = await xp.award_quest_bonus(
        session,
        game_row=game_row,
        user=user,
        requested=quest.reward_xp,
        now=now,
    )
    row.xp_awarded = paid
    await session.flush()
    return paid


# ---------------------------------------------------------------------- badges
async def _facts(
    session: AsyncSession, *, user_id: uuid.UUID, longest_streak: int
) -> badge_rules.BadgeFacts:
    """Counts only — no XP total is read anywhere in this function."""
    live = GameResult.superseded_by.is_(None)

    games_played = (
        await session.execute(
            select(func.count(GameResult.id)).where(GameResult.user_id == user_id, live)
        )
    ).scalar_one()

    wins = (
        await session.execute(
            select(func.count(GameResult.id)).where(
                GameResult.user_id == user_id,
                live,
                GameResult.outcome == "win",
            )
        )
    ).scalar_one()

    checkers_wins = (
        await session.execute(
            select(func.count(GameResult.id))
            .select_from(GameResult)
            .join(GameSession, GameSession.id == GameResult.session_id)
            .where(
                GameResult.user_id == user_id,
                live,
                GameResult.outcome == "win",
                GameSession.game_id == "checkers",
            )
        )
    ).scalar_one()

    games_tried = (
        await session.execute(
            select(func.count(func.distinct(GameSession.game_id)))
            .select_from(GameResult)
            .join(GameSession, GameSession.id == GameResult.session_id)
            .where(GameResult.user_id == user_id, live)
        )
    ).scalar_one()

    # Most rounds of Number Guess ever solved in one game. Stored in the result
    # details by the game's own service.
    best_guess_solved = (
        await session.execute(
            select(func.coalesce(func.max(GameResult.details["solved"].astext.cast(Integer)), 0))
            .select_from(GameResult)
            .join(GameSession, GameSession.id == GameResult.session_id)
            .where(
                GameResult.user_id == user_id,
                live,
                GameSession.game_id == "number_guess",
            )
        )
    ).scalar_one()

    quests_completed = (
        await session.execute(
            select(func.count(LearnerDailyQuest.quest_id)).where(
                LearnerDailyQuest.user_id == user_id,
                LearnerDailyQuest.completed_at.is_not(None),
            )
        )
    ).scalar_one()

    return badge_rules.BadgeFacts(
        games_played=int(games_played),
        wins=int(wins),
        checkers_wins=int(checkers_wins),
        games_tried=int(games_tried),
        best_guess_solved=int(best_guess_solved),
        longest_streak=longest_streak,
        quests_completed=int(quests_completed),
    )


async def sync_badges(
    session: AsyncSession, *, user: User, now: dt.datetime | None = None
) -> list[str]:
    """Write any badge the learner has earned and does not have yet.

    Returns the ids of badges awarded by this call, which is what a post-game
    screen says out loud. ``ON CONFLICT DO NOTHING`` makes it idempotent, so the
    read path may call it as often as it likes.
    """
    now = now or _now()
    today = await _local_date(session, user, now)

    streak = (
        (await session.execute(select(LearnerStreak).where(LearnerStreak.user_id == user.id)))
        .scalars()
        .first()
    )

    facts = await _facts(
        session, user_id=user.id, longest_streak=streak.longest_days if streak else 0
    )
    wanted = badge_rules.earned_badges(facts)
    if not wanted:
        return []

    existing = set(
        (
            await session.execute(
                select(LearnerBadge.badge_id).where(LearnerBadge.user_id == user.id)
            )
        ).scalars()
    )
    new_ids = [badge.id for badge in wanted if badge.id not in existing]
    if not new_ids:
        return []

    await session.execute(
        pg_insert(LearnerBadge)
        .values(
            [{"user_id": user.id, "badge_id": badge_id, "earned_on": today} for badge_id in new_ids]
        )
        .on_conflict_do_nothing(index_elements=["user_id", "badge_id"])
    )
    await session.flush()
    return new_ids


# ---------------------------------------------------------------------- bests
async def _bests(session: AsyncSession, *, user_id: uuid.UUID) -> list[dict]:
    live = GameResult.superseded_by.is_(None)
    rows = (
        await session.execute(
            select(
                GameSession.game_id,
                Game.name,
                func.count(GameResult.id).label("played"),
                func.max(GameResult.score).label("best_score"),
                func.count(GameResult.id).filter(GameResult.outcome == "win").label("wins"),
            )
            .select_from(GameResult)
            .join(GameSession, GameSession.id == GameResult.session_id)
            .join(Game, Game.id == GameSession.game_id)
            .where(GameResult.user_id == user_id, live)
            .group_by(GameSession.game_id, Game.name)
            .order_by(Game.name)
        )
    ).all()

    solved_by_game = dict(
        (
            await session.execute(
                select(
                    GameSession.game_id,
                    func.coalesce(func.max(GameResult.details["solved"].astext.cast(Integer)), 0),
                )
                .select_from(GameResult)
                .join(GameSession, GameSession.id == GameResult.session_id)
                .where(GameResult.user_id == user_id, live)
                .group_by(GameSession.game_id)
            )
        ).all()
    )

    out: list[dict] = []
    for row in rows:
        played = int(row.played)
        # A zero is not a best. A game with nothing to show yet is left out
        # rather than printed as "Best: 0" — that reads like a score, not a gap.
        if row.game_id == "checkers":
            wins = int(row.wins)
            if wins <= 0:
                continue
            value = f"{wins} wins"
        elif row.game_id == "number_guess":
            solved = int(solved_by_game.get(row.game_id) or 0)
            if solved <= 0:
                continue
            value = f"{solved} numbers in one game"
        else:
            best_score = int(row.best_score or 0)
            if best_score <= 0:
                continue
            value = f"{best_score} points in one game"
        out.append(
            {
                "game_id": row.game_id,
                "name": row.name,
                "value": value,
                "played": played,
            }
        )
    return out


# ------------------------------------------------------------------ new best
async def best_for_finished(
    session: AsyncSession, *, user_id: uuid.UUID, session_id: uuid.UUID, game_id: str
) -> tuple[str, bool] | None:
    """The learner's best for one game, after this session finished.

    Returns ``(label, is_new)``. ``None`` when the game has no scored best to
    compare (Checkers is won or lost, not scored), because "New best!" on a win
    would be noise and "Best: 0" would be a lie.
    """
    live = GameResult.superseded_by.is_(None)

    if game_id == "number_guess":
        mine = (
            await session.execute(
                select(GameResult.details["solved"].astext.cast(Integer)).where(
                    GameResult.session_id == session_id,
                    GameResult.user_id == user_id,
                    live,
                )
            )
        ).scalar_one_or_none()
        if mine is None:
            return None
        previous = (
            await session.execute(
                select(
                    func.coalesce(
                        func.max(GameResult.details["solved"].astext.cast(Integer)), 0
                    )
                )
                .join(GameSession, GameSession.id == GameResult.session_id)
                .where(
                    GameResult.user_id == user_id,
                    live,
                    GameSession.game_id == game_id,
                    GameResult.session_id != session_id,
                )
            )
        ).scalar_one()
        value = int(mine)
        return f"{value} numbers in one game", value > int(previous)

    if game_id == "word_scramble":
        mine = (
            await session.execute(
                select(GameResult.score).where(
                    GameResult.session_id == session_id,
                    GameResult.user_id == user_id,
                    live,
                )
            )
        ).scalar_one_or_none()
        if mine is None:
            return None
        previous = (
            await session.execute(
                select(func.coalesce(func.max(GameResult.score), 0))
                .join(GameSession, GameSession.id == GameResult.session_id)
                .where(
                    GameResult.user_id == user_id,
                    live,
                    GameSession.game_id == game_id,
                    GameResult.session_id != session_id,
                )
            )
        ).scalar_one()
        value = int(mine)
        return f"{value} points in one game", value > int(previous)

    return None


# -------------------------------------------------------------------- overview
async def overview(session: AsyncSession, *, actor: Actor, now: dt.datetime | None = None) -> dict:
    """Everything the dashboard capsule and the profile page need, in one call."""
    now = now or _now()
    user = await session.get(User, actor.id)
    if user is None:  # pragma: no cover - the token already proved they exist
        return {}

    tz = await _school_tz(session, actor.school_id)
    today = now.astimezone(tz).date()

    streak = (
        (await session.execute(select(LearnerStreak).where(LearnerStreak.user_id == user.id)))
        .scalars()
        .first()
    )

    last = streak.last_played_on if streak is not None else None
    played_today = last == today
    # A stored number only counts while the run is still alive.
    current = 0
    if last is not None and last >= today - dt.timedelta(days=1):
        current = streak.current_days if streak else 0

    quest_row = (
        (
            await session.execute(
                select(LearnerDailyQuest).where(
                    LearnerDailyQuest.user_id == user.id,
                    LearnerDailyQuest.local_date == today,
                    LearnerDailyQuest.quest_id == rules.DAILY_QUEST.id,
                )
            )
        )
        .scalars()
        .first()
    )

    # Award anything already earned by play that happened before this feature
    # existed. A read normally rolls back, so this one commits when it actually
    # wrote something; on every later read it writes nothing and commits nothing.
    if await sync_badges(session, user=user, now=now):
        await session.commit()

    earned = {
        row.badge_id: row.earned_on
        for row in (
            await session.execute(select(LearnerBadge).where(LearnerBadge.user_id == user.id))
        ).scalars()
    }

    xp_summary = await xp.summary(session, actor=actor, now=now)
    level = rules.level_for(int(xp_summary["profile_xp_total"]))

    return {
        "streak": {
            "current": current,
            "longest": streak.longest_days if streak else 0,
            "played_today": played_today,
            "last_played_on": last.isoformat() if last else None,
        },
        "quest": {
            "id": rules.DAILY_QUEST.id,
            "title": rules.DAILY_QUEST.title,
            "target": rules.DAILY_QUEST.target,
            "progress": min(int(quest_row.progress) if quest_row else 0, rules.DAILY_QUEST.target),
            "completed": bool(quest_row and quest_row.completed_at),
            "reward_xp": rules.DAILY_QUEST.reward_xp,
        },
        "badges": [
            {
                "id": badge.id,
                "title": badge.title,
                "sentence": badge.sentence,
                "hint": badge.hint,
                "earned_on": earned[badge.id].isoformat() if badge.id in earned else None,
            }
            for badge in badge_rules.BADGES
        ],
        "bests": await _bests(session, user_id=user.id),
        "level": {
            "number": level.number,
            "xp_into": level.xp_into,
            "xp_span": level.xp_span,
            "xp_to_next": level.xp_to_next,
            "profile_xp": int(xp_summary["profile_xp_total"]),
        },
    }
