"""Phase 6: Number Guess (P6-T01 .. P6-T06).

The promises under test, in the plan's own terms:

- the difficulty table is Easy 1-50 / 8 tries, Medium 1-200 / 9, Hard 1-1000 /
  10, and a perfect binary search always fits inside the tries;
- **the secret and the seed never reach a response** (D-25) — and the secret is
  not even stored, so the only way to a number is the seed plus the position;
- a wrong guess spends a try and shrinks the window; an out-of-range or repeated
  guess spends nothing, because it is a slip, not an answer;
- five numbers make a session, score is ``round(100 * (N - k + 1) / N)`` per
  number, and XP follows the result;
- **a session that solves fewer than two numbers awards zero XP** but still
  writes an auditable ledger row (D-29);
- the game needs no content packs (P6-T05) and is in the catalog.

Time is injected wherever a deadline matters, so nothing sleeps.
"""

from __future__ import annotations

import datetime as dt
import uuid

import pytest
from app.games import repository as repo
from app.games.domain import guessing as game
from app.games.models import GameSession, GameXpEntry
from sqlalchemy import select
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


async def _start(client, difficulty: int = 1) -> dict[str, object]:
    response = await client.post(
        "/api/games/number_guess/sessions", json={"difficulty": difficulty}
    )
    assert response.status_code == 201, response.text
    return dict(response.json())


async def _secret_for(db: AsyncSession, session_id: str, index: int, difficulty: int = 1) -> int:
    """Test-only: the number the server will never send."""
    row = await repo.get_session(db, uuid.UUID(session_id))
    assert row is not None and row.seed is not None
    return game.secret_for(row.seed, index, difficulty)


# --------------------------------------------------------------------- rules
def test_the_difficulty_table_is_the_one_in_the_plan() -> None:
    easy, medium, hard = game.level_for(1), game.level_for(2), game.level_for(3)
    assert (easy.low, easy.high, easy.tries) == (1, 50, 8)
    assert (medium.low, medium.high, medium.tries) == (1, 200, 9)
    assert (hard.low, hard.high, hard.tries) == (1, 1000, 10)


def test_an_unknown_difficulty_is_a_clear_failure() -> None:
    with pytest.raises(ValueError):
        game.level_for(7)


@pytest.mark.parametrize("difficulty", [1, 2, 3])
def test_a_perfect_binary_search_always_fits_in_the_tries(difficulty: int) -> None:
    """The sanity check the plan asks for: the tries are enough, not generous."""
    level = game.level_for(difficulty)
    for seed in range(200):
        secret = game.secret_for(seed, 0, difficulty)
        low, high = level.low, level.high
        used = 0
        while low <= high:
            used += 1
            guess = (low + high) // 2
            verdict = game.compare(secret, guess)
            if verdict == "correct":
                break
            low, high = game.narrow(low, high, guess, verdict)
        assert used <= level.tries, (difficulty, seed, secret, used)


def test_the_score_falls_with_every_try() -> None:
    # First try out of eight is the whole hundred; the last try is a sliver.
    assert game.score_for(attempt=1, tries=8) == 100
    assert game.score_for(attempt=8, tries=8) == 13
    assert game.score_for(attempt=1, tries=10) == 100
    assert game.score_for(attempt=5, tries=10) == 60
    assert game.score_for(attempt=10, tries=10) == 10
    # Half-up, not banker's rounding: 12.5 points is 13, never 12.
    assert game.score_for(attempt=8, tries=8) == 13


def test_the_secret_is_reproducible_from_the_seed_and_the_position_only() -> None:
    seed = 123456789
    for difficulty, level in game.LEVELS.items():
        numbers = [game.secret_for(seed, index, difficulty) for index in range(5)]
        assert all(level.low <= number <= level.high for number in numbers)
        assert numbers == [game.secret_for(seed, index, difficulty) for index in range(5)]
    # A different seed must move the numbers: this is what makes a replay proof.
    other = [game.secret_for(seed + 1, index, 1) for index in range(5)]
    assert other != [game.secret_for(seed, index, 1) for index in range(5)]


def test_narrowing_moves_only_the_side_the_secret_is_on() -> None:
    assert game.narrow(1, 50, 20, "higher") == (21, 50)
    assert game.narrow(1, 50, 20, "lower") == (1, 19)
    # A correct guess does not narrow anything: the number is over.
    assert game.narrow(1, 50, 20, "correct") == (1, 50)


def test_every_feedback_code_has_one_plain_sentence() -> None:
    for code in ("higher", "lower", "correct", "repeat", "out_of_range"):
        sentence = game.feedback_sentence(code)
        assert sentence.endswith((".", "!"))
        assert "_" not in sentence
        assert len(sentence.split()) <= 8


# ----------------------------------------------------------------------- API
async def test_creating_a_session_hides_the_secret_and_the_seed(
    client, db_session: AsyncSession
) -> None:
    world = await build_world(db_session)
    await login(client, world.learner_a)

    body = await _start(client)
    row = await repo.get_session(db_session, uuid.UUID(str(body["session_id"])))
    assert row is not None and row.seed is not None

    assert body["rounds_total"] == 5
    assert body["round"]["number"] == 1
    assert body["round"]["low"] == 1
    assert body["round"]["high"] == 50
    assert body["round"]["tries_total"] == 8
    assert body["round"]["tries_left"] == 8

    keys = _forbidden_keys(body)
    assert "seed" not in keys
    assert "secret" not in keys
    assert "answer" not in keys
    # Not just absent by name: the number itself must not appear anywhere.
    secret = game.secret_for(row.seed, 0, 1)
    assert f'"{secret}"' not in str(body)


async def test_higher_or_lower_spends_one_try(client, db_session: AsyncSession) -> None:
    world = await build_world(db_session)
    await login(client, world.learner_a)
    created = await _start(client)
    session_id = str(created["session_id"])

    await _act(client, session_id, type_="round_seen")
    secret = await _secret_for(db_session, session_id, 0)
    wrong = 1 if secret != 1 else 2

    body = (await _act(client, session_id, type_="guess", value=str(wrong))).json()
    assert body["round"]["feedback"] == ("higher" if secret > wrong else "lower")
    assert body["round"]["tries_left"] == 7
    assert body["round_index"] == 0
    assert body["round"]["guesses"] == [wrong]
    assert body["message"]
    # The window narrows against the guess, not against the secret.
    if secret > wrong:
        assert body["round"]["low"] == wrong + 1
    else:
        assert body["round"]["high"] == wrong - 1


async def test_a_slip_costs_no_try(client, db_session: AsyncSession) -> None:
    world = await build_world(db_session)
    await login(client, world.learner_a)
    created = await _start(client)
    session_id = str(created["session_id"])

    await _act(client, session_id, type_="round_seen")

    # Outside the box: the pad already shows 1-50, so this is a slip.
    outside = (await _act(client, session_id, type_="guess", value="9999")).json()
    assert outside["round"]["feedback"] == "out_of_range"
    assert outside["round"]["tries_left"] == 8
    assert outside["scores"] == []

    # Repeating a number the learner already tried is free too.
    secret = await _secret_for(db_session, session_id, 0)
    first = 1 if secret != 1 else 2
    await _act(client, session_id, type_="guess", value=str(first))
    repeat = (await _act(client, session_id, type_="guess", value=str(first))).json()
    assert repeat["round"]["feedback"] == "repeat"
    assert repeat["round"]["tries_left"] == 7  # only the first guess spent one


async def test_a_guess_before_the_number_starts_is_refused(
    client, db_session: AsyncSession
) -> None:
    world = await build_world(db_session)
    await login(client, world.learner_a)
    created = await _start(client)

    response = await _act(client, str(created["session_id"]), type_="guess", value="20")
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "round_not_started"


async def test_finding_all_five_numbers_finishes_with_full_marks_and_xp(
    client, db_session: AsyncSession
) -> None:
    world = await build_world(db_session)
    await login(client, world.learner_a)
    created = await _start(client)
    session_id = str(created["session_id"])

    body: dict[str, object] = {}
    for index in range(5):
        await _act(client, session_id, type_="round_seen")
        secret = await _secret_for(db_session, session_id, index)
        body = (await _act(client, session_id, type_="guess", value=str(secret))).json()

    assert body["finished"] is True
    assert body["scores"] == [100, 100, 100, 100, 100]
    assert body["score"] == 500
    # Participation 5 + full performance bonus 10.
    assert body["xp"] == {"awarded": 15, "today": 15, "daily_cap": body["xp"]["daily_cap"]}

    result = await repo.live_result(
        db_session, session_id=uuid.UUID(session_id), user_id=world.learner_a.id
    )
    assert result is not None
    assert result.details["solved"] == 5
    assert result.details["game_id"] == "number_guess"


async def test_a_session_under_the_minimum_writes_xp_but_awards_none(
    client, db_session: AsyncSession
) -> None:
    world = await build_world(db_session)
    await login(client, world.learner_a)
    created = await _start(client)
    session_id = str(created["session_id"])

    # One number found, four given up: below the D-29 minimum of two.
    await _act(client, session_id, type_="round_seen")
    secret = await _secret_for(db_session, session_id, 0)
    await _act(client, session_id, type_="guess", value=str(secret))
    for _ in range(4):
        await _act(client, session_id, type_="round_seen")
        body = (await _act(client, session_id, type_="skip")).json()

    assert body["finished"] is True
    assert body["xp"]["awarded"] == 0

    rows = list(
        (
            await db_session.execute(
                select(GameXpEntry).where(GameXpEntry.session_id == uuid.UUID(session_id))
            )
        )
        .scalars()
        .all()
    )
    assert len(rows) == 1
    assert rows[0].reason == "below_minimum"
    assert rows[0].requested_amount == 0
    assert rows[0].leaderboard_eligible is False


async def test_running_out_of_tries_ends_that_number(client, db_session: AsyncSession) -> None:
    world = await build_world(db_session)
    await login(client, world.learner_a)
    created = await _start(client)
    session_id = str(created["session_id"])

    await _act(client, session_id, type_="round_seen")
    secret = await _secret_for(db_session, session_id, 0)
    wrong = [number for number in range(2, 50) if number != secret][:8]

    body: dict[str, object] = {}
    for number in wrong:
        body = (await _act(client, session_id, type_="guess", value=str(number))).json()

    # Eight wrong guesses is eight tries: the number is over with no points.
    assert body["round_index"] == 1
    assert body["scores"] == [0]
    assert "It was" in str(body["message"])


async def test_the_catalog_lists_the_new_game(client, db_session: AsyncSession) -> None:
    world = await build_world(db_session)
    await login(client, world.learner_a)

    response = await client.get("/api/games/catalog")
    assert response.status_code == 200
    ids = {row["id"] for row in response.json()}
    assert "number_guess" in ids


async def test_the_game_needs_no_content_packs(client, db_session: AsyncSession) -> None:
    """P6-T05: a brand new school can play with an empty content table."""
    world = await build_world(db_session)
    await login(client, world.learner_a)

    body = await _start(client, difficulty=2)
    assert body["rounds_total"] == 5
    assert body["round"]["low"] == 1
    assert body["round"]["high"] == 200


async def _row(db: AsyncSession, session_id: str) -> GameSession:
    row = await repo.get_session(db, uuid.UUID(session_id))
    assert row is not None
    return row


# ------------------------------------------------------- the entry control, P6-T03
@pytest.mark.asyncio
@pytest.mark.parametrize("difficulty", [1, 2, 3])
async def test_the_round_payload_names_its_band(
    client, db_session: AsyncSession, difficulty: int
) -> None:
    """The screen picks its entry control from the band, so the band must be sent.

    Easy and Medium draw the 12-key pad; Hard keeps the typed box and the big
    button. Inferring that from the range width would silently change the screen
    if a level's range ever moved.
    """
    world = await build_world(db_session)
    await login(client, world.learner_a)

    body = await _start(client, difficulty=difficulty)
    assert body["round"]["difficulty"] == difficulty


@pytest.mark.asyncio
async def test_a_number_that_runs_out_says_which_number_it_was(
    client, db_session: AsyncSession
) -> None:
    """D.2.3: the consequence is spoken, and the next number must not arrive silently.

    The screen used to draw the fresh round with no word about the old one, so a
    learner who paused mid-entry saw the board reset for no visible reason.
    """
    world = await build_world(db_session)
    await login(client, world.learner_a)
    created = await _start(client)
    session_id = str(created["session_id"])
    await _act(client, session_id, type_="round_seen")

    secret = await _secret_for(db_session, session_id, 0)

    # Wind the clock past the number's deadline: the server reads its own clock,
    # so this is the only honest way to be late without sleeping for a minute.
    row = await _row(db_session, session_id)
    cfg = dict(row.config)
    cfg["round_started_at"] = (
        dt.datetime.now(dt.UTC) - dt.timedelta(seconds=game.ROUND_SECONDS + 5)
    ).isoformat()
    row.config = cfg
    await db_session.commit()

    body = (await client.get(f"/api/games/sessions/{session_id}")).json()

    assert body["message"] == f"Time is up. It was {secret}."
    assert body["round_index"] == 1
    assert body["round"]["number"] == 2
