"""Word Scramble rules, pure (P4-T10).

No database, no clock, no randomness except an injected ``Random``. That is
what lets the scoring table and the scramble be tested exactly, and what lets
the same seed reproduce a session on the moderator replay tool later.

The one rule that matters most to a child: **the server sends scrambled letters
and a clue, never the answer**. The answer is checked here, on the server, and
nothing in this module hands it back.
"""

from __future__ import annotations

import datetime as dt
import random
import re
from dataclasses import dataclass

from app.games.domain import safe_language

GAME_ID = "word_scramble"
ROUND_SECONDS = 45
# A slow connection must not lose a round (D-24), so a late answer is still
# accepted for two seconds after the deadline.
DEADLINE_GRACE_SECONDS = 2
MAX_ATTEMPTS = 2
HINT_COST = 3
BASE_POINTS = 10
MAX_TIME_BONUS = 5
ROUNDS = 10
MIN_ITEMS_PER_PACK = 15

_WORD = re.compile(r"^[a-z]{4,12}$")


@dataclass(frozen=True, slots=True)
class Item:
    """One scramble item, as stored in a pack payload."""

    id: str
    answer: str
    alt_answers: tuple[str, ...]
    clue: str | None
    clue_image_key: str | None
    clue_audio_key: str | None
    difficulty: int


def normalise(value: str) -> str:
    return value.strip().lower()


def has_another_arrangement(word: str) -> bool:
    """False for ``zzzz``, which has exactly one arrangement.

    Not a stylistic check: a word whose letters are all identical cannot be
    scrambled into something different, so the generator would have to send the
    answer as the puzzle.
    """
    return len(set(word)) > 1


def validate_item(
    payload: dict[str, object],
    *,
    youngest_band: bool = False,
    extra_blocked: frozenset[str] = frozenset(),
) -> list[str]:
    """Every reason this item may not be published (P4-T03). Empty means fine.

    ``extra_blocked`` is the school's own safe-language list; the built-in list
    is always checked. Passed in, never read from the database here, because
    this module has no I/O by rule.
    """
    problems: list[str] = []
    answer = normalise(str(payload.get("answer", "")))
    if not _WORD.match(answer):
        problems.append("The answer must be 4 to 12 letters, with no spaces.")

    alts = payload.get("alt_answers") or []
    if not isinstance(alts, list):
        problems.append("Other spellings must be a list.")
        alts = []
    for alt in alts:
        if not _WORD.match(normalise(str(alt))):
            problems.append("Another spelling is not 4 to 12 letters.")
        if normalise(str(alt)) == answer:
            problems.append("Another spelling repeats the answer.")

    clue = payload.get("clue")
    clue_text = normalise(str(clue)) if clue else ""
    image = payload.get("clue_image_key")
    audio = payload.get("clue_audio_key")

    if not clue_text and not image and not audio:
        problems.append("A clue is required: words, a picture, or a sound.")
    if youngest_band and not (image or audio):
        problems.append("The youngest band needs a picture or a sound clue.")
    if clue_text and answer and answer in clue_text:
        problems.append("The clue gives away the answer.")
    if clue_text and len(clue_text) > 120:
        problems.append("The clue is too long.")

    if answer and not has_another_arrangement(answer):
        problems.append("These letters cannot be mixed up.")

    # Safe language as its own question (P4-T03): a word or a clue a school
    # would not hand a child must never reach a game, whatever route put it
    # there. One sentence each, and the offending word is never echoed.
    #
    # It goes **first** in the list on purpose: the screen shows the first
    # problem, and "not safe for children" is the one that matters, even when a
    # word is also too long.
    problems = (
        safe_language.problems(
            answer=answer,
            clue=clue_text or None,
            alt_answers=[str(alt) for alt in alts],
            extra=extra_blocked,
        )
        + problems
    )

    difficulty = payload.get("difficulty", 1)
    if not isinstance(difficulty, int) or difficulty not in (1, 2, 3):
        problems.append("Difficulty must be 1, 2 or 3.")

    return problems


def scramble(answer: str, rng: random.Random) -> str:
    """A different arrangement of the answer's letters.

    ``validate_item`` guarantees another arrangement exists, so the loop always
    ends; the fallback keeps a bad item from hanging a session rather than
    crashing it.
    """
    letters = list(answer)
    for _ in range(20):
        rng.shuffle(letters)
        mixed = "".join(letters)
        if mixed != answer:
            return mixed
    # Deterministic rotation: different from the answer for the same reason.
    return answer[1:] + answer[0]


def time_bonus(elapsed_seconds: float) -> int:
    """0..5, linear over the round timer. Faster answers score more."""
    remaining = max(0.0, ROUND_SECONDS - max(0.0, elapsed_seconds))
    return min(MAX_TIME_BONUS, int(MAX_TIME_BONUS * remaining / ROUND_SECONDS))


def round_score(*, elapsed_seconds: float, used_hint: bool, attempt: int) -> int:
    """The points for a correct answer.

    Attempt 1 keeps the round score; attempt 2 halves it, rounded down. A hint
    costs three points and can never push the round below zero.
    """
    score = BASE_POINTS + time_bonus(elapsed_seconds)
    if used_hint:
        score -= HINT_COST
    score = max(0, score)
    if attempt >= 2:
        score //= 2
    return max(0, score)


def deadline(started_at: dt.datetime) -> dt.datetime:
    return started_at + dt.timedelta(seconds=ROUND_SECONDS + DEADLINE_GRACE_SECONDS)


def is_late(started_at: dt.datetime, now: dt.datetime) -> bool:
    return now > deadline(started_at)


def is_correct(item: Item, value: str) -> bool:
    guess = normalise(value)
    return guess == normalise(item.answer) or guess in {normalise(alt) for alt in item.alt_answers}


def revelation(answer: str) -> str:
    """What a hint shows: the first letter only."""
    return answer[:1].upper()


def build_rounds(items: list[Item], rng: random.Random) -> list[dict[str, object]]:
    """Pick ten items and scramble them (P4-T10).

    The rounds carry the letters and the clue — never the answer. Answers stay
    in the content table and are looked up at checking time.
    """
    if len(items) < ROUNDS:
        raise ValueError("not enough items to build a session")
    chosen = rng.sample(items, ROUNDS)
    return [
        {
            "item_id": item.id,
            "letters": scramble(item.answer, rng),
            "clue": item.clue,
            "clue_image_key": item.clue_image_key,
            "clue_audio_key": item.clue_audio_key,
        }
        for item in chosen
    ]
