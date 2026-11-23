"""Turn Checkers on now that it can actually be played.

Phase 8 builds the rules, the clock and the socket; without this boolean the
game never reaches a learner's lobby. Phase 4 flipped ``word_scramble`` and
Phase 6 ``number_guess`` the same way: the row already exists from
``0004_games_model``, so this is one flag and its downgrade is the same flag.

No table is added by this phase. A live match is a ``game_sessions`` row with
``mode = 'live'``; its board, clocks, connection flags and draw state live in
the existing ``config`` JSONB, and its moves are ``game_moves`` rows like every
other game. That keeps the append-only guarantees of Phase 2 untouched.

One status is new: **ready**. A match whose second seat has been taken is not
``active`` yet — nobody is playing until both players are present, and the
clock must not run while one of them is still walking to the table. The status
constraint is widened here, because the database is where a typo in a service
should be caught, not discovered later.

Revision ID: 0015_checkers_live
Revises: 0014_social
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0015_checkers_live"
down_revision = "0014_social"
branch_labels = None
depends_on = None


STATUSES_WITH_READY = (
    "created",
    "ready",
    "active",
    "paused",
    "finished",
    "abandoned",
    "timed_out_allowance",
    "no_contest",
    "expired",
)

STATUSES_WITHOUT_READY = tuple(status for status in STATUSES_WITH_READY if status != "ready")


def _status_check(values: tuple[str, ...]) -> str:
    joined = ", ".join(f"'{value}'" for value in values)
    return f"status IN ({joined})"


def upgrade() -> None:
    op.execute("UPDATE games SET enabled = true WHERE id = 'checkers'")
    op.drop_constraint("ck_game_sessions_status", "game_sessions", type_="check")
    op.create_check_constraint(
        "ck_game_sessions_status", "game_sessions", sa.text(_status_check(STATUSES_WITH_READY))
    )


def downgrade() -> None:
    # A match waiting for its second player is back to being merely created, so
    # the narrower constraint can be restored without losing the row.
    op.execute("UPDATE game_sessions SET status = 'created' WHERE status = 'ready'")
    op.drop_constraint("ck_game_sessions_status", "game_sessions", type_="check")
    op.create_check_constraint(
        "ck_game_sessions_status",
        "game_sessions",
        sa.text(_status_check(STATUSES_WITHOUT_READY)),
    )
    op.execute("UPDATE games SET enabled = false WHERE id = 'checkers'")
