"""The daily quest and the level ring (pure).

Both are motivational only. The level is a presentational restatement of Profile
XP — it is not a grade, not a badge, and nothing reads it to decide anything
(P5-T05). The quest is a small fixed goal with a small XP bonus, paid through the
normal capped award so it can never exceed the day's cap.
"""

from __future__ import annotations

from dataclasses import dataclass

# A level costs a little more than the one before: 50 XP to leave level 1,
# then 75, 100, 125 ... One number, in one place, so the ring and the header can
# never disagree.
#
# The first step is short on purpose: the very first game should move the ring,
# or the bar looks broken. After that the growth is gentle enough that a learner
# who plays most days still sees a new level every week or so, and the gap stays
# readable — level 10 arrives at 1,350 XP, level 20 at 5,225.
FIRST_SPAN = 50
SPAN_STEP = 25


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


def span_for(number: int) -> int:
    """The XP a level costs, by its number: 50, 75, 100, 125 ...

    ``number`` is 1-based, and the span belongs to the level being *left*.
    """
    return FIRST_SPAN + SPAN_STEP * (max(1, int(number)) - 1)


def level_for(profile_xp: int) -> Level:
    """Where a total lands on the ring. Never used for eligibility."""
    total = max(0, int(profile_xp))
    number = 1
    span = span_for(number)
    # Each step is spent before the next one starts: 50 takes you to level 2,
    # the next 75 to level 3. The sum is quadratic, so this loop runs a few
    # hundred times at most for a real learner.
    while total >= span:
        total -= span
        number += 1
        span = span_for(number)
    return Level(number=number, xp_into=total, xp_span=span)
