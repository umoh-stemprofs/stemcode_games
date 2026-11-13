"""Identity and school context: schools, users, classes, auth sessions.

Implements P1-T01 plus the age-band table (P1-T04, D-22) and the Learning XP
stub (P1-T09). Hand-written and reviewed, like every migration here: no
autogenerate step (AGENTS.md).

Revision ID: 0002_identity
Revises: 0001_baseline
Create Date: 2026-11-13
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0002_identity"
down_revision = "0001_baseline"
branch_labels = None
depends_on = None

ROLE_VALUES = (
    "learner",
    "coach",
    "school_admin",
    "platform_admin",
    "content_contributor",
    "content_reviewer",
    "moderator",
)
STATUS_VALUES = ("active", "suspended", "disabled")

role_enum = postgresql.ENUM(*ROLE_VALUES, name="identity_role", create_type=False)
status_enum = postgresql.ENUM(*STATUS_VALUES, name="identity_user_status", create_type=False)


def upgrade() -> None:
    bind = op.get_bind()

    role_enum.create(bind, checkfirst=True)
    status_enum.create(bind, checkfirst=True)

    op.create_table(
        "schools",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("timezone", sa.Text(), nullable=False),
        sa.Column(
            "leaderboards_enabled",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("true"),
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )

    op.create_table(
        "users",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "school_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("schools.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("role", role_enum, nullable=False),
        sa.Column(
            "status",
            status_enum,
            nullable=False,
            server_default=sa.text("'active'"),
        ),
        sa.Column("preferred_name", sa.Text(), nullable=False),
        sa.Column("real_name", sa.Text(), nullable=False),
        sa.Column("avatar_key", sa.Text(), nullable=False),
        sa.Column("date_of_birth", sa.Date(), nullable=False),
        sa.Column("email", sa.Text(), nullable=True),
        sa.Column("username", sa.Text(), nullable=True),
        sa.Column("password_hash", sa.Text(), nullable=True),
        sa.Column(
            "failed_login_count",
            sa.Integer(),
            nullable=False,
            server_default=sa.text("0"),
        ),
        sa.Column("locked_until", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        # A user must be reachable somehow; a person without any login handle
        # would be unreachable rows in a table of accounts.
        sa.CheckConstraint(
            "email IS NOT NULL OR username IS NOT NULL",
            name="ck_users_has_login_handle",
        ),
    )
    op.create_index("ix_users_school_id", "users", ["school_id"])
    op.create_index(
        "ux_users_email_lower",
        "users",
        [sa.text("lower(email)")],
        unique=True,
        postgresql_where=sa.text("email IS NOT NULL"),
    )
    op.create_index(
        "ux_users_username_lower",
        "users",
        [sa.text("lower(username)")],
        unique=True,
        postgresql_where=sa.text("username IS NOT NULL"),
    )

    op.create_table(
        "classes",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "school_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("schools.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("grade", sa.SmallInteger(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )
    op.create_index("ix_classes_school_id", "classes", ["school_id"])

    op.create_table(
        "class_members",
        sa.Column(
            "class_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("classes.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column(
            "user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )
    op.create_index("ix_class_members_user_id", "class_members", ["user_id"])

    op.create_table(
        "coach_assignments",
        sa.Column(
            "coach_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column(
            "class_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("classes.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )
    op.create_index("ix_coach_assignments_class_id", "coach_assignments", ["class_id"])

    op.create_table(
        "auth_sessions",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("refresh_token_hash", sa.Text(), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revoked_reason", sa.Text(), nullable=True),
        sa.Column("created_ip", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column("last_used_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint("refresh_token_hash", name="ux_auth_sessions_refresh_token_hash"),
    )
    op.create_index("ix_auth_sessions_user_id", "auth_sessions", ["user_id"])
    op.create_index("ix_auth_sessions_expires_at", "auth_sessions", ["expires_at"])

    op.create_table(
        "age_bands",
        sa.Column("id", sa.Text(), primary_key=True),
        sa.Column("label", sa.Text(), nullable=False),
        sa.Column("min_age", sa.SmallInteger(), nullable=False),
        sa.Column("max_age", sa.SmallInteger(), nullable=True),
        sa.UniqueConstraint("min_age", name="ux_age_bands_min_age"),
    )

    op.create_table(
        "learning_xp_ledger",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column(
            "user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("amount", sa.Integer(), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )
    op.create_index(
        "ix_learning_xp_ledger_user_id", "learning_xp_ledger", ["user_id", "created_at"]
    )

    # Default bands from D-22. Ids are stable keys; labels are display text.
    op.execute(
        """
        INSERT INTO age_bands (id, label, min_age, max_age) VALUES
            ('8-10', 'Ages 8 to 10', 8, 10),
            ('11-13', 'Ages 11 to 13', 11, 13),
            ('14-16', 'Ages 14 to 16', 14, 16),
            ('17+', 'Ages 17 and up', 17, NULL)
        ON CONFLICT (id) DO NOTHING
        """
    )


def downgrade() -> None:
    op.drop_index("ix_learning_xp_ledger_user_id", table_name="learning_xp_ledger")
    op.drop_table("learning_xp_ledger")

    op.drop_table("age_bands")

    op.drop_index("ix_auth_sessions_expires_at", table_name="auth_sessions")
    op.drop_index("ix_auth_sessions_user_id", table_name="auth_sessions")
    op.drop_table("auth_sessions")

    op.drop_index("ix_coach_assignments_class_id", table_name="coach_assignments")
    op.drop_table("coach_assignments")

    op.drop_index("ix_class_members_user_id", table_name="class_members")
    op.drop_table("class_members")

    op.drop_index("ix_classes_school_id", table_name="classes")
    op.drop_table("classes")

    op.drop_index("ux_users_username_lower", table_name="users")
    op.drop_index("ux_users_email_lower", table_name="users")
    op.drop_index("ix_users_school_id", table_name="users")
    op.drop_table("users")

    op.drop_table("schools")

    bind = op.get_bind()
    postgresql.ENUM(name="identity_user_status").drop(bind, checkfirst=True)
    postgresql.ENUM(name="identity_role").drop(bind, checkfirst=True)
