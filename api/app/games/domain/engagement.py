"""The daily quest and the level ring (pure).

Both are motivational only. The level is a presentational restatement of Profile
XP — it is not a grade, not a badge, and nothing reads it to decide anything
(P5-T05). The quest is a small fixed goal with a small XP bonus, paid through the
normal capped award so it can never exceed the day's cap.
"""

from __future__ import annotations

from dataclasses import dataclass

# Level 1 is 0-99 Profile XP, level 2 starts at 100, and so on. One number, in
# one place, so the ring and the header can never disagree.
LEVEL_SPAN = 100


@dataclass(frozen=True, slots=True)
class Quest:
    id: str
    title: str
    target: int
    reward_xp: int


DAILY_QUEST = Quest(
    id="two_games",
    title="Play 2 games today",
    target=2,
    reward_xp=10,
)


@dataclass(frozen=True, slots=True)
class Level:
    number: int
    xp_into: int
    xp_span: int

    @property
    def xp_to_next(self) -> int:
        return max(0, self.xp_span - self.xp_into)


def level_for(profile_xp: int) -> Level:
    """Where a total lands on the ring. Never used for eligibility."""
    total = max(0, int(profile_xp))
    return Level(
        number=total // LEVEL_SPAN + 1,
        xp_into=total % LEVEL_SPAN,
        xp_span=LEVEL_SPAN,
    )
