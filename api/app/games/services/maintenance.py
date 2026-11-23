"""Keeping the boards honest: period roll and reconcile (P5-T06, P5-T07).

Two jobs, one idea: the ledger is the record, and the projection is a cache of it.

- **Roll.** Close the period that ended and open the one that started, for every
  school and every board it can have. Generated at a boundary, on first read
  (``services/leaderboards``) and here, so a quiet school still rolls over.
- **Reconcile.** Recompute every open period from the ledger and repair any
  drift. It filters exactly the way the award path filters (D-33), so a
  fair-play flag removes a session from the board **without** touching a single
  append-only row: the board changes, the history does not.

Reconcile is idempotent: run twice, the second run reports zero drift and writes
nothing, which is what the phase's DoD asks to see.
"""

from __future__ import annotations

import datetime as dt
import uuid
from dataclasses import dataclass, field

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.games import repository as repo
from app.games.domain import periods as period_rules
from app.games.models import LeaderboardEntry, LeaderboardPeriod
from app.games.services import leaderboards
from app.identity.models import School


@dataclass(slots=True)
class ReconcileReport:
    """What one reconcile pass found and fixed."""

    periods_checked: int = 0
    drift_rows: int = 0
    schools: set[uuid.UUID] = field(default_factory=set)

    def as_dict(self) -> dict[str, object]:
        return {
            "status": "ok",
            "periods_checked": self.periods_checked,
            "drift_rows": self.drift_rows,
            "drift": self.drift_rows,
            "schools": len(self.schools),
        }


def _now() -> dt.datetime:
    return dt.datetime.now(dt.UTC)


async def _monthly_enabled(session: AsyncSession) -> bool:
    value = await repo.get_platform_setting(session, "leaderboards.monthly_enabled")
    return bool(value)


async def roll_periods(
    session: AsyncSession, *, now: dt.datetime | None = None
) -> dict[str, object]:
    """Close ended periods and open the current one, for every school."""
    now = now or _now()
    monthly = await _monthly_enabled(session)
    wanted = list(period_rules.SHIPPED_PERIODS)
    if monthly:
        wanted.append("monthly")

    schools = list((await session.execute(select(School))).scalars().all())
    closed = 0
    opened = 0
    for school in schools:
        for period_type in wanted:
            before = await repo.open_period(session, school_id=school.id, period_type=period_type)
            after = await leaderboards.ensure_period(
                session,
                school_id=school.id,
                period_type=period_type,
                now=now,
                timezone=school.timezone,
            )
            if before is not None and after is not None and before.id != after.id:
                closed += 1
                opened += 1

    await session.commit()
    return {
        "status": "ok",
        "schools": len(schools),
        "periods_closed": closed,
        "periods_opened": opened,
    }


async def reconcile_period(session: AsyncSession, period: LeaderboardPeriod) -> int:
    """Rebuild one period's rows from the ledger. Returns the number of rows fixed."""
    flagged = await repo.flagged_session_ids(session, school_id=period.school_id)

    # key = (user, game-or-None, class, age band)
    expected: dict[tuple, tuple[int, int, dt.datetime]] = {}
    per_game = await repo.ledger_totals(
        session,
        school_id=period.school_id,
        starts_at=period.starts_at,
        ends_at=period.ends_at,
        flagged=flagged,
    )
    for row in per_game:
        key = (row.user_id, row.game_id, row.class_id_snapshot, row.age_band_snapshot)
        expected[key] = (int(row.xp_total), int(row.sessions_count), row.last_award_at)

    all_games = await repo.ledger_totals_all_games(
        session,
        school_id=period.school_id,
        starts_at=period.starts_at,
        ends_at=period.ends_at,
        flagged=flagged,
    )
    for row in all_games:
        key = (row.user_id, None, row.class_id_snapshot, row.age_band_snapshot)
        expected[key] = (int(row.xp_total), int(row.sessions_count), row.last_award_at)

    current = {
        (entry.user_id, entry.game_id, entry.class_id, entry.age_band): entry
        for entry in await repo.period_entries(session, period_id=period.id)
    }

    fixed = 0
    for key, (xp_total, sessions_count, last_award_at) in expected.items():
        entry = current.pop(key, None)
        if entry is None:
            session.add(
                LeaderboardEntry(
                    period_id=period.id,
                    school_id=period.school_id,
                    user_id=key[0],
                    game_id=key[1],
                    class_id=key[2],
                    age_band=key[3],
                    xp_total=xp_total,
                    sessions_count=sessions_count,
                    last_award_at=last_award_at,
                )
            )
            fixed += 1
        elif int(entry.xp_total) != xp_total or int(entry.sessions_count) != sessions_count:
            entry.xp_total = xp_total
            entry.sessions_count = sessions_count
            entry.last_award_at = last_award_at
            fixed += 1

    # Anything still here has no eligible award behind it. A deleted derived row
    # is not history: the ledger row that explains it is still there.
    for orphan in current.values():
        await session.delete(orphan)
        fixed += 1

    return fixed


async def reconcile(session: AsyncSession, *, now: dt.datetime | None = None) -> ReconcileReport:
    """Reconcile every open period, then close the ones that have ended."""
    now = now or _now()
    report = ReconcileReport()

    for period in await repo.all_open_periods(session):
        if period.ends_at is not None and period.ends_at <= now:
            # Its window is over: stop projecting into it. The rows stay for the
            # final standings; nothing is added after the whistle.
            period.status = "closed"
            continue
        report.periods_checked += 1
        report.schools.add(period.school_id)
        report.drift_rows += await reconcile_period(session, period)

    await session.commit()
    return report
