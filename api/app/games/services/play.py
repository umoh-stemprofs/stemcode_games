"""Playing a game: create, act, read state (P4-T08, P4-T10 .. P4-T12).

The shape of every game is the same, and this module is the only place that
knows it:

- **create** picks a published pack for the learner's age band, draws rounds
  from a server-private seed, and starts the session through Phase 3's access
  checks (limits, lockouts, one open play).
- **act** applies one action, records it in ``game_moves`` so the session is
  replayable, charges play time, and finishes the session on the last round.
- **state** is what a refreshed tab needs, including the time left this
  instant, computed on the server.

Nothing here returns an answer. A round carries letters, a clue, and how many
tries remain; the answer stays in the content table and the seed stays in the
session row (D-25).
"""

from __future__ import annotations

import datetime as dt
import secrets
import uuid
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import AppError, ConflictError, NotFoundError
from app.games import repository as repo
from app.games.domain import access as rules
from app.games.domain import guessing as guess_rules
from app.games.domain import wordscramble as ws
from app.games.models import ContentItem, GameParticipant, GameSession
from app.games.registry import content_handler_for, handler_for
from app.games.services import access, guessing, results, rounds, xp
from app.games.services import clock as play_clock
from app.games.services import sessions as lifecycle
from app.games.services.views import PlayView, RoundView
from app.identity.models import User

# Re-exported: the routers and the tests import these from here.
__all__ = ["PlayView", "RoundView", "abandon_stale", "create_solo", "get_state", "submit_action"]


def _now() -> dt.datetime:
    return dt.datetime.now(dt.UTC)


def _parse(value: object) -> dt.datetime | None:
    if not isinstance(value, str) or not value:
        return None
    return dt.datetime.fromisoformat(value)


def _item_from_row(row: ContentItem) -> ws.Item:
    payload = row.payload
    alts = payload.get("alt_answers") or []
    return ws.Item(
        id=str(row.id),
        answer=str(payload.get("answer", "")),
        alt_answers=tuple(str(a) for a in alts) if isinstance(alts, list) else (),
        clue=payload.get("clue") if isinstance(payload.get("clue"), str) else None,
        clue_image_key=payload.get("clue_image_key")
        if isinstance(payload.get("clue_image_key"), str)
        else None,
        clue_audio_key=payload.get("clue_audio_key")
        if isinstance(payload.get("clue_audio_key"), str)
        else None,
        difficulty=int(payload.get("difficulty", 1)),
    )


async def create_solo(
    session: AsyncSession,
    *,
    user: User,
    game_id: str,
    difficulty: int,
    now: dt.datetime | None = None,
) -> GameSession:
    """Open a solo session and start its clock (D-26, D-27 do not apply: solo)."""
    now = now or _now()
    if game_id == guess_rules.GAME_ID:
        # No content to pick (P6-T05), so the numbers come from the seed.
        return await guessing.create_solo(session, user=user, difficulty=difficulty, now=now)
    timezone = await access.school_timezone(session, user.school_id)
    today = rules.local_date(now, timezone)

    seed = secrets.randbits(63)
    built = await rounds.build(
        session,
        user=user,
        game_id=game_id,
        difficulty=difficulty,
        seed=seed,
        local_date=today,
    )

    class_ids = await access.class_ids_for(session, user.id)
    class_id = next(iter(sorted(class_ids, key=str)), None)

    row = await repo.create_session(
        session,
        game_id=game_id,
        mode="solo",
        status="created",
        seed=seed,
        school_id=user.school_id,
        created_by=user.id,
        content_pack_id=built.content_pack_id,
        config=built.config,
    )
    await repo.add_participant(
        session,
        session_id=row.id,
        user_id=user.id,
        seat=1,
        age_band_snapshot=built.age_band,
        class_id_snapshot=class_id,
    )

    # Phase 3 owns the start: limits, lockout, and the one-open-play rule.
    await lifecycle.start_play(session, user=user, session_id=row.id, now=now)
    return row


# ------------------------------------------------------------------- reading
async def _load(
    session: AsyncSession, *, user: User, session_id: uuid.UUID
) -> tuple[GameSession, GameParticipant]:
    row = await repo.get_session(session, session_id)
    if row is None or row.school_id != user.school_id:
        raise NotFoundError("That game was not found.")
    participant = await repo.get_participant(session, session_id, user.id)
    if participant is None:
        raise NotFoundError("That game was not found.")
    return row, participant


def _config(row: GameSession) -> dict[str, Any]:
    return dict(row.config)


def _rounds(row: GameSession) -> list[dict[str, Any]]:
    rounds = _config(row).get("rounds")
    return list(rounds) if isinstance(rounds, list) else []


def _view(row: GameSession, now: dt.datetime, award: xp.Award | None = None) -> PlayView:
    handler = handler_for(row.game_id)
    cfg = _config(row)
    rounds = _rounds(row)
    index = int(cfg.get("round_index", 0))
    scores = [int(s) for s in cfg.get("scores", [])]

    round_view: RoundView | None = None
    if index < len(rounds):
        current = rounds[index]
        started = _parse(cfg.get("round_started_at"))
        if started is None:
            left_ms = handler.round_seconds * 1000
        else:
            elapsed = (now - started).total_seconds()
            left_ms = max(0, int((handler.round_seconds - elapsed) * 1000))
        round_view = RoundView(
            number=index + 1,
            letters=str(current.get("letters", "")),
            clue=current.get("clue") if isinstance(current.get("clue"), str) else None,
            clue_image_key=current.get("clue_image_key")
            if isinstance(current.get("clue_image_key"), str)
            else None,
            clue_audio_key=current.get("clue_audio_key")
            if isinstance(current.get("clue_audio_key"), str)
            else None,
            revealed=cfg.get("revealed") if isinstance(cfg.get("revealed"), str) else None,
            tries_left=max(0, ws.MAX_ATTEMPTS - int(cfg.get("attempts", 0))),
            time_left_ms=left_ms,
            round_seconds=handler.round_seconds,
        )

    return PlayView(
        session_id=row.id,
        game_id=row.game_id,
        status=row.status,
        round=round_view,
        round_index=min(index, len(rounds)),
        rounds_total=len(rounds),
        score=sum(scores),
        scores=scores,
        finished=row.status == "finished",
        xp=None if award is None else _xp_out(award),
    )


def _xp_out(award: xp.Award) -> dict[str, int]:
    return results.award_out(award)


async def get_state(
    session: AsyncSession, *, user: User, session_id: uuid.UUID, now: dt.datetime | None = None
) -> PlayView:
    now = now or _now()
    row, _participant = await _load(session, user=user, session_id=session_id)
    if row.game_id == guess_rules.GAME_ID:
        return await guessing.get_state(session, user=user, row=row, now=now)
    await _advance_expired(session, user=user, row=row, now=now)
    await session.commit()
    return _view(row, now)


# ------------------------------------------------------------------- actions
async def submit_action(
    session: AsyncSession,
    *,
    user: User,
    session_id: uuid.UUID,
    client_move_id: str,
    action: str,
    value: str | None = None,
    now: dt.datetime | None = None,
) -> PlayView:
    now = now or _now()
    row, participant = await _load(session, user=user, session_id=session_id)
    if row.game_id == guess_rules.GAME_ID:
        return await guessing.submit_action(
            session,
            user=user,
            row=row,
            participant=participant,
            client_move_id=client_move_id,
            action=action,
            value=value,
            now=now,
        )
    handler = content_handler_for(row.game_id)

    if row.status == "finished":
        return _view(row, now)
    if row.status != "active":
        raise AppError("That game has ended.", code="session_ended", status_code=409)

    # A retried request must not score twice (P4-T15).
    if await repo.move_by_client_id(session, session_id=row.id, client_move_id=client_move_id):
        return _view(row, now)

    # A late action closes its round for nothing and is then refused, so the
    # client cannot keep answering a word whose time is up.
    pending_start = _parse(_config(row).get("round_started_at"))
    if (
        pending_start is not None
        and ws.is_late(pending_start, now)
        and action in ("answer", "skip", "hint")
    ):
        await _advance_expired(session, user=user, row=row, now=now)
        await session.commit()
        raise AppError("Time is up for that word.", code="round_expired", status_code=409)

    expired_award = await _advance_expired(session, user=user, row=row, now=now)
    if row.status == "finished":
        await session.commit()
        return _view(row, now, expired_award)

    cfg = _config(row)
    rounds = _rounds(row)
    index = int(cfg.get("round_index", 0))
    if index >= len(rounds):
        raise AppError("That game has ended.", code="session_ended", status_code=409)

    started = _parse(cfg.get("round_started_at"))
    outcome = "seen"
    scored: int | None = None

    if action == "round_seen":
        if started is None:
            cfg["round_started_at"] = now.isoformat()
        outcome = "seen"

    elif action == "hint":
        if started is None:
            raise AppError("Start the round first.", code="round_not_started", status_code=409)
        if cfg.get("hint_used"):
            raise ConflictError("You already used the hint.", code="hint_used")
        item = await _item_for_round(session, rounds, index)
        cfg["hint_used"] = True
        cfg["revealed"] = ws.revelation(item.answer)
        outcome = "hint"

    elif action in ("answer", "skip"):
        if started is None:
            raise AppError("Start the round first.", code="round_not_started", status_code=409)

        if action == "skip":
            scored = 0
            outcome = "skip"
            _close_round(cfg)
        else:
            item = await _item_for_round(session, rounds, index)
            guess = value or ""
            if handler.is_correct(item, guess):
                elapsed = (now - started).total_seconds()
                attempt = int(cfg.get("attempts", 0)) + 1
                scored = handler.round_score(
                    elapsed_seconds=elapsed,
                    used_hint=bool(cfg.get("hint_used")),
                    attempt=attempt,
                )
                outcome = "correct"
                _close_round(cfg)
            else:
                attempts = int(cfg.get("attempts", 0)) + 1
                cfg["attempts"] = attempts
                outcome = "wrong"
                if attempts >= ws.MAX_ATTEMPTS:
                    scored = 0
                    _close_round(cfg)
    else:
        raise AppError("That action is not allowed.", code="bad_action", status_code=400)

    if scored is not None:
        scores = list(cfg.get("scores", []))
        scores.append(scored)
        cfg["scores"] = scores

    row.config = cfg

    await repo.append_move(
        session,
        session_id=row.id,
        user_id=user.id,
        move_number=await repo.next_move_number(session, row.id),
        client_move_id=client_move_id,
        payload={
            "type": action,
            "value": value,
            "round": index + 1,
            "outcome": outcome,
            "score": scored,
        },
        server_ts=now,
    )

    # Every action proves the learner is playing, so it charges time (P3-T05).
    timezone = await access.school_timezone(session, user.school_id)
    await play_clock.record_activity(
        session, user_id=user.id, school_timezone=timezone, at=now, source="action"
    )

    if int(cfg.get("round_index", 0)) >= len(rounds):
        award = await results.finish_session(
            session, row=row, participant=participant, user=user, now=now
        )
        await session.commit()
        return _view(row, now, award)

    await session.commit()
    return _view(row, now)


async def _item_for_round(
    session: AsyncSession, rounds: list[dict[str, Any]], index: int
) -> ws.Item:
    item_id = rounds[index].get("item_id")
    if not isinstance(item_id, str):
        raise AppError("That round is missing.", code="bad_state", status_code=500)
    found = await repo.items_by_id(session, [uuid.UUID(item_id)])
    row = found.get(uuid.UUID(item_id))
    if row is None:
        raise AppError("That round is missing.", code="bad_state", status_code=500)
    return _item_from_row(row)


def _close_round(cfg: dict[str, Any]) -> None:
    cfg["round_index"] = int(cfg.get("round_index", 0)) + 1
    cfg["attempts"] = 0
    cfg["hint_used"] = False
    cfg["revealed"] = None
    cfg["round_started_at"] = None


async def _advance_expired(
    session: AsyncSession, *, user: User, row: GameSession, now: dt.datetime
) -> xp.Award | None:
    """Close rounds whose clock ran out while the session was open.

    A round that was never seen has no deadline: the tab may simply be closed,
    and the sweeper is the only thing that ends a silent session (P4-T08).

    Returns the award when this call finished the session, so a timeout still
    shows the post-game summary rather than ending the game silently.
    """
    if row.status != "active":
        return None

    rounds = _rounds(row)
    cfg = _config(row)
    changed = False

    started = _parse(cfg.get("round_started_at"))
    while started is not None and ws.is_late(started, now):
        scores = list(cfg.get("scores", []))
        scores.append(0)
        cfg["scores"] = scores
        _close_round(cfg)
        changed = True
        if int(cfg.get("round_index", 0)) >= len(rounds):
            break
        started = None  # the next round has not been seen yet

    if not changed:
        return None

    row.config = cfg
    participant = await repo.get_participant(session, row.id, user.id)
    award: xp.Award | None = None
    if int(cfg.get("round_index", 0)) >= len(rounds):
        if participant is not None:
            award = await results.finish_session(
                session, row=row, participant=participant, user=user, now=now
            )
    await session.flush()
    return award


# ------------------------------------------------------------- the sweeper
async def abandon_stale(
    session: AsyncSession, *, now: dt.datetime | None = None, silence_minutes: int = 10
) -> int:
    """Abandon solo sessions nobody has touched (P4-T08).

    No result row, no XP; the time already accrued stays counted. This is the
    only way a silent session ends — rounds never auto-complete a session.
    """
    from sqlalchemy import func, select

    from app.games.models import GameMove

    now = now or _now()
    cutoff = now - dt.timedelta(minutes=silence_minutes)

    last_move = (
        select(GameMove.session_id, func.max(GameMove.server_ts).label("last_ts"))
        .group_by(GameMove.session_id)
        .subquery()
    )
    stmt = (
        select(GameSession)
        .outerjoin(last_move, last_move.c.session_id == GameSession.id)
        .where(
            GameSession.status.in_(("active", "paused")),
            GameSession.mode == "solo",
            func.coalesce(last_move.c.last_ts, GameSession.started_at, GameSession.created_at)
            < cutoff,
        )
    )
    rows = list((await session.execute(stmt)).scalars().all())
    for row in rows:
        row.status = "abandoned"
        row.ended_at = now
        participants = await repo.list_participants(session, row.id)
        for participant in participants:
            if participant.attempt_status == "in_progress":
                participant.attempt_status = "expired"
    await session.commit()
    return len(rows)
