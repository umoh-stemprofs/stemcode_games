"""Identity business logic: login, rotation, and scope guards (P1-T02, P1-T03).

Every function here takes an ``actor`` or the caller's own session row. No
router decides who may see what; the guards below do, so a new endpoint cannot
forget a check it never had.

Scope rule for cross-school reads (Phase 1 DoD): a resource in another school
is reported as **not found**, not as forbidden. A 403 would confirm that the id
exists somewhere else, which is exactly what isolation is meant to hide.
"""

from __future__ import annotations

import datetime as dt
import uuid
from dataclasses import dataclass

from app.core.config import Settings
from app.core.errors import NotFoundError, UnauthorizedError
from app.identity.models import (
    AgeBand,
    AuthSession,
    Class,
    ClassMember,
    CoachAssignment,
    LearningXpEntry,
    Role,
    School,
    User,
    UserStatus,
)
from app.identity.security import (
    create_access_token,
    decode_access_token,
    hash_refresh_token,
    hash_secret,
    new_refresh_token,
    normalize_code,
    secret_needs_rehash,
    verify_secret,
)
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

# Roles that may see every class in their own school.
ADMIN_ROLES = (Role.school_admin,)


@dataclass(frozen=True, slots=True)
class Actor:
    """The authenticated caller, plus the context every service needs."""

    id: uuid.UUID
    role: Role
    school_id: uuid.UUID
    session_id: uuid.UUID
    preferred_name: str
    avatar_key: str
    school_timezone: str

    @property
    def is_admin(self) -> bool:
        return self.role in ADMIN_ROLES


@dataclass(frozen=True, slots=True)
class AuthTokens:
    access_token: str
    refresh_token: str
    user: User
    session_id: uuid.UUID


def _now() -> dt.datetime:
    return dt.datetime.now(dt.UTC)


def _as_aware(value: dt.datetime | None) -> dt.datetime | None:
    """Postgres hands back aware datetimes; be explicit anyway."""
    if value is None:
        return None
    return value if value.tzinfo else value.replace(tzinfo=dt.UTC)


async def find_user_by_code(session: AsyncSession, code: str) -> User | None:
    """Look a person up by their student code. Codes are stored uppercase."""
    needle = normalize_code(code)
    if not needle:
        return None
    stmt = select(User).where(User.student_code == needle)
    return (await session.execute(stmt)).scalars().first()


async def _issue_tokens(
    session: AsyncSession,
    user: User,
    settings: Settings,
    *,
    ip: str | None,
) -> AuthTokens:
    refresh_raw = new_refresh_token()
    row = AuthSession(
        user_id=user.id,
        refresh_token_hash=hash_refresh_token(refresh_raw),
        expires_at=_now() + dt.timedelta(seconds=settings.refresh_token_ttl_s),
        created_ip=ip,
    )
    session.add(row)
    await session.flush()

    access = create_access_token(
        user_id=user.id,
        session_id=row.id,
        role=user.role.value,
        school_id=user.school_id,
        settings=settings,
    )
    return AuthTokens(
        access_token=access,
        refresh_token=refresh_raw,
        user=user,
        session_id=row.id,
    )


async def authenticate(
    session: AsyncSession,
    *,
    code: str,
    pin: str,
    ip: str | None,
    settings: Settings,
) -> AuthTokens:
    """Check credentials and open a session.

    Every failure returns the same sentence on purpose: it must not reveal
    whether the code exists, is locked, or simply has the wrong PIN.
    """
    user = await find_user_by_code(session, code)
    if user is None:
        verify_secret(None, pin)
        raise UnauthorizedError("That code or PIN is not right.", code="invalid_credentials")

    now = _now()
    locked_until = _as_aware(user.locked_until)
    if user.status is not UserStatus.active or (locked_until and locked_until > now):
        verify_secret(None, pin)
        raise UnauthorizedError("That code or PIN is not right.", code="invalid_credentials")

    if not verify_secret(user.pin_hash, pin):
        user.failed_login_count += 1
        if user.failed_login_count >= settings.lockout_threshold:
            # Linear backoff: each extra failure past the threshold locks for
            # one more window, so a scripted attack slows itself down.
            over = user.failed_login_count - settings.lockout_threshold + 1
            user.locked_until = now + dt.timedelta(seconds=settings.lockout_seconds * over)
        await session.commit()
        raise UnauthorizedError("That code or PIN is not right.", code="invalid_credentials")

    user.failed_login_count = 0
    user.locked_until = None
    if user.pin_hash and secret_needs_rehash(user.pin_hash):
        user.pin_hash = hash_secret(pin)

    tokens = await _issue_tokens(session, user, settings, ip=ip)
    await session.commit()
    return tokens


async def rotate_refresh_token(
    session: AsyncSession,
    *,
    raw_refresh: str,
    settings: Settings,
    ip: str | None,
) -> AuthTokens:
    """Exchange a refresh token for a new pair, revoking the old row.

    A token that is already revoked is a theft signal: either the cookie was
    copied, or the user has two tabs racing. Both are handled by revoking the
    whole family and forcing a fresh sign-in.
    """
    digest = hash_refresh_token(raw_refresh)
    row = (
        (await session.execute(select(AuthSession).where(AuthSession.refresh_token_hash == digest)))
        .scalars()
        .first()
    )

    if row is None:
        raise UnauthorizedError("Please sign in again.")

    if row.revoked_at is not None:
        await revoke_user_sessions(session, row.user_id, reason="reuse_detected")
        await session.commit()
        raise UnauthorizedError("Please sign in again.")

    expires_at = _as_aware(row.expires_at)
    if expires_at is None or expires_at <= _now():
        raise UnauthorizedError("Please sign in again.")

    user = (await session.execute(select(User).where(User.id == row.user_id))).scalars().first()
    if user is None or user.status is not UserStatus.active:
        raise UnauthorizedError("Please sign in again.")

    row.revoked_at = _now()
    row.revoked_reason = "rotated"
    row.last_used_at = _now()

    tokens = await _issue_tokens(session, user, settings, ip=ip)
    await session.commit()
    return tokens


async def revoke_session_by_token(
    session: AsyncSession, *, raw_refresh: str, reason: str = "logout"
) -> None:
    digest = hash_refresh_token(raw_refresh)
    row = (
        (await session.execute(select(AuthSession).where(AuthSession.refresh_token_hash == digest)))
        .scalars()
        .first()
    )
    if row is None or row.revoked_at is not None:
        return
    row.revoked_at = _now()
    row.revoked_reason = reason
    await session.commit()


async def revoke_user_sessions(session: AsyncSession, user_id: uuid.UUID, *, reason: str) -> None:
    rows = (
        await session.execute(
            select(AuthSession).where(
                AuthSession.user_id == user_id, AuthSession.revoked_at.is_(None)
            )
        )
    ).scalars()
    now = _now()
    for row in rows:
        row.revoked_at = now
        row.revoked_reason = reason


async def actor_from_access_token(session: AsyncSession, token: str, settings: Settings) -> Actor:
    claims = decode_access_token(token, settings)
    stmt = (
        select(User, School)
        .join(School, School.id == User.school_id)
        .where(User.id == claims.user_id)
    )
    found = (await session.execute(stmt)).first()
    if found is None:
        raise UnauthorizedError("Please sign in again.")
    user, school = found

    if user.status is not UserStatus.active:
        raise UnauthorizedError("Please sign in again.")

    # The token is a claim about a session; make sure that session still exists
    # and was not revoked, so logout takes effect before the token expires.
    row = (
        (await session.execute(select(AuthSession).where(AuthSession.id == claims.session_id)))
        .scalars()
        .first()
    )
    if row is None or row.revoked_at is not None:
        raise UnauthorizedError("Please sign in again.")

    return Actor(
        id=user.id,
        role=user.role,
        school_id=user.school_id,
        session_id=row.id,
        preferred_name=user.preferred_name,
        avatar_key=user.avatar_key,
        school_timezone=school.timezone,
    )


# --------------------------------------------------------------------------
# Age bands (P1-T04)
# --------------------------------------------------------------------------


def age_on(date_of_birth: dt.date, on_date: dt.date) -> int:
    """Whole years, not a rough subtraction: birthdays matter on the day."""
    years = on_date.year - date_of_birth.year
    if (on_date.month, on_date.day) < (date_of_birth.month, date_of_birth.day):
        years -= 1
    return years


async def get_age_band(
    session: AsyncSession, *, date_of_birth: dt.date, on_date: dt.date
) -> AgeBand | None:
    age = age_on(date_of_birth, on_date)
    stmt = (
        select(AgeBand)
        .where(AgeBand.min_age <= age)
        .where(or_(AgeBand.max_age.is_(None), AgeBand.max_age >= age))
        .order_by(AgeBand.min_age.desc())
        .limit(1)
    )
    return (await session.execute(stmt)).scalars().first()


# --------------------------------------------------------------------------
# Scope guards (P1-T03)
# --------------------------------------------------------------------------


async def _coaches_class(session: AsyncSession, actor: Actor, class_id: uuid.UUID) -> bool:
    row = (
        (
            await session.execute(
                select(CoachAssignment).where(
                    CoachAssignment.coach_id == actor.id,
                    CoachAssignment.class_id == class_id,
                )
            )
        )
        .scalars()
        .first()
    )
    return row is not None


async def _is_member(session: AsyncSession, actor: Actor, class_id: uuid.UUID) -> bool:
    row = (
        (
            await session.execute(
                select(ClassMember).where(
                    ClassMember.user_id == actor.id, ClassMember.class_id == class_id
                )
            )
        )
        .scalars()
        .first()
    )
    return row is not None


async def visible_class(session: AsyncSession, *, actor: Actor, class_id: uuid.UUID) -> Class:
    """Return the class if this actor may see it, else pretend it does not exist."""
    klass = (await session.execute(select(Class).where(Class.id == class_id))).scalars().first()
    if klass is None or klass.school_id != actor.school_id:
        raise NotFoundError("That class was not found.")

    if actor.is_admin:
        return klass
    if actor.role is Role.coach:
        if await _coaches_class(session, actor, class_id):
            return klass
        raise NotFoundError("That class was not found.")
    if await _is_member(session, actor, class_id):
        return klass
    raise NotFoundError("That class was not found.")


async def require_coach_of_class(
    session: AsyncSession, *, actor: Actor, class_id: uuid.UUID
) -> Class:
    """Stricter than ``visible_class``: a learner is never enough."""
    if actor.is_admin:
        klass = await visible_class(session, actor=actor, class_id=class_id)
        return klass
    if actor.role is not Role.coach:
        raise NotFoundError("That class was not found.")
    klass = await visible_class(session, actor=actor, class_id=class_id)
    return klass


async def visible_classes(session: AsyncSession, *, actor: Actor) -> list[Class]:
    base = select(Class).where(Class.school_id == actor.school_id).order_by(Class.name)
    if actor.is_admin:
        return list((await session.execute(base)).scalars().all())
    if actor.role is Role.coach:
        stmt = base.join(CoachAssignment, CoachAssignment.class_id == Class.id).where(
            CoachAssignment.coach_id == actor.id
        )
        return list((await session.execute(stmt)).scalars().all())
    stmt = base.join(ClassMember, ClassMember.class_id == Class.id).where(
        ClassMember.user_id == actor.id
    )
    return list((await session.execute(stmt)).scalars().all())


async def require_same_school_user(
    session: AsyncSession, *, actor: Actor, user_id: uuid.UUID
) -> User:
    """A user in the actor's own school, or a 404."""
    user = (await session.execute(select(User).where(User.id == user_id))).scalars().first()
    if user is None or user.school_id != actor.school_id:
        raise NotFoundError("That person was not found.")
    return user


async def class_members(session: AsyncSession, *, actor: Actor, class_id: uuid.UUID) -> list[User]:
    """Roster visibility (Phase 1 DoD): coaches/admins see members, learners too.

    The projection is what differs, not the access: only ``PublicProfile`` ever
    leaves the building for a learner (P1-T05).
    """
    await visible_class(session, actor=actor, class_id=class_id)
    stmt = (
        select(User)
        .join(ClassMember, ClassMember.user_id == User.id)
        .where(ClassMember.class_id == class_id)
        .order_by(User.preferred_name)
    )
    return list((await session.execute(stmt)).scalars().all())


async def record_learning_xp(
    session: AsyncSession, *, user_id: uuid.UUID, amount: int, reason: str
) -> LearningXpEntry:
    """Stub used by tests and by the future host-platform adapter (P1-T09)."""
    entry = LearningXpEntry(user_id=user_id, amount=amount, reason=reason)
    session.add(entry)
    await session.commit()
    await session.refresh(entry)
    return entry
