"""Invitations, the in-app inbox, blocks and reports (P7-T01, T07, T08, T09).

Four small tables, one per job:

- ``game_invitations`` — how a learner asks another learner to play. A roster
  tap names the invitee; a code or a link reaches somebody outside the class.
  Only SHA-256 hashes are stored (D-31), so a database dump cannot be used to
  join a challenge.
- ``game_notifications`` — one sentence, one action, no email (P7-T07).
- ``game_blocks`` — a block stops invites in both directions and is never
  announced to the blocked learner.
- ``game_reports`` — the minimum a school admin needs to act on a report.

The challenge itself lives in ``game_sessions``: a ``challenge`` parent with
``parent_session_id`` pointing at it from two ``solo`` children, a shape Phase 2
already created columns for, so this migration adds no session columns.

Revision ID: 0014_social
Revises: 0013_number_guess_live
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID

revision = "0014_social"
down_revision = "0013_number_guess_live"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 0004 shipped empty placeholders for all four of these tables (Phase 2
    # guessed at their shape); this migration is the real thing. On a database that has
    # migrated straight through, the placeholders are still there and
    # ``create_table`` would stop at "already exists" — which is why a brand-new
    # install could never reach head. Drop the shells, keep nothing from them:
    # no row has ever been written to them before this revision.
    op.execute("DROP TABLE IF EXISTS game_notifications CASCADE")
    op.execute("DROP TABLE IF EXISTS game_invitations CASCADE")
    op.execute("DROP TABLE IF EXISTS game_blocks CASCADE")
    op.execute("DROP TABLE IF EXISTS game_reports CASCADE")

    op.create_table(
        "game_invitations",
        sa.Column("id", UUID, primary_key=True),
        sa.Column("game_id", sa.Text, sa.ForeignKey("games.id"), nullable=False),
        sa.Column(
            "session_id",
            UUID,
            sa.ForeignKey("game_sessions.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("inviter_id", UUID, sa.ForeignKey("users.id"), nullable=False),
        sa.Column("invitee_id", UUID, sa.ForeignKey("users.id"), nullable=True),
        sa.Column("code_hash", sa.Text, nullable=True),
        sa.Column("token_hash", sa.Text, nullable=True),
        sa.Column("status", sa.Text, nullable=False, server_default="pending"),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("redeemed_by", UUID, sa.ForeignKey("users.id"), nullable=True),
        sa.Column("redeemed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.CheckConstraint(
            "status IN ('pending','accepted','declined','expired','cancelled','revoked')",
            name="ck_invitations_status",
        ),
        sa.CheckConstraint(
            "invitee_id IS NOT NULL OR code_hash IS NOT NULL OR token_hash IS NOT NULL",
            name="ck_invitations_reachable",
        ),
    )
    # Unique where present: PostgreSQL allows many NULLs in a unique index, so
    # roster invites (no code) do not collide with each other.
    op.create_index("ux_invitations_code", "game_invitations", ["code_hash"], unique=True)
    op.create_index("ux_invitations_token", "game_invitations", ["token_hash"], unique=True)
    op.create_index("ix_invitations_invitee", "game_invitations", ["invitee_id", "status"])
    op.create_index("ix_invitations_session", "game_invitations", ["session_id"])

    op.create_table(
        "game_notifications",
        sa.Column("id", UUID, primary_key=True),
        sa.Column(
            "user_id",
            UUID,
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("kind", sa.Text, nullable=False),
        sa.Column(
            "invitation_id",
            UUID,
            sa.ForeignKey("game_invitations.id", ondelete="CASCADE"),
            nullable=True,
        ),
        sa.Column("session_id", UUID, sa.ForeignKey("game_sessions.id"), nullable=True),
        sa.Column("body", sa.Text, nullable=False),
        sa.Column("read_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.CheckConstraint("kind IN ('invite','challenge_result')", name="ck_notifications_kind"),
    )
    op.create_index("ix_notifications_user", "game_notifications", ["user_id", "read_at"])

    op.create_table(
        "game_blocks",
        sa.Column(
            "blocker_id",
            UUID,
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column(
            "blocked_id",
            UUID,
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("type", sa.Text, primary_key=True, server_default="block"),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.CheckConstraint("type IN ('block','mute')", name="ck_blocks_type"),
        sa.CheckConstraint("blocker_id <> blocked_id", name="ck_blocks_not_self"),
    )
    op.create_index("ix_blocks_blocked", "game_blocks", ["blocked_id"])

    op.create_table(
        "game_reports",
        sa.Column("id", UUID, primary_key=True),
        sa.Column("reporter_id", UUID, sa.ForeignKey("users.id"), nullable=False),
        sa.Column("reported_id", UUID, sa.ForeignKey("users.id"), nullable=False),
        sa.Column("session_id", UUID, sa.ForeignKey("game_sessions.id"), nullable=True),
        sa.Column("reason", sa.Text, nullable=False),
        sa.Column("note", sa.Text, nullable=True),
        sa.Column("status", sa.Text, nullable=False, server_default="open"),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.CheckConstraint(
            "reason IN ('bullying','cheating','inappropriate_name','other')",
            name="ck_reports_reason",
        ),
        sa.CheckConstraint("status IN ('open','reviewed','dismissed')", name="ck_reports_status"),
    )
    op.create_index("ix_reports_status", "game_reports", ["status", "created_at"])


def downgrade() -> None:
    op.drop_index("ix_reports_status", table_name="game_reports")
    op.drop_table("game_reports")

    op.drop_index("ix_blocks_blocked", table_name="game_blocks")
    op.drop_table("game_blocks")

    op.drop_index("ix_notifications_user", table_name="game_notifications")
    op.drop_table("game_notifications")

    op.drop_index("ix_invitations_session", table_name="game_invitations")
    op.drop_index("ix_invitations_invitee", table_name="game_invitations")
    op.drop_index("ux_invitations_token", table_name="game_invitations")
    op.drop_index("ux_invitations_code", table_name="game_invitations")
    op.drop_table("game_invitations")
