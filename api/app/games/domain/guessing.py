"""Number Guess rules, pure (P6-T01).

Five numbers per session: one number is too short to be worth playing, let
alone worth XP. Each number has a fixed number of tries, and the score falls the
longer the learner takes to find it.

The one decision that shapes everything here: **the secret is derived, never
stored.** ``secret_for(seed, index, difficulty)`` is the only way to learn a
number, and it needs the session seed, which lives in the session row and never
leaves the server (D-25). So there is nothing to strip from a response, nothing
to forget to remove from a log line, and a moderator can still replay a session
exactly from its seed and its moves (P6-T06).

Difficulty, tries and score all come from the table below, so re-tuning the hard
band — which has no margin today: ten tries for a thousand numbers is exactly
enough for a perfect binary search — is a one-line change, not a rewrite.
"""

from __future__ import annotations

import datetime as dt
import random
from dataclasses import dataclass

GAME_ID = "number_guess"

ROUNDS = 5
ROUND_SECONDS = 60
# A slow connection must not lose a number (D-24), so a guess is accepted for
# two seconds after the clock says the number is over.
DEADLINE_GRACE_SECONDS = 2

# D-29's activity minimum: a session that solved fewer numbers than this awards
# no XP (``domain/xp_rules.py`` reads ``solved`` from the result details).
MIN_SOLVED = 2

MAX_POINTS_PER_NUMBER = 100


@dataclass(frozen=True, slots=True)
class Level:
    """One difficulty: the range to search, and how many tries that deserves."""

    low: int
    high: int
    tries: int


LEVELS: dict[int, Level] = {
    1: Level(low=1, high=50, tries=8),
    2: Level(low=1, high=200, tries=9),
    3: Level(low=1, high=1000, tries=10),
}


def level_for(difficulty: int) -> Level:
    """The level, or a clear failure — a silent default would change the game."""
    level = LEVELS.get(difficulty)
    if level is None:
        raise ValueError(f"no difficulty {difficulty}")
    return level


def rounds_for(difficulty: int) -> list[dict[str, object]]:
    """The five numbers of a session, without their secrets.

    The index is what the secret is derived from, so the stored rounds are safe
    to keep in the session row next to the seed.
    """
    level = level_for(difficulty)
    return [
        {"number": index + 1, "low": level.low, "high": level.high, "tries": level.tries}
        for index in range(ROUNDS)
    ]


def secret_for(seed: int, index: int, difficulty: int) -> int:
    """The number to find, reproducible from the session seed alone.

    Seeded with a string, not the bare seed: two positions in one session must
    not share a stream, and ``Random(str)`` hashes the whole string, so
    ``f"{seed}:{index}"`` gives every number its own independent draw.
    """
    level = level_for(difficulty)
    return random.Random(f"{seed}:{index}").randint(level.low, level.high)  # noqa: S311


def in_range(value: int, level: Level) -> bool:
    return level.low <= value <= level.high


def compare(secret: int, guess: int) -> str:
    """``correct``, or which way the learner must move next."""
    if guess == secret:
        return "correct"
    return "higher" if secret > guess else "lower"


def narrow(low: int, high: int, guess: int, feedback: str) -> tuple[int, int]:
    """The range after a wrong guess, so the bar visibly shrinks (P6-T03).

    Narrowed against the guess, not against the secret, so the window never
    reveals more than the learner has earned.
    """
    if feedback == "higher":
        return max(low, guess + 1), high
    if feedback == "lower":
        return low, min(high, guess - 1)
    return low, high


def score_for(*, attempt: int, tries: int) -> int:
    """Points for a correct guess: 100 on the first try, less on later ones.

    ``round(100 * (N - k + 1) / N)`` with half-up rounding, because Python's
    ``round`` is banker's rounding and two learners on the same try would get
    different points depending on the neighbour's parity.
    """
    if tries <= 0:  # pragma: no cover - configuration cannot reach this
        return 0
    used = min(max(1, attempt), tries)
    remaining = tries - used + 1
    return int(MAX_POINTS_PER_NUMBER * remaining / tries + 0.5)


def deadline(started_at: dt.datetime) -> dt.datetime:
    return started_at + dt.timedelta(seconds=ROUND_SECONDS + DEADLINE_GRACE_SECONDS)


def is_late(started_at: dt.datetime, now: dt.datetime) -> bool:
    return now > deadline(started_at)


def feedback_sentence(feedback: str) -> str:
    """The one sentence a learner sees for a server feedback code (Appendix D).

    Kept here with the codes so a new code cannot reach a screen as a raw word
    like ``out_of_range``: the mapping is exhaustive and lives next to the
    values it describes.
    """
    return {
        "higher": "Too low. Go up.",
        "lower": "Too high. Go down.",
        "correct": "You found it!",
        "repeat": "You tried that number.",
        "out_of_range": "That number is outside the box.",
    }.get(feedback, "Try another number.")
