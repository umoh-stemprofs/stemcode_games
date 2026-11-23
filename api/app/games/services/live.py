"""Live Checkers: one match, two seats, server-authoritative clocks (P8-T09..T16).

The shape of a match lives in ``game_sessions.config`` (JSONB), because every
part of it changes on almost every move and none of it is worth a column:

```
seats          {white: user_id, black: user_id}
clock_ms       {white: 300000, black: 300000}
increment_ms   3000
turn_started_at ISO time, or null while that player's clock is paused
state          the pure Checkers state (board, side, counters, repetition)
move_number    the last accepted move; a client must send this + 1
moves_by       {white: n, black: n}  — D-29's activity minimum
connected      {white: bool, black: bool}
disconnect     {white: {since, cumulative_ms}, ...}  — D-30
draw           {offered_by, offered_at, offers: {white, black}}
outcome        {winner, reason} once the match has ended
```

Everything a client may know is built by :func:`snapshot`; the seed, the other
side's legal moves and any server-only counter never leave here (D-25).
"""

from __future__ import annotations

import copy
import datetime as dt
import json
import secrets
import uuid
from typing import Any
from zoneinfo import ZoneInfo

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import AppError, ConflictError, NotFoundError
from app.games import repository as repo
from app.games.domain import checkers as rules
from app.games.domain import invites as invite_rules
from app.games.models import GameResult, GameSession
from app.games.services import access, xp
from app.identity.models import User

GAME_ID = "checkers"
GAME_NAME = "Checkers"

WHITE = rules.WHITE
BLACK = rules.BLACK

DEFAULT_CLOCK_MS = 5 * 60 * 1000
DEFAULT_INCREMENT_MS = 3 * 1000
DEFAULT_INVITE_MINUTES = 30
DEFAULT_FORFEIT_SINGLE_MS = 3 * 60 * 1000
DEFAULT_FORFEIT_TOTAL_MS = 10 * 60 * 1000
DEFAULT_DRAW_OFFERS = 3
DRAW_OFFER_SECONDS = 30
# D-29: eight moves a side is "real play" and what XP is gated on.
ACTIVITY_MINIMUM_MOVES = 8

BAD_INVITE = "That code did not work."


def _now() -> dt.datetime:
    return dt.datetime.now(dt.UTC)


def _parse(value: object) -> dt.datetime | None:
    if isinstance(value, str):
        return dt.datetime.fromisoformat(value)
    return None


def _millis_since(started: dt.datetime | None, now: dt.datetime) -> int:
    if started is None:
        return 0
    return max(0, int((now - started).total_seconds() * 1000))


def _display(user: User) -> str:
    return user.preferred_name or user.real_name


def _cfg(row: GameSession) -> dict[str, Any]:
    """A deep copy of the match config.

    Not a shallow one: the callers below mutate nested members in place
    (`cfg["connected"][seat] = True`, the clock dict, the disconnect records).
    With a shallow copy that mutation lands on `row.config` too, so the old and
    the new value compare equal and SQLAlchemy detects no change — the write was
    silently dropped and a match could never leave `ready`.
    """
    return copy.deepcopy(row.config or {})


def _save(row: GameSession, cfg: dict[str, Any]) -> None:
    # A new dict, so SQLAlchemy sees the JSONB change.
    row.config = {**cfg}


def _state_of(cfg: dict[str, Any]) -> rules.State:
    raw = cfg["state"]
    return rules.State(
        board=tuple(int(piece) for piece in raw["board"]),
        side=str(raw["side"]),
        plies_since_progress=int(raw["plies"]),
        history=tuple(str(entry) for entry in raw.get("history", ())),
    )


def _state_to_cfg(state: rules.State) -> dict[str, Any]:
    # A short history is enough for the repetition rule and keeps the row small.
    return {
        "board": list(state.board),
        "side": state.side,
        "plies": state.plies_since_progress,
        "history": list(state.history[-24:]),
    }


# --------------------------------------------------------------------- create
async def create(
    session: AsyncSession,
    *,
    user: User,
    clock_ms: int | None = None,
    increment_ms: int | None = None,
    with_code: bool = True,
    with_link: bool = True,
    invitee: User | None = None,
    preferred_seat: str | None = None,
    now: dt.datetime | None = None,
) -> tuple[GameSession, Any, str | None, str | None]:
    """Open a live match and invite an opponent (P8-T09, D-27).

    The 15-minute bar is checked here, at creation, and again when the invite is
    redeemed: a match that could not legally start should not be creatable, and
    a match created an hour ago should not start on the last two minutes of a
    daily allowance.

    The inviter's colour is chosen **now**, not when the invite is redeemed.
    Otherwise the inviter is not a seat in their own match yet, so their board
    answers "we could not find that match" until somebody accepts, and the board
    would then flip colour under them at the moment a second player arrived.
    """
    now = now or _now()
    minimum = await access.live_minimum_seconds(session)
    await access.require_access(session, user=user, now=now, min_remaining_s=minimum)

    seed = secrets.randbits(63)
    state = rules.initial_state(side=WHITE)
    clock = clock_ms or DEFAULT_CLOCK_MS
    increment = increment_ms if increment_ms is not None else DEFAULT_INCREMENT_MS

    # Server-chosen, from the RNG or from a rematch's owed swap (P8-T13).
    inviter_seat = (
        preferred_seat
        if preferred_seat in (WHITE, BLACK)
        else (WHITE if secrets.randbits(1) == 0 else BLACK)
    )
    other_seat = BLACK if inviter_seat == WHITE else WHITE
    names: dict[str, str] = {inviter_seat: _display(user)}
    if invitee is not None:
        # The waiting screen can then say "Waiting for Bayo", not "for your
        # friend". The redeemer's own name is written over it in `accept`.
        names[other_seat] = _display(invitee)

    row = await repo.create_session(
        session,
        game_id=GAME_ID,
        mode="live",
        status="created",
        seed=seed,
        school_id=user.school_id,
        created_by=user.id,
        config={
            "seats": {inviter_seat: str(user.id)},
            "names": names,
            "clock_ms": {WHITE: clock, BLACK: clock},
            "increment_ms": increment,
            "turn_started_at": None,
            "state": _state_to_cfg(state),
            "move_number": 0,
            "moves_by": {WHITE: 0, BLACK: 0},
            "connected": {WHITE: False, BLACK: False},
            "disconnect": {
                WHITE: {"since": None, "cumulative_ms": 0},
                BLACK: {"since": None, "cumulative_ms": 0},
            },
            "draw": {"offered_by": None, "offered_at": None, "offers": {WHITE: 0, BLACK: 0}},
            "outcome": None,
        },
    )

    code = invite_rules.generate_code() if with_code else None
    link_token = invite_rules.generate_token() if with_link else None
    invitation = await repo.create_invitation(
        session,
        game_id=GAME_ID,
        session_id=row.id,
        inviter_id=user.id,
        invitee_id=invitee.id if invitee else None,
        code_hash=invite_rules.hash_secret(code) if code else None,
        token_hash=invite_rules.hash_secret(link_token) if link_token else None,
        status="pending",
        expires_at=now + dt.timedelta(minutes=DEFAULT_INVITE_MINUTES),
    )
    # The inviter is a player from the moment the match exists: the ticket
    # endpoint and the open-session rule both read participant rows, so without
    # this row the inviter's own board cannot even subscribe to their match.
    await repo.add_participant(
        session,
        session_id=row.id,
        user_id=user.id,
        seat=1 if inviter_seat == WHITE else 2,
        attempt_status="not_started",
    )

    if invitee is not None:
        # Picking a classmate from the roster is the shortest path into a match,
        # so the invite lands in their inbox instead of only on a screen.
        await repo.add_notification(
            session,
            user_id=invitee.id,
            kind="invite",
            invitation_id=invitation.id,
            session_id=row.id,
            body=f"{_display(user)} wants to play {GAME_NAME} with you.",
        )
    await session.commit()
    return row, invitation, code, link_token


# --------------------------------------------------------------------- accept
async def accept(
    session: AsyncSession,
    *,
    user: User,
    invitation_id: uuid.UUID | None = None,
    code: str | None = None,
    token: str | None = None,
    now: dt.datetime | None = None,
) -> GameSession:
    """Take the second seat (P7-T03's rules, P8-T09's colours)."""
    now = now or _now()

    invitation = None
    if invitation_id is not None:
        invitation = await repo.get_invitation(session, invitation_id)
    elif code:
        normalised = invite_rules.normalise_code(code)
        if normalised is not None:
            invitation = await repo.invitation_by_code_hash(
                session, code_hash=invite_rules.hash_secret(normalised)
            )
    elif token:
        invitation = await repo.invitation_by_token_hash(
            session, token_hash=invite_rules.hash_secret(token)
        )

    if invitation is None or invitation.status != "pending" or invitation.expires_at <= now:
        raise NotFoundError(BAD_INVITE, code="invite_not_found")
    if invitation.inviter_id == user.id:
        raise AppError("That is your own invite.", code="invite_own", status_code=400)

    row = await repo.get_session(session, invitation.session_id)
    if row is None or row.mode != "live" or row.status not in ("created", "ready"):
        raise NotFoundError(BAD_INVITE, code="invite_not_found")

    inviter = await session.get(User, invitation.inviter_id)
    if inviter is None or inviter.school_id != user.school_id:
        raise NotFoundError(BAD_INVITE, code="invite_not_found")
    if await repo.block_exists_between(session, a=user.id, b=inviter.id):
        raise NotFoundError(BAD_INVITE, code="invite_not_found")

    # D-27 again, for the second player.
    minimum = await access.live_minimum_seconds(session)
    await access.require_access(session, user=user, now=now, min_remaining_s=minimum)
    if await repo.active_session_for_user(session, user.id) is not None:
        raise ConflictError("You have a game open somewhere else.", code="another_session_active")

    claimed = await repo.accept_invitation(
        session, invitation_id=invitation.id, user_id=user.id, now=now
    )
    if not claimed:
        raise NotFoundError(BAD_INVITE, code="invite_not_found")

    cfg = _cfg(row)
    # The inviter's colour was chosen by the server at creation (P8-T09), so the
    # redeemer simply takes whatever seat is free. A row created before that rule
    # carries no seat; it still falls back to the server RNG here.
    seats = dict(cfg.get("seats") or {})
    inviter_seat = next((seat for seat, raw in seats.items() if raw == str(inviter.id)), None)
    if inviter_seat not in (WHITE, BLACK):
        preferred = cfg.get("preferred_inviter_seat")
        inviter_seat = (
            preferred
            if preferred in (WHITE, BLACK)
            else (WHITE if secrets.randbits(1) == 0 else BLACK)
        )
    other_seat = BLACK if inviter_seat == WHITE else WHITE
    cfg["seats"] = {inviter_seat: str(inviter.id), other_seat: str(user.id)}
    cfg["names"] = {inviter_seat: _display(inviter), other_seat: _display(user)}
    _save(row, cfg)

    # The inviter's row already exists from creation, which is what lets them
    # hold a socket ticket while they wait. Only the redeemer's row is new, so a
    # plain insert per player would collide on the composite key.
    for seat, player in ((inviter_seat, inviter), (other_seat, user)):
        if await repo.get_participant(session, row.id, player.id) is not None:
            continue
        await repo.add_participant(
            session,
            session_id=row.id,
            user_id=player.id,
            seat=1 if seat == WHITE else 2,
            attempt_status="not_started",
        )

    row.status = "ready"
    await repo.add_notification(
        session,
        user_id=inviter.id,
        kind="invite",
        invitation_id=invitation.id,
        session_id=row.id,
        body=f"{_display(user)} will play {GAME_NAME} with you.",
    )
    await session.commit()
    return row


# ------------------------------------------------------------------ presence
def _seat_of(cfg: dict[str, Any], user_id: uuid.UUID) -> str | None:
    for seat, raw in dict(cfg.get("seats") or {}).items():
        if raw == str(user_id):
            return seat
    return None


async def _load(
    session: AsyncSession, *, user: User, session_id: uuid.UUID
) -> tuple[GameSession, dict[str, Any], str]:
    """The row, its config and this player's seat, locked for this transaction.

    Every caller here mutates the match, so the row lock is taken as it is read:
    a move and the retry of the same move must not both believe they are first.
    """
    row = await repo.get_session(session, session_id, for_update=True)
    if row is None or row.mode != "live" or row.school_id != user.school_id:
        raise NotFoundError("That match was not found.")
    cfg = _cfg(row)
    seat = _seat_of(cfg, user.id)
    if seat is None:
        raise NotFoundError("That match was not found.")
    return row, cfg, seat


async def join(
    session: AsyncSession,
    *,
    user: User,
    session_id: uuid.UUID,
    now: dt.datetime | None = None,
) -> dict[str, Any]:
    """A socket (or a refreshed tab) is here (P8-T12).

    Both seats present turns `ready` into `active`, and that is when the first
    turn's clock starts: nobody loses time waiting in a lobby.
    """
    now = now or _now()
    row, cfg, seat = await _load(session, user=user, session_id=session_id)

    cfg["connected"][seat] = True
    disconnect = dict(cfg["disconnect"][seat])
    if disconnect.get("since"):
        disconnect["cumulative_ms"] = int(disconnect.get("cumulative_ms", 0)) + _millis_since(
            _parse(disconnect["since"]), now
        )
        disconnect["since"] = None
    cfg["disconnect"][seat] = disconnect

    both_here = bool(cfg["connected"][WHITE]) and bool(cfg["connected"][BLACK])

    if row.status == "ready" and both_here:
        row.status = "active"
        row.started_at = now
        cfg["turn_started_at"] = now.isoformat()
    elif row.status == "active" and cfg["state"]["side"] == seat and not cfg.get("turn_started_at"):
        # Their turn resumes when they come back (D-30).
        cfg["turn_started_at"] = now.isoformat()

    _save(row, cfg)
    await session.commit()
    return await snapshot(session, row=row, user=user, now=now)


async def leave(
    session: AsyncSession,
    *,
    user: User,
    session_id: uuid.UUID,
    now: dt.datetime | None = None,
) -> None:
    """A socket closed. The disconnected player's clock pauses (D-30)."""
    now = now or _now()
    row, cfg, seat = await _load(session, user=user, session_id=session_id)
    if row.status not in ("ready", "active"):
        return

    if cfg["state"]["side"] == seat and cfg.get("turn_started_at"):
        clock = _charged(cfg, now=now)
        cfg["clock_ms"] = clock
        cfg["turn_started_at"] = None

    cfg["connected"][seat] = False
    disconnect = dict(cfg["disconnect"][seat])
    disconnect["since"] = now.isoformat()
    cfg["disconnect"][seat] = disconnect

    _save(row, cfg)
    await session.commit()


# --------------------------------------------------------------------- clocks
def _charged(cfg: dict[str, Any], *, now: dt.datetime) -> dict[str, int]:
    """The clock as of *now*, with the side to move charged for elapsed time."""
    clock = {seat: int(value) for seat, value in dict(cfg["clock_ms"]).items()}
    started = _parse(cfg.get("turn_started_at"))
    if started is not None:
        side = str(cfg["state"]["side"])
        clock[side] = max(0, clock[side] - _millis_since(started, now))
    return clock


# --------------------------------------------------------------------- moves
async def submit(
    session: AsyncSession,
    *,
    user: User,
    session_id: uuid.UUID,
    client_move_id: str,
    expected_move_number: int,
    move_key: str,
    now: dt.datetime | None = None,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """One accepted move, or a refusal that changed nothing (P8-T10)."""
    now = now or _now()
    row, cfg, seat = await _load(session, user=user, session_id=session_id)

    if row.status != "active":
        raise AppError("That match is not being played.", code="match_not_active", status_code=409)

    # A retry is not a second move (P4-T15's rule, now over the wire).
    duplicate = await repo.move_by_client_id(
        session, session_id=row.id, client_move_id=client_move_id
    )
    if duplicate is not None:
        return await snapshot(session, row=row, user=user, now=now), []

    if cfg["state"]["side"] != seat:
        raise AppError("It is not your turn.", code="not_your_turn", status_code=409)
    if int(expected_move_number) != int(cfg["move_number"]) + 1:
        raise AppError("That move is out of date.", code="stale_move", status_code=409)

    state = _state_of(cfg)
    move = rules.find_move(state, move_key)
    if move is None:
        raise AppError("That move is not allowed.", code="illegal_move", status_code=400)

    clock = _charged(cfg, now=now)
    if clock[seat] <= 0:
        # The clock ran out while this move was in flight.
        await _finish(session, row=row, cfg=cfg, winner=_other(seat), reason="timeout", now=now)
        return await snapshot(session, row=row, user=user, now=now), [
            {"type": "match.ended", "session_id": str(row.id)}
        ]

    clock[seat] += int(cfg.get("increment_ms", 0))
    next_state = rules.apply_move(state, move)

    cfg["clock_ms"] = clock
    cfg["state"] = _state_to_cfg(next_state)
    cfg["move_number"] = int(cfg["move_number"]) + 1
    cfg["moves_by"][seat] = int(cfg["moves_by"][seat]) + 1
    cfg["turn_started_at"] = now.isoformat()
    # An offer dies the moment a move is made (P8-T13).
    cfg["draw"] = {
        "offered_by": None,
        "offered_at": None,
        "offers": dict(cfg["draw"]["offers"]),
    }
    _save(row, cfg)

    await repo.append_move(
        session,
        session_id=row.id,
        user_id=user.id,
        move_number=int(cfg["move_number"]),
        client_move_id=client_move_id,
        payload={
            "move": move.key,
            "from": move.from_square,
            "to": move.to_square,
            "captures": list(move.captures),
            "king": move.becomes_king,
        },
    )

    outcome = rules.result(next_state)
    events: list[dict[str, Any]] = [
        {
            "type": "move.accepted",
            "session_id": str(row.id),
            "move_number": cfg["move_number"],
            "by": seat,
        }
    ]
    if outcome is not None:
        winner = None if outcome == "draw" else outcome
        await _finish(session, row=row, cfg=cfg, winner=winner, reason=outcome, now=now)
        events.append({"type": "match.ended", "session_id": str(row.id)})
    else:
        await session.commit()

    return await snapshot(session, row=row, user=user, now=now), events


def _other(seat: str) -> str:
    return BLACK if seat == WHITE else WHITE


# -------------------------------------------------------------------- resign
async def resign(
    session: AsyncSession,
    *,
    user: User,
    session_id: uuid.UUID,
    now: dt.datetime | None = None,
) -> dict[str, Any]:
    now = now or _now()
    row, cfg, seat = await _load(session, user=user, session_id=session_id)
    if row.status != "active":
        raise AppError("That match is not being played.", code="match_not_active", status_code=409)
    await _finish(session, row=row, cfg=cfg, winner=_other(seat), reason="resign", now=now)
    return await snapshot(session, row=row, user=user, now=now)


# ---------------------------------------------------------------------- draw
async def offer_draw(
    session: AsyncSession,
    *,
    user: User,
    session_id: uuid.UUID,
    now: dt.datetime | None = None,
) -> dict[str, Any]:
    now = now or _now()
    row, cfg, seat = await _load(session, user=user, session_id=session_id)
    if row.status != "active":
        raise AppError("That match is not being played.", code="match_not_active", status_code=409)

    limit = await _draw_offer_limit(session)
    offers = dict(cfg["draw"]["offers"])
    if int(offers.get(seat, 0)) >= limit:
        raise AppError("No more draws this match.", code="draw_limit", status_code=409)

    offers[seat] = int(offers.get(seat, 0)) + 1
    cfg["draw"] = {"offered_by": seat, "offered_at": now.isoformat(), "offers": offers}
    _save(row, cfg)
    await session.commit()
    return await snapshot(session, row=row, user=user, now=now)


async def accept_draw(
    session: AsyncSession,
    *,
    user: User,
    session_id: uuid.UUID,
    now: dt.datetime | None = None,
) -> dict[str, Any]:
    now = now or _now()
    row, cfg, seat = await _load(session, user=user, session_id=session_id)
    offered_by = cfg["draw"].get("offered_by")
    offered_at = _parse(cfg["draw"].get("offered_at"))
    if row.status != "active" or offered_by in (None, seat):
        raise AppError("There is no draw to accept.", code="no_draw_offer", status_code=409)
    if offered_at is None or (now - offered_at).total_seconds() > DRAW_OFFER_SECONDS:
        raise AppError("That draw offer has expired.", code="draw_expired", status_code=409)
    await _finish(session, row=row, cfg=cfg, winner=None, reason="agreement", now=now)
    return await snapshot(session, row=row, user=user, now=now)


async def decline_draw(
    session: AsyncSession,
    *,
    user: User,
    session_id: uuid.UUID,
    now: dt.datetime | None = None,
) -> dict[str, Any]:
    now = now or _now()
    row, cfg, seat = await _load(session, user=user, session_id=session_id)
    if cfg["draw"].get("offered_by") in (None, seat):
        raise AppError("There is no draw to decline.", code="no_draw_offer", status_code=409)
    cfg["draw"] = {
        "offered_by": None,
        "offered_at": None,
        "offers": dict(cfg["draw"]["offers"]),
    }
    _save(row, cfg)
    await session.commit()
    return await snapshot(session, row=row, user=user, now=now)


async def _draw_offer_limit(session: AsyncSession) -> int:
    from app.games.services.access import _setting_int

    return await _setting_int(session, "live.draw_offers", DEFAULT_DRAW_OFFERS)


# --------------------------------------------------------------------- finish
async def _finish(
    session: AsyncSession,
    *,
    row: GameSession,
    cfg: dict[str, Any],
    winner: str | None,
    reason: str,
    now: dt.datetime,
) -> None:
    """Write both results in the same transaction as the last move (P8-T15)."""
    cfg["outcome"] = {"winner": winner, "reason": reason}
    cfg["turn_started_at"] = None
    cfg["clock_ms"] = _charged(cfg, now=now)
    _save(row, cfg)
    row.status = (
        "no_contest"
        if reason == "no_contest"
        else ("abandoned" if reason == "abandoned" else "finished")
    )
    row.ended_at = now

    if reason == "abandoned":
        # Nobody gets a result for a match nobody played (P8-T14).
        await session.commit()
        return

    seats = dict(cfg["seats"])
    moves_by = dict(cfg["moves_by"])
    enough_play = (
        min(int(moves_by.get(WHITE, 0)), int(moves_by.get(BLACK, 0))) >= ACTIVITY_MINIMUM_MOVES
    )
    pair_capped = await _pair_is_capped(session, seats=seats, school_id=row.school_id, now=now)

    for seat, raw_user_id in seats.items():
        player = await session.get(User, uuid.UUID(raw_user_id))
        if player is None:  # pragma: no cover - a seat without a user is corruption
            continue
        opponent_id = seats.get(_other(seat))
        if reason == "no_contest":
            outcome = "no_contest"
        elif winner is None:
            outcome = "draw"
        else:
            outcome = "win" if seat == winner else "loss"

        result = GameResult(
            session_id=row.id,
            user_id=player.id,
            outcome=outcome,
            score=int(moves_by.get(seat, 0)),
            details={
                "moves": int(moves_by.get(seat, 0)),
                "match": {
                    "opponent_id": opponent_id,
                    "reason": reason,
                    "moves_by": moves_by,
                    "winner": winner,
                    "enough_play": enough_play,
                },
            },
            leaderboard_eligible=enough_play and reason != "no_contest",
        )
        session.add(result)
        await session.flush()

        if enough_play and reason != "no_contest" and not pair_capped:
            await xp.award_for_result(session, result=result, game_row=row, user=player, now=now)

        await repo.add_notification(
            session,
            user_id=player.id,
            kind="challenge_result",
            session_id=row.id,
            body=_result_sentence(outcome, cfg, seat),
        )

    if enough_play and not pair_capped and reason != "no_contest":
        small, large = sorted(seats.values(), key=str)
        tz = ZoneInfo(await access.school_timezone(session, row.school_id))
        await repo.bump_pair_count(
            session,
            user_id=uuid.UUID(small),
            other_user_id=uuid.UUID(large),
            local_date=now.astimezone(tz).date(),
        )

    await session.commit()


def _result_sentence(outcome: str, cfg: dict[str, Any], seat: str) -> str:
    opponent = cfg["names"].get(_other(seat), "Your opponent")
    if outcome == "win":
        return f"You won {GAME_NAME} against {opponent}."
    if outcome == "loss":
        return f"{opponent} won {GAME_NAME} this time."
    if outcome == "draw":
        return f"It was a draw with {opponent}."
    return f"The {GAME_NAME} match with {opponent} was stopped."


async def _pair_is_capped(
    session: AsyncSession, *, seats: dict[str, str], school_id: uuid.UUID, now: dt.datetime
) -> bool:
    """D-13: three rewarded two-player sessions per pair per day."""
    from app.games.services.access import _setting_int

    small, large = sorted(seats.values(), key=str)
    tz = ZoneInfo(await access.school_timezone(session, school_id))
    local_date = now.astimezone(tz).date()
    count = await repo.pair_count(
        session,
        user_id=uuid.UUID(small),
        other_user_id=uuid.UUID(large),
        local_date=local_date,
    )
    cap = await _setting_int(session, "challenge.pair_daily_cap", 3)
    return count >= cap


# --------------------------------------------------------------- lazy checks
async def _apply_time_limits(
    session: AsyncSession, *, row: GameSession, cfg: dict[str, Any], now: dt.datetime
) -> bool:
    """Timeout and forfeit, checked on read as well as by the sweeper.

    Works with no worker running, which is what local development is (D-34).
    """
    if row.status != "active":
        return False

    clock = _charged(cfg, now=now)
    side = str(cfg["state"]["side"])
    if clock[side] <= 0:
        await _finish(session, row=row, cfg=cfg, winner=_other(side), reason="timeout", now=now)
        return True

    single = await _limit_ms(session, "live.forfeit_single_ms", DEFAULT_FORFEIT_SINGLE_MS)
    total = await _limit_ms(session, "live.forfeit_total_ms", DEFAULT_FORFEIT_TOTAL_MS)
    for seat in (WHITE, BLACK):
        if cfg["connected"].get(seat):
            continue
        entry = dict(cfg["disconnect"].get(seat) or {})
        since = _parse(entry.get("since"))
        if since is None:
            continue
        away = _millis_since(since, now) + int(entry.get("cumulative_ms", 0))
        single_away = _millis_since(since, now)
        if single_away >= single or away >= total:
            await _finish(session, row=row, cfg=cfg, winner=_other(seat), reason="forfeit", now=now)
            return True
    return False


async def _limit_ms(session: AsyncSession, name: str, default: int) -> int:
    from app.games.services.access import _setting_int

    return await _setting_int(session, name, default)


# ------------------------------------------------------------------- snapshot
async def snapshot(
    session: AsyncSession,
    *,
    row: GameSession,
    user: User,
    now: dt.datetime | None = None,
) -> dict[str, Any]:
    """Everything this player's screen needs, and nothing else (D-25)."""
    now = now or _now()
    cfg = _cfg(row)
    seat = _seat_of(cfg, user.id)
    if seat is None:
        raise NotFoundError("That match was not found.")

    if await _apply_time_limits(session, row=row, cfg=cfg, now=now):
        await session.refresh(row)
        cfg = _cfg(row)

    state = _state_of(cfg)
    clock = _charged(cfg, now=now)
    mine = seat
    theirs = _other(seat)
    legal = rules.legal_moves(state) if state.side == mine and row.status == "active" else []

    return {
        # A string, not the UUID: this dict is also a WebSocket frame, and
        # `json.dumps` refuses a UUID, which killed every socket on its first
        # frame. Pydantic coerces the string back for the REST response.
        "session_id": str(row.id),
        "game_id": GAME_ID,
        "status": row.status,
        "seat": mine,
        "side_to_move": state.side,
        "your_turn": state.side == mine and row.status == "active",
        "board": list(state.board),
        "legal_moves": [move.as_dict() for move in legal],
        "move_number": int(cfg["move_number"]),
        "clock_ms": {mine: clock[mine], theirs: clock[theirs]},
        "increment_ms": int(cfg.get("increment_ms", 0)),
        "moves_by": {mine: int(cfg["moves_by"][mine]), theirs: int(cfg["moves_by"][theirs])},
        "captures": rules.material(state),
        "opponent": {
            "name": cfg["names"].get(theirs),
            "connected": bool(cfg["connected"].get(theirs)),
        },
        "you_connected": bool(cfg["connected"].get(mine)),
        "draw_offer_from": cfg["draw"].get("offered_by"),
        "draw_offered_at": cfg["draw"].get("offered_at"),
        "outcome": cfg.get("outcome"),
        "moves_since_progress": state.plies_since_progress,
    }


# --------------------------------------------------------------------- sweeper
async def sweep(session: AsyncSession, *, now: dt.datetime | None = None) -> dict[str, int]:
    """The minute job (P8-T11 .. T14), plus the invite age-out that owns it."""
    now = now or _now()
    expired_invites = await repo.expire_overdue_invitations(session, now=now)
    await session.commit()

    ended = 0
    for row in await repo.live_matches(session):
        cfg = _cfg(row)
        if await _apply_time_limits(session, row=row, cfg=cfg, now=now):
            ended += 1
        elif row.status == "created":
            # Nobody redeemed the invite: nothing to play.
            invitation = await repo.invitation_for_session(session, session_id=row.id)
            if invitation is not None and invitation.expires_at <= now:
                row.status = "expired"
                row.ended_at = now
                await session.commit()
                ended += 1
    return {"invites_expired": expired_invites, "matches_ended": ended}


# -------------------------------------------------------------------- rematch
async def rematch(
    session: AsyncSession,
    *,
    user: User,
    session_id: uuid.UUID,
    now: dt.datetime | None = None,
) -> tuple[GameSession, Any, str | None, str | None]:
    """A new match with the same pair, colours swapped (P8-T13).

    Still subject to the pair cap for XP and to the 15-minute bar, because a
    rematch is a new match, not a continuation.
    """
    now = now or _now()
    row, cfg, seat = await _load(session, user=user, session_id=session_id)
    if row.status not in ("finished", "abandoned", "no_contest"):
        raise AppError("That match is still being played.", code="match_active", status_code=409)

    opponent_id = cfg["seats"].get(_other(seat))
    if opponent_id is None:
        raise AppError("There is nobody to play again.", code="no_opponent", status_code=409)

    # The seat the inviter held last time goes to the other player this time, so
    # the new row is created already holding the swapped colour.
    new_row, invitation, code, link_token = await create(
        session, user=user, now=now, preferred_seat=_other(seat)
    )
    new_row.rematch_of = row.id
    invitation.invitee_id = uuid.UUID(opponent_id)
    await repo.add_notification(
        session,
        user_id=uuid.UUID(opponent_id),
        kind="invite",
        invitation_id=invitation.id,
        session_id=new_row.id,
        body=f"{_display(user)} wants a rematch.",
    )
    await session.commit()
    return new_row, invitation, code, link_token


# -------------------------------------------------------------------- presence
async def presence(
    session: AsyncSession,
    *,
    user: User,
    cache: Any,
    now: dt.datetime | None = None,
) -> list[dict[str, Any]]:
    """Who you may challenge, and why not when the answer is no (P8-T04).

    A learner who cannot play is **named** with a short sentence rather than
    dropped from the list: an empty roster reads as a broken screen, and a name
    with a reason reads as a school (Appendix D.2.4).
    """
    now = now or _now()
    rows = await repo.classmates(session, user_id=user.id, school_id=user.school_id)
    hidden = await repo.blocked_user_ids(session, user_id=user.id)
    out: list[dict[str, Any]] = []
    for mate in rows:
        if mate.id == user.id or mate.id in hidden:
            continue
        name = _display(mate)
        raw = await cache.get(f"presence:{mate.id}")
        status = "available"
        if raw:
            try:
                status = json.loads(raw).get("status") or "available"
            except ValueError:  # pragma: no cover - we write our own JSON only
                status = "available"

        state = await access.access_for(session, user=mate, now=now, ignore_active_session=True)
        if not state.allowed:
            out.append(
                {
                    "user_id": mate.id,
                    "name": name,
                    "avatar_key": mate.avatar_key,
                    "status": "busy",
                    "sentence": f"{name} cannot play right now.",
                }
            )
        elif status == "in_match":
            out.append(
                {
                    "user_id": mate.id,
                    "name": name,
                    "avatar_key": mate.avatar_key,
                    "status": "in_match",
                    "sentence": f"{name} is in a match.",
                }
            )
        else:
            out.append(
                {
                    "user_id": mate.id,
                    "name": name,
                    "avatar_key": mate.avatar_key,
                    "status": "available",
                    "sentence": f"Tap {name} to play.",
                }
            )
    return out
