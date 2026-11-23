"""Phase 8: tickets, live Checkers, clocks and forfeits (P8-T01 .. P8-T16).

The promises, in the plan's own words:

- a socket is opened by a **single-use ticket** and closed when the match ends
  (P8-T01, P8-T05) — a copied ticket is already dead, and a ticket never has to
  be same-origin;
- **the server decides** every move, clock and outcome; the client sends an
  intent and the move number it was looking at (P8-T10);
- a disconnect **pauses** the clock and the match waits, then forfeits on a
  window rather than on a dropped packet (D-30);
- a live match needs **fifteen minutes left** before it starts (D-27);
- both players get a result row in one transaction, and XP needs real play on
  **both** sides (D-29) and holds to the pair cap (D-13).

Time is injected everywhere it matters, so nothing here sleeps.
"""

from __future__ import annotations

import datetime as dt
import json
import uuid

import pytest
from app.api import realtime
from app.core.errors import NotFoundError
from app.games import repository as repo
from app.games.domain import checkers as rules
from app.games.services import live
from app.identity.models import Role
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from tests.factories import build_world, login, make_user

NOW = dt.datetime(2026, 11, 14, 9, 0, tzinfo=dt.UTC)


# --------------------------------------------------------------------- helpers
def _cache(client) -> object:
    """The cache the test app is using, so a ticket can be read back."""
    return client._transport.app.state.cache


async def _create(user, db: AsyncSession, *, now: dt.datetime = NOW, **kwargs):
    row, invitation, code, token = await live.create(db, user=user, now=now, **kwargs)
    return row, invitation, code, token


async def _matched(db: AsyncSession, world, *, now: dt.datetime = NOW):
    """A match with both seats filled, nobody connected yet."""
    row, _invitation, _code, _token = await _create(world.learner_a, db, now=now)
    invitation = await repo.invitation_for_session(db, session_id=row.id)
    assert invitation is not None
    row = await live.accept(db, user=world.learner_a2, invitation_id=invitation.id, now=now)
    return row


async def _started(db: AsyncSession, world, *, now: dt.datetime = NOW):
    """Both players present, so the match is active and a clock is running."""
    row = await _matched(db, world, now=now)
    await live.join(db, user=world.learner_a, session_id=row.id, now=now)
    await live.join(db, user=world.learner_a2, session_id=row.id, now=now)
    fresh = await repo.get_session(db, row.id)
    assert fresh is not None
    assert fresh.status == "active"
    assert fresh.config["turn_started_at"] == now.isoformat()
    return fresh


def _seat_of(cfg: dict, user) -> str:
    for seat, raw in cfg["seats"].items():
        if raw == str(user.id):
            return seat
    raise AssertionError("user has no seat")


def _on_turn(cfg: dict, world):
    """The player whose clock is running. Colours are the server's choice, so
    every test asks rather than assuming who is white."""
    side = cfg["state"]["side"]
    for player in (world.learner_a, world.learner_a2):
        if _seat_of(cfg, player) == side:
            return player
    raise AssertionError("nobody is on turn")


def _waiting(cfg: dict, world):
    on_turn = _on_turn(cfg, world)
    return world.learner_a2 if on_turn is world.learner_a else world.learner_a


async def _seat_and_move(db: AsyncSession, row, user):
    """The player's seat and one legal move from their own snapshot."""
    snapshot = await live.snapshot(db, row=row, user=user, now=NOW + dt.timedelta(seconds=5))
    assert snapshot["your_turn"], "expected this player to be on turn"
    return snapshot["seat"], snapshot["legal_moves"][0]["key"]


async def _results(db: AsyncSession, session_id: uuid.UUID) -> list:
    return list(
        (
            await db.execute(
                select(repo.GameResult).where(repo.GameResult.session_id == session_id)
            )
        ).scalars()
    )


async def _xp_rows(db: AsyncSession, user_id: uuid.UUID) -> int:
    from app.games.models import GameXpEntry

    return int(
        (
            await db.execute(
                select(func.count()).select_from(GameXpEntry).where(GameXpEntry.user_id == user_id)
            )
        ).scalar_one()
    )


async def _set_daily_limit(db: AsyncSession, *, user, minutes: int) -> None:
    await repo.create_policy(
        db,
        scope_type="student",
        scope_id=user.id,
        daily_limit_minutes=minutes,
        valid_from=NOW - dt.timedelta(days=1),
        valid_until=None,
        set_by=user.id,
        reason="test",
    )


# --------------------------------------------------------------------- tickets
async def test_ticket_is_single_use_and_only_for_a_participant(
    client, db_session: AsyncSession
) -> None:
    world = await build_world(db_session)
    row = await _matched(db_session, world)

    await login(client, world.learner_a)
    issued = await client.post("/api/ws/ticket", json={"session_id": str(row.id)})
    assert issued.status_code == 201, issued.text
    body = issued.json()
    assert body["expires_in"] == 30
    ticket = body["ticket"]

    cache = _cache(client)
    first = await realtime.consume_ticket(cache, ticket)
    assert first == (world.learner_a.id, row.id)
    # The second handshake with the same ticket is refused: one socket, one key.
    assert await realtime.consume_ticket(cache, ticket) is None

    # A stranger in the same school is not in the match, so the match is not
    # theirs to open — the same sentence as a match that does not exist.
    stranger = await make_user(
        db_session,
        school=world.school_a,
        role=Role.learner,
        code=f"T-{uuid.uuid4().hex[:8].upper()}",
        preferred="Stranger",
    )
    await login(client, stranger)
    refused = await client.post("/api/ws/ticket", json={"session_id": str(row.id)})
    assert refused.status_code == 404
    assert refused.json()["error"]["code"] == "not_found"

    # Another school cannot even see it.
    await login(client, world.learner_b)
    other_school = await client.post("/api/ws/ticket", json={"session_id": str(row.id)})
    assert other_school.status_code == 404


async def test_origin_is_checked_before_a_socket_is_accepted(client, db_session: AsyncSession):
    """A ticket proves who you are; the origin check is what stops another page."""

    class _FakeSocket:
        def __init__(self, origin: str | None) -> None:
            self.headers = {"origin": origin} if origin else {}
            self.app = client._transport.app

    assert realtime.origin_refused(_FakeSocket("http://localhost:3000")) is False
    assert realtime.origin_refused(_FakeSocket("http://127.0.0.1:3000")) is False
    assert realtime.origin_refused(_FakeSocket("https://evil.example")) is True
    # A missing Origin is a refusal, not a pass.
    assert realtime.origin_refused(_FakeSocket(None)) is True


# ---------------------------------------------------------------------- create
async def test_a_live_match_needs_fifteen_minutes_left(client, db_session: AsyncSession) -> None:
    world = await build_world(db_session)
    await _set_daily_limit(db_session, user=world.learner_a, minutes=10)

    await login(client, world.learner_a)
    refused = await client.post("/api/games/live", json={})
    assert refused.status_code == 403, refused.text
    # Not "you have used all your time" — they simply cannot fit a match in.
    assert refused.json()["error"]["code"] == "not_enough_time"
    assert refused.json()["error"]["message"] == "You need more time left for a match."


async def test_accepting_your_own_invite_is_refused(client, db_session: AsyncSession) -> None:
    world = await build_world(db_session)
    # Real time: this test redeems the code over HTTP, and the API checks the
    # invite's own clock, not a test's.
    row, _invitation, code, _token = await _create(
        world.learner_a, db_session, now=dt.datetime.now(dt.UTC)
    )

    await login(client, world.learner_a)
    mine = await client.post("/api/games/live/accept", json={"code": code})
    assert mine.status_code == 400
    assert mine.json()["error"]["code"] == "invite_own"

    # A learner in the other school gets the one sentence, never "wrong school".
    await login(client, world.learner_b)
    other = await client.post("/api/games/live/accept", json={"code": code})
    assert other.status_code == 404
    assert other.json()["error"]["code"] == "invite_not_found"

    # The friend redeems it and takes the second seat.
    await login(client, world.learner_a2)
    accepted = await client.post("/api/games/live/accept", json={"code": code})
    assert accepted.status_code == 200, accepted.text
    payload = accepted.json()
    assert payload["status"] == "ready"
    assert payload["seat"] in ("white", "black")
    # One seat per player, from the server.
    cfg = (await repo.get_session(db_session, row.id)).config
    assert sorted(cfg["seats"].values()) == sorted(
        [str(world.learner_a.id), str(world.learner_a2.id)]
    )


async def test_the_match_starts_when_both_players_are_present(
    client, db_session: AsyncSession
) -> None:
    world = await build_world(db_session)
    row = await _matched(db_session, world)

    await live.join(db_session, user=world.learner_a, session_id=row.id, now=NOW)
    still_ready = await repo.get_session(db_session, row.id)
    assert still_ready is not None and still_ready.status == "ready"

    await live.join(db_session, user=world.learner_a2, session_id=row.id, now=NOW)
    active = await repo.get_session(db_session, row.id)
    assert active is not None and active.status == "active"
    assert active.started_at is not None
    # The first move's clock starts when the second player arrives, so nobody
    # loses time waiting in a lobby.
    assert active.config["turn_started_at"] == NOW.isoformat()


# ----------------------------------------------------------------------- moves
async def test_only_the_server_decides_which_moves_are_legal(
    client, db_session: AsyncSession
) -> None:
    world = await build_world(db_session)
    row = await _started(db_session, world)

    cfg = (await repo.get_session(db_session, row.id)).config
    on_turn = _on_turn(cfg, world)
    waiting = _waiting(cfg, world)
    seat, move_key = await _seat_and_move(db_session, row, on_turn)
    assert seat == cfg["state"]["side"]

    # The player not on turn is refused.
    with pytest.raises(Exception) as not_turn:
        await live.submit(
            db_session,
            user=waiting,
            session_id=row.id,
            client_move_id=uuid.uuid4().hex * 2,
            expected_move_number=1,
            move_key=move_key,
            now=NOW + dt.timedelta(seconds=2),
        )
    assert getattr(not_turn.value, "code", None) == "not_your_turn"

    # A move the board does not allow is refused, and changes nothing.
    with pytest.raises(Exception) as illegal:
        await live.submit(
            db_session,
            user=on_turn,
            session_id=row.id,
            client_move_id=uuid.uuid4().hex * 2,
            expected_move_number=1,
            move_key="0-63:",
            now=NOW + dt.timedelta(seconds=2),
        )
    assert getattr(illegal.value, "code", None) == "illegal_move"

    # A client looking at an older board is refused rather than silently
    # playing the wrong move (P8-T10).
    with pytest.raises(Exception) as stale:
        await live.submit(
            db_session,
            user=on_turn,
            session_id=row.id,
            client_move_id=uuid.uuid4().hex * 2,
            expected_move_number=7,
            move_key=move_key,
            now=NOW + dt.timedelta(seconds=2),
        )
    assert getattr(stale.value, "code", None) == "stale_move"

    client_move_id = uuid.uuid4().hex * 2
    state, events = await live.submit(
        db_session,
        user=on_turn,
        session_id=row.id,
        client_move_id=client_move_id,
        expected_move_number=1,
        move_key=move_key,
        now=NOW + dt.timedelta(seconds=3),
    )
    assert state["move_number"] == 1
    assert events[0]["type"] == "move.accepted"

    # The same intent again is a retry, not a second move.
    again, retry_events = await live.submit(
        db_session,
        user=on_turn,
        session_id=row.id,
        client_move_id=client_move_id,
        expected_move_number=2,
        move_key=move_key,
        now=NOW + dt.timedelta(seconds=4),
    )
    assert retry_events == []
    assert again["move_number"] == 1

    # The increment went to the player who moved.
    fresh = await repo.get_session(db_session, row.id)
    assert fresh is not None
    assert fresh.config["moves_by"][seat] == 1
    # And the turn passed to the other side.
    assert fresh.config["state"]["side"] != seat


async def test_a_snapshot_never_carries_the_seed_or_the_other_side(
    client, db_session: AsyncSession
) -> None:
    world = await build_world(db_session)
    row = await _started(db_session, world)

    cfg = (await repo.get_session(db_session, row.id)).config
    on_turn = _on_turn(cfg, world)
    waiting = _waiting(cfg, world)

    mine = await live.snapshot(db_session, row=row, user=on_turn, now=NOW)
    theirs = await live.snapshot(db_session, row=row, user=waiting, now=NOW)

    assert "seed" not in mine and "seed" not in theirs
    assert mine["legal_moves"], "the player on turn is offered moves"
    # The player waiting is offered nothing: legal moves are the server's answer
    # to the player whose turn it is, not a list both sides can read.
    assert theirs["legal_moves"] == []
    assert theirs["your_turn"] is False
    # Each player's clocks are keyed by their own seat.
    assert set(mine["clock_ms"]) == {"white", "black"}
    assert mine["seat"] == _seat_of(cfg, on_turn)


# ----------------------------------------------------------- disconnect clocks
async def test_leaving_pauses_the_clock_and_coming_back_resumes_it(
    client, db_session: AsyncSession
) -> None:
    world = await build_world(db_session)
    row = await _started(db_session, world)

    cfg = (await repo.get_session(db_session, row.id)).config
    on_turn = _on_turn(cfg, world)

    # Ten seconds on the clock, then the socket drops.
    dropped_at = NOW + dt.timedelta(seconds=10)
    left = await live.snapshot(db_session, row=row, user=on_turn, now=dropped_at)
    seat = left["seat"]
    before = left["clock_ms"][seat]
    assert before < 5 * 60 * 1000

    await live.leave(db_session, user=on_turn, session_id=row.id, now=dropped_at)

    # A minute later the clock has not moved: the match is waiting (D-30).
    later = await repo.get_session(db_session, row.id)
    assert later is not None
    paused = await live.snapshot(
        db_session, row=later, user=on_turn, now=dropped_at + dt.timedelta(minutes=1)
    )
    assert paused["clock_ms"][seat] == before
    assert paused["you_connected"] is False

    # Back inside the forfeit window, the clock resumes from where it stopped.
    await live.join(
        db_session, user=on_turn, session_id=row.id, now=dropped_at + dt.timedelta(minutes=1)
    )
    resumed = await repo.get_session(db_session, row.id)
    assert resumed is not None
    assert resumed.config["turn_started_at"] is not None
    assert resumed.config["disconnect"][seat]["since"] is None
    assert resumed.config["disconnect"][seat]["cumulative_ms"] == 60_000


async def test_being_away_past_the_window_forfeits_the_match(
    client, db_session: AsyncSession
) -> None:
    world = await build_world(db_session)
    row = await _started(db_session, world)

    cfg = (await repo.get_session(db_session, row.id)).config
    on_turn = _on_turn(cfg, world)
    other = _waiting(cfg, world)

    await live.leave(db_session, user=on_turn, session_id=row.id, now=NOW + dt.timedelta(seconds=5))
    counts = await live.sweep(db_session, now=NOW + dt.timedelta(minutes=4))
    assert counts["matches_ended"] == 1

    row = await repo.get_session(db_session, row.id)
    assert row is not None and row.status == "finished"
    assert row.config["outcome"] == {"winner": _seat_of(cfg, other), "reason": "forfeit"}

    results = await _results(db_session, row.id)
    assert len(results) == 2
    by_user = {result.user_id: result for result in results}
    assert by_user[other.id].outcome == "win"
    assert by_user[on_turn.id].outcome == "loss"
    # Nobody made eight moves, so this is a real result and not a rewarded one.
    assert all(result.leaderboard_eligible is False for result in results)
    assert await _xp_rows(db_session, other.id) == 0


async def test_running_out_of_time_ends_the_match_on_read(client, db_session: AsyncSession) -> None:
    """The timeout is enforced by reading the match, so no worker is needed."""
    world = await build_world(db_session)
    row = await _started(db_session, world, now=NOW)

    # Take the match as it stands and wind the clock right down.
    fresh = await repo.get_session(db_session, row.id)
    assert fresh is not None
    cfg = dict(fresh.config)
    cfg["clock_ms"] = {"white": 60_000, "black": 60_000}
    fresh.config = {**cfg}
    await db_session.flush()

    ended = await live.snapshot(
        db_session, row=fresh, user=world.learner_a, now=NOW + dt.timedelta(minutes=5)
    )
    assert ended["status"] == "finished"
    assert ended["outcome"]["reason"] == "timeout"


# ------------------------------------------------------- resign, draw, rematch
async def test_resigning_gives_both_players_a_result_and_no_xp(
    client, db_session: AsyncSession
) -> None:
    world = await build_world(db_session)
    row = await _started(db_session, world)

    state = await live.resign(
        db_session, user=world.learner_a, session_id=row.id, now=NOW + dt.timedelta(seconds=20)
    )
    assert state["status"] == "finished"
    assert state["outcome"]["reason"] == "resign"

    results = await _results(db_session, row.id)
    assert {result.user_id for result in results} == {world.learner_a.id, world.learner_a2.id}
    by_user = {result.user_id: result for result in results}
    assert by_user[world.learner_a.id].outcome == "loss"
    assert by_user[world.learner_a2.id].outcome == "win"
    # Under the activity minimum there is no bonus and no daily XP.
    assert await _xp_rows(db_session, world.learner_a2.id) == 0

    # Resigning a match that has already ended says so, plainly.
    with pytest.raises(Exception) as again:
        await live.resign(db_session, user=world.learner_a, session_id=row.id, now=NOW)
    assert getattr(again.value, "code", None) == "match_not_active"


async def test_a_draw_is_offered_declined_and_then_agreed(client, db_session: AsyncSession) -> None:
    world = await build_world(db_session)
    row = await _started(db_session, world)

    offered = await live.offer_draw(
        db_session, user=world.learner_a, session_id=row.id, now=NOW + dt.timedelta(seconds=10)
    )
    assert offered["draw_offer_from"] is not None

    # You cannot accept your own offer.
    with pytest.raises(Exception) as own:
        await live.accept_draw(
            db_session, user=world.learner_a, session_id=row.id, now=NOW + dt.timedelta(seconds=11)
        )
    assert getattr(own.value, "code", None) == "no_draw_offer"

    declined = await live.decline_draw(
        db_session, user=world.learner_a2, session_id=row.id, now=NOW + dt.timedelta(seconds=12)
    )
    assert declined["draw_offer_from"] is None

    # An expired offer is not accepted by accident.
    await live.offer_draw(
        db_session, user=world.learner_a, session_id=row.id, now=NOW + dt.timedelta(seconds=13)
    )
    with pytest.raises(Exception) as expired:
        await live.accept_draw(
            db_session,
            user=world.learner_a2,
            session_id=row.id,
            now=NOW + dt.timedelta(minutes=2),
        )
    assert getattr(expired.value, "code", None) in ("draw_expired", "no_draw_offer")

    await live.decline_draw(
        db_session, user=world.learner_a2, session_id=row.id, now=NOW + dt.timedelta(minutes=2)
    )
    await live.offer_draw(
        db_session, user=world.learner_a, session_id=row.id, now=NOW + dt.timedelta(minutes=2)
    )
    agreed = await live.accept_draw(
        db_session,
        user=world.learner_a2,
        session_id=row.id,
        now=NOW + dt.timedelta(minutes=2, seconds=5),
    )
    assert agreed["status"] == "finished"
    assert agreed["outcome"]["reason"] == "agreement"
    results = await _results(db_session, row.id)
    assert {result.outcome for result in results} == {"draw"}


async def test_a_rematch_swaps_the_colours(client, db_session: AsyncSession) -> None:
    world = await build_world(db_session)
    row = await _started(db_session, world)
    await live.resign(db_session, user=world.learner_a, session_id=row.id, now=NOW)

    finished = await repo.get_session(db_session, row.id)
    assert finished is not None
    old_seats = dict(finished.config["seats"])

    new_row, invitation, _code, _token = await live.rematch(
        db_session, user=world.learner_a, session_id=row.id, now=NOW
    )
    await live.accept(db_session, user=world.learner_a2, invitation_id=invitation.id, now=NOW)

    fresh = await repo.get_session(db_session, new_row.id)
    assert fresh is not None
    assert fresh.rematch_of == row.id
    # The inviter's seat from last time belongs to the other player now.
    old_inviter_seat = next(
        seat for seat, raw in old_seats.items() if raw == str(world.learner_a.id)
    )
    new_inviter_seat = next(
        seat for seat, raw in fresh.config["seats"].items() if raw == str(world.learner_a.id)
    )
    assert new_inviter_seat != old_inviter_seat


# ------------------------------------------------------------------ presence
async def test_presence_names_who_cannot_play_and_why(client, db_session: AsyncSession) -> None:
    world = await build_world(db_session)
    await _set_daily_limit(db_session, user=world.learner_a2, minutes=0)

    await login(client, world.learner_a)
    rows = (await client.get("/api/games/presence")).json()
    by_name = {row["name"]: row for row in rows}

    assert "Bayo" in by_name
    assert by_name["Bayo"]["status"] == "busy"
    assert by_name["Bayo"]["sentence"] == "Bayo cannot play right now."
    # Nobody from the other school appears.
    assert "Beta Learner" not in by_name


async def test_a_blocked_classmate_is_not_offered(client, db_session: AsyncSession) -> None:
    world = await build_world(db_session)
    await repo.add_block(
        db_session,
        blocker_id=world.learner_a.id,
        blocked_id=world.learner_a2.id,
        type_="block",
    )
    await db_session.commit()

    await login(client, world.learner_a)
    rows = (await client.get("/api/games/presence")).json()
    assert all(row["name"] != "Bayo" for row in rows)


# --------------------------------------------------------------------- the hub
def test_the_hub_caps_connections_and_replaces_the_oldest() -> None:
    from app.games.services.hub import MAX_CONNECTIONS_PER_USER, Connection, Hub

    hub = Hub()
    user_id = uuid.uuid4()
    session_id = uuid.uuid4()
    first = Connection(user_id=user_id, session_id=session_id, conn_id="a")
    second = Connection(user_id=user_id, session_id=session_id, conn_id="b")
    hub.register(first)
    hub.register(second)
    assert hub.count() == 2

    # A third socket does not get an error: the oldest one is replaced, which is
    # what a reconnect after school wifi drops needs to look like (P8-T05).
    third = Connection(user_id=user_id, session_id=session_id, conn_id="c")
    replaced = hub.register(third)
    assert replaced is not None and replaced.conn_id == "a"
    assert hub.count() == MAX_CONNECTIONS_PER_USER
    assert [conn.conn_id for conn in hub.connections(session_id)] == ["b", "c"]

    hub.close_session(session_id)
    assert hub.connections(session_id) == []
    assert hub.count() == 0


def test_a_move_key_is_the_wire_form_of_a_legal_move() -> None:
    state = rules.initial_state(side=rules.WHITE)
    move = rules.legal_moves(state)[0]
    assert move.key == f"{move.from_square}-{move.to_square}:"
    assert rules.find_move(state, move.key) is not None
    assert rules.find_move(state, "0-63:") is None


# ------------------------------------ the four things only a browser found (P8)
async def test_the_inviter_can_open_their_own_board_before_anyone_accepts(
    db_session: AsyncSession,
) -> None:
    """The waiting player needs a seat, not a 404.

    Colours used to be chosen when the invite was redeemed, so the inviter was
    not a seat in their own match: their board answered "we could not find that
    match" until somebody accepted, and then flipped colour under them.
    """
    world = await build_world(db_session)
    row, invitation, _code, _token = await _create(
        world.learner_a, db_session, invitee=world.learner_a2
    )

    snapshot = await live.snapshot(db_session, row=row, user=world.learner_a)

    assert snapshot["status"] == "created"
    assert snapshot["seat"] in ("white", "black")
    assert snapshot["your_turn"] is False
    # The waiting sentence can name the person who was invited.
    assert snapshot["opponent"]["name"] is not None
    # And the redeemer is not a participant yet, so they cannot read the match.
    with pytest.raises(NotFoundError):
        await live.snapshot(db_session, row=row, user=world.learner_a2)
    assert (await repo.get_participant(db_session, row.id, world.learner_a.id)) is not None


async def test_accepting_finds_the_inviters_seat_already_taken(
    db_session: AsyncSession,
) -> None:
    """Accept must fill the free seat, not try to seat the inviter twice."""
    world = await build_world(db_session)
    row, _invitation, _code, _token = await _create(world.learner_a, db_session)
    before = await live.snapshot(db_session, row=row, user=world.learner_a)
    original_seat = before["seat"]

    invitation = await repo.invitation_for_session(db_session, session_id=row.id)
    assert invitation is not None
    row = await live.accept(db_session, user=world.learner_a2, invitation_id=invitation.id, now=NOW)

    after = await live.snapshot(db_session, row=row, user=world.learner_a)
    assert after["seat"] == original_seat
    assert after["opponent"]["name"] is not None


async def test_joining_is_written_to_the_row(db_session: AsyncSession) -> None:
    """`connected` has to survive the commit.

    The config is JSONB and the services mutate nested members in place, so a
    shallow copy made the old and new value compare equal and SQLAlchemy wrote
    nothing. The match then sat in `ready` forever with both players looking at
    a board that said the other one had left.
    """
    world = await build_world(db_session)
    row = await _matched(db_session, world)
    seat = _seat_of(row.config, world.learner_a)

    await live.join(db_session, user=world.learner_a, session_id=row.id, now=NOW)

    # Read it back out of Postgres, not out of the identity map: the bug was
    # that nothing was written at all.
    stored = (
        await db_session.execute(
            text("select config -> 'connected' ->> :seat from game_sessions where id = :id"),
            {"seat": seat, "id": row.id},
        )
    ).scalar()
    assert json.loads(stored) is True


async def test_a_snapshot_is_a_json_frame(db_session: AsyncSession) -> None:
    """The socket sends the snapshot with `json.dumps`, so it must be plain JSON.

    A UUID here raised TypeError inside the gateway and every socket died on its
    first frame — the board stayed on "you are offline" for both players.
    """
    world = await build_world(db_session)
    row = await _matched(db_session, world)
    snapshot = await live.snapshot(db_session, row=row, user=world.learner_a)

    frame = json.dumps({"type": "match.state", **snapshot})
    assert '"session_id"' in frame


async def test_every_move_is_made_under_the_row_lock(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A move and the retry of that move must not both believe they are first.

    The chaos gate (fifty socket kills mid-move, `tools/phase8_chaos.py`) found
    this: a reconnect resent the pending move while the original request was
    still committing, the retry read the document before it changed, saw no
    duplicate, and hit the unique constraint on `client_move_id` — so the player
    got no frame at all and the board froze.

    A race cannot be reproduced on one connection, so this pins the mechanism
    instead: every mutating path reads the match row `FOR UPDATE`. A read that
    skips the lock is the bug, whether or not it loses the race today.
    """
    world = await build_world(db_session)
    row = await _started(db_session, world)
    on_turn = _on_turn(row.config, world)
    _seat, move_key = await _seat_and_move(db_session, row, on_turn)

    original = repo.get_session
    seen: list[bool] = []

    async def spy(session, session_id, *, for_update=False):
        seen.append(for_update)
        return await original(session, session_id, for_update=for_update)

    monkeypatch.setattr(repo, "get_session", spy)

    async def locked(call) -> None:
        seen.clear()
        await call
        assert seen, "the mutation never read the match row"
        assert all(seen), "a mutating path read the match row without locking it"

    await locked(live.join(db_session, user=world.learner_a, session_id=row.id, now=NOW))
    await locked(
        live.submit(
            db_session,
            user=on_turn,
            session_id=row.id,
            client_move_id=uuid.uuid4().hex * 2,
            expected_move_number=1,
            move_key=move_key,
            now=NOW + dt.timedelta(seconds=3),
        )
    )
    await locked(
        live.leave(
            db_session, user=world.learner_a, session_id=row.id, now=NOW + dt.timedelta(seconds=4)
        )
    )
    await locked(
        live.resign(
            db_session, user=world.learner_a, session_id=row.id, now=NOW + dt.timedelta(seconds=5)
        )
    )
