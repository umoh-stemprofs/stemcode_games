"""Engagement: streak, daily quest, badges and the level ring.

The promises under test:

- a streak counts *school-local days*, not plays: two games today is one day;
- a missed day starts the run again, and the longest run is remembered;
- the quest pays its bonus once, through the normal capped ledger;
- badges come from play, never from XP;
- the level is a restatement of Profile XP and nothing else.

Nothing here reads a clock: ``now`` is injected.
"""

from __future__ import annotations

import datetime as dt
import uuid

from app.games import repository as repo
from app.games.domain import engagement as rules
from app.games.models import GameSession, LearnerBadge, LearnerDailyQuest, LearnerStreak
from app.games.services import engagement, xp
from app.identity.service import Actor
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from tests.factories import build_world

DAY_ONE = dt.datetime(2026, 11, 14, 9, 0, tzinfo=dt.UTC)  # 10:00 in Lagos


def _actor(user, school) -> Actor:
    return Actor(
        id=user.id,
        role=user.role,
        school_id=school.id,
        session_id=uuid.uuid4(),
        preferred_name=user.preferred_name,
        avatar_key=user.avatar_key,
        school_timezone=school.timezone,
    )


async def _session(db: AsyncSession, *, school_id: uuid.UUID, learner_id: uuid.UUID) -> GameSession:
    row = GameSession(
        game_id="word_scramble",
        mode="solo",
        status="finished",
        school_id=school_id,
        created_by=learner_id,
        config={"rounds": []},
    )
    db.add(row)
    await db.flush()
    return row


async def test_two_games_today_are_one_day_of_streak(db_session: AsyncSession) -> None:
    world = await build_world(db_session)

    first = await engagement.touch_streak(db_session, user=world.learner_a, now=DAY_ONE)
    second = await engagement.touch_streak(
        db_session, user=world.learner_a, now=DAY_ONE + dt.timedelta(hours=2)
    )
    assert (first.current_days, second.current_days) == (1, 1)
    assert second.longest_days == 1


async def test_yesterday_extends_and_a_gap_restarts(db_session: AsyncSession) -> None:
    world = await build_world(db_session)

    await engagement.touch_streak(db_session, user=world.learner_a, now=DAY_ONE)
    await engagement.touch_streak(
        db_session, user=world.learner_a, now=DAY_ONE + dt.timedelta(days=1)
    )
    third = await engagement.touch_streak(
        db_session, user=world.learner_a, now=DAY_ONE + dt.timedelta(days=3)
    )

    assert third.current_days == 1
    assert third.longest_days == 2

    row = (
        await db_session.execute(
            select(LearnerStreak).where(LearnerStreak.user_id == world.learner_a.id)
        )
    ).scalar_one()
    assert row.last_played_on == (DAY_ONE + dt.timedelta(days=3)).date()


async def test_the_quest_pays_ten_once_for_two_games(db_session: AsyncSession) -> None:
    world = await build_world(db_session)
    first = await _session(
        db_session, school_id=world.school_a.id, learner_id=world.learner_a.id
    )
    second = await _session(
        db_session, school_id=world.school_a.id, learner_id=world.learner_a.id
    )

    paid_first = await engagement.advance_quest(
        db_session, user=world.learner_a, game_row=first, now=DAY_ONE
    )
    paid_second = await engagement.advance_quest(
        db_session, user=world.learner_a, game_row=second, now=DAY_ONE
    )
    # A third game the same day must not pay again.
    third = await _session(
        db_session, school_id=world.school_a.id, learner_id=world.learner_a.id
    )
    paid_third = await engagement.advance_quest(
        db_session, user=world.learner_a, game_row=third, now=DAY_ONE
    )

    assert (paid_first, paid_second, paid_third) == (0, 10, 0)

    rows = (
        (
            await db_session.execute(
                select(repo.GameXpEntry).where(
                    repo.GameXpEntry.user_id == world.learner_a.id,
                    repo.GameXpEntry.reason == "daily_quest",
                )
            )
        )
        .scalars()
        .all()
    )
    assert len(rows) == 1
    assert rows[0].awarded_amount == 10

    quest = (
        await db_session.execute(
            select(LearnerDailyQuest).where(
                LearnerDailyQuest.user_id == world.learner_a.id
            )
        )
    ).scalar_one()
    # Progress stops at the target: a finished quest is not a counter to farm.
    assert quest.progress == 2
    assert quest.completed_at is not None


async def test_badges_come_from_play_not_from_xp(db_session: AsyncSession) -> None:
    world = await build_world(db_session)

    # Nothing played: nothing earned, however many XP rows a fixture invents.
    assert await engagement.sync_badges(db_session, user=world.learner_a, now=DAY_ONE) == []

    await repo.append_result(
        db_session,
        session_id=(
            await _session(db_session, school_id=world.school_a.id, learner_id=world.learner_a.id)
        ).id,
        user_id=world.learner_a.id,
        outcome="completed",
        score=30,
        details={"rounds": [10, 10, 10], "game_id": "word_scramble"},
        leaderboard_eligible=True,
    )
    await db_session.flush()
    awarded = await engagement.sync_badges(db_session, user=world.learner_a, now=DAY_ONE)

    assert awarded == ["first_game"]
    earned = (
        (
            await db_session.execute(
                select(LearnerBadge.badge_id).where(
                    LearnerBadge.user_id == world.learner_a.id
                )
            )
        )
        .scalars()
        .all()
    )
    assert earned == ["first_game"]
    # Idempotent: a second sync adds nothing.
    assert await engagement.sync_badges(db_session, user=world.learner_a, now=DAY_ONE) == []


async def test_the_level_is_only_a_restatement_of_profile_xp(db_session: AsyncSession) -> None:
    world = await build_world(db_session)
    # Each level costs more than the last: 50, 75, 100 ...
    assert rules.level_for(0) == rules.Level(number=1, xp_into=0, xp_span=50)
    assert rules.level_for(49).xp_to_next == 1
    assert rules.level_for(50).number == 2
    assert rules.level_for(50).xp_span == 75
    assert rules.level_for(124).number == 2
    assert rules.level_for(125).number == 3
    assert rules.level_for(125).xp_span == 100
    assert rules.level_for(225).number == 4

    view = await engagement.overview(
        db_session, actor=_actor(world.learner_a, world.school_a), now=DAY_ONE
    )
    summary = await xp.summary(
        db_session, actor=_actor(world.learner_a, world.school_a), now=DAY_ONE
    )
    assert view["level"]["profile_xp"] == summary["profile_xp_total"]
    assert view["level"]["number"] == rules.level_for(summary["profile_xp_total"]).number
