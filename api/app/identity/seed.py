"""Development seed data (P1-T08).

Two schools on purpose: the second one exists so isolation can be tested with
real rows instead of mocks. Ids are derived from the student code, so re-running
the seed is idempotent and tests can rely on stable identifiers.

Every account signs in with **a code and a PIN**, never an email (0003).
Codes are readable out loud: one letter for the school, then four digits.
"""

from __future__ import annotations

import datetime as dt
import uuid

from app.games.models import SchoolTerm
from app.identity.avatars import AVATAR_KEYS
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
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

# Development-only credentials, documented in README.md. Not secrets: they only
# exist in a seeded local/test database, and the CLI refuses to seed when
# APP_ENV is staging or prod.
SEED_PIN = "2468"  # noqa: S105 - dev fixture, not a real secret
NAMESPACE = uuid.UUID("6f0d1f0e-6d4f-4b1e-9d3a-1c2b3a4d5e6f")


def seed_id(code: str) -> uuid.UUID:
    return uuid.uuid5(NAMESPACE, code)


def _person(
    *,
    school: School,
    code: str,
    role: Role,
    preferred: str,
    real: str,
    avatar: str,
    dob: dt.date,
) -> User:
    return User(
        id=seed_id(code),
        school_id=school.id,
        role=role,
        status=UserStatus.active,
        preferred_name=preferred,
        real_name=real,
        avatar_key=avatar,
        date_of_birth=dob,
        student_code=code,
        pin_hash=hash_secret(SEED_PIN),
    )


async def _ensure_terms(session: AsyncSession, schools: list[School]) -> None:
    """Insert the sample terms if this school has none yet.

    Separate from the main body because it must also run for a database that
    was seeded before terms existed: re-running the seed should complete the
    config, not skip past it.
    """
    existing = (await session.execute(select(SchoolTerm.id).limit(1))).scalars().first()
    if existing is not None:
        return

    terms = {
        "school:alpha": [
            ("Term 1", dt.date(2026, 9, 7), dt.date(2026, 12, 11)),
            ("Term 2", dt.date(2027, 1, 11), dt.date(2027, 3, 26)),
        ],
        "school:beta": [
            ("Autumn", dt.date(2026, 9, 1), dt.date(2026, 12, 18)),
            ("Spring", dt.date(2027, 1, 6), dt.date(2027, 3, 31)),
        ],
    }
    for school in schools:
        key = "school:alpha" if school.name == "Alpha Academy" else "school:beta"
        for index, (name, starts, ends) in enumerate(terms[key], start=1):
            session.add(
                SchoolTerm(
                    id=seed_id(f"term:{key}:{index}"),
                    school_id=school.id,
                    name=name,
                    starts_on=starts,
                    ends_on=ends,
                )
            )
    await session.flush()


# Staff fixtures whose role changed when the enum went from seven values to
# three (D-37, 0009_three_roles). A database seeded before that migration keeps
# the old preferred names, so a coach is still called "Writer Tunde" and an
# admin is still called "Checker Ese". Re-running the seed repairs the label,
# never the password, and only for these known demo codes.
_STAFF_LABELS = {
    "A-9004": (Role.school_admin, "Mallam Okonkwo"),
    "A-9005": (Role.coach, "Coach Tunde"),
    "A-9006": (Role.school_admin, "Mallam Igho"),
}


async def _refresh_staff_labels(session: AsyncSession) -> int:
    changed = 0
    for code, (role, preferred) in _STAFF_LABELS.items():
        user = (
            (await session.execute(select(User).where(User.student_code == code))).scalars().first()
        )
        if user is None:
            continue
        if user.role is not role or user.preferred_name != preferred:
            user.role = role
            user.preferred_name = preferred
            changed += 1
    await session.flush()
    return changed


async def seed_identity(session: AsyncSession) -> dict[str, int]:
    """Create the demo schools and people. Safe to run repeatedly."""
    existing = (await session.execute(select(School).limit(1))).scalars().first()
    if existing is not None:
        schools = list((await session.execute(select(School))).scalars().all())
        await _ensure_terms(session, schools)
        await _refresh_staff_labels(session)
        await session.commit()
        return {"schools": 0, "users": 0, "classes": 0, "memberships": 0}

    alpha = School(
        id=seed_id("school:alpha"),
        name="Alpha Academy",
        timezone="Africa/Lagos",
        leaderboards_enabled=True,
    )
    beta = School(
        id=seed_id("school:beta"),
        name="Beta College",
        timezone="Europe/London",
        leaderboards_enabled=True,
    )
    session.add_all([alpha, beta])
    await session.flush()

    users: list[User] = [
        # School A staff. 9xxx are staff codes, so they never collide with a
        # learner's 1xxx code in the same school.
        _person(
            school=alpha,
            code="A-9001",
            role=Role.school_admin,
            preferred="Mrs Adeyemi",
            real="Folake Adeyemi",
            avatar="owl",
            dob=dt.date(1985, 4, 12),
        ),
        _person(
            school=alpha,
            code="A-9002",
            role=Role.coach,
            preferred="Coach Bello",
            real="Ibrahim Bello",
            avatar="lion",
            dob=dt.date(1990, 9, 3),
        ),
        _person(
            school=alpha,
            code="A-9003",
            role=Role.coach,
            preferred="Coach Nwosu",
            real="Chidi Nwosu",
            avatar="tiger",
            dob=dt.date(1992, 1, 27),
        ),
        # A second admin, so words one admin writes can still be checked by
        # another person when a school wants that. Not required (D-38): a word's
        # author may make it live, and the draft step is the safety.
        _person(
            school=alpha,
            code="A-9004",
            role=Role.school_admin,
            preferred="Mallam Okonkwo",
            real="Ada Okonkwo",
            avatar="seal",
            dob=dt.date(1988, 6, 8),
        ),
        # The word writer. A coach, because coaches are the people who know
        # what a class needs (D-37). Holds no class of their own.
        _person(
            school=alpha,
            code="A-9005",
            role=Role.coach,
            preferred="Coach Tunde",
            real="Tunde Salami",
            avatar="camel",
            dob=dt.date(1991, 11, 2),
        ),
        # School B staff: the isolation counterpart.
        _person(
            school=beta,
            code="B-9001",
            role=Role.school_admin,
            preferred="Mr Clarke",
            real="Peter Clarke",
            avatar="penguin",
            dob=dt.date(1980, 3, 30),
        ),
    ]

    classes = [
        Class(id=seed_id("class:alpha:5a"), school_id=alpha.id, name="Year 5A", grade=5),
        Class(id=seed_id("class:alpha:5b"), school_id=alpha.id, name="Year 5B", grade=5),
        Class(id=seed_id("class:alpha:6a"), school_id=alpha.id, name="Year 6A", grade=6),
    ]
    session.add_all(classes)

    # 30 learners in school A, ten per class: codes A-1001 .. A-1030.
    first_names = [
        "Amara",
        "Bayo",
        "Chika",
        "Dayo",
        "Efe",
        "Funmi",
        "Gideon",
        "Halima",
        "Ifeoma",
        "Jide",
        "Kemi",
        "Lami",
        "Musa",
        "Ngozi",
        "Obi",
        "Precious",
        "Qasim",
        "Ruth",
        "Sade",
        "Tayo",
        "Uche",
        "Vera",
        "Wale",
        "Xola",
        "Yemi",
        "Zainab",
        "Ade",
        "Bisi",
        "Chinedu",
        "Dupe",
    ]
    for index, name in enumerate(first_names, start=1):
        users.append(
            _person(
                school=alpha,
                code=f"A-{1000 + index}",
                role=Role.learner,
                preferred=name,
                real=f"{name} Okafor",
                avatar=AVATAR_KEYS[(index - 1) % len(AVATAR_KEYS)],
                dob=dt.date(2015 - (index % 4), 1 + (index % 12), 1 + (index % 27)),
            )
        )

    # A handful in school B, so "cannot read school B" has real targets.
    for index in range(1, 6):
        users.append(
            _person(
                school=beta,
                code=f"B-{1000 + index}",
                role=Role.learner,
                preferred=f"Beta {index}",
                real=f"Beta Learner {index}",
                avatar=AVATAR_KEYS[(index + 7) % len(AVATAR_KEYS)],
                dob=dt.date(2014, 5, 1 + index),
            )
        )

    session.add_all(users)
    await session.flush()

    # Coach assignments: coach1 owns 5A and 6A, coach2 owns 5B only.
    session.add_all(
        [
            CoachAssignment(coach_id=seed_id("A-9002"), class_id=classes[0].id),
            CoachAssignment(coach_id=seed_id("A-9002"), class_id=classes[2].id),
            CoachAssignment(coach_id=seed_id("A-9003"), class_id=classes[1].id),
        ]
    )

    memberships = 0
    for index in range(1, 31):
        klass = classes[(index - 1) // 10]
        session.add(ClassMember(class_id=klass.id, user_id=seed_id(f"A-{1000 + index}")))
        memberships += 1

    await _ensure_terms(session, [alpha, beta])

    await session.commit()
    return {
        "schools": 2,
        "users": len(users),
        "classes": len(classes),
        "memberships": memberships,
    }
