"""Turn Number Guess on for the pilot.

P6-T05 needs no content packs, so there is nothing to publish before the game
can be played — but a game only appears in the learner's catalog when its
``games`` row is enabled. Phase 4 flipped ``word_scramble`` the same way.

Deliberately not a data migration that inserts anything new: the row already
exists from ``0004_games_model``, and a second insert would fail on the primary
key. This is one boolean, and its downgrade is the same boolean back.

Revision ID: 0013_number_guess_live
Revises: 0012_fairplay_session
"""

from __future__ import annotations

from alembic import op

revision = "0013_number_guess_live"
down_revision = "0012_fairplay_session"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("UPDATE games SET enabled = true WHERE id = 'number_guess'")


def downgrade() -> None:
    op.execute("UPDATE games SET enabled = false WHERE id = 'number_guess'")
