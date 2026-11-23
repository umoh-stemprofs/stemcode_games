"""Access decisions and their administration (P3-T02, P3-T06, P3-T09).

Every question a game asks — may this learner start, how much time is left,
why is it refused — is answered here, and only here. Games in later phases
call ``require_access``; they never re-implement a rule.

The order of checks lives in ``domain/access.decide`` so it is unit-tested.
This module's job is gathering: which policies apply, which lockout is live,
how much has been used today, and whether another tab is open.
"""

from __future__ import annotations

import datetime as dt
import uuid
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import AppError, ConflictError, ForbiddenError, NotFoundError
from app.games import repository as repo
from app.games.domain import access as rules
from app.games.models import AccessPolicy, GameLockout
from app.identity.models import (
    Class,
    ClassMember,
    CoachAssignment,
    Role,
    School,
    User,
)
from app.identity.service import (
    Actor,
    class_members,
    require_coach_of_class,
    require_same_school_user,
    visible_class,
)

DEFAULT_LIMIT_MINUTES = 120
DEFAULT_CEILING_MINUTES = 240
DEFAULT_GRACE_MINUTES = 10
DEFAULT_LIVE_MINIMUM_SECONDS = 900
DEFAULT_LEADERBOARD_MIN_SESSIONS = 3

# One fixed sentence per reason (Appendix D). The UI may use its own wording,
# but it must never show the code itself.
REASON_SENTENCES = {
    rules.LIMIT_REACHED: "You have used all your time for today.",
    rules.NOT_ENOUGH_TIME: "You need more time left for a match.",
    rules.LOCKED_OUT: "Games are paused for you right now.",
    rules.GAMES_DISABLED: "Games are off right now.",
    rules.ANOTHER_SESSION_ACTIVE: "You have a game open somewhere else.",
    rules.LEADERBOARDS_ONLY: "You can look at the boards. Games are off right now.",
}


@dataclass(frozen=True, slots=True)
class AccessState:
    allowed: bool
    reason: str
    limit_minutes: int
    limit_source: str
    used_seconds: int
    remaining_seconds: int
    locked_until: dt.datetime | None
    lockout_reason: str | None
    local_date: dt.date
    resets_at: dt.datetime
    server_time: dt.datetime


async def school_timezone(session: AsyncSession, school_id: uuid.UUID) -> str:
    school = await session.get(School, school_id)
    if school is None:  # pragma: no cover - foreign keys make this unreachable
        raise NotFoundError("That school was not found.")
    return school.timezone


async def class_ids_for(session: AsyncSession, user_id: uuid.UUID) -> frozenset[uuid.UUID]:
    stmt = select(ClassMember.class_id).where(ClassMember.user_id == user_id)
    return frozenset((await session.execute(stmt)).scalars().all())


async def _setting_int(session: AsyncSession, key: str, default: int) -> int:
    value = await repo.get_platform_setting(session, key)
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


async def _setting_bool(session: AsyncSession, key: str, default: bool) -> bool:
    value = await repo.get_platform_setting(session, key)
    return default if value is None else bool(value)


async def resolve_limit(
    session: AsyncSession,
    *,
    user: User,
    class_ids: frozenset[uuid.UUID],
    at: dt.datetime,
) -> tuple[int, str]:
    """The limit that applies now, and which level set it (D-08)."""
    ceiling = await _setting_int(session, "daily_limit_ceiling_minutes", DEFAULT_CEILING_MINUTES)
    default = await _setting_int(session, "daily_limit_minutes", DEFAULT_LIMIT_MINUTES)

    rows = await repo.candidate_policies(
        session,
        user_id=user.id,
        school_id=user.school_id,
        class_ids=tuple(class_ids),
        at=at,
    )
    policy = rules.pick_policy(
        [
            rules.PolicyView(
                scope_type=row.scope_type,
                scope_id=row.scope_id,
                daily_limit_minutes=row.daily_limit_minutes,
                valid_from=row.valid_from,
                valid_until=row.valid_until,
            )
            for row in rows
        ],
        at=at,
        user_id=user.id,
        school_id=user.school_id,
        class_ids=class_ids,
    )
    if policy is None:
        # No policy at all: the platform default, which is itself clamped.
        return rules.clamp_limit(default, ceiling), "platform"
    return rules.clamp_limit(policy.daily_limit_minutes, ceiling), policy.scope_type


async def active_lockout(
    session: AsyncSession,
    *,
    user_id: uuid.UUID,
    class_ids: frozenset[uuid.UUID],
    at: dt.datetime,
) -> GameLockout | None:
    """A learner lockout beats a class one; otherwise the earliest expiry."""
    rows = await repo.lockouts_for(session, user_id=user_id, class_ids=tuple(class_ids), at=at)
    if not rows:
        return None
    return min(rows, key=lambda r: (r.scope_type != "student", r.expires_at))


async def access_for(
    session: AsyncSession,
    *,
    user: User,
    now: dt.datetime | None = None,
    min_remaining_s: int = 0,
    ignore_active_session: bool = False,
    current_session_id: uuid.UUID | None = None,
) -> AccessState:
    """Everything the hub header and every start button need (P3-T06)."""
    now = now or dt.datetime.now(dt.UTC)
    tz = await school_timezone(session, user.school_id)
    today = rules.local_date(now, tz)
    class_ids = await class_ids_for(session, user.id)

    limit_minutes, limit_source = await resolve_limit(
        session, user=user, class_ids=class_ids, at=now
    )
    used = await repo.used_seconds(session, user_id=user.id, local_date=today)
    lockout = await active_lockout(session, user_id=user.id, class_ids=class_ids, at=now)

    another = False
    if not ignore_active_session:
        open_session = await repo.active_session_for_user(session, user.id)
        # Resuming the session already open is not "another" session.
        another = open_session is not None and open_session.id != current_session_id

    games_enabled = await _setting_bool(session, "games_enabled", True)
    leaderboards_only = await _setting_bool(session, "leaderboards_only", False)

    view = rules.AccessView(
        limit_minutes=limit_minutes,
        limit_source=limit_source,
        used_seconds=used,
        games_enabled=games_enabled,
        leaderboards_only=leaderboards_only,
        locked_until=lockout.expires_at if lockout else None,
        another_session_active=another,
        min_remaining_s=min_remaining_s,
    )
    allowed, reason = rules.decide(view, now=now)

    return AccessState(
        allowed=allowed,
        reason=reason,
        limit_minutes=limit_minutes,
        limit_source=limit_source,
        used_seconds=used,
        remaining_seconds=rules.remaining_seconds(limit_minutes, used),
        locked_until=lockout.expires_at if lockout else None,
        lockout_reason=lockout.reason if lockout else None,
        local_date=today,
        resets_at=rules.next_local_midnight(now, tz),
        server_time=now,
    )


async def require_access(
    session: AsyncSession,
    *,
    user: User,
    now: dt.datetime | None = None,
    min_remaining_s: int = 0,
    current_session_id: uuid.UUID | None = None,
) -> AccessState:
    """Refuse with a stable reason code, or return the state and let play start."""
    state = await access_for(
        session,
        user=user,
        now=now,
        min_remaining_s=min_remaining_s,
        current_session_id=current_session_id,
    )
    if state.allowed:
        return state
    sentence = REASON_SENTENCES.get(state.reason, "You cannot play right now.")
    if state.reason == rules.ANOTHER_SESSION_ACTIVE:
        # A conflict, not a permission problem: finishing the other game fixes it.
        raise ConflictError(sentence, code=state.reason)
    raise AppError(sentence, code=state.reason, status_code=403)


async def grace_minutes(session: AsyncSession) -> int:
    return await _setting_int(session, "soft_limit_grace_minutes", DEFAULT_GRACE_MINUTES)


async def live_minimum_seconds(session: AsyncSession) -> int:
    return await _setting_int(session, "live_min_remaining_seconds", DEFAULT_LIVE_MINIMUM_SECONDS)


# ------------------------------------------------------------ administration
@dataclass(frozen=True, slots=True)
class PolicyChange:
    scope_type: str
    scope_id: uuid.UUID | None
    daily_limit_minutes: int
    reason: str
    valid_until: dt.datetime | None = None


async def _coach_covers_user(
    session: AsyncSession, *, coach_id: uuid.UUID, user_id: uuid.UUID
) -> bool:
    stmt = (
        select(ClassMember.user_id)
        .join(CoachAssignment, CoachAssignment.class_id == ClassMember.class_id)
        .where(CoachAssignment.coach_id == coach_id, ClassMember.user_id == user_id)
        .limit(1)
    )
    return (await session.execute(stmt)).first() is not None


async def _check_policy_scope(
    session: AsyncSession, *, actor: Actor, scope_type: str, scope_id: uuid.UUID | None
) -> None:
    """Who may set a limit where (P3-T09). Never trust the client's scope."""
    if scope_type == "platform":
        # With three roles there is nobody above a school (D-37), and no school
        # may set the number that applies to every other school. The default is
        # written on the server, so every role is refused here.
        if scope_id is not None:
            raise AppError("The default has no school.", code="bad_scope", status_code=400)
        raise ForbiddenError("This can only be changed on the server.")

    if scope_type == "school":
        if actor.role is not Role.school_admin:
            raise ForbiddenError("Only a school admin can change this.")
        if scope_id != actor.school_id:
            raise NotFoundError("That school was not found.")
        return

    if scope_type == "class":
        if scope_id is None:
            raise AppError("Choose a class.", code="bad_scope", status_code=400)
        await visible_class(session, actor=actor, class_id=scope_id)
        if actor.role is not Role.coach and not actor.is_admin:
            raise ForbiddenError("Only a coach can change this.")
        return

    if scope_type == "student":
        if scope_id is None:
            raise AppError("Choose a learner.", code="bad_scope", status_code=400)
        target = await require_same_school_user(session, actor=actor, user_id=scope_id)
        if actor.role is Role.coach and not await _coach_covers_user(
            session, coach_id=actor.id, user_id=target.id
        ):
            raise NotFoundError("That person was not found.")
        if actor.role not in (Role.coach, Role.school_admin):
            raise ForbiddenError("Only a coach can change this.")
        return

    raise AppError("Choose where the limit applies.", code="bad_scope", status_code=400)


async def set_limit(
    session: AsyncSession, *, actor: Actor, change: PolicyChange, now: dt.datetime | None = None
) -> AccessPolicy:
    """Add a policy. History is kept: the newest policy simply wins from now on."""
    now = now or dt.datetime.now(dt.UTC)
    await _check_policy_scope(
        session, actor=actor, scope_type=change.scope_type, scope_id=change.scope_id
    )

    ceiling = await _setting_int(session, "daily_limit_ceiling_minutes", DEFAULT_CEILING_MINUTES)
    if not 0 <= change.daily_limit_minutes <= ceiling:
        raise AppError(
            f"The most you can allow is {ceiling} minutes a day.",
            code="limit_above_ceiling",
            status_code=400,
        )
    if not change.reason.strip():
        raise AppError("Please say why.", code="reason_required", status_code=400)
    if change.valid_until is not None and change.valid_until <= now:
        raise AppError("That end time has passed.", code="bad_window", status_code=400)

    row = await repo.create_policy(
        session,
        scope_type=change.scope_type,
        scope_id=change.scope_id,
        daily_limit_minutes=change.daily_limit_minutes,
        valid_from=now,
        valid_until=change.valid_until,
        set_by=actor.id,
        reason=change.reason.strip(),
    )
    await repo.audit(
        session,
        actor_id=actor.id,
        action="access_policy.create",
        target_type="access_policy",
        target_id=str(row.id),
        details={
            "scope_type": change.scope_type,
            "scope_id": str(change.scope_id) if change.scope_id else None,
            "minutes": change.daily_limit_minutes,
        },
    )
    await session.commit()
    return row


async def _visible_scope_ids(session: AsyncSession, *, actor: Actor) -> set[uuid.UUID]:
    """Class ids this actor may administer, plus the ids of their members."""
    if actor.role is Role.school_admin:
        class_ids = set(
            (await session.execute(select(Class.id).where(Class.school_id == actor.school_id)))
            .scalars()
            .all()
        )
    else:
        class_ids = set(
            (
                await session.execute(
                    select(CoachAssignment.class_id).where(CoachAssignment.coach_id == actor.id)
                )
            )
            .scalars()
            .all()
        )

    member_ids: set[uuid.UUID] = set()
    if class_ids:
        rows = await session.execute(
            select(ClassMember.user_id).where(ClassMember.class_id.in_(class_ids))
        )
        member_ids = set(rows.scalars().all())
    return class_ids | member_ids | {actor.id}


async def list_policies(session: AsyncSession, *, actor: Actor) -> list[AccessPolicy]:
    """History, filtered to what this actor may see (P3-T10)."""
    rows = await repo.list_policies(session)
    visible = await _visible_scope_ids(session, actor=actor)
    out: list[AccessPolicy] = []
    for row in rows:
        if row.scope_type == "platform":
            # Everyone is subject to the default, so everyone may read it.
            out.append(row)
        elif row.scope_type == "school":
            if row.scope_id == actor.school_id:
                out.append(row)
        elif row.scope_id in visible:
            out.append(row)
    return out


async def lock_out(
    session: AsyncSession,
    *,
    actor: Actor,
    scope_type: str,
    scope_id: uuid.UUID,
    reason: str,
    expires_at: dt.datetime,
    now: dt.datetime | None = None,
) -> GameLockout:
    now = now or dt.datetime.now(dt.UTC)
    if scope_type not in ("class", "student"):
        raise AppError("Choose a class or a learner.", code="bad_scope", status_code=400)
    await _check_policy_scope(session, actor=actor, scope_type=scope_type, scope_id=scope_id)
    if not reason.strip():
        raise AppError("Please say why.", code="reason_required", status_code=400)
    if expires_at <= now:
        raise AppError("Choose a time in the future.", code="bad_window", status_code=400)

    row = await repo.create_lockout(
        session,
        scope_type=scope_type,
        scope_id=scope_id,
        reason=reason.strip(),
        starts_at=now,
        expires_at=expires_at,
        created_by=actor.id,
    )
    await repo.audit(
        session,
        actor_id=actor.id,
        action="lockout.create",
        target_type="lockout",
        target_id=str(row.id),
        details={"scope_type": scope_type, "scope_id": str(scope_id)},
    )
    await session.commit()
    return row


async def revoke_lockout(
    session: AsyncSession,
    *,
    actor: Actor,
    lockout_id: uuid.UUID,
    now: dt.datetime | None = None,
) -> GameLockout:
    now = now or dt.datetime.now(dt.UTC)
    row = await repo.get_lockout(session, lockout_id)
    if row is None:
        raise NotFoundError("That pause was not found.")
    await _check_policy_scope(
        session, actor=actor, scope_type=row.scope_type, scope_id=row.scope_id
    )
    if row.revoked_at is None:
        row.revoked_at = now
        await session.flush()
        await repo.audit(
            session,
            actor_id=actor.id,
            action="lockout.revoke",
            target_type="lockout",
            target_id=str(row.id),
            details={},
        )
        await session.commit()
    return row


async def list_lockouts(session: AsyncSession, *, actor: Actor) -> list[GameLockout]:
    rows = await repo.list_lockouts(session)
    visible = await _visible_scope_ids(session, actor=actor)
    return [r for r in rows if r.scope_id in visible]


@dataclass(frozen=True, slots=True)
class MemberAccess:
    """One row of the coach's table (P3-T10)."""

    user_id: uuid.UUID
    preferred_name: str
    avatar_key: str
    limit_minutes: int
    limit_source: str
    used_seconds: int
    remaining_seconds: int
    locked_until: dt.datetime | None
    lockout_reason: str | None


async def class_access_table(
    session: AsyncSession, *, actor: Actor, class_id: uuid.UUID, now: dt.datetime | None = None
) -> list[MemberAccess]:
    """Every learner in a class, with the time they actually have left.

    Resolved through the same ``access_for`` the learner's own screen uses, so a
    coach cannot be shown a different number than the child.
    """
    now = now or dt.datetime.now(dt.UTC)
    await require_coach_of_class(session, actor=actor, class_id=class_id)
    members = await class_members(session, actor=actor, class_id=class_id)

    rows: list[MemberAccess] = []
    for member in members:
        state = await access_for(session, user=member, now=now)
        rows.append(
            MemberAccess(
                user_id=member.id,
                preferred_name=member.preferred_name,
                avatar_key=member.avatar_key,
                limit_minutes=state.limit_minutes,
                limit_source=state.limit_source,
                used_seconds=state.used_seconds,
                remaining_seconds=state.remaining_seconds,
                locked_until=state.locked_until,
                lockout_reason=state.lockout_reason,
            )
        )
    return rows
