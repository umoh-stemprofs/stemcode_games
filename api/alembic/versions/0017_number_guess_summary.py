"""Correct the Number Guess card summary.

0004 introduced the games with the summary "We say higher or lower." That was
true of every band until Hard started answering with a temperature word
instead of a direction, and it is now only half true. The card sits on the
Games Hub, where the band is not yet chosen, so it must not promise a clue the
learner may not get.

One row changes, and ``down`` puts the old sentence back. ``games`` is not
append-only: its summary is copy, not history, so an UPDATE is the right tool
here (the append-only rule covers game_moves, game_results and game_xp_ledger).

Revision ID: 0017_number_guess_summary
Revises: 0016_engagement
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0017_number_guess_summary"
down_revision = "0016_engagement"
branch_labels = None
depends_on = None

NEW_SUMMARY = "Find the secret number. Follow the clues."
OLD_SUMMARY = "Find the secret number. We say higher or lower."


def _set_summary(text: str) -> None:
    op.execute(
        sa.text("UPDATE games SET summary = :summary WHERE id = 'number_guess'").bindparams(
            summary=text
        )
    )


def upgrade() -> None:
    _set_summary(NEW_SUMMARY)


def downgrade() -> None:
    _set_summary(OLD_SUMMARY)
