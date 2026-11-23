"""Phase 5: the projection and the boards (P5-T06, P5-T07, P5-T09, D-33, D-35).

The promises under test:

- an eligible award lands in every open period, twice (game and all games);
- a board reads one row set, so nothing is counted twice;
- a learner below the D-14 minimum is hidden, and told so;
- all-time is the school admin's board, and everyone else gets a 404;
- a school with no term calendar hides its termly board instead of guessing;
- a school that turned leaderboards off gets a 404.
"""

from __future__ import annotations

import datetime as dt
import uuid

from app.games.domain import periods as period_rules
from app.games.models import GameResult, GameSession, LeaderboardEntry, LeaderboardPeriod
from app.games.services import leaderboards, xp
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from tests.factories import build_world, login

# Today at 09:00 UTC (10:00 in Lagos), not a frozen date. One path reads the
# real clock — a board asks "which period contains right now?" — so a fixed
# date rots the day after it is written: the awards land in yesterday's period
# and the board looks empty.
NOW = dt.datetime.now(dt.UTC).replace(hour=9, minute=0, second=0, microsecond=0)


async def _award(
    db: AsyncSession,
    *,
    school_id: uuid.UUID,
    learner,
    rounds: list[int],
    now: dt.datetime = NOW,
) -> xp.Award:
    row = GameSession(
        game_id="word_scramble",
        mode="solo",
        status="finished",
        school_id=school_id,
        created_by=learner.id,
        config={"rounds": []},
    )
    db.add(row)
    await db.flush()
    stored = GameResult(
        session_id=row.id,
        user_id=learner.id,
        outcome="completed",
        score=sum(rounds),
        details={"rounds": rounds},
        leaderboard_eligible=True,
    )
    db.add(stored)
    await db.flush()
    return await xp.award_for_result(db, result=stored, game_row=row, user=learner, now=now)


async def _entries(db: AsyncSession, period_id: uuid.UUID) -> list[LeaderboardEntry]:
    return list(
        (await db.execute(select(LeaderboardEntry).where(LeaderboardEntry.period_id == period_id)))
        .scalars()
        .all()
    )


# ------------------------------------------------------------ the projection
async def test_an_award_writes_two_rows_into_every_open_period(
    db_session: AsyncSession,
) -> None:
    world = await build_world(db_session)
    await _award(db_session, school_id=world.school_a.id, learner=world.learner_a, rounds=[15] * 10)

    periods = list(
        (
            await db_session.execute(
                select(LeaderboardPeriod).where(LeaderboardPeriod.school_id == world.school_a.id)
            )
        )
        .scalars()
        .all()
    )
    # No term calendar in this fixture, so daily, weekly and all-time exist.
    assert {row.period_type for row in periods} == {"daily", "weekly", "all_time"}

    for period in periods:
        rows = await _entries(db_session, period.id)
        assert len(rows) == 2, period.period_type
        assert sorted(row.game_id or "*" for row in rows) == ["*", "word_scramble"]
        assert all(row.xp_total == 15 for row in rows)
        assert all(row.sessions_count == 1 for row in rows)


async def test_a_second_award_adds_to_the_same_rows(db_session: AsyncSession) -> None:
    world = await build_world(db_session)
    for _ in range(2):
        await _award(
            db_session, school_id=world.school_a.id, learner=world.learner_a, rounds=[15] * 10
        )

    daily = await leaderboards.ensure_period(
        db_session,
        school_id=world.school_a.id,
        period_type="daily",
        now=NOW,
        timezone=world.school_a.timezone,
    )
    assert daily is not None
    rows = await _entries(db_session, daily.id)
    assert len(rows) == 2  # still two rows, not four
    assert all(row.xp_total == 30 for row in rows)
    assert all(row.sessions_count == 2 for row in rows)


async def test_all_time_never_resets(db_session: AsyncSession) -> None:
    world = await build_world(db_session)
    await _award(db_session, school_id=world.school_a.id, learner=world.learner_a, rounds=[15] * 10)
    # A week later the daily board is a new period; all-time is the same row.
    later = NOW + dt.timedelta(days=8)
    await _award(
        db_session,
        school_id=world.school_a.id,
        learner=world.learner_a,
        rounds=[15] * 10,
        now=later,
    )

    all_time = await leaderboards.ensure_period(
        db_session,
        school_id=world.school_a.id,
        period_type="all_time",
        now=later,
        timezone=world.school_a.timezone,
    )
    assert all_time is not None
    rows = await _entries(db_session, all_time.id)
    assert all(row.xp_total == 30 for row in rows)

    dailies = (
        await db_session.execute(
            select(func.count())
            .select_from(LeaderboardPeriod)
            .where(
                LeaderboardPeriod.school_id == world.school_a.id,
                LeaderboardPeriod.period_type == "daily",
            )
        )
    ).scalar_one()
    assert dailies == 2


# ------------------------------------------------------------------- reading
async def test_a_board_reads_one_row_set_and_never_double_counts(
    db_session: AsyncSession,
) -> None:
    world = await build_world(db_session)
    for _ in range(3):
        await _award(
            db_session, school_id=world.school_a.id, learner=world.learner_a, rounds=[15] * 10
        )

    from tests.test_xp import _actor

    board = await leaderboards.board(
        db_session,
        actor=_actor(world.learner_a, world.school_a),
        period_type="daily",
    )
    assert [(row.preferred_name, row.xp_total) for row in board.entries] == [("Amara", 45)]
    assert board.me is not None
    assert board.me.rank == 1

    per_game = await leaderboards.board(
        db_session,
        actor=_actor(world.learner_a, world.school_a),
        period_type="daily",
        game_id="word_scramble",
    )
    assert per_game.entries[0].xp_total == 45


async def test_a_learner_below_the_minimum_is_hidden_and_told(
    db_session: AsyncSession,
) -> None:
    world = await build_world(db_session)
    await _award(db_session, school_id=world.school_a.id, learner=world.learner_a, rounds=[15] * 10)

    from tests.test_xp import _actor

    board = await leaderboards.board(
        db_session, actor=_actor(world.learner_a, world.school_a), period_type="daily"
    )
    assert board.entries == []
    assert board.me is None
    assert board.me_eligible is False


async def test_the_board_is_masked_identity_only(db_session: AsyncSession) -> None:
    world = await build_world(db_session)
    for _ in range(3):
        await _award(
            db_session, school_id=world.school_a.id, learner=world.learner_a, rounds=[15] * 10
        )

    from tests.test_xp import _actor

    board = await leaderboards.board(
        db_session, actor=_actor(world.learner_a2, world.school_a), period_type="daily"
    )
    assert board.entries[0].preferred_name == "Amara"
    assert not hasattr(board.entries[0], "real_name")


async def test_a_school_with_leaderboards_off_has_no_boards(
    db_session: AsyncSession,
) -> None:
    world = await build_world(db_session)
    world.school_a.leaderboards_enabled = False
    await db_session.flush()

    from tests.test_xp import _actor

    try:
        await leaderboards.board(
            db_session, actor=_actor(world.learner_a, world.school_a), period_type="daily"
        )
    except Exception as error:  # noqa: BLE001 - the code is the assertion
        assert getattr(error, "code", None) == "not_found"
    else:  # pragma: no cover
        raise AssertionError("a disabled school must not have boards")


# ---------------------------------------------------------------------- API
async def test_me_xp_reports_today_and_the_cap(client, db_session: AsyncSession) -> None:
    world = await build_world(db_session)
    await login(client, world.learner_a)

    response = await client.get("/api/me/xp")
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["game_xp_today"] == 0
    assert body["daily_cap"] == 60
    assert body["profile_xp_total"] == body["learning_xp_total"] + body["game_xp_total"]


async def test_all_time_is_admin_only(client, db_session: AsyncSession) -> None:
    world = await build_world(db_session)

    await login(client, world.learner_a)
    learner = await client.get("/api/leaderboards/all_time")
    assert learner.status_code == 404

    await login(client, world.coach_a)
    coach = await client.get("/api/leaderboards/all_time")
    assert coach.status_code == 404

    await login(client, world.admin_a)
    admin = await client.get("/api/leaderboards/all_time")
    assert admin.status_code == 200, admin.text
    assert admin.json()["period"] == "all_time"


async def test_a_learner_may_read_daily_and_weekly(client, db_session: AsyncSession) -> None:
    world = await build_world(db_session)
    await login(client, world.learner_a)

    for period in ("daily", "weekly"):
        response = await client.get(f"/api/leaderboards/{period}")
        assert response.status_code == 200, (period, response.text)
        assert response.json()["period"] == period
        assert response.json()["me_eligible"] is False


async def test_termly_is_hidden_without_a_calendar_then_appears(
    client, db_session: AsyncSession
) -> None:
    from app.games.models import SchoolTerm

    world = await build_world(db_session)
    await login(client, world.learner_a)

    hidden = await client.get("/api/leaderboards/termly")
    assert hidden.status_code == 404, hidden.text

    db_session.add(
        SchoolTerm(
            school_id=world.school_a.id,
            name="Autumn",
            starts_on=dt.date(2026, 9, 1),
            ends_on=dt.date(2026, 12, 20),
        )
    )
    await db_session.flush()

    shown = await client.get("/api/leaderboards/termly")
    assert shown.status_code == 200, shown.text
    assert shown.json()["period"] == "termly"


async def test_a_month_is_hidden_unless_the_flag_is_on(client, db_session: AsyncSession) -> None:
    world = await build_world(db_session)
    await login(client, world.learner_a)

    response = await client.get("/api/leaderboards/monthly")
    assert response.status_code == 404


async def test_an_admin_can_add_a_term_and_a_bad_range_is_refused(
    client, db_session: AsyncSession
) -> None:
    world = await build_world(db_session)
    await login(client, world.admin_a)

    created = await client.post(
        "/api/school/terms",
        json={"name": "Spring", "starts_on": "2027-01-05", "ends_on": "2027-04-01"},
    )
    assert created.status_code == 201, created.text
    assert created.json()["name"] == "Spring"

    listed = await client.get("/api/school/terms")
    assert listed.status_code == 200
    assert any(row["name"] == "Spring" for row in listed.json())

    backwards = await client.post(
        "/api/school/terms",
        json={"name": "Nonsense", "starts_on": "2027-05-01", "ends_on": "2027-04-01"},
    )
    assert backwards.status_code == 400
    assert backwards.json()["error"]["code"] == "term_invalid"


async def test_a_coach_cannot_add_a_term(client, db_session: AsyncSession) -> None:
    world = await build_world(db_session)
    await login(client, world.coach_a)

    response = await client.post(
        "/api/school/terms",
        json={"name": "Spring", "starts_on": "2027-01-05", "ends_on": "2027-04-01"},
    )
    assert response.status_code == 403


# ------------------------------------------------------------------ windows
def test_the_weekly_window_starts_on_monday_local_time() -> None:
    from zoneinfo import ZoneInfo

    tz = ZoneInfo("Africa/Lagos")
    # Saturday 14 November 2026, 10:00 local.
    local = dt.datetime(2026, 11, 14, 10, 0, tzinfo=tz)
    window = period_rules.window("weekly", now_local=local, tz=tz)
    assert window is not None
    assert window.starts_at.astimezone(tz).date() == dt.date(2026, 11, 9)
    assert window.starts_at.astimezone(tz).strftime("%A") == "Monday"
    assert window.ends_at is not None
    assert (window.ends_at - window.starts_at) == dt.timedelta(days=7)


def test_the_daily_window_ends_at_the_next_midnight() -> None:
    from zoneinfo import ZoneInfo

    tz = ZoneInfo("Africa/Lagos")
    local = dt.datetime(2026, 11, 14, 23, 59, 30, tzinfo=tz)
    window = period_rules.window("daily", now_local=local, tz=tz)
    assert window is not None
    assert window.ends_at is not None
    assert window.ends_at.astimezone(tz).time() == dt.time(0, 0)


def test_termly_without_a_calendar_does_not_exist() -> None:
    from zoneinfo import ZoneInfo

    tz = ZoneInfo("Africa/Lagos")
    local = dt.datetime(2026, 11, 14, 10, 0, tzinfo=tz)
    assert period_rules.window("termly", now_local=local, tz=tz) is None
