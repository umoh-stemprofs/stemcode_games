"""Leaderboard period boundaries, pure (P5-T06, D-07, D-35).

Boundaries are **school-local**: "today" starts at midnight where the school is,
not in UTC. The one exception is ``all_time``, which starts when the school's
first eligible award happened and never ends.

``ends_at`` is exclusive. A window of one day is ``[midnight, next midnight)``,
so an award at 23:59:59 belongs to exactly one daily period and no border case
can land in two.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass
from datetime import tzinfo

PERIOD_TYPES: tuple[str, ...] = ("daily", "weekly", "monthly", "termly", "all_time")
# What the first release shows. ``monthly`` is the same generator behind a
# flag, so it is not a second code path (D-35). ``termly`` is still a valid
# period type — a school that already has term dates can read it — but it is no
# longer offered: the learners' third tab is the all-time board.
SHIPPED_PERIODS: tuple[str, ...] = ("daily", "weekly", "all_time")


@dataclass(frozen=True, slots=True)
class Window:
    starts_at: dt.datetime
    ends_at: dt.datetime | None


def _midnight(day: dt.date, tz: tzinfo) -> dt.datetime:
    return dt.datetime.combine(day, dt.time.min, tzinfo=tz)


def _next_month(day: dt.date) -> dt.date:
    year, month = (day.year + 1, 1) if day.month == 12 else (day.year, day.month + 1)
    return dt.date(year, month, 1)


def window(
    period_type: str,
    *,
    now_local: dt.datetime,
    tz: tzinfo,
    term: tuple[dt.date, dt.date] | None = None,
    first_award: dt.datetime | None = None,
) -> Window | None:
    """The current window for one period, or ``None`` when it cannot exist.

    ``termly`` without a term calendar returns ``None``: the plan says hide that
    board rather than invent a term (D-35).
    """
    today = now_local.date()

    if period_type == "daily":
        start = _midnight(today, tz)
        return Window(start, start + dt.timedelta(days=1))

    if period_type == "weekly":
        monday = today - dt.timedelta(days=today.weekday())
        start = _midnight(monday, tz)
        return Window(start, start + dt.timedelta(days=7))

    if period_type == "monthly":
        start = _midnight(today.replace(day=1), tz)
        end_day = _next_month(today)
        return Window(start, _midnight(end_day, tz))

    if period_type == "termly":
        if term is None:
            return None
        starts_on, ends_on = term
        return Window(_midnight(starts_on, tz), _midnight(ends_on + dt.timedelta(days=1), tz))

    if period_type == "all_time":
        # One row per school, created when the school's first award lands.
        if first_award is None:
            return None
        return Window(first_award, None)

    raise ValueError(f"unknown period type: {period_type}")
