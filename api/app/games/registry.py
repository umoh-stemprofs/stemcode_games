"""Game registry (P4-T09).

A game is a ``game_id`` plus, for a content game, the functions that turn stored
words into rounds and a guess into an answer. Sessions record which version they
were played on, so a later rules change cannot silently rewrite what a past
result meant.

Two kinds of game, and the difference is real:

- **content games** (Word Scramble) draw rounds from published words, so they
  also carry the builders that make a round and score an answer.
- **seed games** (Number Guess, Phase 6) draw everything from the session seed,
  so they only need their metadata here; their rules live in their own domain
  module. P6-T05 asks the shared pipeline to handle a game with no packs, and
  this is how: the handler says so by not being a ``ContentGameHandler``.

Checkers (Phase 8) plugs in here rather than growing special cases in the play
service.
"""

from __future__ import annotations

import random
from collections.abc import Callable
from dataclasses import dataclass

from app.games.domain import guessing
from app.games.domain import wordscramble as ws


@dataclass(frozen=True, slots=True)
class GameHandler:
    """What every game has: a name, a length of session, a round clock."""

    game_id: str
    rounds: int
    round_seconds: int


@dataclass(frozen=True, slots=True)
class ContentGameHandler(GameHandler):
    """A game whose rounds come from published content items."""

    build_rounds: Callable[[list[ws.Item], random.Random], list[dict[str, object]]]
    is_correct: Callable[[ws.Item, str], bool]
    round_score: Callable[..., int]


HANDLERS: dict[str, GameHandler] = {
    ws.GAME_ID: ContentGameHandler(
        game_id=ws.GAME_ID,
        rounds=ws.ROUNDS,
        round_seconds=ws.ROUND_SECONDS,
        build_rounds=ws.build_rounds,
        is_correct=ws.is_correct,
        round_score=ws.round_score,
    ),
    guessing.GAME_ID: GameHandler(
        game_id=guessing.GAME_ID,
        rounds=guessing.ROUNDS,
        round_seconds=guessing.ROUND_SECONDS,
    ),
}


def handler_for(game_id: str) -> GameHandler:
    """The handler for a game, or a clear failure — never a silent no-op."""
    handler = HANDLERS.get(game_id)
    if handler is None:
        raise KeyError(f"no handler registered for {game_id}")
    return handler


def content_handler_for(game_id: str) -> ContentGameHandler:
    """The handler for a content game, or a clear failure.

    Raising here rather than returning ``None`` keeps the play service from
    quietly treating a seed game as an empty content game.
    """
    handler = handler_for(game_id)
    if not isinstance(handler, ContentGameHandler):
        raise KeyError(f"{game_id} is not a content game")
    return handler
