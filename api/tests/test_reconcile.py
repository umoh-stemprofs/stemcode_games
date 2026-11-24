"""Phase 5 maintenance and the coach view (P5-T06, P5-T07, P5-T11, D-33).

What these tests protect:

- **The ledger is the record.** Reconcile recomputes the board from it; a clean
  board produces zero drift and zero writes, and a tampered row is repaired.
- **A flag filters, it does not delete.** A flagged session leaves the board at
  the next reconcile while every ledger row stays exactly where it was.
- **Periods roll.** An open period whose window ended is closed and today's is
  opened, which is what makes a daily board reset.
- **A coach sees their class, and only their class.**
"""

from __future__ import annotations

import datetime as dt
import uuid

from app.games.models import FairplayFlag, GameXpEntry, LeaderboardPeriod
from app.games.services import maintenance
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from tests.factories import build_world, login
from tests.test_leaderboards import NOW, _award, _entries


async def _daily(db: AsyncSession, school_id: uuid.UUID, timezone: str) -> LeaderboardPeriod:
    from app.games.services import leaderboards

    period = await leaderboards.ensure_period(
        db,
        school_id=school_id,
        period_type="daily",
        now=NOW,
        timezone=timezone,
    )
    assert period is not None
    return period


# ------------------------------------------------------------------ reconcile
async def test_a_correct_board_has_zero_drift(db_session: AsyncSession) -> None:
    world = await build_world(db_session)
    await _award(db_session, school_id=world.school_a.id, learner=world.learner_a, rounds=[15] * 10)
    period = await _daily(db_session, world.school_a.id, world.school_a.timezone)

    assert await maintenance.reconcile_period(db_session, period) == 0
    # Running it twice changes nothing, so the job is safe to repeat.
    assert await maintenance.reconcile_period(db_session, period) == 0


async def test_reconcile_repairs_a_drifted_row(db_session: AsyncSession) -> None:
    world = await build_world(db_session)
    for _ in range(2):
        await _award(
            db_session, school_id=world.school_a.id, learner=world.learner_a, rounds=[15] * 10
        )
    period = await _daily(db_session, world.school_a.id, world.school_a.timezone)

    # Derived data, so a corrupt total is repairable — unlike a ledger row.
    rows = await _entries(db_session, period.id)
    for row in rows:
        row.xp_total = 999
    await db_session.flush()

    assert await maintenance.reconcile_period(db_session, period) == len(rows)

    repaired = await _entries(db_session, period.id)
    assert all(row.xp_total == 30 for row in repaired)
    assert all(row.sessions_count == 2 for row in repaired)


async def test_a_flagged_session_leaves_the_board_and_stays_in_the_ledger(
    db_session: AsyncSession,
) -> None:
    world = await build_world(db_session)
    award = await _award(
        db_session, school_id=world.school_a.id, learner=world.learner_a, rounds=[15] * 10
    )
    assert award.awarded > 0
    period = await _daily(db_session, world.school_a.id, world.school_a.timezone)
    assert await _entries(db_session, period.id)

    session_id = (
        (
            await db_session.execute(
                select(GameXpEntry.session_id).where(GameXpEntry.user_id == world.learner_a.id)
            )
        )
        .scalars()
        .first()
    )
    assert session_id is not None

    db_session.add(
        FairplayFlag(
            user_id=world.learner_a.id,
            session_id=session_id,
            flag_type="too_fast",
            status="open",
        )
    )
    await db_session.flush()

    ledger_before = (
        await db_session.execute(select(func.count()).select_from(GameXpEntry))
    ).scalar_one()

    assert await maintenance.reconcile_period(db_session, period) > 0
    assert await _entries(db_session, period.id) == []

    ledger_after = (
        await db_session.execute(select(func.count()).select_from(GameXpEntry))
    ).scalar_one()
    assert ledger_after == ledger_before, "reconcile must never rewrite the ledger"

    # Clearing the flag puts the same session back on the board.
    flag = (
        (
            await db_session.execute(
                select(FairplayFlag).where(FairplayFlag.session_id == session_id)
            )
        )
        .scalars()
        .one()
    )
    flag.status = "cleared"
    await db_session.flush()
    assert await maintenance.reconcile_period(db_session, period) > 0
    assert all(row.xp_total == award.awarded for row in await _entries(db_session, period.id))


async def test_reconcile_closes_a_period_whose_window_ended(
    db_session: AsyncSession,
) -> None:
    world = await build_world(db_session)
    period = await _daily(db_session, world.school_a.id, world.school_a.timezone)

    report = await maintenance.reconcile(db_session, now=NOW + dt.timedelta(days=2))
    assert report.as_dict()["status"] == "ok"

    await db_session.refresh(period)
    assert period.status == "closed"


# --------------------------------------------------------------------- rolling
async def test_roll_periods_closes_the_old_day_and_opens_a_new_one(
    db_session: AsyncSession,
) -> None:
    world = await build_world(db_session)
    old = await _daily(db_session, world.school_a.id, world.school_a.timezone)

    tomorrow = NOW + dt.timedelta(days=1)
    result = await maintenance.roll_periods(db_session, now=tomorrow)
    assert result["status"] == "ok"
    assert result["periods_closed"] >= 1

    await db_session.refresh(old)
    assert old.status == "closed"

    fresh = (
        (
            await db_session.execute(
                select(LeaderboardPeriod).where(
                    LeaderboardPeriod.school_id == world.school_a.id,
                    LeaderboardPeriod.period_type == "daily",
                    LeaderboardPeriod.status == "open",
                )
            )
        )
        .scalars()
        .one()
    )
    assert fresh.starts_at > old.starts_at


# ----------------------------------------------------------------- coach view
async def test_a_coach_sees_their_class_with_a_per_game_breakdown(
    client, db_session: AsyncSession
) -> None:
    world = await build_world(db_session)
    await _award(db_session, school_id=world.school_a.id, learner=world.learner_a, rounds=[15] * 10)
    await login(client, world.coach_a)

    response = await client.get(f"/api/leaderboards/weekly/students?class_id={world.class_a.id}")
    assert response.status_code == 200, response.text
    body = response.json()

    assert [row["preferred_name"] for row in body["students"]] == ["Amara"]
    student = body["students"][0]
    assert student["xp_total"] > 0
    assert [game["game_id"] for game in student["games"]] == ["word_scramble"]
    # Masked identity: no real name anywhere in the payload (D-15).
    assert "Amara Okoro" not in response.text


async def test_a_learner_cannot_read_the_coach_view(client, db_session: AsyncSession) -> None:
    world = await build_world(db_session)
    await login(client, world.learner_a)

    response = await client.get(f"/api/leaderboards/daily/students?class_id={world.class_a.id}")
    assert response.status_code == 403


async def test_a_coach_gets_a_404_for_a_class_they_do_not_run(
    client, db_session: AsyncSession
) -> None:
    world = await build_world(db_session)
    await login(client, world.coach_b)

    response = await client.get(f"/api/leaderboards/daily/students?class_id={world.class_a.id}")
    assert response.status_code == 404


async def test_a_coach_reads_the_all_time_view_for_their_own_class(
    client, db_session: AsyncSession
) -> None:
    """All-time replaced the termly tab, so a coach reads it for their class."""
    world = await build_world(db_session)
    await login(client, world.coach_a)

    response = await client.get(
        f"/api/leaderboards/all_time/students?class_id={world.class_a.id}"
    )
    assert response.status_code == 200, response.text
    assert response.json()["period"] == "all_time"


async def test_the_breakdown_reads_per_game_rows_only(db_session: AsyncSession) -> None:
    """D-33: a breakdown must never mix the all-games row into a game total."""
    from app.games import repository as repo

    world = await build_world(db_session)
    award = await _award(
        db_session, school_id=world.school_a.id, learner=world.learner_a, rounds=[15] * 10
    )
    period = await _daily(db_session, world.school_a.id, world.school_a.timezone)

    rows = await repo.per_game_entries(
        db_session,
        period_id=period.id,
        class_ids=[world.class_a.id],
        age_band=None,
        user_ids=[world.learner_a.id],
    )
    assert [row.game_id for row in rows] == ["word_scramble"]
    assert int(rows[0].xp_total) == award.awarded
