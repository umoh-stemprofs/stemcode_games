"""Schema rules from Phase 2 (P2-T03, P2-T07).

These are the promises the rest of the build leans on:

- history cannot be rewritten (append-only triggers);
- a retried move cannot be recorded twice (unique constraints);
- two answers cannot both be the live result for one player;
- an ``all_time`` period can never gain an end date;
- a ``seed`` cannot reach a client, because no response schema has the field.
"""

from __future__ import annotations

import datetime as dt
import uuid

import pytest
from app.games import models as games
from app.games import repository as repo
from pydantic import BaseModel
from sqlalchemy import select, text
from sqlalchemy.exc import DBAPIError, IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from tests.factories import build_world


async def make_session(
    db: AsyncSession, *, world, game_id: str = "word_scramble", mode: str = "solo"
) -> games.GameSession:
    return await repo.create_session(
        db,
        game_id=game_id,
        mode=mode,
        status="active",
        seed=123456789,
        school_id=world.school_a.id,
        created_by=world.learner_a.id,
    )


# ------------------------------------------------------------------ append-only
@pytest.mark.parametrize("table", ["game_moves", "game_results", "game_xp_ledger"])
async def test_history_tables_reject_delete(db_session: AsyncSession, table: str) -> None:
    world = await build_world(db_session)
    session = await make_session(db_session, world=world)

    # The trigger is FOR EACH ROW, so each table needs a row for this to mean
    # anything: deleting from an empty table would prove nothing.
    if table == "game_moves":
        await repo.append_move(
            db_session,
            session_id=session.id,
            user_id=world.learner_a.id,
            move_number=1,
            client_move_id="m1",
            payload={"word": "cat"},
        )
    elif table == "game_results":
        await repo.append_result(
            db_session,
            session_id=session.id,
            user_id=world.learner_a.id,
            outcome="completed",
            score=10,
        )
    else:
        await repo.append_xp(
            db_session,
            user_id=world.learner_a.id,
            game_id="word_scramble",
            session_id=session.id,
            reason="solo_complete",
            requested_amount=10,
            awarded_amount=10,
            local_date=dt.date(2026, 11, 14),
            school_id=world.school_a.id,
        )
    await db_session.flush()

    with pytest.raises(DBAPIError):
        # `table` comes from the parametrize list above, never from input.
        await db_session.execute(text(f"DELETE FROM {table}"))  # noqa: S608
        await db_session.flush()


async def test_moves_cannot_be_updated(db_session: AsyncSession) -> None:
    world = await build_world(db_session)
    session = await make_session(db_session, world=world)
    await repo.append_move(
        db_session,
        session_id=session.id,
        user_id=world.learner_a.id,
        move_number=1,
        client_move_id="m1",
        payload={"word": "cat"},
    )
    await db_session.flush()

    with pytest.raises(DBAPIError):
        await db_session.execute(text('UPDATE game_moves SET payload = \'{"word":"dog"}\'::jsonb'))
        await db_session.flush()


# ---------------------------------------------------------------- constraints
async def test_a_move_number_cannot_repeat_in_a_session(db_session: AsyncSession) -> None:
    world = await build_world(db_session)
    session = await make_session(db_session, world=world)
    await repo.append_move(
        db_session,
        session_id=session.id,
        user_id=world.learner_a.id,
        move_number=1,
        client_move_id="m1",
        payload={},
    )
    await db_session.flush()

    with pytest.raises(IntegrityError):
        await repo.append_move(
            db_session,
            session_id=session.id,
            user_id=world.learner_a.id,
            move_number=1,
            client_move_id="m2",
            payload={},
        )
        await db_session.flush()


async def test_a_client_move_id_is_idempotent(db_session: AsyncSession) -> None:
    world = await build_world(db_session)
    session = await make_session(db_session, world=world)
    await repo.append_move(
        db_session,
        session_id=session.id,
        user_id=world.learner_a.id,
        move_number=1,
        client_move_id="same-id",
        payload={},
    )
    await db_session.flush()

    with pytest.raises(IntegrityError):
        await repo.append_move(
            db_session,
            session_id=session.id,
            user_id=world.learner_a.id,
            move_number=2,
            client_move_id="same-id",
            payload={},
        )
        await db_session.flush()


async def test_only_one_live_result_per_player(db_session: AsyncSession) -> None:
    world = await build_world(db_session)
    session = await make_session(db_session, world=world)
    await repo.append_result(
        db_session,
        session_id=session.id,
        user_id=world.learner_a.id,
        outcome="completed",
        score=10,
    )
    await db_session.flush()

    with pytest.raises(IntegrityError):
        await repo.append_result(
            db_session,
            session_id=session.id,
            user_id=world.learner_a.id,
            outcome="completed",
            score=20,
        )
        await db_session.flush()


async def test_a_correction_links_both_ways(db_session: AsyncSession) -> None:
    world = await build_world(db_session)
    session = await make_session(db_session, world=world)
    original = await repo.append_result(
        db_session,
        session_id=session.id,
        user_id=world.learner_a.id,
        outcome="completed",
        score=10,
    )
    await db_session.flush()

    replacement = games.GameResult(
        session_id=session.id,
        user_id=world.learner_a.id,
        outcome="completed",
        score=8,
    )
    await repo.supersede_result(db_session, old_result_id=original.id, new_result=replacement)
    await db_session.flush()

    live = await repo.live_result(db_session, session_id=session.id, user_id=world.learner_a.id)
    assert live is not None and live.score == 8
    assert live.supersedes_id == original.id

    old = (
        (
            await db_session.execute(
                select(games.GameResult).where(games.GameResult.id == original.id)
            )
        )
        .scalars()
        .first()
    )
    assert old is not None and old.superseded_by == live.id


async def test_session_requires_a_real_game(db_session: AsyncSession) -> None:
    world = await build_world(db_session)
    with pytest.raises(IntegrityError):
        await repo.create_session(
            db_session,
            game_id="not_a_game",
            mode="solo",
            school_id=world.school_a.id,
        )
        await db_session.flush()


async def test_one_seat_per_player_per_session(db_session: AsyncSession) -> None:
    world = await build_world(db_session)
    session = await make_session(db_session, world=world)
    await repo.add_participant(
        db_session, session_id=session.id, user_id=world.learner_a.id, seat=1
    )
    await db_session.flush()

    with pytest.raises(IntegrityError):
        await repo.add_participant(
            db_session, session_id=session.id, user_id=world.learner_a2.id, seat=1
        )
        await db_session.flush()


async def test_xp_award_is_idempotent_per_reason(db_session: AsyncSession) -> None:
    world = await build_world(db_session)
    session = await make_session(db_session, world=world)
    fields = dict(
        user_id=world.learner_a.id,
        game_id="word_scramble",
        session_id=session.id,
        reason="solo_complete",
        requested_amount=10,
        awarded_amount=10,
        local_date=dt.date(2026, 11, 14),
        school_id=world.school_a.id,
    )
    await repo.append_xp(db_session, **fields)
    await db_session.flush()

    with pytest.raises(IntegrityError):
        await repo.append_xp(db_session, **fields)
        await db_session.flush()


# ------------------------------------------------------------------ periods
async def test_all_time_never_ends(db_session: AsyncSession) -> None:
    world = await build_world(db_session)
    # D-33: the game dimension lives on the entry, not the period.
    period = games.LeaderboardPeriod(
        id=uuid.uuid4(),
        period_type="all_time",
        school_id=world.school_a.id,
        starts_at=dt.datetime(2026, 1, 1, tzinfo=dt.UTC),
        ends_at=dt.datetime(2026, 2, 1, tzinfo=dt.UTC),
    )
    db_session.add(period)
    with pytest.raises(IntegrityError):
        await db_session.flush()


async def test_a_timed_period_must_end(db_session: AsyncSession) -> None:
    world = await build_world(db_session)
    period = games.LeaderboardPeriod(
        id=uuid.uuid4(),
        period_type="weekly",
        school_id=world.school_a.id,
        starts_at=dt.datetime(2026, 1, 1, tzinfo=dt.UTC),
        ends_at=None,
    )
    db_session.add(period)
    with pytest.raises(IntegrityError):
        await db_session.flush()


# --------------------------------------------------------------- seed secrecy
def test_no_response_schema_has_a_seed_field() -> None:
    """D-25: the seed is server-private. A schema field would leak it."""
    import importlib
    import pkgutil

    import app

    offenders: list[str] = []
    for module_info in pkgutil.walk_packages(app.__path__, prefix="app."):
        module = importlib.import_module(module_info.name)
        for name in dir(module):
            obj = getattr(module, name)
            if (
                isinstance(obj, type)
                and issubclass(obj, BaseModel)
                and obj is not BaseModel
                and "seed" in getattr(obj, "model_fields", {})
            ):
                offenders.append(f"{module_info.name}.{name}")
    assert offenders == [], f"seed exposed in response schemas: {offenders}"


# ------------------------------------------------------------------- defaults
async def test_launch_games_exist_and_only_played_games_are_on(db_session: AsyncSession) -> None:
    """Phase 2 shipped every game off; each later phase turns on its own game.

    Phase 4 turned on Word Scramble, Phase 6 Number Guess, and Phase 8 Checkers
    (migration 0015) once its rules engine shipped. A game is listed only when
    it can be played, so every launch game is on and only Checkers seats two.
    """
    games_rows = {g.id: g for g in await repo.list_games(db_session, enabled_only=False)}
    assert set(games_rows) == {"word_scramble", "number_guess", "checkers"}
    assert all(g.enabled for g in games_rows.values())
    assert games_rows["checkers"].is_live is True
    assert games_rows["checkers"].max_players == 2
    assert games_rows["word_scramble"].max_players == 1


async def test_platform_defaults_are_seeded(db_session: AsyncSession) -> None:
    assert await repo.get_platform_setting(db_session, "daily_limit_minutes") == 120
    assert await repo.get_platform_setting(db_session, "daily_limit_ceiling_minutes") == 240
    assert await repo.get_platform_setting(db_session, "daily_xp_cap") == 60
    assert await repo.get_platform_setting(db_session, "live_min_remaining_seconds") == 900


# ------------------------------------------------- one active play (D-26, D-28)
async def _playing(db: AsyncSession, *, world, session, user) -> None:
    await repo.add_participant(db, session_id=session.id, user_id=user.id, seat=1)
    await repo.set_attempt_status(db, session.id, user.id, status="in_progress")


async def test_a_second_open_play_is_refused(db_session: AsyncSession) -> None:
    """Opening a second game in another tab must fail in the database (D-26)."""
    world = await build_world(db_session)
    first = await make_session(db_session, world=world)
    await _playing(db_session, world=world, session=first, user=world.learner_a)

    second = await make_session(db_session, world=world, game_id="number_guess")
    with pytest.raises(IntegrityError):
        await _playing(db_session, world=world, session=second, user=world.learner_a)


async def test_a_finished_play_frees_the_learner(db_session: AsyncSession) -> None:
    world = await build_world(db_session)
    first = await make_session(db_session, world=world)
    await _playing(db_session, world=world, session=first, user=world.learner_a)

    await repo.set_attempt_status(db_session, first.id, world.learner_a.id, status="finished")
    assert await repo.active_session_for_user(db_session, world.learner_a.id) is None

    second = await make_session(db_session, world=world, game_id="number_guess")
    await _playing(db_session, world=world, session=second, user=world.learner_a)
    found = await repo.active_session_for_user(db_session, world.learner_a.id)
    assert found is not None and found.id == second.id


async def test_a_challenge_is_one_parent_and_two_children(
    db_session: AsyncSession,
) -> None:
    """D-28: two players, two attempts, one shared seed, two children."""
    world = await build_world(db_session)
    shared_seed = 42424242
    parent = await repo.create_session(
        db_session,
        game_id="number_guess",
        mode="challenge",
        status="active",
        seed=shared_seed,
        school_id=world.school_a.id,
        created_by=world.learner_a.id,
    )

    children = []
    for seat, player in enumerate((world.learner_a, world.learner_b), start=1):
        await repo.add_participant(
            db_session,
            session_id=parent.id,
            user_id=player.id,
            seat=seat,
            counts_as_active=False,
            attempt_status="in_progress",
        )
        child = await repo.create_session(
            db_session,
            game_id="number_guess",
            mode="solo",
            status="active",
            seed=shared_seed,
            school_id=world.school_a.id,
            created_by=player.id,
            parent_session_id=parent.id,
        )
        await _playing(db_session, world=world, session=child, user=player)
        children.append(child)

    assert len(children) == 2
    assert {c.parent_session_id for c in children} == {parent.id}
    assert {c.seed for c in children} == {shared_seed}
    assert len(await repo.list_moves(db_session, parent.id)) == 0


async def test_two_classmates_may_play_at_the_same_time(
    db_session: AsyncSession,
) -> None:
    """The limit is per learner, not per class."""
    world = await build_world(db_session)
    live = await make_session(db_session, world=world, game_id="checkers", mode="live")
    await repo.add_participant(db_session, session_id=live.id, user_id=world.learner_a.id, seat=1)
    await repo.add_participant(db_session, session_id=live.id, user_id=world.learner_b.id, seat=2)
    await repo.set_attempt_status(db_session, live.id, world.learner_a.id, status="in_progress")
    await repo.set_attempt_status(db_session, live.id, world.learner_b.id, status="in_progress")

    assert await repo.active_session_for_user(db_session, world.learner_a.id) is not None
    assert await repo.active_session_for_user(db_session, world.learner_b.id) is not None


# ---------------------------------------------------------------- repository
async def test_repository_round_trip(db_session: AsyncSession) -> None:
    world = await build_world(db_session)
    session = await make_session(db_session, world=world)

    await repo.add_participant(
        db_session, session_id=session.id, user_id=world.learner_a.id, seat=1
    )
    await repo.set_attempt_status(db_session, session.id, world.learner_a.id, status="in_progress")
    assert await repo.next_move_number(db_session, session.id) == 1
    await repo.append_move(
        db_session,
        session_id=session.id,
        user_id=world.learner_a.id,
        move_number=1,
        client_move_id="first",
        payload={"guess": 50},
    )

    assert await repo.next_move_number(db_session, session.id) == 2
    moves = await repo.list_moves(db_session, session.id)
    assert len(moves) == 1 and moves[0].payload == {"guess": 50}

    found = await repo.active_session_for_user(db_session, world.learner_a.id)
    assert found is not None and found.id == session.id

    assert (
        await repo.xp_for_user_on_date(
            db_session, user_id=world.learner_a.id, local_date=dt.date(2026, 11, 14)
        )
        == 0
    )
