"""Ending a session: one result row, one XP decision (P5-T03).

Every game finishes the same way, so it happens in one place: mark the session
finished, write the append-only result, and award XP in the *same* transaction,
so a rolled-back result can never leave an award behind. The only thing that
differs per game is what the result details say — Word Scramble its round
scores, Number Guess its solved count — and that arrives as ``details_extra``.

Kept out of ``services/play.py`` because Number Guess does not share that
module's content pipeline and must not import it just to end a game.
"""

from __future__ import annotations

import dataclasses
import datetime as dt
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.games import repository as repo
from app.games.models import GameParticipant, GameSession
from app.games.services import engagement, xp
from app.identity.models import Role, User


def award_out(award: xp.Award) -> dict[str, int]:
    """The post-game summary a learner sees: awarded now, and room today."""
    return {
        "awarded": award.awarded,
        "today": award.today,
        "daily_cap": award.daily_cap,
    }


async def finish_session(
    session: AsyncSession,
    *,
    row: GameSession,
    participant: GameParticipant,
    user: User,
    now: dt.datetime,
    details_extra: dict[str, Any] | None = None,
) -> xp.Award:
    """Close the session and award XP for the result just written."""
    cfg = dict(row.config)
    scores = [int(value) for value in cfg.get("scores", [])]
    row.status = "finished"
    row.ended_at = now
    participant.attempt_status = "finished"

    details: dict[str, Any] = {
        "difficulty": cfg.get("difficulty"),
        # Per-round scores, in order: what the screen shows and what a
        # moderator replays. Never an answer, never a secret.
        "rounds": scores,
        "game_id": row.game_id,
    }
    if details_extra:
        details.update(details_extra)

    result = await repo.append_result(
        session,
        session_id=row.id,
        user_id=user.id,
        outcome="completed",
        score=sum(scores),
        details=details,
        # Server-verified; the XP rules still decide whether real play happened.
        leaderboard_eligible=True,
    )
    await session.flush()
    award = await xp.award_for_result(session, result=result, game_row=row, user=user, now=now)

    # Engagement facts are written in the same transaction as the result, so a
    # rolled-back game can never leave a streak, a quest tick or a badge behind.
    if user.role is Role.learner:
        await engagement.touch_streak(session, user=user, now=now)
        quest_paid = await engagement.advance_quest(
            session, user=user, game_row=row, now=now
        )
        await engagement.sync_badges(session, user=user, now=now)
        if quest_paid:
            # The quest bonus landed *after* the game award was summarised, so
            # the end screen's "today" would otherwise be 10 short.
            award = dataclasses.replace(award, today=award.today + quest_paid)

    # A challenge child settles the moment both attempts are in (P7-T05).
    # Imported here so the shared finish path does not force every caller to
    # know that challenges exist.
    if row.parent_session_id is not None:
        from app.games.services import challenge

        await challenge.apply(session, child=row, now=now)
    return award
