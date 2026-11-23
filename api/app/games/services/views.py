"""What a player's screen is allowed to know (P4-T12, P6-T03).

One round model for every game. Word Scramble fills the letters half, Number
Guess fills the window half, and neither ever fills an answer or a secret: the
model simply has no field for one.

These live outside a game's service module because more than one game ends up
building them, and a shared model is cheaper than a copy that slowly drifts
(the screen is the same shape, so the payload is too).
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class RoundView:
    number: int
    time_left_ms: int
    round_seconds: int
    # Word Scramble (P4-T10)
    letters: str = ""
    clue: str | None = None
    clue_image_key: str | None = None
    clue_audio_key: str | None = None
    revealed: str | None = None
    tries_left: int = 0
    # Number Guess (P6-T03)
    low: int | None = None
    high: int | None = None
    # The level's own box (1-50, 1-200, 1-1000), so the screen can show how far
    # the search has narrowed without knowing the difficulty.
    range_low: int | None = None
    range_high: int | None = None
    # Which band this number came from (Number Guess only). The screen picks its
    # entry control from this, so the decision stays on the server.
    difficulty: int | None = None
    tries_total: int | None = None
    feedback: str | None = None
    # The fixed sentence for `feedback` (Appendix D): the server owns the
    # wording, so a screen never has to turn a code into English itself.
    message: str | None = None
    guesses: tuple[int, ...] = ()


@dataclass(frozen=True, slots=True)
class PlayView:
    session_id: uuid.UUID
    game_id: str
    status: str
    round: RoundView | None
    round_index: int
    rounds_total: int
    score: int
    scores: list[int]
    finished: bool
    # The post-game summary, present only at the moment a session finishes.
    xp: dict[str, int] | None = None
    # One sentence about what just happened, when the round payload cannot
    # carry it (a finished number, a timeout).
    message: str | None = None
