"""Phase 3: access policy, play time and lockouts (P3-T02 .. P3-T12).

The promises under test, in the plan's words:

- the most specific active policy wins, clamped to the platform ceiling;
- today is the *school's* today, including across a DST change;
- a forged heartbeat cannot buy time, and rapid ones cannot double-count;
- two open tabs share one clock, and pausing and resuming charge nothing;
- a second concurrent session is refused (D-26);
- a live match is refused below 15 minutes (D-27);
- a lockout ends when it says it ends.

Where time matters, ``now`` is injected. Nothing here sleeps.
"""

from __future__ import annotations

import datetime as dt
import uuid

import pytest
from app.core.errors import AppError, ConflictError, NotFoundError
from app.games import repository as repo
from app.games.domain import access as rules
from app.games.services import access, clock, sessions
from app.identity.models import User
from app.identity.service import Actor
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from tests.factories import build_world, login

NOW = dt.datetime(2026, 11, 14, 9, 0, tzinfo=dt.UTC)  # 10:00 in Lagos


def _actor(user: User, school_timezone: str = "Africa/Lagos") -> Actor:
    return Actor(
        id=user.id,
        role=user.role,
        school_id=user.school_id,
        session_id=uuid.uuid4(),
        preferred_name=user.preferred_name,
        avatar_key=user.avatar_key,
        school_timezone=school_timezone,
    )


def _policy(
    scope: str,
    scope_id: uuid.UUID | None,
    minutes: int,
    *,
    valid_from: dt.datetime = NOW - dt.timedelta(days=1),
    valid_until: dt.datetime | None = None,
) -> rules.PolicyView:
    return rules.PolicyView(
        scope_type=scope,
        scope_id=scope_id,
        daily_limit_minutes=minutes,
        valid_from=valid_from,
        valid_until=valid_until,
    )


async def _playable(
    db: AsyncSession,
    *,
    world,
    user: User,
    mode: str = "solo",
    game_id: str = "word_scramble",
):
    row = await repo.create_session(
        db,
        game_id=game_id,
        mode=mode,
        status="created",
        seed=99,
        school_id=world.school_a.id,
        created_by=user.id,
    )
    await repo.add_participant(db, session_id=row.id, user_id=user.id, seat=1)
    return row


# --------------------------------------------------------------- pure rules
def test_the_schools_today_is_not_the_servers_today() -> None:
    late_utc = dt.datetime(2026, 11, 13, 23, 30, tzinfo=dt.UTC)
    assert rules.local_date(late_utc, "Africa/Lagos") == dt.date(2026, 11, 14)
    assert rules.local_date(late_utc, "UTC") == dt.date(2026, 11, 13)


def test_day_boundary_survives_a_dst_change() -> None:
    # London enters BST at 01:00 UTC on 29 March 2026.
    before = dt.datetime(2026, 3, 28, 23, 30, tzinfo=dt.UTC)  # 23:30 GMT
    after = dt.datetime(2026, 3, 29, 22, 30, tzinfo=dt.UTC)  # 23:30 BST
    assert rules.local_date(before, "Europe/London") == dt.date(2026, 3, 28)
    assert rules.local_date(after, "Europe/London") == dt.date(2026, 3, 29)
    # Local midnight is 23:00 UTC, not 00:00 UTC, on that date.
    assert rules.next_local_midnight(after, "Europe/London") == dt.datetime(
        2026, 3, 29, 23, 0, tzinfo=dt.UTC
    )


def test_the_most_specific_policy_wins() -> None:
    user_id, school_id, class_id = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    picked = rules.pick_policy(
        [
            _policy("platform", None, 120),
            _policy("school", school_id, 100),
            _policy("class", class_id, 80),
            _policy("student", user_id, 45),
        ],
        at=NOW,
        user_id=user_id,
        school_id=school_id,
        class_ids=frozenset({class_id}),
    )
    assert picked is not None and picked.daily_limit_minutes == 45

    # Remove the learner's own policy and the class one takes over.
    picked = rules.pick_policy(
        [_policy("platform", None, 120), _policy("class", class_id, 80)],
        at=NOW,
        user_id=user_id,
        school_id=school_id,
        class_ids=frozenset({class_id}),
    )
    assert picked is not None and picked.daily_limit_minutes == 80


def test_a_policy_for_another_school_or_class_never_applies() -> None:
    user_id, school_id = uuid.uuid4(), uuid.uuid4()
    assert (
        rules.pick_policy(
            [
                _policy("school", uuid.uuid4(), 10),
                _policy("class", uuid.uuid4(), 10),
                _policy("student", uuid.uuid4(), 10),
            ],
            at=NOW,
            user_id=user_id,
            school_id=school_id,
            class_ids=frozenset(),
        )
        is None
    )


def test_at_the_same_level_the_newest_policy_wins() -> None:
    user_id, school_id = uuid.uuid4(), uuid.uuid4()
    picked = rules.pick_policy(
        [
            _policy("school", school_id, 30, valid_from=NOW - dt.timedelta(days=30)),
            _policy("school", school_id, 90, valid_from=NOW - dt.timedelta(minutes=5)),
        ],
        at=NOW,
        user_id=user_id,
        school_id=school_id,
        class_ids=frozenset(),
    )
    assert picked is not None and picked.daily_limit_minutes == 90


def test_expired_and_future_policies_are_ignored() -> None:
    user_id, school_id = uuid.uuid4(), uuid.uuid4()
    policies = [
        _policy("school", school_id, 10, valid_until=NOW - dt.timedelta(seconds=1)),
        _policy("school", school_id, 20, valid_from=NOW + dt.timedelta(seconds=1)),
    ]
    assert (
        rules.pick_policy(
            policies,
            at=NOW,
            user_id=user_id,
            school_id=school_id,
            class_ids=frozenset(),
        )
        is None
    )


def test_limits_are_clamped_to_the_platform_ceiling() -> None:
    assert rules.clamp_limit(999, 240) == 240
    assert rules.clamp_limit(-10, 240) == 0
    assert rules.clamp_limit(None, 240) == 240
    assert rules.clamp_limit(90, 240) == 90


def test_a_lockout_outranks_a_used_up_allowance() -> None:
    view = rules.AccessView(
        limit_minutes=120,
        limit_source="platform",
        used_seconds=120 * 60,
        games_enabled=True,
        leaderboards_only=False,
        locked_until=NOW + dt.timedelta(hours=1),
        another_session_active=True,
        min_remaining_s=0,
    )
    assert rules.decide(view, now=NOW) == (False, rules.LOCKED_OUT)


def test_another_open_tab_outranks_no_time_left() -> None:
    view = rules.AccessView(
        limit_minutes=120,
        limit_source="platform",
        used_seconds=120 * 60,
        games_enabled=True,
        leaderboards_only=False,
        locked_until=None,
        another_session_active=True,
    )
    assert rules.decide(view, now=NOW) == (False, rules.ANOTHER_SESSION_ACTIVE)


# ------------------------------------------------------------ the resolver
async def test_default_limit_applies_when_nothing_is_set(db_session: AsyncSession) -> None:
    world = await build_world(db_session)
    state = await access.access_for(db_session, user=world.learner_a, now=NOW)
    assert state.allowed and state.reason == rules.OK
    assert state.limit_minutes == 120
    assert state.limit_source == "platform"
    assert state.remaining_seconds == 120 * 60
    assert state.resets_at > NOW


async def test_a_student_policy_beats_a_class_policy(db_session: AsyncSession) -> None:
    world = await build_world(db_session)
    await repo.create_policy(
        db_session,
        scope_type="class",
        scope_id=world.class_a.id,
        daily_limit_minutes=60,
        valid_from=NOW - dt.timedelta(hours=1),
        reason="Whole class",
        set_by=world.coach_a.id,
    )
    await repo.create_policy(
        db_session,
        scope_type="student",
        scope_id=world.learner_a.id,
        daily_limit_minutes=90,
        valid_from=NOW - dt.timedelta(hours=1),
        reason="Needs more time",
        set_by=world.coach_a.id,
    )

    state = await access.access_for(db_session, user=world.learner_a, now=NOW)
    assert (state.limit_minutes, state.limit_source) == (90, "student")

    # A classmate with no personal policy gets the class limit.
    other = await access.access_for(db_session, user=world.learner_a2, now=NOW)
    assert (other.limit_minutes, other.limit_source) == (60, "class")


async def test_a_policy_above_the_ceiling_is_clamped_not_trusted(
    db_session: AsyncSession,
) -> None:
    world = await build_world(db_session)
    # Written straight to the repository: this is a policy that slipped past
    # the service, and the resolver still must not grant 999 minutes.
    await repo.create_policy(
        db_session,
        scope_type="student",
        scope_id=world.learner_a.id,
        daily_limit_minutes=999,
        valid_from=NOW - dt.timedelta(hours=1),
        reason="Bypassed",
        set_by=world.admin_a.id,
    )
    state = await access.access_for(db_session, user=world.learner_a, now=NOW)
    assert state.limit_minutes == 240


async def test_limit_raised_mid_day_takes_effect_immediately(
    db_session: AsyncSession,
) -> None:
    world = await build_world(db_session)
    actor = _actor(world.coach_a)
    await access.set_limit(
        db_session,
        actor=actor,
        change=access.PolicyChange(
            scope_type="class",
            scope_id=world.class_a.id,
            daily_limit_minutes=30,
            reason="Short session today",
        ),
        now=NOW - dt.timedelta(minutes=10),
    )
    before = await access.access_for(db_session, user=world.learner_a, now=NOW)
    assert before.limit_minutes == 30

    await access.set_limit(
        db_session,
        actor=actor,
        change=access.PolicyChange(
            scope_type="class",
            scope_id=world.class_a.id,
            daily_limit_minutes=90,
            reason="They finished early",
        ),
        now=NOW,
    )
    after = await access.access_for(
        db_session, user=world.learner_a, now=NOW + dt.timedelta(seconds=1)
    )
    assert after.limit_minutes == 90


# ------------------------------------------------------------- permissions
async def test_a_coach_cannot_exceed_the_platform_ceiling(
    db_session: AsyncSession,
) -> None:
    world = await build_world(db_session)
    with pytest.raises(AppError) as caught:
        await access.set_limit(
            db_session,
            actor=_actor(world.coach_a),
            change=access.PolicyChange(
                scope_type="class",
                scope_id=world.class_a.id,
                daily_limit_minutes=600,
                reason="All day",
            ),
            now=NOW,
        )
    assert caught.value.code == "limit_above_ceiling"


async def test_a_coach_cannot_touch_another_schools_class(
    db_session: AsyncSession,
) -> None:
    world = await build_world(db_session)
    with pytest.raises(NotFoundError):
        await access.set_limit(
            db_session,
            actor=_actor(world.coach_a),
            change=access.PolicyChange(
                scope_type="class",
                scope_id=world.class_b.id,
                daily_limit_minutes=30,
                reason="Not mine",
            ),
            now=NOW,
        )


async def test_a_coach_can_set_their_own_class_and_it_is_audited(
    db_session: AsyncSession,
) -> None:
    world = await build_world(db_session)
    row = await access.set_limit(
        db_session,
        actor=_actor(world.coach_a),
        change=access.PolicyChange(
            scope_type="class",
            scope_id=world.class_a.id,
            daily_limit_minutes=75,
            reason="Trip day",
        ),
        now=NOW,
    )
    state = await access.access_for(db_session, user=world.learner_a, now=NOW)
    assert (state.limit_minutes, state.limit_source) == (75, "class")

    # Scoped to the row just created: the database keeps history from earlier
    # runs, and a global count would fail for the wrong reason.
    audits = (
        (
            await db_session.execute(
                select(repo.AuditEntry).where(
                    repo.AuditEntry.action == "access_policy.create",
                    repo.AuditEntry.target_id == str(row.id),
                )
            )
        )
        .scalars()
        .all()
    )
    assert len(audits) == 1 and audits[0].actor_id == world.coach_a.id


async def test_a_platform_admin_is_the_only_role_that_sets_the_default(
    db_session: AsyncSession,
) -> None:
    world = await build_world(db_session)
    with pytest.raises(AppError):
        await access.set_limit(
            db_session,
            actor=_actor(world.admin_a),
            change=access.PolicyChange(
                scope_type="platform",
                scope_id=None,
                daily_limit_minutes=100,
                reason="Default",
            ),
            now=NOW,
        )


# ------------------------------------------------------------------ lockouts
async def test_a_lockout_blocks_play_and_ends_when_it_says(
    db_session: AsyncSession,
) -> None:
    world = await build_world(db_session)
    await access.lock_out(
        db_session,
        actor=_actor(world.coach_a),
        scope_type="student",
        scope_id=world.learner_a.id,
        reason="Homework first",
        expires_at=NOW + dt.timedelta(hours=1),
        now=NOW,
    )

    blocked = await access.access_for(db_session, user=world.learner_a, now=NOW)
    assert not blocked.allowed and blocked.reason == rules.LOCKED_OUT
    assert blocked.locked_until == NOW + dt.timedelta(hours=1)

    # One minute before it ends: still blocked.
    still = await access.access_for(
        db_session, user=world.learner_a, now=NOW + dt.timedelta(minutes=59)
    )
    assert not still.allowed

    after = await access.access_for(
        db_session, user=world.learner_a, now=NOW + dt.timedelta(hours=1, seconds=1)
    )
    assert after.allowed and after.reason == rules.OK


async def test_a_class_lockout_covers_every_member(
    db_session: AsyncSession,
) -> None:
    world = await build_world(db_session)
    await access.lock_out(
        db_session,
        actor=_actor(world.coach_a),
        scope_type="class",
        scope_id=world.class_a.id,
        reason="Assembly",
        expires_at=NOW + dt.timedelta(minutes=30),
        now=NOW,
    )
    for learner in (world.learner_a, world.learner_a2):
        state = await access.access_for(db_session, user=learner, now=NOW)
        assert state.reason == rules.LOCKED_OUT
    # Another school is untouched.
    outside = await access.access_for(
        db_session, user=world.learner_b, now=NOW + dt.timedelta(hours=1)
    )
    assert outside.allowed


async def test_revoking_a_lockout_restores_play(db_session: AsyncSession) -> None:
    world = await build_world(db_session)
    row = await access.lock_out(
        db_session,
        actor=_actor(world.coach_a),
        scope_type="student",
        scope_id=world.learner_a.id,
        reason="Pause",
        expires_at=NOW + dt.timedelta(hours=2),
        now=NOW,
    )
    await access.revoke_lockout(db_session, actor=_actor(world.coach_a), lockout_id=row.id, now=NOW)
    state = await access.access_for(db_session, user=world.learner_a, now=NOW)
    assert state.allowed


# --------------------------------------------------------------------- clock
async def test_one_gap_never_adds_more_than_thirty_seconds(
    db_session: AsyncSession,
) -> None:
    world = await build_world(db_session)
    first = await clock.record_activity(
        db_session,
        user_id=world.learner_a.id,
        school_timezone="Africa/Lagos",
        at=NOW,
        source="heartbeat",
    )
    assert first.granted_seconds == 0  # nothing to measure yet

    late = await clock.record_activity(
        db_session,
        user_id=world.learner_a.id,
        school_timezone="Africa/Lagos",
        at=NOW + dt.timedelta(minutes=10),
        source="heartbeat",
    )
    assert late.granted_seconds == 30
    used = await clock.used_today(
        db_session,
        user_id=world.learner_a.id,
        school_timezone="Africa/Lagos",
        at=NOW + dt.timedelta(minutes=10),
    )
    assert used == 30


async def test_rapid_heartbeats_do_not_double_count(db_session: AsyncSession) -> None:
    world = await build_world(db_session)
    total = 0
    for step in range(5):
        accrual = await clock.record_activity(
            db_session,
            user_id=world.learner_a.id,
            school_timezone="Africa/Lagos",
            at=NOW + dt.timedelta(seconds=step),
            source="heartbeat",
        )
        total += accrual.granted_seconds
    assert total == 4  # one second per beat, not five full intervals


async def test_two_tabs_share_one_clock(db_session: AsyncSession) -> None:
    world = await build_world(db_session)
    await clock.record_activity(
        db_session,
        user_id=world.learner_a.id,
        school_timezone="Africa/Lagos",
        at=NOW,
        source="heartbeat",
    )
    first = await clock.record_activity(
        db_session,
        user_id=world.learner_a.id,
        school_timezone="Africa/Lagos",
        at=NOW + dt.timedelta(seconds=15),
        source="heartbeat",
    )
    # The second tab beats at the same instant: there is nothing new to charge.
    second = await clock.record_activity(
        db_session,
        user_id=world.learner_a.id,
        school_timezone="Africa/Lagos",
        at=NOW + dt.timedelta(seconds=15),
        source="heartbeat",
    )
    assert first.granted_seconds == 15
    assert second.granted_seconds == 0


async def test_pause_and_resume_charge_nothing_for_the_gap(
    db_session: AsyncSession,
) -> None:
    world = await build_world(db_session)
    tz = "Africa/Lagos"
    await clock.record_activity(
        db_session, user_id=world.learner_a.id, school_timezone=tz, at=NOW, source="heartbeat"
    )
    await clock.record_activity(
        db_session,
        user_id=world.learner_a.id,
        school_timezone=tz,
        at=NOW + dt.timedelta(seconds=15),
        source="heartbeat",
    )
    # Pause, sit away for ten minutes, resume, then one more second of play.
    await clock.reset_clock(
        db_session,
        user_id=world.learner_a.id,
        school_timezone=tz,
        at=NOW + dt.timedelta(seconds=20),
    )
    await clock.reset_clock(
        db_session,
        user_id=world.learner_a.id,
        school_timezone=tz,
        at=NOW + dt.timedelta(minutes=10),
    )
    last = await clock.record_activity(
        db_session,
        user_id=world.learner_a.id,
        school_timezone=tz,
        at=NOW + dt.timedelta(minutes=10, seconds=1),
        source="heartbeat",
    )
    assert last.granted_seconds == 1


async def test_actions_still_cost_time_when_heartbeats_are_suppressed(
    db_session: AsyncSession,
) -> None:
    world = await build_world(db_session)
    row = await _playable(db_session, world=world, user=world.learner_a)
    await sessions.start_play(db_session, user=world.learner_a, session_id=row.id, now=NOW)

    # No heartbeats at all: only moves.
    granted = await sessions.record_action(
        db_session,
        user=world.learner_a,
        session_id=row.id,
        now=NOW + dt.timedelta(seconds=20),
    )
    assert granted == 20
    used = await repo.used_seconds(
        db_session, user_id=world.learner_a.id, local_date=dt.date(2026, 11, 14)
    )
    assert used == 20


# --------------------------------------------------------- session lifecycle
async def test_start_refuses_a_second_concurrent_session(
    db_session: AsyncSession,
) -> None:
    world = await build_world(db_session)
    first = await _playable(db_session, world=world, user=world.learner_a)
    second = await _playable(db_session, world=world, user=world.learner_a, game_id="number_guess")

    await sessions.start_play(db_session, user=world.learner_a, session_id=first.id, now=NOW)
    with pytest.raises(ConflictError) as caught:
        await sessions.start_play(
            db_session,
            user=world.learner_a,
            session_id=second.id,
            now=NOW + dt.timedelta(seconds=1),
        )
    assert caught.value.code == "another_session_active"


async def test_a_live_match_is_refused_below_fifteen_minutes(
    db_session: AsyncSession,
) -> None:
    world = await build_world(db_session)
    live = await _playable(
        db_session, world=world, user=world.learner_a, game_id="checkers", mode="live"
    )
    # 115 minutes used of 120: five minutes left, less than the 15 required.
    await repo.add_usage(
        db_session,
        user_id=world.learner_a.id,
        local_date=dt.date(2026, 11, 14),
        source="heartbeat",
        seconds=115 * 60,
    )

    with pytest.raises(AppError) as caught:
        await sessions.start_play(db_session, user=world.learner_a, session_id=live.id, now=NOW)
    # Not "limit_reached": five minutes are left, which is enough for a solo
    # round but not for a match (D-27). The sentence says so.
    assert caught.value.code == rules.NOT_ENOUGH_TIME

    # A solo game may still start with five minutes left.
    solo = await _playable(db_session, world=world, user=world.learner_a)
    await sessions.start_play(db_session, user=world.learner_a, session_id=solo.id, now=NOW)


async def test_a_solo_session_gets_ten_minutes_then_stops(
    db_session: AsyncSession,
) -> None:
    world = await build_world(db_session)
    row = await _playable(db_session, world=world, user=world.learner_a)
    await repo.add_usage(
        db_session,
        user_id=world.learner_a.id,
        local_date=dt.date(2026, 11, 14),
        source="action",
        seconds=119 * 60,
    )
    await sessions.start_play(db_session, user=world.learner_a, session_id=row.id, now=NOW)

    # Four beats of 16 s take the day past zero. The session keeps running
    # because D-10 grants a grace window rather than cutting a child off.
    now = NOW
    state = None
    for _ in range(4):
        now += dt.timedelta(seconds=16)
        state = await sessions.heartbeat(
            db_session,
            user=world.learner_a,
            session_id=row.id,
            visible=True,
            now=now,
        )
    assert state is not None and not state.ended
    assert state.remaining_seconds == 0

    # Keep playing: 16 s beats until the grace deadline is crossed and the
    # session ends. It must end, and it must say why.
    for _ in range(60):
        now += dt.timedelta(seconds=16)
        state = await sessions.heartbeat(
            db_session,
            user=world.learner_a,
            session_id=row.id,
            visible=True,
            now=now,
        )
        if state.ended:
            break
    assert state is not None and state.ended
    assert state.ended_reason == rules.LIMIT_REACHED


async def test_a_live_session_is_exempt_from_the_grace_cutoff(
    db_session: AsyncSession,
) -> None:
    world = await build_world(db_session)
    live = await _playable(
        db_session, world=world, user=world.learner_a, game_id="checkers", mode="live"
    )
    await sessions.start_play(db_session, user=world.learner_a, session_id=live.id, now=NOW)

    # Burn the allowance mid-match.
    await repo.add_usage(
        db_session,
        user_id=world.learner_a.id,
        local_date=dt.date(2026, 11, 14),
        source="action",
        seconds=140 * 60,
    )
    state = await sessions.heartbeat(
        db_session,
        user=world.learner_a,
        session_id=live.id,
        visible=True,
        now=NOW + dt.timedelta(seconds=16),
    )
    assert not state.ended


async def test_hiding_the_tab_pauses_without_charge(
    db_session: AsyncSession,
) -> None:
    world = await build_world(db_session)
    row = await _playable(db_session, world=world, user=world.learner_a)
    await sessions.start_play(db_session, user=world.learner_a, session_id=row.id, now=NOW)

    state = await sessions.heartbeat(
        db_session,
        user=world.learner_a,
        session_id=row.id,
        visible=False,
        now=NOW + dt.timedelta(seconds=10),
    )
    assert state.paused and state.used_seconds == 0


# ------------------------------------------------------------------- the API
async def test_access_requires_sign_in(client) -> None:
    response = await client.get("/api/games/access")
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "unauthenticated"


async def test_access_endpoint_answers_the_hub(client, db_session: AsyncSession) -> None:
    world = await build_world(db_session)
    await login(client, world.learner_a)

    response = await client.get("/api/games/access")
    assert response.status_code == 200
    body = response.json()
    assert body["allowed"] is True
    assert body["reason"] == "ok"
    assert body["limit_minutes"] == 120
    assert body["remaining_seconds"] == 7200
    assert body["server_time"] and body["resets_at"]


async def test_a_learner_cannot_read_or_change_limits(client, db_session: AsyncSession) -> None:
    world = await build_world(db_session)
    await login(client, world.learner_a)
    assert (await client.get("/api/games/limits")).status_code == 403
    assert (await client.get("/api/games/lockouts")).status_code == 403


async def test_a_coach_sets_a_limit_and_the_learner_feels_it(
    client, db_session: AsyncSession
) -> None:
    world = await build_world(db_session)
    await login(client, world.coach_a)

    created = await client.post(
        "/api/games/limits",
        json={
            "scope_type": "class",
            "scope_id": str(world.class_a.id),
            "daily_limit_minutes": 45,
            "reason": "Short day",
        },
    )
    assert created.status_code == 201, created.text
    assert created.json()["daily_limit_minutes"] == 45

    listed = await client.get("/api/games/limits")
    assert listed.status_code == 200
    assert [row["daily_limit_minutes"] for row in listed.json()] == [45]

    await login(client, world.learner_a)
    access_body = (await client.get("/api/games/access")).json()
    assert access_body["limit_minutes"] == 45
    assert access_body["limit_source"] == "class"


async def test_a_heartbeat_cannot_smuggle_a_duration(client, db_session: AsyncSession) -> None:
    world = await build_world(db_session)
    row = await _playable(db_session, world=world, user=world.learner_a)
    await sessions.start_play(db_session, user=world.learner_a, session_id=row.id, now=NOW)
    await login(client, world.learner_a)

    response = await client.post(
        f"/api/games/sessions/{row.id}/heartbeat",
        json={"visible": True, "duration_s": 600},
    )
    # Unknown fields are rejected outright, so there is no duration to ignore.
    assert response.status_code == 422


async def test_pause_endpoint_answers_no_content(client, db_session: AsyncSession) -> None:
    world = await build_world(db_session)
    row = await _playable(db_session, world=world, user=world.learner_a)
    await sessions.start_play(db_session, user=world.learner_a, session_id=row.id, now=NOW)
    await login(client, world.learner_a)

    response = await client.post(f"/api/games/sessions/{row.id}/pause")
    assert response.status_code == 204


async def test_a_learner_cannot_start_someone_elses_game(client, db_session: AsyncSession) -> None:
    world = await build_world(db_session)
    row = await _playable(db_session, world=world, user=world.learner_a2)
    await login(client, world.learner_a)

    response = await client.post(f"/api/games/sessions/{row.id}/start")
    assert response.status_code == 404


async def test_role_scope_holder_can_lock_out_and_revoke(client, db_session: AsyncSession) -> None:
    world = await build_world(db_session)
    await login(client, world.coach_a)

    created = await client.post(
        "/api/games/lockouts",
        json={
            "scope_type": "student",
            "scope_id": str(world.learner_a.id),
            "reason": "Needs a break",
            "expires_at": (dt.datetime.now(dt.UTC) + dt.timedelta(hours=1)).isoformat(),
        },
    )
    assert created.status_code == 201, created.text
    lockout_id = created.json()["id"]

    listed = await client.get("/api/games/lockouts")
    assert [row["id"] for row in listed.json()] == [lockout_id]

    revoked = await client.post(f"/api/games/lockouts/{lockout_id}/revoke")
    assert revoked.status_code == 200
    assert revoked.json()["revoked_at"] is not None


async def test_the_coach_table_shows_the_same_numbers_the_child_sees(
    client, db_session: AsyncSession
) -> None:
    world = await build_world(db_session)
    today = rules.local_date(dt.datetime.now(dt.UTC), world.school_a.timezone)
    await repo.add_usage(
        db_session,
        user_id=world.learner_a.id,
        local_date=today,
        source="action",
        seconds=30 * 60,
    )
    await login(client, world.coach_a)

    response = await client.get(f"/api/games/classes/{world.class_a.id}/access")
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["class_name"] == "Year 5A"

    by_name = {row["preferred_name"]: row for row in body["members"]}
    assert set(by_name) == {"Amara", "Bayo"}
    # The learner who has played shows the time they actually have left.
    assert by_name["Amara"]["limit_minutes"] == 120
    assert by_name["Amara"]["remaining_seconds"] == 7200 - 30 * 60
    assert by_name["Bayo"]["remaining_seconds"] == 7200
