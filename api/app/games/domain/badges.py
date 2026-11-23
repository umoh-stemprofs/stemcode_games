"""Badge definitions (pure).

A badge is a fact about *play*: how many games, how many wins, how many days in
a row, how many quests finished. It is deliberately not a fact about XP —
P5-T05 forbids Game XP or Profile XP from feeding badges, certificates or any
eligibility decision, and this module has no field for a total to be passed in.

Criteria are functions over ``BadgeFacts`` so the database never stores a rule:
adding a badge is a code change with a test, not a migration.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class BadgeFacts:
    """Everything a badge may look at. Counts, never points."""

    games_played: int
    wins: int
    checkers_wins: int
    games_tried: int
    best_guess_solved: int
    longest_streak: int
    quests_completed: int


@dataclass(frozen=True, slots=True)
class Badge:
    id: str
    title: str
    # What the learner reads once it is theirs (Appendix D: short sentences).
    sentence: str
    # The one line that tells them how to get it, before they have it.
    hint: str
    earned: Callable[[BadgeFacts], bool]


BADGES: tuple[Badge, ...] = (
    Badge(
        id="first_game",
        title="First game",
        sentence="You played your first game.",
        hint="Play a game.",
        earned=lambda f: f.games_played >= 1,
    ),
    Badge(
        id="five_games",
        title="Five games",
        sentence="You played five games.",
        hint="Play five games.",
        earned=lambda f: f.games_played >= 5,
    ),
    Badge(
        id="twenty_games",
        title="Twenty games",
        sentence="You played twenty games.",
        hint="Play twenty games.",
        earned=lambda f: f.games_played >= 20,
    ),
    Badge(
        id="first_win",
        title="First win",
        sentence="You won a game.",
        hint="Win a game.",
        earned=lambda f: f.wins >= 1,
    ),
    Badge(
        id="checkers_champ",
        title="Checker champ",
        sentence="You won at Checkers.",
        hint="Win a Checkers match.",
        earned=lambda f: f.checkers_wins >= 1,
    ),
    Badge(
        id="number_hunter",
        title="Number hunter",
        sentence="You solved three numbers in one game.",
        hint="Solve three numbers in one game.",
        earned=lambda f: f.best_guess_solved >= 3,
    ),
    Badge(
        id="all_games",
        title="Tried them all",
        sentence="You played every game.",
        hint="Play all three games.",
        earned=lambda f: f.games_tried >= 3,
    ),
    Badge(
        id="streak_3",
        title="Three in a row",
        sentence="You played three days in a row.",
        hint="Play three days in a row.",
        earned=lambda f: f.longest_streak >= 3,
    ),
    Badge(
        id="streak_7",
        title="Week strong",
        sentence="You played seven days in a row.",
        hint="Play seven days in a row.",
        earned=lambda f: f.longest_streak >= 7,
    ),
    Badge(
        id="quest_keeper",
        title="Quest keeper",
        sentence="You finished five daily quests.",
        hint="Finish five daily quests.",
        earned=lambda f: f.quests_completed >= 5,
    ),
)

BY_ID: dict[str, Badge] = {badge.id: badge for badge in BADGES}


def earned_badges(facts: BadgeFacts) -> list[Badge]:
    """Every badge these facts satisfy, in definition order."""
    return [badge for badge in BADGES if badge.earned(facts)]
