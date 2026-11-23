"""Access rules as pure functions (P3-T02, P3-T03, D-08).

Nothing here touches the database or reads a clock. The caller passes ``now``
and the rows it already loaded, which is what makes the precedence matrix,
DST edges and clamping testable without fixtures.

Two ideas carry the whole module:

- **Specific wins.** A limit set on one learner beats a limit on their class,
  which beats the school, which beats the platform default. Among policies at
  the same level, the newest ``valid_from`` wins.
- **Today is the school's today.** ``local_date`` resolves the date in the
  school's own zone. A learner in Lagos at 00:30 is on the new day; the server
  being in UTC must not move their allowance.
"""

from __future__ import annotations

import datetime as dt
import uuid
from dataclasses import dataclass
from zoneinfo import ZoneInfo

# Reasons a learner can be stopped. Every one maps to one fixed sentence in
# the UI, so a new value here is a product decision, not an implementation
# detail (Appendix D).
OK = "ok"
LIMIT_REACHED = "limit_reached"
# A live match needs fifteen minutes left before it starts (D-27). That is a
# different sentence from "you are out of time", so it is a different reason.
NOT_ENOUGH_TIME = "not_enough_time"
LOCKED_OUT = "locked_out"
GAMES_DISABLED = "games_disabled"
ANOTHER_SESSION_ACTIVE = "another_session_active"
LEADERBOARDS_ONLY = "leaderboards_only"

# Most specific first.
SCOPE_RANK = {"student": 0, "class": 1, "school": 2, "platform": 3}


@dataclass(frozen=True, slots=True)
class PolicyView:
    """One policy row, reduced to what the decision needs."""

    scope_type: str
    scope_id: uuid.UUID | None
    daily_limit_minutes: int
    valid_from: dt.datetime
    valid_until: dt.datetime | None


@dataclass(frozen=True, slots=True)
class AccessView:
    """Everything the decision depends on, already gathered by the service."""

    limit_minutes: int
    limit_source: str
    used_seconds: int
    games_enabled: bool
    leaderboards_only: bool
    locked_until: dt.datetime | None
    another_session_active: bool
    min_remaining_s: int = 0


def local_date(now_utc: dt.datetime, timezone: str) -> dt.date:
    """The date as the school experiences it (P3-T03).

    ``now_utc`` must be timezone-aware: an accidental naive datetime would
    silently mean "server local time", which is the bug this function exists
    to prevent.
    """
    if now_utc.tzinfo is None:
        raise ValueError("local_date needs a timezone-aware datetime")
    return now_utc.astimezone(ZoneInfo(timezone)).date()


def next_local_midnight(now_utc: dt.datetime, timezone: str) -> dt.datetime:
    """When the allowance resets, as a UTC instant.

    The client is told the reset time so it never has to trust the device
    clock (P3-T06 ``server_time``).
    """
    zone = ZoneInfo(timezone)
    here = now_utc.astimezone(zone)
    tomorrow = (here + dt.timedelta(days=1)).date()
    return dt.datetime.combine(tomorrow, dt.time(0, 0), tzinfo=zone).astimezone(dt.UTC)


def _is_active(policy: PolicyView, at: dt.datetime) -> bool:
    if policy.valid_from > at:
        return False
    return policy.valid_until is None or at < policy.valid_until


def _applies_to(
    policy: PolicyView,
    *,
    user_id: uuid.UUID,
    school_id: uuid.UUID,
    class_ids: frozenset[uuid.UUID],
) -> bool:
    match policy.scope_type:
        case "platform":
            return True
        case "school":
            return policy.scope_id == school_id
        case "class":
            return policy.scope_id in class_ids
        case "student":
            return policy.scope_id == user_id
        case _:  # pragma: no cover - the database CHECK forbids this
            return False


def pick_policy(
    policies: list[PolicyView],
    *,
    at: dt.datetime,
    user_id: uuid.UUID,
    school_id: uuid.UUID,
    class_ids: frozenset[uuid.UUID],
) -> PolicyView | None:
    """The policy that decides today: most specific, then newest."""
    candidates = [
        p
        for p in policies
        if _is_active(p, at)
        and _applies_to(p, user_id=user_id, school_id=school_id, class_ids=class_ids)
    ]
    if not candidates:
        return None
    return min(
        candidates,
        key=lambda p: (SCOPE_RANK[p.scope_type], -p.valid_from.timestamp()),
    )


def clamp_limit(minutes: int | None, ceiling: int) -> int:
    """A limit can be zero (a full stop) but never above the platform ceiling."""
    if minutes is None:
        return ceiling
    return max(0, min(int(minutes), ceiling))


def remaining_seconds(limit_minutes: int, used_seconds: int) -> int:
    return max(0, limit_minutes * 60 - max(0, used_seconds))


def grace_deadline(now: dt.datetime, grace_minutes: int) -> dt.datetime:
    return now + dt.timedelta(minutes=grace_minutes)


def decide(view: AccessView, *, now: dt.datetime) -> tuple[bool, str]:
    """Decide whether play may start, and why not if it may not.

    Order matters and is chosen to be the most useful sentence first: a coach
    lockout outranks a full allowance, and "you have another game open" is
    more actionable than "you have no time left" when both are true.
    """
    if not view.games_enabled:
        return False, GAMES_DISABLED
    if view.locked_until is not None and view.locked_until > now:
        return False, LOCKED_OUT
    if view.leaderboards_only:
        return False, LEADERBOARDS_ONLY
    if view.another_session_active:
        return False, ANOTHER_SESSION_ACTIVE
    remaining = remaining_seconds(view.limit_minutes, view.used_seconds)
    if remaining <= 0:
        return False, LIMIT_REACHED
    if remaining <= view.min_remaining_s:
        return False, NOT_ENOUGH_TIME
    return True, OK


def may_continue(used_seconds: int, limit_minutes: int) -> bool:
    """Inside an already-running solo session (D-10).

    The allowance being used up does not end the session immediately: the
    session gets a grace window so a child is never cut off mid-answer.
    """
    return used_seconds < limit_minutes * 60
