"""Leaving a game for good (P3-T04 lifecycle, P8's disconnect).

The promise: tapping "quit" ends the attempt the learner is in, gives them
nothing, and frees the one-open-play seat so the next game can start. A
challenge turn that is quit also closes the window, so the friend who did play
is not left waiting a day for somebody who has already gone.
"""

from __future__ import annotations

import uuid

from app.games import repository as repo
from app.games.domain import guessing as guess_rules
from sqlalchemy.ext.asyncio import AsyncSession

from tests.factories import build_world, login


async def _act(client, session_id: str, *, type_: str, value: str | None = None):
    return await client.post(
        f"/api/games/sessions/{session_id}/actions",
        json={"client_move_id": uuid.uuid4().hex, "type": type_, "value": value},
    )


async def _secret_for(db: AsyncSession, session_id: str, index: int) -> int:
    row = await repo.get_session(db, uuid.UUID(session_id))
    assert row is not None and row.seed is not None
    return guess_rules.secret_for(row.seed, index, 1)


async def _play_all(client, db: AsyncSession, session_id: str) -> None:
    for index in range(guess_rules.ROUNDS):
        assert (await _act(client, session_id, type_="round_seen")).status_code == 200
        secret = await _secret_for(db, session_id, index)
        guessed = await _act(client, session_id, type_="guess", value=str(secret))
        assert guessed.status_code == 200, guessed.text


async def test_quitting_ends_the_game_and_frees_the_seat(client, db_session: AsyncSession) -> None:
    world = await build_world(db_session)
    await login(client, world.learner_a)
    started = await client.post("/api/games/number_guess/sessions", json={"difficulty": 1})
    assert started.status_code == 201, started.text
    session_id = uuid.UUID(started.json()["session_id"])
    await _act(client, str(session_id), type_="round_seen")

    quit_response = await client.post(f"/api/games/sessions/{session_id}/quit")
    assert quit_response.status_code == 204, quit_response.text

    row = await repo.get_session(db_session, session_id)
    assert row is not None and row.status == "abandoned" and row.ended_at is not None
    participant = await repo.get_participant(db_session, session_id, world.learner_a.id)
    assert participant is not None and participant.attempt_status == "expired"
    # Nothing was scored, so there is no result to stand behind.
    assert (
        await repo.live_result(db_session, session_id=session_id, user_id=world.learner_a.id)
        is None
    )

    # The seat is free: the next game starts normally.
    again = await client.post("/api/games/number_guess/sessions", json={"difficulty": 1})
    assert again.status_code == 201, again.text

    # Quitting twice is not an error on a slow double tap.
    twice = await client.post(f"/api/games/sessions/{again.json()['session_id']}/quit")
    assert twice.status_code == 204
    third = await client.post(f"/api/games/sessions/{again.json()['session_id']}/quit")
    assert third.status_code == 204


async def test_quitting_a_challenge_closes_it_for_the_one_who_played(
    client, db_session: AsyncSession
) -> None:
    world = await build_world(db_session)
    await login(client, world.learner_a)
    created = await client.post(
        "/api/games/challenges",
        json={"game_id": "number_guess", "difficulty": 1, "invitee_id": str(world.learner_a2.id)},
    )
    assert created.status_code == 201, created.text
    parent_id = created.json()["parent_id"]

    await login(client, world.learner_a2)
    accepted = await client.post(
        "/api/games/invites/accept",
        json={"invitation_id": created.json()["invitation_id"]},
    )
    assert accepted.status_code == 200, accepted.text
    child_b = accepted.json()["session_id"]

    # Amara plays her turn properly.
    await login(client, world.learner_a)
    mine = await client.post(f"/api/games/challenges/{parent_id}/start")
    assert mine.status_code == 200, mine.text
    await _play_all(client, db_session, mine.json()["session_id"])

    parent = await repo.get_session(db_session, uuid.UUID(parent_id))
    assert parent is not None and parent.status != "finished"  # still waiting

    # Bayo leaves instead of playing, and the challenge closes there and then.
    await login(client, world.learner_a2)
    quit_response = await client.post(f"/api/games/sessions/{child_b}/quit")
    assert quit_response.status_code == 204, quit_response.text

    await db_session.refresh(parent)
    assert parent.status == "finished"

    # The one who played keeps the result they earned, with no win bonus.
    kept = await repo.live_result(
        db_session, session_id=uuid.UUID(mine.json()["session_id"]), user_id=world.learner_a.id
    )
    assert kept is not None
    assert kept.outcome == "completed"
    assert kept.supersedes_id is None

    # The one who left gets nothing at all.
    nothing = await repo.live_result(
        db_session, session_id=uuid.UUID(child_b), user_id=world.learner_a2.id
    )
    assert nothing is None
    # Inside a challenge an attempt that produced nothing reads `expired`: the
    # plan's own word for a seat with no result, whichever way it got there.
    child = await repo.get_session(db_session, uuid.UUID(child_b))
    assert child is not None and child.status == "expired"

    # And the sentence names what happened, rather than blaming the clock.
    await login(client, world.learner_a)
    inbox = await client.get("/api/games/inbox")
    assert inbox.status_code == 200
    bodies = [row["body"] for row in inbox.json()["notifications"]]
    assert "Bayo stopped playing." in bodies


async def test_a_quit_after_the_window_does_not_invent_a_result(
    client, db_session: AsyncSession
) -> None:
    """Quitting an already-finished attempt changes nothing."""
    world = await build_world(db_session)
    await login(client, world.learner_a)
    started = await client.post("/api/games/number_guess/sessions", json={"difficulty": 1})
    session_id = uuid.UUID(started.json()["session_id"])
    await _play_all(client, db_session, str(session_id))

    before = await repo.live_result(db_session, session_id=session_id, user_id=world.learner_a.id)
    assert before is not None
    assert (await client.post(f"/api/games/sessions/{session_id}/quit")).status_code == 204

    row = await repo.get_session(db_session, session_id)
    assert row is not None and row.status == "finished"
    after = await repo.live_result(db_session, session_id=session_id, user_id=world.learner_a.id)
    assert after is not None and after.id == before.id
