"""Streaks, badges and the daily quest.

Three small tables, all about *the learner*, none of them a source of truth for
XP or for a board:

- ``learner_streaks`` — one row per learner, advanced the first time they finish
  a game on a school-local day. The date is theirs, not UTC's, so a streak does
  not break at midnight in another country (D-07).
- ``learner_badges`` — the badges a learner has earned. A badge is a *gameplay*
  fact ("you played five games"), never an XP total: P5-T05 forbids Game XP and
  Profile XP from feeding badges or eligibility, and ``domain/badges.py`` is
  written so it cannot.
- ``learner_daily_quests`` — one row per learner per day. The quest is the same
  one every day (play two games) and the row is what makes the +10 bonus pay
  once. The XP itself still lands in ``game_xp_ledger`` through the normal
  capped award path, keyed by the session that completed the quest.

Append-only tables are untouched: a streak is a counter, a badge is a fact, and
a quest row describes today, not history.

Revision ID: 0016_engagement
Revises: 0015_checkers_live
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID

revision = "0016_engagement"
down_revision = "0015_checkers_live"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "learner_streaks",
        sa.Column(
            "user_id",
            UUID,
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column(
            "school_id", UUID, sa.ForeignKey("schools.id", ondelete="CASCADE"), nullable=False
        ),
        sa.Column("current_days", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("longest_days", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("last_played_on", sa.Date(), nullable=True),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.CheckConstraint(
            "current_days >= 0 AND longest_days >= current_days",
            name="ck_streaks_shape",
        ),
    )

    op.create_table(
        "learner_badges",
        sa.Column(
            "user_id",
            UUID,
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("badge_id", sa.Text(), primary_key=True),
        sa.Column("earned_on", sa.Date(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )

    op.create_table(
        "learner_daily_quests",
        sa.Column(
            "user_id",
            UUID,
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("local_date", sa.Date(), primary_key=True),
        sa.Column("quest_id", sa.Text(), primary_key=True),
        sa.Column("progress", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("target", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("xp_awarded", sa.Integer(), nullable=False, server_default="0"),
        sa.CheckConstraint("progress >= 0 AND target > 0", name="ck_quests_progress"),
    )
    # "How many quests has this learner finished?" is a badge question, and it
    # is asked once per profile read.
    op.create_index(
        "ix_quests_user_completed",
        "learner_daily_quests",
        ["user_id", "completed_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_quests_user_completed", table_name="learner_daily_quests")
    op.drop_table("learner_daily_quests")
    op.drop_table("learner_badges")
    op.drop_table("learner_streaks")
