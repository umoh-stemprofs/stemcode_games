"""A fair-play flag points at the session it is about.

Phase 4 created ``fairplay_flags`` with a user and free-form evidence, which
cannot answer the one question Phase 5's reconcile asks: *which sessions must be
left off the boards?* P10-T02 specifies the table as
``(user_id, session_id, signal, score, status)``; this adds the missing
``session_id`` now so the exclusion can be enforced by filtering (D-33) without
editing append-only ledger rows.

Nullable, because a flag may be about a learner rather than one game (for
example, a pattern seen across a week). Only rows with a ``session_id`` affect a
leaderboard.

Revision ID: 0012_fairplay_session
Revises: 0011_leaderboard_shape
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID

revision = "0012_fairplay_session"
down_revision = "0011_leaderboard_shape"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("fairplay_flags", sa.Column("session_id", UUID, nullable=True))
    op.create_foreign_key(
        "fk_flags_session",
        "fairplay_flags",
        "game_sessions",
        ["session_id"],
        ["id"],
        ondelete="CASCADE",
    )
    # The reconcile reads the flagged session ids for one school's boards, so
    # index the column it filters on rather than the whole table.
    op.create_index("ix_flags_session", "fairplay_flags", ["session_id"])


def downgrade() -> None:
    op.drop_index("ix_flags_session", table_name="fairplay_flags")
    op.drop_constraint("fk_flags_session", "fairplay_flags", type_="foreignkey")
    op.drop_column("fairplay_flags", "session_id")
