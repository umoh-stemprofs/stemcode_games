"""Turning a seed and a learner into a session's rounds (P4-T10, P6-T05, P7-T05).

Both solo play and challenge mode need exactly this, and they must agree: a
challenge's two children are only fair if they were built the same way. So the
round building lives here once, for both kinds of game:

- a **content game** draws its rounds from the words that are live for the
  learner's age band;
- a **seed game** derives everything from the seed.

The seed is passed in, never read here, and never returned (D-25). The caller
owns the transaction.
"""

from __future__ import annotations

import random
from dataclasses import dataclass
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import AppError
from app.games import repository as repo
from app.games.domain import guessing as guess_rules
from app.games.domain import wordscramble as ws
from app.games.models import ContentItem, ContentPack
from app.games.registry import content_handler_for, handler_for
from app.identity.models import User
from app.identity.service import get_age_band

LOCALE = "en"


@dataclass(frozen=True, slots=True)
class Built:
    """What a session needs to exist: its config and where it came from."""

    config: dict[str, Any]
    age_band: str | None
    content_pack_id: Any | None


def item_from_row(row: ContentItem) -> ws.Item:
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


async def build(
    session: AsyncSession,
    *,
    user: User,
    game_id: str,
    difficulty: int,
    seed: int,
    local_date: Any,
) -> Built:
    """Build the config for one session, or explain why it cannot exist."""
    handler = handler_for(game_id)

    if game_id == guess_rules.GAME_ID:
        try:
            level = guess_rules.level_for(difficulty)
        except ValueError as exc:
            raise AppError("Pick a level to play.", code="bad_difficulty", status_code=400) from exc
        band = await get_age_band(session, date_of_birth=user.date_of_birth, on_date=local_date)
        return Built(
            config={
                "difficulty": difficulty,
                "rounds": guess_rules.rounds_for(difficulty),
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
            age_band=band.id if band is not None else None,
            content_pack_id=None,
        )

    # A content game: live words for this band, at this level.
    content_handler = content_handler_for(game_id)
    band = await get_age_band(session, date_of_birth=user.date_of_birth, on_date=local_date)
    if band is None:
        raise AppError(
            "There are no words for your year group yet.",
            code="not_enough_content",
            status_code=409,
        )
    rows = await repo.live_items(session, game_id=game_id, locale=LOCALE, age_band=band.id)
    if not rows:
        raise AppError(
            "There are no words for your year group yet.",
            code="not_enough_content",
            status_code=409,
        )
    playable = [item_from_row(row) for row in rows if row.difficulty == difficulty]
    if len(playable) < handler.rounds:
        raise AppError(
            "There are not enough words at that level yet.",
            code="not_enough_content",
            status_code=409,
        )

    rng = random.Random(seed)  # noqa: S311 - reproducible, not secret
    rounds = content_handler.build_rounds(playable, rng)
    pack: ContentPack | None = await repo.serving_pack(
        session, game_id=game_id, locale=LOCALE, age_band=band.id
    )
    return Built(
        config={
            "difficulty": difficulty,
            "rounds": rounds,
            "round_index": 0,
            "scores": [],
            "attempts": 0,
            "hint_used": False,
            "revealed": None,
            "round_started_at": None,
        },
        age_band=band.id,
        content_pack_id=pack.id if pack is not None else None,
    )
