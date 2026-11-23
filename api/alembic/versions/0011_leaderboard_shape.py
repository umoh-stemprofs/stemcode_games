"""Leaderboard periods become one per school, entries carry the dimensions.

Phase 4 shipped the tables from ``0004`` with a shape that cannot express D-33:
a period was keyed by game, band and class, so "the same week" was several rows
and an award had to guess which one to write. The projection in P5-T07 needs
exactly one open period per ``(school, period_type)``, and every dimension
(``game_id``, ``class_id``, ``age_band``) on the *entry*, so one award can
write two rows into each open period and every board reads one row set.

Both tables are derived data, never a source of truth (the ledger is), and they
are empty at this point in the build, so this migration recreates them rather
than performing a column-by-column rewrite.

Revision ID: 0011_leaderboard_shape
Revises: 0010_blocked_words
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID

revision = "0011_leaderboard_shape"
down_revision = "0010_blocked_words"
branch_labels = None
depends_on = None

NOW = sa.text("now()")


def upgrade() -> None:
    op.drop_index("ix_entries_ranking", table_name="leaderboard_entries")
    op.drop_table("leaderboard_entries")
    op.drop_index("ix_periods_lookup", table_name="leaderboard_periods")
    op.drop_table("leaderboard_periods")

    op.create_table(
        "leaderboard_periods",
        sa.Column("id", UUID, primary_key=True),
        sa.Column(
            "school_id",
            UUID,
            sa.ForeignKey("schools.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("period_type", sa.Text(), nullable=False),
        sa.Column("starts_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("ends_at", sa.DateTime(timezone=True)),
        sa.Column("status", sa.Text(), nullable=False, server_default=sa.text("'open'")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=NOW),
        sa.CheckConstraint(
            "period_type IN ('daily','weekly','monthly','termly','all_time')",
            name="ck_periods_type",
        ),
        # all_time never resets: no end date, ever.
        sa.CheckConstraint(
            "(period_type = 'all_time') = (ends_at IS NULL)", name="ck_periods_all_time_no_end"
        ),
        sa.CheckConstraint("status IN ('open','closed')", name="ck_periods_status"),
        sa.UniqueConstraint("school_id", "period_type", "starts_at", name="ux_periods_identity"),
    )
    op.create_index(
        "ix_periods_lookup", "leaderboard_periods", ["school_id", "period_type", "status"]
    )

    op.create_table(
        "leaderboard_entries",
        sa.Column("id", UUID, primary_key=True),
        sa.Column(
            "period_id",
            UUID,
            sa.ForeignKey("leaderboard_periods.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "school_id", UUID, sa.ForeignKey("schools.id", ondelete="CASCADE"), nullable=False
        ),
        sa.Column("user_id", UUID, sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("game_id", sa.Text(), sa.ForeignKey("games.id", ondelete="CASCADE")),
        sa.Column("class_id", UUID, sa.ForeignKey("classes.id", ondelete="SET NULL")),
        sa.Column("age_band", sa.Text()),
        sa.Column("xp_total", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("sessions_count", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("last_award_at", sa.DateTime(timezone=True)),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=NOW),
    )
    # One row per learner per dimension set. ``COALESCE`` rather than a plain
    # unique constraint because a NULL game_id is the "all games" row, and two
    # NULLs are not equal to Postgres, which would let it be written twice.
    op.execute(
        """
        CREATE UNIQUE INDEX ux_entries_identity ON leaderboard_entries (
            period_id,
            user_id,
            COALESCE(game_id, ''),
            COALESCE(class_id, '00000000-0000-0000-0000-000000000000'::uuid),
            COALESCE(age_band, '')
        )
        """
    )
    op.create_index(
        "ix_entries_ranking",
        "leaderboard_entries",
        ["period_id", "xp_total"],
        postgresql_ops={"xp_total": "DESC"},
    )


def downgrade() -> None:
    op.drop_index("ix_entries_ranking", table_name="leaderboard_entries")
    op.drop_index("ux_entries_identity", table_name="leaderboard_entries")
    op.drop_table("leaderboard_entries")
    op.drop_index("ix_periods_lookup", table_name="leaderboard_periods")
    op.drop_table("leaderboard_periods")

    # The pre-Phase-5 shape, restored exactly as 0004 created it.
    op.create_table(
        "leaderboard_periods",
        sa.Column("id", UUID, primary_key=True),
        sa.Column("period_type", sa.Text(), nullable=False),
        sa.Column("game_id", sa.Text(), sa.ForeignKey("games.id", ondelete="CASCADE")),
        sa.Column(
            "school_id", UUID, sa.ForeignKey("schools.id", ondelete="CASCADE"), nullable=False
        ),
        sa.Column("age_band", sa.Text()),
        sa.Column("class_id", UUID, sa.ForeignKey("classes.id", ondelete="SET NULL")),
        sa.Column("starts_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("ends_at", sa.DateTime(timezone=True)),
        sa.Column("status", sa.Text(), nullable=False, server_default=sa.text("'open'")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=NOW),
        sa.CheckConstraint(
            "period_type IN ('daily','weekly','monthly','termly','all_time')",
            name="ck_periods_type",
        ),
        sa.CheckConstraint(
            "(period_type = 'all_time') = (ends_at IS NULL)", name="ck_periods_all_time_no_end"
        ),
        sa.CheckConstraint("status IN ('open','closed')", name="ck_periods_status"),
        sa.UniqueConstraint(
            "period_type",
            "game_id",
            "school_id",
            "age_band",
            "starts_at",
            name="ux_periods_identity",
        ),
    )
    op.create_index(
        "ix_periods_lookup", "leaderboard_periods", ["school_id", "period_type", "status"]
    )

    op.create_table(
        "leaderboard_entries",
        sa.Column(
            "period_id",
            UUID,
            sa.ForeignKey("leaderboard_periods.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("user_id", UUID, sa.ForeignKey("users.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("game_id", sa.Text(), sa.ForeignKey("games.id", ondelete="CASCADE")),
        sa.Column("xp_total", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("rank", sa.Integer()),
        sa.Column("sessions_count", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=NOW),
    )
    op.create_index(
        "ix_entries_ranking",
        "leaderboard_entries",
        ["period_id", "xp_total"],
        postgresql_ops={"xp_total": "DESC"},
    )
