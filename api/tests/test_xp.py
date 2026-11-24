"""Phase 5: XP rules and the capped award (P5-T01, P5-T02, P5-T12).

The promises under test:

- the XP table is exact: participation, the 10-point performance bonus, and
  Checkers' win/draw replacing that bonus rather than adding to it;
- a session below the D-29 activity minimum requests zero, with a reason;
- the daily cap clamps, never goes negative, and a retry does not pay twice;
- the ledger keeps both numbers, so capping is auditable.

Nothing here reads a clock: "now" is injected.
"""

from __future__ import annotations

import datetime as dt
import uuid

import pytest
from app.games import repository as repo
from app.games.domain import xp_rules
from app.games.models import GameResult, GameSession
from app.games.services import xp
from app.identity.service import Actor
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from tests.factories import build_world

NOW = dt.datetime(2026, 11, 14, 9, 0, tzinfo=dt.UTC)  # 10:00 in Lagos


# --------------------------------------------------------------------- rules
def test_participation_plus_a_scaled_bonus() -> None:
    request = xp_rules.request_xp(
        game_id="word_scramble",
        outcome="completed",
        score=75,
        details={"rounds": [10, 10, 10, 10, 0, 0, 0, 0, 0, 0]},
    )
    assert request.requested == 10  # 5 participation + round(10 * 75/150) = 5 + 5
    assert request.reason == "played"


def test_a_perfect_game_pays_the_full_bonus() -> None:
    request = xp_rules.request_xp(
        game_id="word_scramble",
        outcome="completed",
        score=150,
        details={"rounds": [15] * 10},
    )
    assert request.requested == 15


def test_checkers_win_replaces_the_performance_bonus() -> None:
    win = xp_rules.request_xp(game_id="checkers", outcome="win", score=0, details={"moves": 12})
    draw = xp_rules.request_xp(game_id="checkers", outcome="draw", score=0, details={"moves": 12})
    loss = xp_rules.request_xp(game_id="checkers", outcome="loss", score=0, details={"moves": 12})
    assert (win.requested, draw.requested, loss.requested) == (15, 10, 5)


def test_below_the_activity_minimum_requests_nothing_but_says_why() -> None:
    idle = xp_rules.request_xp(
        game_id="word_scramble",
        outcome="completed",
        score=0,
        details={"rounds": [0, 0, 0, 0, 0, 0, 0, 0, 0, 0]},
    )
    assert idle.requested == 0
    assert idle.reason == "below_minimum"
    assert idle.meets_minimum is False


def test_an_unknown_game_earns_nothing() -> None:
    request = xp_rules.request_xp(game_id="not_a_game", outcome="win", score=999, details={})
    assert request.requested == 0


def test_no_contest_is_worth_nothing() -> None:
    request = xp_rules.request_xp(
        game_id="word_scramble",
        outcome="no_contest",
        score=150,
        details={"rounds": [15] * 10},
    )
    assert request.requested == 0
    assert request.reason == "no_contest"


def test_a_challenge_win_adds_five() -> None:
    plain = xp_rules.request_xp(
        game_id="word_scramble",
        outcome="completed",
        score=150,
        details={"rounds": [15] * 10},
    )
    challenge = xp_rules.request_xp(
        game_id="word_scramble",
        outcome="completed",
        score=150,
        details={"rounds": [15] * 10},
        challenge_win=True,
    )
    assert challenge.requested == plain.requested + 5


def test_the_cap_clamps_and_never_goes_negative() -> None:
    assert xp_rules.capped_award(15, 50, 60) == 10
    assert xp_rules.capped_award(15, 60, 60) == 0
    assert xp_rules.capped_award(15, 90, 60) == 0


# ------------------------------------------------------------------- awarding
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


async def _finished_session(
    db: AsyncSession, *, school_id: uuid.UUID, learner_id: uuid.UUID, rounds: list[int]
) -> tuple[GameSession, GameResult]:
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
    result = await repo.append_result(
        db,
        session_id=row.id,
        user_id=learner_id,
        outcome="completed",
        score=sum(rounds),
        details={"rounds": rounds, "game_id": "word_scramble"},
        leaderboard_eligible=True,
    )
    await db.flush()
    return row, result


async def test_a_first_game_awards_and_records_both_numbers(db_session: AsyncSession) -> None:
    world = await build_world(db_session)
    row, result = await _finished_session(
        db_session,
        school_id=world.school_a.id,
        learner_id=world.learner_a.id,
        rounds=[15] * 10,
    )

    award = await xp.award_for_result(
        db_session, result=result, game_row=row, user=world.learner_a, now=NOW
    )
    assert award.awarded == 15
    assert award.today == 15
    # No daily cap by default: 0 in the payload means "nothing to stop at".
    assert award.daily_cap == 0
    assert award.eligible is True

    ledger = (
        (
            await db_session.execute(
                select(repo.GameXpEntry).where(repo.GameXpEntry.session_id == row.id)
            )
        )
        .scalars()
        .all()
    )
    assert len(ledger) == 1
    assert ledger[0].requested_amount == 15
    assert ledger[0].awarded_amount == 15
    assert ledger[0].age_band_snapshot == "11-13"


async def test_a_retry_does_not_pay_twice(db_session: AsyncSession) -> None:
    world = await build_world(db_session)
    row, result = await _finished_session(
        db_session,
        school_id=world.school_a.id,
        learner_id=world.learner_a.id,
        rounds=[15] * 10,
    )

    first = await xp.award_for_result(
        db_session, result=result, game_row=row, user=world.learner_a, now=NOW
    )
    again = await xp.award_for_result(
        db_session, result=result, game_row=row, user=world.learner_a, now=NOW
    )
    assert (first.awarded, again.awarded) == (15, 15)
    assert again.today == 15

    total = await repo.xp_for_user_on_date(
        db_session, user_id=world.learner_a.id, local_date=NOW.date()
    )
    assert total == 15


def test_there_is_no_daily_cap_by_default() -> None:
    assert xp_rules.DEFAULT_DAILY_CAP == 0
    assert xp_rules.capped_award(40, 5000, xp_rules.DEFAULT_DAILY_CAP) == 40


def test_a_configured_cap_still_clips() -> None:
    """The setting survived the default: a school that wants a cap still gets one."""
    assert xp_rules.capped_award(40, 20, 60) == 40
    assert xp_rules.capped_award(40, 55, 60) == 5
    assert xp_rules.capped_award(40, 90, 60) == 0


async def test_six_games_in_one_day_are_paid_in_full(db_session: AsyncSession) -> None:
    world = await build_world(db_session)
    totals: list[int] = []
    for _ in range(6):
        row, result = await _finished_session(
            db_session,
            school_id=world.school_a.id,
            learner_id=world.learner_a.id,
            rounds=[15] * 10,
        )
        award = await xp.award_for_result(
            db_session, result=result, game_row=row, user=world.learner_a, now=NOW
        )
        totals.append(award.awarded)

    assert totals == [15, 15, 15, 15, 15, 15]
    assert award.today == 90


async def test_a_below_minimum_session_writes_an_auditable_zero(
    db_session: AsyncSession,
) -> None:
    world = await build_world(db_session)
    row, result = await _finished_session(
        db_session,
        school_id=world.school_a.id,
        learner_id=world.learner_a.id,
        rounds=[0, 0, 0, 0, 0, 0, 0, 0, 0, 0],
    )
    award = await xp.award_for_result(
        db_session, result=result, game_row=row, user=world.learner_a, now=NOW
    )
    assert award.awarded == 0
    assert award.reason == "below_minimum"
    assert award.eligible is False

    entry = (
        (
            await db_session.execute(
                select(repo.GameXpEntry).where(repo.GameXpEntry.session_id == row.id)
            )
        )
        .scalars()
        .first()
    )
    assert entry is not None
    assert entry.awarded_amount == 0
    assert entry.leaderboard_eligible is False


async def test_the_summary_splits_learning_from_game(db_session: AsyncSession) -> None:
    world = await build_world(db_session)
    row, result = await _finished_session(
        db_session,
        school_id=world.school_a.id,
        learner_id=world.learner_a.id,
        rounds=[15] * 10,
    )
    await xp.award_for_result(
        db_session, result=result, game_row=row, user=world.learner_a, now=NOW
    )

    summary = await xp.summary(db_session, actor=_actor(world.learner_a, world.school_a), now=NOW)
    assert summary["game_xp_total"] == 15
    assert summary["game_xp_today"] == 15
    assert summary["profile_xp_total"] == summary["learning_xp_total"] + 15
    assert summary["daily_cap"] == 0


@pytest.mark.parametrize(
    ("rounds", "expected"),
    # 150 points is full marks (15 XP); 100 points is 5 + round(6.67) = 12.
    [([15] * 10, 15), ([10] * 10, 12), ([0] * 10, 0)],
)
async def test_the_same_inputs_always_give_the_same_award(
    db_session: AsyncSession, rounds: list[int], expected: int
) -> None:
    world = await build_world(db_session)
    row, result = await _finished_session(
        db_session, school_id=world.school_a.id, learner_id=world.learner_a.id, rounds=rounds
    )
    award = await xp.award_for_result(
        db_session, result=result, game_row=row, user=world.learner_a, now=NOW
    )
    assert award.awarded == expected
