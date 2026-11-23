"""A place for the reviewer's sentence (P4-T05).

Rejecting a pack has to say why, or the author is guessing. The workflow the
plan describes is ``draft -> in_review -> approved -> published -> retired``,
with rejection returning a pack to ``draft``; this column carries the note
across that step. Keeping it a column rather than an audit-log detail means
the author sees it on the pack itself, which is where they are looking.

Revision ID: 0008_content_review_note
Revises: 0007_content_workflow
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0008_content_review_note"
down_revision = "0007_content_workflow"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("game_content_packs", sa.Column("review_note", sa.Text()))


def downgrade() -> None:
    op.drop_column("game_content_packs", "review_note")
