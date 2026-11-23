"""One active play per learner (D-26, D-28).

Phase 2 left the rule in application code. That is not enough: two tabs opened
at the same moment both pass a "is anyone playing?" check, and the slower one
wins. A partial unique index moves the decision into Postgres, where exactly
one insert succeeds.

The index is on ``game_participants`` rather than ``game_sessions`` because a
player is what is playing, not a game: a live Checkers match has two players,
and both are spending their own time.

``counts_as_active`` exists for one case only: a challenge **parent** session
(D-28) carries participant rows so both names can be shown, but it is never a
player's open session -- the child session is. Its rows are stored with
``counts_as_active = false`` and are ignored by the index.

Revision ID: 0005_one_active_play
Revises: 0004_games_model
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0005_one_active_play"
down_revision = "0004_games_model"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "game_participants",
        sa.Column(
            "counts_as_active",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("true"),
        ),
    )
    op.create_index(
        "ux_participants_one_active_play",
        "game_participants",
        ["user_id"],
        unique=True,
        postgresql_where=sa.text("counts_as_active AND attempt_status = 'in_progress'"),
    )


def downgrade() -> None:
    op.drop_index("ux_participants_one_active_play", table_name="game_participants")
    op.drop_column("game_participants", "counts_as_active")
