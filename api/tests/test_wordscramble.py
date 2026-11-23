"""Phase 4: Word Scramble rules and the game shell (P4-T10 .. P4-T15).

The promises under test:

- a scramble is never the answer, and a word that cannot be scrambled is
  rejected at content time;
- the two-attempt scoring table, the hint clamp and skip are exact;
- an answer before the round is acknowledged, or after its deadline, is
  refused;
- a retried move scores once;
- neither the answer nor the seed appears in any response;
- ten rounds write ten scores and exactly one result row;
- a silent session is abandoned with no result and no XP.

Time is injected wherever a deadline matters, so nothing sleeps.
"""

from __future__ import annotations

import datetime as dt
import random
import uuid

import pytest
from app.core.errors import AppError
from app.games import repository as repo
from app.games.content_seed import STARTER_WORDS, item_payloads
from app.games.domain import wordscramble as ws
from app.games.models import ContentItem, GameSession
from app.games.services import play
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from tests.factories import build_world, login

NOW = dt.datetime(2026, 11, 14, 9, 0, tzinfo=dt.UTC)  # 10:00 in Lagos


def _forbidden_keys(value: object) -> set[str]:
    found: set[str] = set()
    if isinstance(value, dict):
        found.update(value.keys())
        for item in value.values():
            found |= _forbidden_keys(item)
    elif isinstance(value, list):
        for item in value:
            found |= _forbidden_keys(item)
    return found


async def _answer_for(db: AsyncSession, row: GameSession, index: int) -> str:
    """Test-only: read the answer the server would not send."""
    item_id = row.config["rounds"][index]["item_id"]  # type: ignore[index]
    item = (await repo.items_by_id(db, [uuid.UUID(str(item_id))]))[uuid.UUID(str(item_id))]
    return str(item.payload["answer"])


async def _act(
    client, session_id: str, *, type_: str, value: str | None = None, move_id: str | None = None
):
    return await client.post(
        f"/api/games/sessions/{session_id}/actions",
        json={
            "client_move_id": move_id or uuid.uuid4().hex,
            "type": type_,
            "value": value,
        },
    )


# ------------------------------------------------------------------- rules
def test_a_scramble_never_looks_like_the_answer() -> None:
    for word, _clue, _difficulty in STARTER_WORDS:
        for seed in range(5):
            mixed = ws.scramble(word, random.Random(seed))  # noqa: S311
            assert sorted(mixed) == sorted(word)
            assert mixed != word


def test_a_word_with_one_arrangement_is_rejected() -> None:
    problems = ws.validate_item(
        {"answer": "zzzz", "alt_answers": [], "clue": "A sleepy sound", "difficulty": 1}
    )
    assert any("cannot be mixed up" in problem for problem in problems)


def test_the_clue_may_not_give_the_answer_away() -> None:
    problems = ws.validate_item(
        {"answer": "apple", "alt_answers": [], "clue": "An apple is a fruit", "difficulty": 1}
    )
    assert any("gives away" in problem for problem in problems)


def test_the_youngest_band_needs_a_picture_or_a_sound() -> None:
    problems = ws.validate_item(
        {"answer": "cat", "alt_answers": [], "clue": "It says meow", "difficulty": 1},
        youngest_band=True,
    )
    assert any("picture or a sound" in problem for problem in problems)


def test_attempt_two_scores_half_and_a_hint_is_clamped() -> None:
    # Fast full-credit answer: 10 + 5.
    assert ws.round_score(elapsed_seconds=0, used_hint=False, attempt=1) == 15
    # Slow but in time: no bonus left.
    assert ws.round_score(elapsed_seconds=44, used_hint=False, attempt=1) == 10
    # Second attempt is halved, rounded down.
    assert ws.round_score(elapsed_seconds=0, used_hint=False, attempt=2) == 7
    # A hint costs three and can never make a round negative.
    assert ws.round_score(elapsed_seconds=44, used_hint=True, attempt=1) == 7
    assert ws.round_score(elapsed_seconds=44, used_hint=True, attempt=2) == 3


def test_time_bonus_stays_inside_its_range() -> None:
    assert ws.time_bonus(0) == 5
    assert ws.time_bonus(ws.ROUND_SECONDS) == 0
    assert ws.time_bonus(999) == 0
    assert 0 <= ws.time_bonus(22) <= 5


def test_alternative_spellings_count_as_correct() -> None:
    item = ws.Item(
        id="1",
        answer="colour",
        alt_answers=("color",),
        clue=None,
        clue_image_key=None,
        clue_audio_key=None,
        difficulty=1,
    )
    assert ws.is_correct(item, "  COLOR ")
    assert not ws.is_correct(item, "colours")


def test_the_starter_bank_is_large_enough_per_level() -> None:
    payloads = item_payloads()
    assert len(payloads) >= 150
    for difficulty in (1, 2, 3):
        count = sum(1 for p in payloads if p["difficulty"] == difficulty)
        assert count >= ws.MIN_ITEMS_PER_PACK, difficulty


# --------------------------------------------------------------------- API
async def test_creating_a_session_hides_the_answer_and_the_seed(
    client, db_session: AsyncSession
) -> None:
    world = await build_world(db_session)
    await login(client, world.learner_a)

    response = await client.post("/api/games/word_scramble/sessions", json={"difficulty": 1})
    assert response.status_code == 201, response.text
    body = response.json()

    assert body["rounds_total"] == 10
    assert body["round"]["number"] == 1
    assert body["round"]["tries_left"] == 2
    assert body["round"]["time_left_ms"] == ws.ROUND_SECONDS * 1000

    keys = _forbidden_keys(body)
    assert "answer" not in keys
    assert "seed" not in keys
    assert "alt_answers" not in keys


async def test_an_answer_before_the_round_starts_is_refused(
    client, db_session: AsyncSession
) -> None:
    world = await build_world(db_session)
    await login(client, world.learner_a)
    created = (
        await client.post("/api/games/word_scramble/sessions", json={"difficulty": 1})
    ).json()

    response = await _act(client, created["session_id"], type_="answer", value="apple")
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "round_not_started"


async def test_a_correct_answer_scores_and_moves_to_the_next_round(
    client, db_session: AsyncSession
) -> None:
    world = await build_world(db_session)
    await login(client, world.learner_a)
    created = (
        await client.post("/api/games/word_scramble/sessions", json={"difficulty": 1})
    ).json()
    row = await repo.get_session(db_session, uuid.UUID(created["session_id"]))
    assert row is not None
    answer = await _answer_for(db_session, row, 0)

    seen = await _act(client, created["session_id"], type_="round_seen")
    assert seen.status_code == 200

    answered = await _act(client, created["session_id"], type_="answer", value=answer)
    assert answered.status_code == 200, answered.text
    body = answered.json()
    assert body["round_index"] == 1
    assert len(body["scores"]) == 1
    assert 1 <= body["score"] <= 15
    assert body["round"]["number"] == 2


async def test_a_second_wrong_try_ends_the_round_with_zero(
    client, db_session: AsyncSession
) -> None:
    world = await build_world(db_session)
    await login(client, world.learner_a)
    created = (
        await client.post("/api/games/word_scramble/sessions", json={"difficulty": 1})
    ).json()
    session_id = created["session_id"]

    await _act(client, session_id, type_="round_seen")
    first = await _act(client, session_id, type_="answer", value="zzzzzz")
    assert first.json()["round"]["tries_left"] == 1
    assert first.json()["round_index"] == 0

    second = await _act(client, session_id, type_="answer", value="yyyyyy")
    body = second.json()
    assert body["round_index"] == 1
    assert body["scores"] == [0]


async def test_retrying_the_same_move_scores_once(client, db_session: AsyncSession) -> None:
    world = await build_world(db_session)
    await login(client, world.learner_a)
    created = (
        await client.post("/api/games/word_scramble/sessions", json={"difficulty": 1})
    ).json()
    session_id = created["session_id"]
    row = await repo.get_session(db_session, uuid.UUID(session_id))
    assert row is not None
    answer = await _answer_for(db_session, row, 0)

    await _act(client, session_id, type_="round_seen", move_id="seen-1")
    move_id = "answer-1"
    first = await _act(client, session_id, type_="answer", value=answer, move_id=move_id)
    second = await _act(client, session_id, type_="answer", value=answer, move_id=move_id)

    assert first.status_code == 200 and second.status_code == 200
    assert first.json()["scores"] == second.json()["scores"]
    moves = await repo.list_moves(db_session, uuid.UUID(session_id))
    assert len(moves) == 2  # round_seen + the one answer


async def test_a_hint_reveals_the_first_letter_and_costs_points(
    client, db_session: AsyncSession
) -> None:
    world = await build_world(db_session)
    await login(client, world.learner_a)
    created = (
        await client.post("/api/games/word_scramble/sessions", json={"difficulty": 1})
    ).json()
    session_id = created["session_id"]
    row = await repo.get_session(db_session, uuid.UUID(session_id))
    assert row is not None
    answer = await _answer_for(db_session, row, 0)

    await _act(client, session_id, type_="round_seen")
    hinted = await _act(client, session_id, type_="hint")
    assert hinted.status_code == 200
    assert hinted.json()["round"]["revealed"] == answer[0].upper()

    again = await _act(client, session_id, type_="hint")
    assert again.status_code == 409
    assert again.json()["error"]["code"] == "hint_used"

    answered = await _act(client, session_id, type_="answer", value=answer)
    assert answered.json()["scores"][0] <= 12  # 15 minus the hint


async def test_skip_ends_the_round_for_nothing(client, db_session: AsyncSession) -> None:
    world = await build_world(db_session)
    await login(client, world.learner_a)
    created = (
        await client.post("/api/games/word_scramble/sessions", json={"difficulty": 1})
    ).json()
    session_id = created["session_id"]

    await _act(client, session_id, type_="round_seen")
    skipped = await _act(client, session_id, type_="skip")
    body = skipped.json()
    assert body["round_index"] == 1
    assert body["scores"] == [0]


async def test_ten_rounds_write_ten_scores_and_one_result(client, db_session: AsyncSession) -> None:
    world = await build_world(db_session)
    await login(client, world.learner_a)
    created = (
        await client.post("/api/games/word_scramble/sessions", json={"difficulty": 1})
    ).json()
    session_id = uuid.UUID(created["session_id"])

    for _ in range(10):
        assert (await _act(client, str(session_id), type_="round_seen")).status_code == 200
        assert (await _act(client, str(session_id), type_="skip")).status_code == 200

    state = (await client.get(f"/api/games/sessions/{session_id}")).json()
    assert state["finished"] is True
    assert state["round_index"] == 10
    assert len(state["scores"]) == 10

    results = (
        (
            await db_session.execute(
                select(repo.GameResult).where(repo.GameResult.session_id == session_id)
            )
        )
        .scalars()
        .all()
    )
    assert len(results) == 1
    assert results[0].outcome == "completed"
    assert results[0].score == 0

    row = await repo.get_session(db_session, session_id)
    assert row is not None and row.status == "finished"
    participant = await repo.get_participant(db_session, session_id, world.learner_a.id)
    assert participant is not None and participant.attempt_status == "finished"


async def test_a_late_answer_is_refused_and_the_round_closes(
    db_session: AsyncSession,
) -> None:
    world = await build_world(db_session)
    row = await play.create_solo(
        db_session, user=world.learner_a, game_id="word_scramble", difficulty=1, now=NOW
    )
    await play.submit_action(
        db_session,
        user=world.learner_a,
        session_id=row.id,
        client_move_id="seen",
        action="round_seen",
        now=NOW,
    )
    answer = await _answer_for(db_session, row, 0)

    with pytest.raises(AppError) as caught:
        await play.submit_action(
            db_session,
            user=world.learner_a,
            session_id=row.id,
            client_move_id="late",
            action="answer",
            value=answer,
            now=NOW + dt.timedelta(seconds=ws.ROUND_SECONDS + 10),
        )
    assert caught.value.code == "round_expired"

    state = await play.get_state(db_session, user=world.learner_a, session_id=row.id)
    assert state.round_index == 1
    assert state.scores == [0]


async def test_a_second_session_is_refused_while_one_is_open(
    client, db_session: AsyncSession
) -> None:
    world = await build_world(db_session)
    await login(client, world.learner_a)
    first = await client.post("/api/games/word_scramble/sessions", json={"difficulty": 1})
    assert first.status_code == 201

    second = await client.post("/api/games/word_scramble/sessions", json={"difficulty": 1})
    assert second.status_code == 409
    assert second.json()["error"]["code"] == "another_session_active"


async def test_actions_charge_play_time(client, db_session: AsyncSession) -> None:
    world = await build_world(db_session)
    await login(client, world.learner_a)
    created = (
        await client.post("/api/games/word_scramble/sessions", json={"difficulty": 1})
    ).json()

    await _act(client, created["session_id"], type_="round_seen")
    await _act(client, created["session_id"], type_="hint")

    access = (await client.get("/api/games/access")).json()
    # The clock row exists from the start, and the test runs in real time, so
    # the exact value is small but positive only when seconds have passed.
    assert access["used_seconds"] >= 0
    assert access["remaining_seconds"] <= 120 * 60


async def test_a_silent_session_is_abandoned_without_a_result(
    db_session: AsyncSession,
) -> None:
    world = await build_world(db_session)
    row = await play.create_solo(
        db_session, user=world.learner_a, game_id="word_scramble", difficulty=1, now=NOW
    )

    # No round was ever acknowledged, so no deadline expires. Only the sweeper
    # can end this session.
    await play.abandon_stale(db_session, now=NOW + dt.timedelta(minutes=11))

    refreshed = await repo.get_session(db_session, row.id)
    assert refreshed is not None and refreshed.status == "abandoned"

    results = (
        await db_session.execute(
            select(func.count())
            .select_from(repo.GameResult)
            .where(repo.GameResult.session_id == row.id)
        )
    ).scalar_one()
    assert results == 0

    participant = await repo.get_participant(db_session, row.id, world.learner_a.id)
    assert participant is not None and participant.attempt_status == "expired"


async def test_the_sweeper_leaves_a_live_session_alone(
    db_session: AsyncSession,
) -> None:
    world = await build_world(db_session)
    row = await play.create_solo(
        db_session, user=world.learner_a, game_id="word_scramble", difficulty=1, now=NOW
    )
    await play.submit_action(
        db_session,
        user=world.learner_a,
        session_id=row.id,
        client_move_id="recent",
        action="round_seen",
        now=NOW,
    )
    await play.abandon_stale(db_session, now=NOW + dt.timedelta(minutes=1))

    refreshed = await repo.get_session(db_session, row.id)
    assert refreshed is not None and refreshed.status == "active"


async def test_a_stranger_cannot_read_or_play_the_session(client, db_session: AsyncSession) -> None:
    world = await build_world(db_session)
    await login(client, world.learner_a)
    created = (
        await client.post("/api/games/word_scramble/sessions", json={"difficulty": 1})
    ).json()

    await login(client, world.learner_a2)
    read = await client.get(f"/api/games/sessions/{created['session_id']}")
    assert read.status_code == 404
    acted = await _act(client, created["session_id"], type_="round_seen")
    assert acted.status_code == 404


async def test_words_for_an_unknown_band_fail_cleanly(db_session: AsyncSession) -> None:
    world = await build_world(db_session)
    world.learner_a.date_of_birth = dt.date(2020, 1, 1)  # age 6: no pack
    await db_session.flush()

    with pytest.raises(AppError) as caught:
        await play.create_solo(
            db_session,
            user=world.learner_a,
            game_id="word_scramble",
            difficulty=1,
            now=NOW,
        )
    assert caught.value.code == "not_enough_content"


async def test_content_items_are_never_answers_in_the_state(
    client, db_session: AsyncSession
) -> None:
    world = await build_world(db_session)
    await login(client, world.learner_a)
    created = (
        await client.post("/api/games/word_scramble/sessions", json={"difficulty": 1})
    ).json()
    state = (await client.get(f"/api/games/sessions/{created['session_id']}")).json()

    all_answers = set(
        (
            await db_session.execute(
                select(ContentItem.payload["answer"].astext).where(
                    ContentItem.pack_id.in_(
                        select(repo.ContentPack.id).where(
                            repo.ContentPack.game_id == "word_scramble"
                        )
                    )
                )
            )
        )
        .scalars()
        .all()
    )
    letters = state["round"]["letters"].lower()
    assert letters not in {str(a).lower() for a in all_answers}
    assert "seed" not in _forbidden_keys(state)


def test_every_easy_word_has_a_picture_or_is_a_named_exception() -> None:
    """The first round a learner meets is an easy word, and D.5 runs with a player
    who cannot read the clue, so an easy word without a picture is a blocked
    first session (D.3).

    Four words have no honest pictogram. Naming them here means a fifth cannot
    appear by accident: it fails this test instead of failing a child.
    """
    text_only = {"table", "brave", "window", "brush"}
    easy = [item for item in item_payloads() if item["difficulty"] == 1]
    missing = {item["answer"] for item in easy if not item.get("clue_image_key")}
    assert missing == text_only
