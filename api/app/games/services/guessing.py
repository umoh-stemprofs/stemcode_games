"""Playing Number Guess (P6-T01 .. P6-T05).

The session lifecycle is the same as every other game — Phase 3 starts it, the
clock is charged per action, the result is written once and XP follows it in the
same transaction. What differs is the shape of a round, and that is all this
module adds:

- **No content packs** (P6-T05). The five numbers come from the session seed, so
  a new school can play on day one without publishing a word.
- **One action that matters: ``guess``.** ``round_seen`` starts the number's
  clock, ``skip`` gives the number up, and anything else is refused.
- **A wrong guess is not a mistake.** An out-of-range or repeated number costs
  no try: the learner is told why in one sentence and can try again. Only a
  number the secret can actually be compared against uses a try.

Nothing in here ever puts the secret in the view. ``domain.guessing`` derives it
from the seed when it is needed, and the seed stays in the session row (D-25).
"""

from __future__ import annotations

import datetime as dt
import secrets
import uuid
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import AppError, NotFoundError
from app.games import repository as repo
from app.games.domain import access as rules
from app.games.domain import guessing as game
from app.games.models import GameParticipant, GameSession
from app.games.services import access, results, xp
from app.games.services import clock as play_clock
from app.games.services import sessions as lifecycle
from app.games.services.views import PlayView, RoundView
from app.identity.models import User
from app.identity.service import get_age_band


def _now() -> dt.datetime:
    return dt.datetime.now(dt.UTC)


def _parse(value: object) -> dt.datetime | None:
    if not isinstance(value, str) or not value:
        return None
    return dt.datetime.fromisoformat(value)


# ------------------------------------------------------------------ creating
async def create_solo(
    session: AsyncSession,
    *,
    user: User,
    difficulty: int,
    now: dt.datetime | None = None,
) -> GameSession:
    """Open a session. No content check: the numbers come from the seed."""
    now = now or _now()
    try:
        level = game.level_for(difficulty)
    except ValueError as exc:
        raise AppError("Pick a level to play.", code="bad_difficulty", status_code=400) from exc

    timezone = await access.school_timezone(session, user.school_id)
    today = rules.local_date(now, timezone)
    band = await get_age_band(session, date_of_birth=user.date_of_birth, on_date=today)

    # Not for secrecy: the seed is random, and it is the only thing needed to
    # rebuild this session's numbers (P6-T06).
    seed = secrets.randbits(63)

    class_ids = await access.class_ids_for(session, user.id)
    class_id = next(iter(sorted(class_ids, key=str)), None)

    row = await repo.create_session(
        session,
        game_id=game.GAME_ID,
        mode="solo",
        status="created",
        seed=seed,
        school_id=user.school_id,
        created_by=user.id,
        content_pack_id=None,
        config={
            "difficulty": difficulty,
            "rounds": game.rounds_for(difficulty),
            "round_index": 0,
            "scores": [],
            "solved": 0,
            "attempts": 0,
            "guesses": [],
            "feedback": None,
            "window_low": level.low,
            "window_high": level.high,
            "round_started_at": None,
        },
    )
    await repo.add_participant(
        session,
        session_id=row.id,
        user_id=user.id,
        seat=1,
        age_band_snapshot=band.id if band is not None else None,
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
    return [dict(entry) for entry in rounds] if isinstance(rounds, list) else []


def _secret(row: GameSession, index: int) -> int:
    seed = row.seed
    if seed is None:  # pragma: no cover - create_solo always writes one
        raise AppError("That number is missing.", code="bad_state", status_code=500)
    return game.secret_for(seed, index, int(_config(row).get("difficulty", 1)))


def _view(
    row: GameSession, now: dt.datetime, award: xp.Award | None = None, message: str | None = None
) -> PlayView:
    cfg = _config(row)
    rounds = _rounds(row)
    index = int(cfg.get("round_index", 0))
    scores = [int(value) for value in cfg.get("scores", [])]

    round_view: RoundView | None = None
    if index < len(rounds) and row.status != "finished":
        entry = rounds[index]
        tries = int(entry.get("tries", 0))
        attempts = int(cfg.get("attempts", 0))
        started = _parse(cfg.get("round_started_at"))
        if started is None:
            left_ms = game.ROUND_SECONDS * 1000
        else:
            elapsed = (now - started).total_seconds()
            left_ms = max(0, int((game.ROUND_SECONDS - elapsed) * 1000))

        guesses = cfg.get("guesses")
        last_feedback = cfg.get("feedback")
        round_view = RoundView(
            number=index + 1,
            low=int(cfg.get("window_low", entry.get("low", 1))),
            high=int(cfg.get("window_high", entry.get("high", 100))),
            range_low=int(entry.get("low", 1)),
            range_high=int(entry.get("high", 100)),
            difficulty=int(cfg.get("difficulty", 1)),
            tries_left=max(0, tries - attempts),
            tries_total=tries,
            time_left_ms=left_ms,
            round_seconds=game.ROUND_SECONDS,
            feedback=last_feedback if isinstance(last_feedback, str) else None,
            message=game.feedback_sentence(last_feedback)
            if isinstance(last_feedback, str)
            else None,
            guesses=tuple(int(value) for value in guesses) if isinstance(guesses, list) else (),
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
        xp=None if award is None else results.award_out(award),
        message=message,
    )


async def get_state(
    session: AsyncSession,
    *,
    user: User,
    row: GameSession,
    now: dt.datetime | None = None,
) -> PlayView:
    now = now or _now()
    award, message = await _advance_expired(session, user=user, row=row, now=now)
    await session.commit()
    return _view(row, now, award, message)


# ------------------------------------------------------------------- actions
async def submit_action(
    session: AsyncSession,
    *,
    user: User,
    row: GameSession,
    participant: GameParticipant,
    client_move_id: str,
    action: str,
    value: str | None = None,
    now: dt.datetime | None = None,
) -> PlayView:
    now = now or _now()

    if row.status == "finished":
        return _view(row, now)
    if row.status != "active":
        raise AppError("That game has ended.", code="session_ended", status_code=409)

    # A retried request must not score twice (P4-T15).
    if await repo.move_by_client_id(session, session_id=row.id, client_move_id=client_move_id):
        return _view(row, now)

    # A guess that arrives after the number's clock ran out closes that number
    # for nothing, then is refused — the client cannot keep playing a dead bar.
    pending = _parse(_config(row).get("round_started_at"))
    if pending is not None and game.is_late(pending, now) and action in ("guess", "skip"):
        await _advance_expired(session, user=user, row=row, now=now)
        await session.commit()
        raise AppError("Time is up for that number.", code="round_expired", status_code=409)

    award, message = await _advance_expired(session, user=user, row=row, now=now)
    if row.status == "finished":
        await session.commit()
        return _view(row, now, award, message)

    cfg = _config(row)
    rounds = _rounds(row)
    index = int(cfg.get("round_index", 0))
    if index >= len(rounds):
        raise AppError("That game has ended.", code="session_ended", status_code=409)

    entry = rounds[index]
    tries = int(entry.get("tries", 0))
    started = _parse(cfg.get("round_started_at"))
    outcome = "seen"
    scored: int | None = None
    feedback: str | None = None
    message = None

    if action == "round_seen":
        if started is None:
            cfg["round_started_at"] = now.isoformat()

    elif action == "skip":
        if started is None:
            raise AppError("Start the number first.", code="round_not_started", status_code=409)
        scored = 0
        message = f"No more tries. It was {_secret(row, index)}."
        outcome = "skip"
        _close_number(cfg, entry)

    elif action == "guess":
        if started is None:
            raise AppError("Start the number first.", code="round_not_started", status_code=409)

        parsed = _parse_guess(value)
        if parsed is None:
            # Not a number at all: the client sent something a pad cannot send.
            raise AppError("Type a number.", code="bad_guess", status_code=400)

        level = game.level_for(int(cfg.get("difficulty", 1)))
        previous = cfg.get("guesses")
        already = [int(value) for value in previous] if isinstance(previous, list) else []

        if not game.in_range(parsed, level):
            # Free: the box already shows the range, so this is a slip, not a
            # wrong answer, and D-24's spirit says do not punish a slip.
            feedback = "out_of_range"
            message = game.feedback_sentence(feedback)
            outcome = "invalid"
        elif parsed in already:
            feedback = "repeat"
            message = game.feedback_sentence(feedback)
            outcome = "invalid"
        else:
            verdict = game.compare(_secret(row, index), parsed)
            attempts = int(cfg.get("attempts", 0)) + 1
            cfg["attempts"] = attempts
            cfg["guesses"] = [*already, parsed]
            feedback = verdict
            message = game.feedback_sentence(verdict)
            if verdict == "correct":
                scored = game.score_for(attempt=attempts, tries=tries)
                cfg["solved"] = int(cfg.get("solved", 0)) + 1
                outcome = "correct"
                _close_number(cfg, entry)
            else:
                low, high = game.narrow(
                    int(cfg.get("window_low", level.low)),
                    int(cfg.get("window_high", level.high)),
                    parsed,
                    verdict,
                )
                cfg["window_low"] = low
                cfg["window_high"] = high
                outcome = "wrong"
                if attempts >= tries:
                    scored = 0
                    message = f"No more tries. It was {_secret(row, index)}."
                    _close_number(cfg, entry)
    else:
        raise AppError("That action is not allowed.", code="bad_action", status_code=400)

    if feedback is not None and int(cfg.get("round_index", 0)) == index:
        # The last word on this number, so a slip (out of range, repeat) is
        # still answered on screen even though it cost nothing.
        cfg["feedback"] = feedback

    if scored is not None:
        cfg["scores"] = [*[int(value) for value in cfg.get("scores", [])], scored]

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
            "number": index + 1,
            "outcome": outcome,
            "feedback": feedback,
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
            session,
            row=row,
            participant=participant,
            user=user,
            now=now,
            details_extra={"solved": int(cfg.get("solved", 0))},
        )
        await session.commit()
        return _view(row, now, award, message)

    await session.commit()
    return _view(row, now, message=message)


def _parse_guess(value: str | None) -> int | None:
    if value is None:
        return None
    text = value.strip()
    if not text or len(text) > 4:
        return None
    try:
        return int(text)
    except ValueError:
        return None


def _close_number(cfg: dict[str, Any], entry: dict[str, Any]) -> None:
    """Move to the next number, and forget this one's tries and window."""
    cfg["round_index"] = int(cfg.get("round_index", 0)) + 1
    cfg["attempts"] = 0
    cfg["guesses"] = []
    cfg["feedback"] = None
    cfg["window_low"] = int(entry.get("low", 1))
    cfg["window_high"] = int(entry.get("high", 100))
    cfg["round_started_at"] = None


async def _advance_expired(
    session: AsyncSession, *, user: User, row: GameSession, now: dt.datetime
) -> tuple[xp.Award | None, str | None]:
    """Close the number whose clock ran out while the tab was open.

    An unseen number has no deadline: a closed tab is not a lost number, and the
    sweeper is the only thing that ends a silent session (P4-T08).
    """
    if row.status != "active":
        return None, None

    cfg = _config(row)
    rounds = _rounds(row)
    index = int(cfg.get("round_index", 0))
    started = _parse(cfg.get("round_started_at"))
    if started is None or not game.is_late(started, now) or index >= len(rounds):
        return None, None

    secret = _secret(row, index)
    cfg["scores"] = [*[int(value) for value in cfg.get("scores", [])], 0]
    _close_number(cfg, rounds[index])
    row.config = cfg

    participant = await repo.get_participant(session, row.id, user.id)
    award: xp.Award | None = None
    if int(cfg.get("round_index", 0)) >= len(rounds) and participant is not None:
        award = await results.finish_session(
            session,
            row=row,
            participant=participant,
            user=user,
            now=now,
            details_extra={"solved": int(cfg.get("solved", 0))},
        )
    await session.flush()
    return award, f"Time is up. It was {secret}."
