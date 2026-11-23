"""Small factories for identity tests.

Deliberately explicit: every test shows which school and role it is building,
so an isolation test cannot pass by accident because two fixtures happened to
share a school.
"""

from __future__ import annotations

import datetime as dt
import uuid
from dataclasses import dataclass

import httpx
from app.identity.models import (
    Class,
    ClassMember,
    CoachAssignment,
    Role,
    School,
    User,
    UserStatus,
)
from app.identity.security import hash_secret
from sqlalchemy.ext.asyncio import AsyncSession

PIN = "2468"


@dataclass
class World:
    """The two-school fixture most isolation tests start from."""

    school_a: School
    school_b: School
    admin_a: User
    coach_a: User
    coach_b: User
    learner_a: User
    learner_a2: User
    learner_b: User
    class_a: Class
    class_b: Class
    class_unassigned: Class


async def make_school(session: AsyncSession, name: str, tz: str = "Africa/Lagos") -> School:
    school = School(id=uuid.uuid4(), name=name, timezone=tz, leaderboards_enabled=True)
    session.add(school)
    await session.flush()
    return school


async def make_user(
    session: AsyncSession,
    *,
    school: School,
    role: Role,
    code: str | None = None,
    preferred: str = "Pupil",
    real: str = "Real Person",
    avatar: str = "fox",
    pin: str = PIN,
    date_of_birth: dt.date | None = None,
    status: UserStatus = UserStatus.active,
) -> User:
    handle = code or f"T-{uuid.uuid4().hex[:8].upper()}"
    user = User(
        id=uuid.uuid4(),
        school_id=school.id,
        role=role,
        status=status,
        preferred_name=preferred,
        real_name=real,
        avatar_key=avatar,
        date_of_birth=date_of_birth or dt.date(2014, 6, 1),
        student_code=handle,
        pin_hash=hash_secret(pin) if pin else None,
    )
    session.add(user)
    await session.flush()
    return user


async def make_class(
    session: AsyncSession, *, school: School, name: str = "Class", grade: int = 5
) -> Class:
    klass = Class(id=uuid.uuid4(), school_id=school.id, name=name, grade=grade)
    session.add(klass)
    await session.flush()
    return klass


async def add_member(session: AsyncSession, *, klass: Class, user: User) -> None:
    session.add(ClassMember(class_id=klass.id, user_id=user.id))
    await session.flush()


async def assign_coach(session: AsyncSession, *, klass: Class, coach: User) -> None:
    session.add(CoachAssignment(class_id=klass.id, coach_id=coach.id))
    await session.flush()


async def build_world(session: AsyncSession) -> World:
    """Two schools, a coach in each, and a class the first coach does not own."""
    school_a = await make_school(session, "School A")
    school_b = await make_school(session, "School B", tz="Europe/London")

    admin_a = await make_user(
        session,
        school=school_a,
        role=Role.school_admin,
        code="ADMIN-A",
        preferred="Admin A",
        real="Admin Realname",
    )
    coach_a = await make_user(
        session,
        school=school_a,
        role=Role.coach,
        code="COACH-A",
        preferred="Coach A",
        real="Coach Realname",
    )
    coach_b = await make_user(
        session,
        school=school_b,
        role=Role.coach,
        code="COACH-B",
        preferred="Coach B",
        real="Other Coach",
    )
    learner_a = await make_user(
        session,
        school=school_a,
        role=Role.learner,
        code="LEARNER-A",
        preferred="Amara",
        real="Amara Okoro",
        avatar="owl",
    )
    learner_a2 = await make_user(
        session,
        school=school_a,
        role=Role.learner,
        code="LEARNER-A2",
        preferred="Bayo",
        real="Bayo Ade",
        avatar="panda",
    )
    learner_b = await make_user(
        session,
        school=school_b,
        role=Role.learner,
        code="LEARNER-B",
        preferred="Beta Learner",
        real="Beta Realname",
        avatar="tiger",
    )

    class_a = await make_class(session, school=school_a, name="Year 5A", grade=5)
    class_b = await make_class(session, school=school_b, name="Year 5B", grade=5)
    class_unassigned = await make_class(session, school=school_a, name="Year 6A", grade=6)

    await add_member(session, klass=class_a, user=learner_a)
    await add_member(session, klass=class_a, user=learner_a2)
    await add_member(session, klass=class_b, user=learner_b)
    await add_member(session, klass=class_unassigned, user=learner_a2)

    await assign_coach(session, klass=class_a, coach=coach_a)
    await assign_coach(session, klass=class_b, coach=coach_b)

    return World(
        school_a=school_a,
        school_b=school_b,
        admin_a=admin_a,
        coach_a=coach_a,
        coach_b=coach_b,
        learner_a=learner_a,
        learner_a2=learner_a2,
        learner_b=learner_b,
        class_a=class_a,
        class_b=class_b,
        class_unassigned=class_unassigned,
    )


async def login(client: httpx.AsyncClient, user: User, pin: str = PIN) -> httpx.Response:
    return await client.post(
        "/api/auth/login",
        json={"code": user.student_code, "pin": pin},
    )
