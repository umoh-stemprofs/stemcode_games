"""Identity and school-context ORM models (P1-T01).

This is the minimum host-platform slice the games need (D-01): schools, users,
classes, coach assignments, auth sessions, age bands, and the Learning XP stub.
If the real platform already has these, this package becomes its adapter and
the tables are dropped — the interfaces do not change.

Every table here is created by migration ``0002_identity``. The models mirror
that migration; they never create anything themselves.
"""

from __future__ import annotations

import datetime as dt
import uuid
from enum import StrEnum

from app.core.db import Base
from sqlalchemy import (
    Boolean,
    Date,
    DateTime,
    Enum,
    ForeignKey,
    Index,
    Integer,
    SmallInteger,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship


class Role(StrEnum):
    """The three doors (D-37, 0008_three_roles).

    Values match the Postgres enum ``identity_role``. There are exactly three:

    * ``learner`` plays games;
    * ``coach`` runs a class and writes words;
    * ``school_admin`` runs a school and is the only one who can publish.

    A coach publishes their own words too (D-38): the draft step, not a second
    person, is what stands between a typed word and a child seeing it.
    There is no platform role: making a school is a command on the server
    (``python -m app.cli``), not a screen.
    """

    learner = "learner"
    coach = "coach"
    school_admin = "school_admin"


class UserStatus(StrEnum):
    active = "active"
    suspended = "suspended"
    disabled = "disabled"


class School(Base):
    __tablename__ = "schools"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    # IANA name, e.g. "Africa/Lagos". Every "today" in the product is resolved
    # against this zone (P3-T03), never the server's own.
    timezone: Mapped[str] = mapped_column(Text, nullable=False)
    leaderboards_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class User(Base):
    __tablename__ = "users"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    school_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("schools.id", ondelete="RESTRICT"), nullable=False
    )
    role: Mapped[Role] = mapped_column(
        Enum(Role, name="identity_role", values_callable=lambda e: [m.value for m in e]),
        nullable=False,
    )
    status: Mapped[UserStatus] = mapped_column(
        Enum(
            UserStatus,
            name="identity_user_status",
            values_callable=lambda e: [m.value for m in e],
        ),
        nullable=False,
        default=UserStatus.active,
    )
    preferred_name: Mapped[str] = mapped_column(Text, nullable=False)
    real_name: Mapped[str] = mapped_column(Text, nullable=False)
    avatar_key: Mapped[str] = mapped_column(Text, nullable=False)
    date_of_birth: Mapped[dt.date] = mapped_column(Date, nullable=False)

    # Login identity: a short code plus a PIN. One form for every role, so
    # there is one set of rules to get right (0003_login_codes).
    student_code: Mapped[str] = mapped_column(Text, nullable=False)
    pin_hash: Mapped[str | None] = mapped_column(Text, nullable=True)

    failed_login_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    locked_until: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True))

    created_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )

    school: Mapped[School] = relationship(lazy="joined")

    __table_args__ = (
        Index("ix_users_school_id", "school_id"),
        # Stored uppercase, so a plain unique index is enough.
        Index("ux_users_student_code", "student_code", unique=True),
    )


class Class(Base):
    __tablename__ = "classes"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    school_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("schools.id", ondelete="CASCADE"), nullable=False
    )
    name: Mapped[str] = mapped_column(Text, nullable=False)
    grade: Mapped[int | None] = mapped_column(SmallInteger)
    created_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    __table_args__ = (Index("ix_classes_school_id", "school_id"),)


class ClassMember(Base):
    __tablename__ = "class_members"

    class_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("classes.id", ondelete="CASCADE"), primary_key=True
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    created_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    __table_args__ = (Index("ix_class_members_user_id", "user_id"),)


class CoachAssignment(Base):
    __tablename__ = "coach_assignments"

    coach_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    class_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("classes.id", ondelete="CASCADE"), primary_key=True
    )
    created_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    __table_args__ = (Index("ix_coach_assignments_class_id", "class_id"),)


class AuthSession(Base):
    """One logged-in browser (D-19).

    The refresh token is opaque and only its SHA-256 hash is stored, so a
    database leak cannot be replayed. Rotation revokes this row and inserts a
    new one; a re-used rotated token is a theft signal.
    """

    __tablename__ = "auth_sessions"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    refresh_token_hash: Mapped[str] = mapped_column(Text, nullable=False)
    expires_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    revoked_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True))
    revoked_reason: Mapped[str | None] = mapped_column(Text)
    created_ip: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    last_used_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True))

    __table_args__ = (
        UniqueConstraint("refresh_token_hash", name="ux_auth_sessions_refresh_token_hash"),
        Index("ix_auth_sessions_user_id", "user_id"),
        Index("ix_auth_sessions_expires_at", "expires_at"),
    )


class AgeBand(Base):
    """Age bands (P1-T04, D-22).

    A learner's band is snapshotted onto results and XP rows when they are
    written, so a birthday never rewrites history.
    """

    __tablename__ = "age_bands"

    id: Mapped[str] = mapped_column(Text, primary_key=True)
    label: Mapped[str] = mapped_column(Text, nullable=False)
    min_age: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    max_age: Mapped[int | None] = mapped_column(SmallInteger)

    __table_args__ = (UniqueConstraint("min_age", name="ux_age_bands_min_age"),)


class LearningXpEntry(Base):
    """Learning XP stub (P1-T09).

    Owned by the host platform in reality. It exists here only so Profile XP
    can be computed later; Game XP never writes to this table (D-01).
    """

    __tablename__ = "learning_xp_ledger"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    amount: Mapped[int] = mapped_column(Integer, nullable=False)
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    __table_args__ = (Index("ix_learning_xp_ledger_user_id", "user_id", "created_at"),)
