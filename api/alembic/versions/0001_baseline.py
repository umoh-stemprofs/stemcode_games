"""Baseline: infrastructure metadata table.

Deliberately does not create any game tables. Those arrive in Phase 2
(P2-T01), each in its own reviewed migration. ``app_meta`` holds non-domain
bookkeeping such as the applied seed version, so the migration chain has one
real object to create and drop.

Revision ID: 0001_baseline
Revises:
Create Date: 2026-11-13
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0001_baseline"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "app_meta",
        sa.Column("key", sa.Text(), primary_key=True),
        sa.Column("value", sa.Text(), nullable=False),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
    )


def downgrade() -> None:
    op.drop_table("app_meta")
