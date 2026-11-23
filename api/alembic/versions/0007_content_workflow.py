"""Content packs get their review fields, and Word Scramble gets switched on.

Phase 2 created the content tables. Phase 4's workflow (P4-T01, P4-T02) needs
three things they do not have:

- ``approved`` as a status, between review and publication. Without it there is
  no place to record "a second person read this", which is the whole point of
  authors not approving their own packs.
- ``source``, so a pack says where its words came from (original, licensed,
  imported). A licence question must be answerable later.
- ``safe_language_reviewed`` and ``curriculum_ref``, both written by a human.

It also turns Word Scramble on. Phase 2 seeded the three games disabled on
purpose, so nothing could be played before the rules existed; the rules now
exist and the DoD asks for a playable pilot.

Revision ID: 0007_content_workflow
Revises: 0006_access_rules
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0007_content_workflow"
down_revision = "0006_access_rules"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("game_content_packs", sa.Column("source", sa.Text()))
    op.add_column(
        "game_content_packs",
        sa.Column(
            "safe_language_reviewed",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
    )
    op.add_column("game_content_packs", sa.Column("curriculum_ref", sa.Text()))

    op.drop_constraint("ck_content_packs_status", "game_content_packs", type_="check")
    op.create_check_constraint(
        "ck_content_packs_status",
        "game_content_packs",
        "status IN ('draft','in_review','approved','published','retired')",
    )

    op.execute("UPDATE games SET enabled = true WHERE id = 'word_scramble'")


def downgrade() -> None:
    op.execute("UPDATE games SET enabled = false WHERE id = 'word_scramble'")
    op.drop_constraint("ck_content_packs_status", "game_content_packs", type_="check")
    op.create_check_constraint(
        "ck_content_packs_status",
        "game_content_packs",
        "status IN ('draft','in_review','published','retired')",
    )
    op.drop_column("game_content_packs", "curriculum_ref")
    op.drop_column("game_content_packs", "safe_language_reviewed")
    op.drop_column("game_content_packs", "source")
