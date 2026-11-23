"""Phase 7: invitations, challenges, blocks and the inbox (P7-T01 .. P7-T11).

The promises, in the plan's own words:

- a challenge is **one parent and two children on one seed** (D-28), the parent
  is never played, and the two children cannot collide;
- **only hashes are stored** (D-31): a code exists in plaintext for exactly one
  response, and the alphabet has no characters a child can misread;
- every failed redemption says the same sentence, whether the code is wrong,
  expired, already taken, or belongs to another school (P7-T04);
- a block stops invites **both ways** and is never announced (P7-T08);
- the winner is decided by comparing the two attempts, not by who finished
  first, and the winner's +5 is its own ledger row;
- a learner who never plays leaves no result, and the learner who did keeps the
  result they earned with no bonus;
- the pair cap and the daily time limit hold.

Time is injected where a window matters, so nothing sleeps.
"""

from __future__ import annotations

import datetime as dt
import uuid

from app.games import repository as repo
from app.games.domain import guessing as guess_rules
from app.games.domain import invites as invite_rules
from app.games.models import GameInvitation, GameXpEntry
from app.games.services import challenge as challenge_service
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from tests.factories import build_world, login

NOW = dt.datetime(2026, 11, 14, 9, 0, tzinfo=dt.UTC)  # 10:00 in Lagos


# --------------------------------------------------------------------- helpers
async def _create(
    client,
    *,
    invitee_id: uuid.UUID | None = None,
    game_id: str = "number_guess",
    with_link: bool = False,
) -> dict:
    response = await client.post(
        "/api/games/challenges",
        json={
            "game_id": game_id,
            "difficulty": 1,
            "invitee_id": str(invitee_id) if invitee_id else None,
            "with_code": True,
            "with_link": with_link,
        },
    )
    assert response.status_code == 201, response.text
    return dict(response.json())


async def _act(client, session_id: str, *, type_: str, value: str | None = None):
    return await client.post(
        f"/api/games/sessions/{session_id}/actions",
        json={"client_move_id": uuid.uuid4().hex, "type": type_, "value": value},
    )


async def _secret_for(db: AsyncSession, session_id: str, index: int, difficulty: int = 1) -> int:
    row = await repo.get_session(db, uuid.UUID(session_id))
    assert row is not None and row.seed is not None
    return guess_rules.secret_for(row.seed, index, difficulty)


def _school_today(range_hours: int = 1) -> dt.date:
    """Today where the school is, which is what every allowance uses."""
    offset = dt.timezone(dt.timedelta(hours=range_hours))
    return dt.datetime.now(dt.UTC).astimezone(offset).date()


async def _play_all(client, db: AsyncSession, session_id: str, *, solve_on: int = 1) -> dict:
    """Finish a Number Guess attempt, solving every number on the given try."""
    state: dict = {}
    for index in range(guess_rules.ROUNDS):
        seen = await _act(client, session_id, type_="round_seen")
        assert seen.status_code == 200, seen.text
        secret = await _secret_for(db, session_id, index)
        for attempt in range(1, solve_on + 1):
            guess = secret if attempt == solve_on else _wrong_for(secret, attempt)
            response = await _act(client, session_id, type_="guess", value=str(guess))
            assert response.status_code == 200, response.text
            state = dict(response.json())
    assert state["finished"] is True, state
    return state


def _wrong_for(secret: int, attempt: int) -> int:
    """A guess that is certainly wrong and inside the 1..50 window."""
    candidate = secret + attempt
    if candidate > 50:
        candidate = secret - attempt
    return candidate


# ------------------------------------------------------------------- the rules
def test_the_code_alphabet_has_no_characters_a_child_can_misread() -> None:
    assert invite_rules.CODE_ALPHABET == "ABCDEFGHJKMNPQRSTUVWXYZ23456789"
    for confusing in ("I", "L", "O", "0", "1"):
        assert confusing not in invite_rules.CODE_ALPHABET


def test_a_code_is_eight_characters_and_is_shown_in_two_groups() -> None:
    code = invite_rules.generate_code()
    assert len(code) == 8
    assert all(character in invite_rules.CODE_ALPHABET for character in code)
    assert invite_rules.format_code(code) == f"{code[:4]} {code[4:]}"


def test_what_a_learner_types_is_read_kindly() -> None:
    assert invite_rules.normalise_code("abcd efgh") == invite_rules.normalise_code("ABCDEFGH")
    assert invite_rules.normalise_code("ABCD-EFGH") == "ABCDEFGH"
    # Too short, and a character that is not in the alphabet, are simply not codes.
    assert invite_rules.normalise_code("ABC") is None
    assert invite_rules.normalise_code("ABCDEFGI") is None  # I is not in it


def test_the_comparison_is_from_one_players_side() -> None:
    assert invite_rules.compare_scores(10, 5) == "win"
    assert invite_rules.compare_scores(5, 10) == "loss"
    assert invite_rules.compare_scores(7, 7) == "draw"


def test_each_result_has_one_short_sentence() -> None:
    assert invite_rules.result_sentence("Word Scramble", "win", "Bayo") == (
        "You won Word Scramble against Bayo."
    )
    assert invite_rules.result_sentence("Word Scramble", "loss", "Bayo") == (
        "Bayo won Word Scramble this time."
    )
    assert invite_rules.result_sentence("Word Scramble", "draw", "Bayo") == (
        "It was a draw with Bayo."
    )


# -------------------------------------------------------------- one parent, two children
async def test_a_challenge_is_one_parent_and_two_children_on_one_seed(
    client, db_session: AsyncSession
) -> None:
    world = await build_world(db_session)
    await login(client, world.learner_a)

    created = await _create(client, invitee_id=world.learner_a2.id)
    parent = await repo.get_session(db_session, uuid.UUID(created["parent_id"]))
    assert parent is not None and parent.mode == "challenge"

    children = await repo.child_sessions(db_session, parent_id=parent.id)
    assert len(children) == 2
    # One seed, two attempts: this is the whole fairness of a challenge (D-28).
    assert {child.seed for child in children} == {parent.seed}
    assert children[0].mode == "solo" and children[1].mode == "solo"
    assert children[0].config == children[1].config

    # The parent holds no participant that counts as an open play, and no moves.
    participants = await repo.list_participants(db_session, parent.id)
    assert participants and all(not row.counts_as_active for row in participants)
    assert await repo.list_moves(db_session, parent.id) == []


async def test_the_invite_stores_only_hashes(client, db_session: AsyncSession) -> None:
    world = await build_world(db_session)
    await login(client, world.learner_a)
    created = await _create(client, with_link=True)

    assert created["code"] and created["join_path"]
    row = (
        (
            await db_session.execute(
                select(GameInvitation).where(
                    GameInvitation.id == uuid.UUID(created["invitation_id"])
                )
            )
        )
        .scalars()
        .one()
    )

    plain_code = created["formatted_code"].replace(" ", "")
    token = created["join_path"].split("t=", 1)[1]
    assert row.code_hash == invite_rules.hash_secret(plain_code)
    assert row.token_hash == invite_rules.hash_secret(token)
    # Neither the code nor the token is in the row in any readable form.
    for value in (row.code_hash, row.token_hash):
        assert value and value not in (plain_code, token)
        assert len(value) == 64  # sha256 hex


# ------------------------------------------------------------------- redemption
async def test_a_roster_tap_is_accepted_by_the_learner_it_names(
    client, db_session: AsyncSession
) -> None:
    world = await build_world(db_session)
    await login(client, world.learner_a)
    created = await _create(client, invitee_id=world.learner_a2.id)

    await login(client, world.learner_a2)
    accepted = await client.post(
        "/api/games/invites/accept",
        json={"invitation_id": created["invitation_id"]},
    )
    assert accepted.status_code == 200, accepted.text
    body = accepted.json()
    assert body["parent_id"] == created["parent_id"]
    assert body["game_id"] == "number_guess"

    child = await repo.get_session(db_session, uuid.UUID(body["session_id"]))
    assert child is not None and child.parent_session_id == uuid.UUID(created["parent_id"])


async def test_every_failed_redeem_says_the_same_sentence(client, db_session: AsyncSession) -> None:
    world = await build_world(db_session)
    await login(client, world.learner_a)
    created = await _create(client)

    # Another school's learner, a wrong code, and an expired code all answer
    # identically: otherwise a code "does not exist" tells you it might (P7-T04).
    await login(client, world.learner_b)
    cross_school = await client.post(
        "/api/games/invites/accept", json={"code": created["formatted_code"]}
    )
    await login(client, world.learner_a2)
    wrong = await client.post("/api/games/invites/accept", json={"code": "ZZZZ ZZZZ"})
    nothing = await client.post("/api/games/invites/accept", json={})

    assert cross_school.status_code == wrong.status_code == nothing.status_code == 404
    detail = cross_school.json()["error"]["message"]
    assert wrong.json()["error"]["message"] == detail
    assert nothing.json()["error"]["message"] == detail


async def test_an_expired_code_does_not_work(client, db_session: AsyncSession) -> None:
    world = await build_world(db_session)
    await login(client, world.learner_a)
    created = await _create(client)

    row = await repo.get_invitation(db_session, uuid.UUID(created["invitation_id"]))
    assert row is not None
    row.expires_at = dt.datetime.now(dt.UTC) - dt.timedelta(minutes=1)
    await db_session.flush()

    await login(client, world.learner_a2)
    response = await client.post(
        "/api/games/invites/accept", json={"code": created["formatted_code"]}
    )
    assert response.status_code == 404


async def test_a_code_works_once(client, db_session: AsyncSession) -> None:
    """Two taps on one seat: the second finds nothing left to claim."""
    world = await build_world(db_session)
    await login(client, world.learner_a)
    created = await _create(client)

    await login(client, world.learner_a2)
    first = await client.post("/api/games/invites/accept", json={"code": created["formatted_code"]})
    assert first.status_code == 200, first.text
    second = await client.post(
        "/api/games/invites/accept", json={"code": created["formatted_code"]}
    )
    assert second.status_code == 404


async def test_the_link_token_is_consumed_from_the_cookie(client, db_session: AsyncSession) -> None:
    world = await build_world(db_session)
    await login(client, world.learner_a)
    created = await _create(client, with_link=True)
    token = created["join_path"].split("t=", 1)[1]

    await login(client, world.learner_a2)
    # The join page sets it with path=/, which is what the API's delete matches.
    client.cookies.set("invite_token", token, path="/")
    accepted = await client.post("/api/games/invites/pending")
    assert accepted.status_code == 200, accepted.text
    assert accepted.json()["parent_id"] == created["parent_id"]
    # The API sends a clearing cookie, so a shared laptop does not join twice.
    cleared = accepted.headers.get_list("set-cookie")
    assert any(header.startswith("invite_token=") for header in cleared), cleared

    again = await client.post("/api/games/invites/pending")
    assert again.status_code == 404


# ---------------------------------------------------------------------- blocks
async def test_a_block_stops_invites_both_ways_and_is_silent(
    client, db_session: AsyncSession
) -> None:
    world = await build_world(db_session)
    await login(client, world.learner_a2)
    blocked = await client.post(
        "/api/games/blocks", json={"user_id": str(world.learner_a.id), "type": "block"}
    )
    assert blocked.status_code == 204

    # The blocker cannot invite the blocked learner...
    await login(client, world.learner_a)
    response = await client.post(
        "/api/games/challenges",
        json={"game_id": "number_guess", "difficulty": 1, "invitee_id": str(world.learner_a2.id)},
    )
    assert response.status_code == 404

    # ...and the blocked learner cannot invite back either, because the check
    # runs in both directions and says nothing about why (P7-T08).
    await login(client, world.learner_a2)
    back = await client.post(
        "/api/games/challenges",
        json={"game_id": "number_guess", "difficulty": 1, "invitee_id": str(world.learner_a.id)},
    )
    assert back.status_code == 404


async def test_a_blocked_learner_is_not_on_the_roster(client, db_session: AsyncSession) -> None:
    world = await build_world(db_session)
    await login(client, world.learner_a2)
    await client.post(
        "/api/games/blocks", json={"user_id": str(world.learner_a.id), "type": "block"}
    )

    await login(client, world.learner_a)
    roster = await client.get("/api/games/friends")
    assert roster.status_code == 200
    assert all(row["id"] != str(world.learner_a2.id) for row in roster.json())


# -------------------------------------------------------------- playing it out
async def test_two_learners_play_the_same_puzzle_and_one_wins(
    client, db_session: AsyncSession
) -> None:
    world = await build_world(db_session)
    await login(client, world.learner_a)
    created = await _create(client, invitee_id=world.learner_a2.id)
    parent_id = created["parent_id"]

    # Bayo accepts and plays first: it does not matter who is first.
    await login(client, world.learner_a2)
    accepted = await client.post(
        "/api/games/invites/accept", json={"invitation_id": created["invitation_id"]}
    )
    child_b = accepted.json()["session_id"]
    started_b = await client.post(f"/api/games/challenges/{parent_id}/start")
    assert started_b.status_code == 200, started_b.text
    await _play_all(client, db_session, child_b, solve_on=3)

    # Amara plays second and solves every number on the first try, so she wins.
    await login(client, world.learner_a)
    started_a = await client.post(f"/api/games/challenges/{parent_id}/start")
    assert started_a.status_code == 200, started_a.text
    child_a = started_a.json()["session_id"]
    assert child_a != child_b
    await _play_all(client, db_session, child_a, solve_on=1)

    # Both children carry the comparison, and it is a comparison of scores.
    result_a = await repo.live_result(
        db_session, session_id=uuid.UUID(child_a), user_id=world.learner_a.id
    )
    result_b = await repo.live_result(
        db_session, session_id=uuid.UUID(child_b), user_id=world.learner_a2.id
    )
    assert result_a is not None and result_b is not None
    assert (result_a.outcome, result_b.outcome) == ("win", "loss")
    assert result_a.supersedes_id is not None and result_b.supersedes_id is not None
    assert result_a.details["challenge"]["opponent_id"] == str(world.learner_a2.id)

    # The win bonus is its own ledger row, paid once (P7-T05).
    bonus = (
        (
            await db_session.execute(
                select(GameXpEntry).where(
                    GameXpEntry.session_id == uuid.UUID(child_a),
                    GameXpEntry.user_id == world.learner_a.id,
                    GameXpEntry.reason == "challenge_win",
                )
            )
        )
        .scalars()
        .all()
    )
    assert len(bonus) == 1 and bonus[0].awarded_amount > 0
    loser_bonus = (
        (
            await db_session.execute(
                select(GameXpEntry).where(
                    GameXpEntry.session_id == uuid.UUID(child_b),
                    GameXpEntry.reason == "challenge_win",
                )
            )
        )
        .scalars()
        .all()
    )
    assert loser_bonus == []

    # Both are told, in one sentence, and can read it in the inbox.
    await login(client, world.learner_a2)
    inbox = await client.get("/api/games/inbox")
    assert inbox.status_code == 200
    bodies = [row["body"] for row in inbox.json()["notifications"]]
    assert "Amara won Number Guess this time." in bodies


async def test_an_unfinished_child_expires_while_the_finisher_keeps_their_result(
    client, db_session: AsyncSession
) -> None:
    world = await build_world(db_session)
    await login(client, world.learner_a)
    created = await _create(client, invitee_id=world.learner_a2.id)

    await login(client, world.learner_a2)
    accepted = await client.post(
        "/api/games/invites/accept", json={"invitation_id": created["invitation_id"]}
    )
    child_b = uuid.UUID(accepted.json()["session_id"])
    await client.post(f"/api/games/challenges/{created['parent_id']}/start")
    # Bayo walks away: no round is ever seen, so there is no result.

    await login(client, world.learner_a)
    started = await client.post(f"/api/games/challenges/{created['parent_id']}/start")
    child_a = uuid.UUID(started.json()["session_id"])
    await _play_all(client, db_session, started.json()["session_id"], solve_on=1)

    parent = await repo.get_session(db_session, uuid.UUID(created["parent_id"]))
    assert parent is not None and parent.status != "finished"  # still waiting

    # The window closes a day later and the job settles it.
    outcome = await challenge_service.sweep(
        db_session, now=dt.datetime.now(dt.UTC) + dt.timedelta(hours=25)
    )
    # The job is global, and this database also holds whatever the dev server
    # left open, so the count is not pinned: the challenge above is the one
    # under test, and it is asserted directly underneath.
    assert outcome["challenges_settled"] >= 1

    await db_session.refresh(parent)
    assert parent.status == "finished"
    still_there = await repo.live_result(db_session, session_id=child_a, user_id=world.learner_a.id)
    assert still_there is not None and still_there.outcome == "completed"
    # No bonus for winning by walkover.
    assert still_there.supersedes_id is None
    absent = await repo.live_result(db_session, session_id=child_b, user_id=world.learner_a2.id)
    assert absent is None


async def test_a_pair_cannot_grind_the_board_together(client, db_session: AsyncSession) -> None:
    world = await build_world(db_session)
    small, large = (
        (world.learner_a.id, world.learner_a2.id)
        if str(world.learner_a.id) < str(world.learner_a2.id)
        else (world.learner_a2.id, world.learner_a.id)
    )
    # One accepted challenge counts once, for the pair, whichever way round.
    await login(client, world.learner_a)
    created = await _create(client, invitee_id=world.learner_a2.id)
    await login(client, world.learner_a2)
    accepted = await client.post(
        "/api/games/invites/accept", json={"invitation_id": created["invitation_id"]}
    )
    assert accepted.status_code == 200, accepted.text
    today = _school_today()
    count = await repo.pair_count(db_session, user_id=small, other_user_id=large, local_date=today)
    assert count == 1

    # Fill the pair's day and the next invite is refused, in plain words.
    cap = challenge_service.DEFAULT_PAIR_CAP
    while count < cap:
        await repo.bump_pair_count(db_session, user_id=small, other_user_id=large, local_date=today)
        count += 1

    await login(client, world.learner_a)
    refused = await client.post(
        "/api/games/challenges",
        json={
            "game_id": "number_guess",
            "difficulty": 1,
            "invitee_id": str(world.learner_a2.id),
        },
    )
    assert refused.status_code == 409
    assert refused.json()["error"]["code"] == "challenge_pair_cap"


async def test_a_learner_over_their_time_limit_cannot_start_but_keeps_the_invite(
    client, db_session: AsyncSession
) -> None:
    world = await build_world(db_session)
    await login(client, world.learner_a)
    created = await _create(client, invitee_id=world.learner_a2.id)

    await login(client, world.learner_a2)
    accepted = await client.post(
        "/api/games/invites/accept", json={"invitation_id": created["invitation_id"]}
    )
    assert accepted.status_code == 200, accepted.text

    # Spend the whole allowance: three hours, more than any default limit.
    from app.games.domain import access as access_rules

    await repo.add_usage(
        db_session,
        user_id=world.learner_a2.id,
        local_date=_school_today(),
        source="heartbeat",
        seconds=10_800,
    )
    await db_session.flush()

    refused = await client.post(f"/api/games/challenges/{created['parent_id']}/start")
    assert refused.status_code == 403
    assert refused.json()["error"]["code"] == access_rules.LIMIT_REACHED

    # The invitation is still accepted and the seat still theirs.
    invitation = await repo.get_invitation(db_session, uuid.UUID(created["invitation_id"]))
    assert invitation is not None and invitation.status == "accepted"


# --------------------------------------------------- guessing a code is slow
async def test_five_wrong_codes_stop_the_guessing(client, db_session: AsyncSession) -> None:
    """P7-T04: a code is 31^8, but a child may still sit there tapping.

    The limiter runs *before* the invite is looked up, so the sixth try is
    refused even when it happens to be the right code — otherwise the answer
    "was that a real code?" would leak one guess at a time.
    """
    world = await build_world(db_session)
    await login(client, world.learner_a)
    created = await _create(client)

    await login(client, world.learner_a2)
    for _ in range(5):
        wrong = await client.post("/api/games/invites/accept", json={"code": "ZZZZ ZZZZ"})
        assert wrong.status_code == 404, wrong.text

    blocked = await client.post(
        "/api/games/invites/accept", json={"code": created["formatted_code"]}
    )
    assert blocked.status_code == 429, blocked.text
    assert blocked.json()["error"]["code"] == "rate_limited"
    assert blocked.headers["retry-after"] == "600"

    # The seat was never taken, so the invite is still good for somebody else.
    row = await repo.get_invitation(db_session, uuid.UUID(created["invitation_id"]))
    assert row is not None and row.status == "pending"


async def test_a_link_is_not_counted_but_a_code_is(client, db_session: AsyncSession) -> None:
    """Only the typed code is guessable, so only it is counted."""
    world = await build_world(db_session)
    await login(client, world.learner_a)
    created = await _create(client, with_link=True)
    token = created["join_path"].split("t=", 1)[1]

    await login(client, world.learner_a2)
    client.cookies.set("invite_token", token, path="/")
    accepted = await client.post("/api/games/invites/pending")
    assert accepted.status_code == 200, accepted.text

    # A single link redemption leaves the code budget untouched.
    await login(client, world.learner_a)
    second = await _create(client)
    await login(client, world.learner_a2)
    response = await client.post(
        "/api/games/invites/accept", json={"code": second["formatted_code"]}
    )
    assert response.status_code == 200, response.text


# ------------------------------------------------------- the end-of-game view
async def test_the_end_screen_waits_then_says_who_won(client, db_session: AsyncSession) -> None:
    """P7-T05, D-25: nothing about the other attempt until both are in."""
    world = await build_world(db_session)
    await login(client, world.learner_a)
    created = await _create(client, invitee_id=world.learner_a2.id)
    parent_id = created["parent_id"]

    await login(client, world.learner_a2)
    accepted = await client.post(
        "/api/games/invites/accept", json={"invitation_id": created["invitation_id"]}
    )
    child_b = accepted.json()["session_id"]
    await client.post(f"/api/games/challenges/{parent_id}/start")
    await _play_all(client, db_session, child_b, solve_on=3)

    waiting = await client.get(f"/api/games/sessions/{child_b}/challenge")
    assert waiting.status_code == 200, waiting.text
    body = waiting.json()
    assert body["settled"] is False
    assert body["outcome"] is None
    assert body["sentence"] == "Waiting for Amara to play."
    # No score of either side exists in the payload before the comparison.
    assert "score" not in waiting.text

    await login(client, world.learner_a)
    started = await client.post(f"/api/games/challenges/{parent_id}/start")
    child_a = started.json()["session_id"]
    await _play_all(client, db_session, child_a, solve_on=1)

    await login(client, world.learner_a2)
    settled = await client.get(f"/api/games/sessions/{child_b}/challenge")
    assert settled.status_code == 200, settled.text
    body = settled.json()
    assert body["settled"] is True
    assert body["outcome"] == "loss"
    assert body["opponent_id"] == str(world.learner_a.id)
    assert body["sentence"] == "Amara won Number Guess this time."


async def test_a_solo_game_has_no_challenge_to_show(client, db_session: AsyncSession) -> None:
    world = await build_world(db_session)
    await login(client, world.learner_a)
    started = await client.post("/api/games/number_guess/sessions", json={"difficulty": 1})
    assert started.status_code == 201, started.text
    solo = await client.get(f"/api/games/sessions/{started.json()['session_id']}/challenge")
    assert solo.status_code == 200 and solo.json() is None


# --------------------------------------------------------------------- reports
async def test_a_report_reaches_the_admin_as_one_sentence(client, db_session: AsyncSession) -> None:
    """P7-T09: a reason, a name, and one sentence — never a raw code."""
    world = await build_world(db_session)
    await login(client, world.learner_a)
    posted = await client.post(
        "/api/games/reports",
        json={"reported_id": str(world.learner_a2.id), "reason": "bullying"},
    )
    assert posted.status_code == 201, posted.text

    await login(client, world.admin_a)
    listed = await client.get("/api/games/reports")
    assert listed.status_code == 200, listed.text
    rows = listed.json()
    assert len(rows) == 1
    assert rows[0]["reported_name"] == "Bayo"
    assert rows[0]["reporter_name"] == "Amara"
    assert rows[0]["reason_sentence"] == "Unkind words or bullying."

    # A learner cannot read the school's reports.
    await login(client, world.learner_a)
    refused = await client.get("/api/games/reports")
    assert refused.status_code == 403


async def test_a_learner_cannot_report_a_classmate_from_another_school(
    client, db_session: AsyncSession
) -> None:
    world = await build_world(db_session)
    await login(client, world.learner_a)
    response = await client.post(
        "/api/games/reports",
        json={"reported_id": str(world.learner_b.id), "reason": "cheating"},
    )
    assert response.status_code == 404


# ------------------------------------------------------------- the last seat
async def test_only_one_claim_can_take_the_last_seat(client, db_session: AsyncSession) -> None:
    """P7-T03's atomic seat: the second claim finds nothing to update.

    The UPDATE carries ``WHERE status = 'pending'``, so two learners arriving
    together get one winner even before either has read the row.
    """
    world = await build_world(db_session)
    await login(client, world.learner_a)
    created = await _create(client)

    row = await repo.get_invitation(db_session, uuid.UUID(created["invitation_id"]))
    assert row is not None
    now = dt.datetime.now(dt.UTC)

    first = await repo.accept_invitation(
        db_session, invitation_id=row.id, user_id=world.learner_a2.id, now=now
    )
    second = await repo.accept_invitation(
        db_session, invitation_id=row.id, user_id=world.learner_b.id, now=now
    )
    assert first is True
    assert second is False


async def test_your_own_turn_is_findable_after_the_tab_closed(
    client, db_session: AsyncSession
) -> None:
    """P7-T06: the sheet is not the only way back into your own attempt."""
    world = await build_world(db_session)
    await login(client, world.learner_a)
    created = await _create(client, invitee_id=world.learner_a2.id)

    mine = await client.get("/api/games/challenges/mine")
    assert mine.status_code == 200, mine.text
    rows = mine.json()
    assert len(rows) == 1
    assert rows[0]["parent_id"] == created["parent_id"]
    assert rows[0]["sentence"] == "Your Number Guess is waiting."

    # The invited learner owes nothing until they accept.
    await login(client, world.learner_a2)
    assert (await client.get("/api/games/challenges/mine")).json() == []

    # Once they accept, both learners have one turn waiting.
    await client.post("/api/games/invites/accept", json={"invitation_id": created["invitation_id"]})
    theirs = await client.get("/api/games/challenges/mine")
    assert theirs.status_code == 200
    assert len(theirs.json()) == 1
    assert theirs.json()[0]["sentence"] == "Your Number Guess with Amara is waiting."

    # Playing it out takes the row away: there is no turn left to take.
    started = await client.post(f"/api/games/challenges/{created['parent_id']}/start")
    await _play_all(client, db_session, started.json()["session_id"], solve_on=1)
    assert (await client.get("/api/games/challenges/mine")).json() == []
