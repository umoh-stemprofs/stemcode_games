"""Game XP rules, pure (P5-T01).

Every number here comes from D-13 and is *configurable in the plan*, not in this
file's callers: the service reads the cap and the minimums, so a school rolling
out with gentler numbers does not need a code change.

Three rules that are easy to get wrong and are therefore decided here, once:

- **Participation XP requires real play** (D-29). A session under the activity
  minimum requests zero — and still records a ledger row, so the decision is
  auditable rather than invisible.
- **Checkers' win/draw value replaces the performance bonus**, it does not add
  to it: otherwise a win is worth more than "played well" by accident.
- **Nothing here awards XP.** This module answers "how much would this result
  request?", and the service applies the cap.
"""

from __future__ import annotations

from dataclasses import dataclass

PARTICIPATION = 5
MAX_PERFORMANCE_BONUS = 10
CHALLENGE_WIN_BONUS = 5
# There is no daily cap by default: every game pays what it earned. The setting
# still exists, so a school that wants one can set a number; 0 means "no cap".
DEFAULT_DAILY_CAP = 0
# One finished game is enough to appear on a board. A minimum above 1 made a
# learner who had just played see an empty board and be told to play again.
DEFAULT_MIN_SESSIONS = 1

# The score that earns the full performance bonus, per game. Word Scramble's
# ten rounds cap at 150 (10 points + 5 time bonus each); Number Guess's five
# numbers at 100 each.
FULL_MARKS: dict[str, int] = {
    "word_scramble": 150,
    "number_guess": 500,
}

# Checkers is decided by the outcome, not by a score.
OUTCOME_VALUES: dict[str, int] = {
    "win": 10,
    "draw": 5,
    "loss": 0,
}


@dataclass(frozen=True, slots=True)
class XpRequest:
    """What a result asks for, and why it got what it got."""

    requested: int
    reason: str
    meets_minimum: bool


def _round_half_up(value: float) -> int:
    """``round()`` in Python is banker's rounding; XP must not be.

    7.5 points should be 8, not 8-or-7 depending on the neighbour's parity.
    """
    return int(value + 0.5) if value >= 0 else -int(-value + 0.5)


def performance_bonus(game_id: str, score: int) -> int:
    """0..10, scaled against the game's full marks."""
    full = FULL_MARKS.get(game_id)
    if not full:
        return 0
    safe_score = max(0, min(score, full))
    return _round_half_up(MAX_PERFORMANCE_BONUS * safe_score / full)


def meets_activity_minimum(game_id: str, details: dict[str, object]) -> bool:
    """D-29: did the learner actually play?

    Read from the server-written result details, never from anything the client
    sends. A game this build does not know is treated as *not* meeting the
    minimum: guessing "yes" would hand out XP for a rule nobody wrote.
    """
    if game_id == "word_scramble":
        rounds = details.get("rounds")
        if not isinstance(rounds, list):
            return False
        correct = sum(1 for value in rounds if isinstance(value, int) and value > 0)
        return correct >= 4
    if game_id == "number_guess":
        solved = details.get("solved")
        return isinstance(solved, int) and solved >= 2
    if game_id == "checkers":
        moves = details.get("moves")
        return isinstance(moves, int) and moves >= 8
    return False


def request_xp(
    *,
    game_id: str,
    outcome: str,
    score: int,
    details: dict[str, object],
    challenge_win: bool = False,
) -> XpRequest:
    """What this result asks for, before the daily cap is applied."""
    if outcome == "no_contest":
        return XpRequest(requested=0, reason="no_contest", meets_minimum=False)

    if not meets_activity_minimum(game_id, details):
        return XpRequest(requested=0, reason="below_minimum", meets_minimum=False)

    if game_id == "checkers":
        bonus = OUTCOME_VALUES.get(outcome, 0)
    else:
        bonus = performance_bonus(game_id, score)

    requested = PARTICIPATION + bonus
    if challenge_win:
        requested += CHALLENGE_WIN_BONUS
    return XpRequest(requested=max(0, requested), reason="played", meets_minimum=True)


def capped_award(requested: int, already_today: int, daily_cap: int) -> int:
    """Never negative, never over the cap (D-13).

    A cap of 0 (or less) is no cap: XP is paid in full, which is the default.
    The cap survives as an opt-in setting rather than a constant, so the rule is
    still applied in one place when a school turns it on.
    """
    wanted = max(0, requested)
    if daily_cap <= 0:
        return wanted
    room = max(0, daily_cap - max(0, already_today))
    return max(0, min(wanted, room))
