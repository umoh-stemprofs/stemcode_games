"""Games data model (P2-T01 .. P2-T05).

27 tables in one reviewed migration, because they are one schema: sessions only
make sense with participants, moves, results, XP, the play clock and the
leaderboard projection. Splitting them would mean shipping foreign keys that
point at tables which do not exist yet.

Three rules are encoded here rather than in application code:

1. **Append-only.** ``game_moves``, ``game_results`` and ``game_xp_ledger``
   reject UPDATE and DELETE with a trigger. A correction is a new row
   (``supersedes_id`` / ``superseded_by``) or a compensating ledger entry.
2. **One live result per player per session.** A partial unique index on
   ``(session_id, user_id) WHERE superseded_by IS NULL``.
3. **Seeds are not here.** ``game_sessions.seed`` is a server-private bigint and
   nothing in this schema exposes it to a client; tests assert it never reaches
   a response schema.

Statuses are text with CHECK constraints rather than Postgres enums: game
statuses are expected to grow as phases land (Appendix A), and adding a value
to a CHECK is a cheap migration while adding one to an enum in use is not.

Revision ID: 0004_games_model
Revises: 0003_login_codes
Create Date: 2026-11-14
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0004_games_model"
down_revision = "0003_login_codes"
branch_labels = None
depends_on = None

UUID = postgresql.UUID(as_uuid=True)
JSONB = postgresql.JSONB()
NOW = sa.text("now()")

SESSION_MODES = ("solo", "challenge", "live", "offline_solo")
PERIOD_TYPES = ("daily", "weekly", "monthly", "termly", "all_time")
POLICY_SCOPES = ("platform", "school", "class", "student")


def upgrade() -> None:
    # ---------------------------------------------------------------- catalog
    op.create_table(
        "games",
        sa.Column("id", sa.Text(), primary_key=True),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("summary", sa.Text(), nullable=False),
        sa.Column("is_live", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("min_players", sa.SmallInteger(), nullable=False, server_default=sa.text("1")),
        sa.Column("max_players", sa.SmallInteger(), nullable=False, server_default=sa.text("1")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=NOW),
    )

    op.create_table(
        "game_versions",
        sa.Column("id", UUID, primary_key=True),
        sa.Column(
            "game_id",
            sa.Text(),
            sa.ForeignKey("games.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("rules", JSONB, nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=NOW),
        sa.UniqueConstraint("game_id", "version", name="ux_game_versions_game_version"),
    )

    op.create_table(
        "game_content_packs",
        sa.Column("id", UUID, primary_key=True),
        sa.Column(
            "game_id",
            sa.Text(),
            sa.ForeignKey("games.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("locale", sa.Text(), nullable=False),
        sa.Column("age_band", sa.Text(), nullable=False),
        sa.Column("difficulty", sa.SmallInteger(), nullable=False, server_default=sa.text("1")),
        sa.Column("status", sa.Text(), nullable=False, server_default=sa.text("'draft'")),
        sa.Column("author_id", UUID, sa.ForeignKey("users.id", ondelete="SET NULL")),
        sa.Column("reviewer_id", UUID, sa.ForeignKey("users.id", ondelete="SET NULL")),
        sa.Column("published_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=NOW),
        sa.CheckConstraint(
            "status IN ('draft','in_review','published','retired')",
            name="ck_content_packs_status",
        ),
        sa.UniqueConstraint(
            "game_id", "version", "locale", "age_band", name="ux_content_packs_version"
        ),
    )
    op.create_index(
        "ix_content_packs_published",
        "game_content_packs",
        ["game_id", "age_band", "status"],
    )

    op.create_table(
        "game_content_items",
        sa.Column("id", UUID, primary_key=True),
        sa.Column(
            "pack_id",
            UUID,
            sa.ForeignKey("game_content_packs.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("payload", JSONB, nullable=False),
        sa.Column("difficulty", sa.SmallInteger(), nullable=False, server_default=sa.text("1")),
        sa.Column("sort_order", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=NOW),
    )
    op.create_index("ix_content_items_pack", "game_content_items", ["pack_id", "sort_order"])

    # --------------------------------------------------------------- sessions
    op.create_table(
        "game_sessions",
        sa.Column("id", UUID, primary_key=True),
        sa.Column(
            "game_id",
            sa.Text(),
            sa.ForeignKey("games.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("game_version_id", UUID, sa.ForeignKey("game_versions.id")),
        sa.Column("mode", sa.Text(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False, server_default=sa.text("'created'")),
        # Server-private (D-25). Nothing may serialise this column.
        sa.Column("seed", sa.BigInteger(), nullable=True),
        sa.Column(
            "school_id",
            UUID,
            sa.ForeignKey("schools.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("created_by", UUID, sa.ForeignKey("users.id", ondelete="SET NULL")),
        sa.Column(
            "parent_session_id",
            UUID,
            sa.ForeignKey("game_sessions.id", ondelete="CASCADE"),
        ),
        sa.Column("rematch_of", UUID, sa.ForeignKey("game_sessions.id", ondelete="SET NULL")),
        sa.Column("content_pack_id", UUID, sa.ForeignKey("game_content_packs.id")),
        sa.Column("config", JSONB, nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("started_at", sa.DateTime(timezone=True)),
        sa.Column("ended_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=NOW),
        sa.CheckConstraint(
            "mode IN ('solo','challenge','live','offline_solo')",
            name="ck_game_sessions_mode",
        ),
        sa.CheckConstraint(
            "status IN ('created','active','paused','finished','abandoned','timed_out_allowance',"
            "'no_contest','expired')",
            name="ck_game_sessions_status",
        ),
    )
    op.create_index("ix_game_sessions_user_created", "game_sessions", ["created_by", "created_at"])
    op.create_index("ix_game_sessions_school_status", "game_sessions", ["school_id", "status"])
    op.create_index(
        "ix_game_sessions_parent",
        "game_sessions",
        ["parent_session_id"],
        postgresql_where=sa.text("parent_session_id IS NOT NULL"),
    )

    op.create_table(
        "game_participants",
        sa.Column(
            "session_id",
            UUID,
            sa.ForeignKey("game_sessions.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column(
            "user_id",
            UUID,
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("seat", sa.SmallInteger(), nullable=False),
        sa.Column(
            "attempt_status", sa.Text(), nullable=False, server_default=sa.text("'not_started'")
        ),
        sa.Column("age_band_snapshot", sa.Text()),
        sa.Column("class_id_snapshot", UUID),
        sa.Column("joined_at", sa.DateTime(timezone=True), nullable=False, server_default=NOW),
        sa.CheckConstraint(
            "attempt_status IN ('not_started','in_progress','finished','expired')",
            name="ck_participants_attempt_status",
        ),
        sa.UniqueConstraint("session_id", "seat", name="ux_participants_session_seat"),
    )
    op.create_index("ix_participants_user", "game_participants", ["user_id"])

    op.create_table(
        "game_moves",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column(
            "session_id",
            UUID,
            sa.ForeignKey("game_sessions.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("user_id", UUID, sa.ForeignKey("users.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("move_number", sa.Integer(), nullable=False),
        sa.Column("client_move_id", sa.Text(), nullable=False),
        sa.Column("payload", JSONB, nullable=False),
        sa.Column("client_ts", sa.DateTime(timezone=True)),
        sa.Column("server_ts", sa.DateTime(timezone=True), nullable=False, server_default=NOW),
        sa.UniqueConstraint("session_id", "move_number", name="ux_moves_session_number"),
        sa.UniqueConstraint("session_id", "client_move_id", name="ux_moves_session_client_id"),
    )

    op.create_table(
        "game_results",
        sa.Column("id", UUID, primary_key=True),
        sa.Column(
            "session_id",
            UUID,
            sa.ForeignKey("game_sessions.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("user_id", UUID, sa.ForeignKey("users.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("outcome", sa.Text(), nullable=False),
        sa.Column("score", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("details", JSONB, nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column(
            "leaderboard_eligible", sa.Boolean(), nullable=False, server_default=sa.text("false")
        ),
        # Deferrable: a correction marks the old row as superseded *before*
        # the new row exists, which the live-result index demands.
        sa.Column(
            "supersedes_id",
            UUID,
            sa.ForeignKey("game_results.id", deferrable=True, initially="DEFERRED"),
        ),
        sa.Column(
            "superseded_by",
            UUID,
            sa.ForeignKey("game_results.id", deferrable=True, initially="DEFERRED"),
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=NOW),
        sa.CheckConstraint(
            "outcome IN ('win','loss','draw','completed','no_contest')",
            name="ck_game_results_outcome",
        ),
    )
    # The correction chain is queryable in both directions, and exactly one
    # result per player per session is live.
    op.create_index(
        "ux_results_live",
        "game_results",
        ["session_id", "user_id"],
        unique=True,
        postgresql_where=sa.text("superseded_by IS NULL"),
    )
    op.create_index("ix_results_user_created", "game_results", ["user_id", "created_at"])

    # ------------------------------------------------------------ invitations
    op.create_table(
        "game_invitations",
        sa.Column("id", UUID, primary_key=True),
        sa.Column(
            "session_id",
            UUID,
            sa.ForeignKey("game_sessions.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "inviter_id", UUID, sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False
        ),
        sa.Column("invitee_id", UUID, sa.ForeignKey("users.id", ondelete="SET NULL")),
        sa.Column("invite_code", sa.Text(), nullable=False),
        sa.Column("token_hash", sa.Text()),
        sa.Column("status", sa.Text(), nullable=False, server_default=sa.text("'pending'")),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("accepted_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=NOW),
        sa.CheckConstraint(
            "status IN ('pending','accepted','declined','expired','revoked')",
            name="ck_invitations_status",
        ),
        sa.UniqueConstraint("invite_code", name="ux_invitations_code"),
        sa.UniqueConstraint("token_hash", name="ux_invitations_token"),
    )
    op.create_index(
        "ix_invitations_active",
        "game_invitations",
        ["session_id", "status"],
        postgresql_where=sa.text("status = 'pending'"),
    )
    op.create_index("ix_invitations_invitee", "game_invitations", ["invitee_id", "status"])

    # ------------------------------------------------------ access and limits
    op.create_table(
        "game_access_policies",
        sa.Column("id", UUID, primary_key=True),
        sa.Column("scope_type", sa.Text(), nullable=False),
        sa.Column("scope_id", UUID),
        sa.Column("daily_limit_minutes", sa.Integer(), nullable=False),
        sa.Column("valid_from", sa.DateTime(timezone=True), nullable=False, server_default=NOW),
        sa.Column("valid_until", sa.DateTime(timezone=True)),
        sa.Column("set_by", UUID, sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=NOW),
        sa.CheckConstraint(
            "scope_type IN ('platform','school','class','student')",
            name="ck_access_policies_scope",
        ),
        sa.CheckConstraint("daily_limit_minutes >= 0", name="ck_access_policies_limit"),
    )
    op.create_index(
        "ix_access_policies_scope",
        "game_access_policies",
        ["scope_type", "scope_id", "valid_from"],
    )

    op.create_table(
        "game_lockouts",
        sa.Column("id", UUID, primary_key=True),
        sa.Column("scope_type", sa.Text(), nullable=False),
        sa.Column("scope_id", UUID, nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("starts_at", sa.DateTime(timezone=True), nullable=False, server_default=NOW),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "created_by", UUID, sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=False
        ),
        sa.Column("revoked_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=NOW),
        sa.CheckConstraint("scope_type IN ('class','student')", name="ck_lockouts_scope"),
    )
    op.create_index(
        "ix_lockouts_active",
        "game_lockouts",
        ["scope_type", "scope_id", "expires_at"],
        postgresql_where=sa.text("revoked_at IS NULL"),
    )

    # -------------------------------------------------------------------- XP
    op.create_table(
        "game_xp_ledger",
        sa.Column("id", UUID, primary_key=True),
        sa.Column("user_id", UUID, sa.ForeignKey("users.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("game_id", sa.Text(), sa.ForeignKey("games.id", ondelete="RESTRICT")),
        sa.Column("session_id", UUID, sa.ForeignKey("game_sessions.id", ondelete="SET NULL")),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("requested_amount", sa.Integer(), nullable=False),
        sa.Column("awarded_amount", sa.Integer(), nullable=False),
        sa.Column("local_date", sa.Date(), nullable=False),
        sa.Column(
            "school_id",
            UUID,
            sa.ForeignKey("schools.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("class_id_snapshot", UUID),
        sa.Column("age_band_snapshot", sa.Text()),
        sa.Column(
            "leaderboard_eligible", sa.Boolean(), nullable=False, server_default=sa.text("false")
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=NOW),
        # Idempotency: one award per reason per player per session (P4).
        sa.UniqueConstraint("session_id", "user_id", "reason", name="ux_xp_session_user_reason"),
    )
    op.create_index(
        "ix_xp_school_band_created",
        "game_xp_ledger",
        ["school_id", "age_band_snapshot", "created_at"],
    )
    op.create_index("ix_xp_user_date", "game_xp_ledger", ["user_id", "local_date"])

    op.create_table(
        "game_xp_daily_totals",
        sa.Column("user_id", UUID, sa.ForeignKey("users.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("local_date", sa.Date(), primary_key=True),
        sa.Column(
            "school_id",
            UUID,
            sa.ForeignKey("schools.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("xp_total", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=NOW),
    )

    op.create_table(
        "game_pair_daily_counts",
        sa.Column("user_id", UUID, sa.ForeignKey("users.id", ondelete="CASCADE"), primary_key=True),
        sa.Column(
            "other_user_id", UUID, sa.ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
        ),
        sa.Column("local_date", sa.Date(), primary_key=True),
        sa.Column("count", sa.Integer(), nullable=False, server_default=sa.text("0")),
    )

    # -------------------------------------------------------------- play time
    op.create_table(
        "game_time_usage",
        sa.Column("user_id", UUID, sa.ForeignKey("users.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("local_date", sa.Date(), primary_key=True),
        sa.Column("source", sa.Text(), primary_key=True),
        sa.Column("active_seconds", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=NOW),
        sa.CheckConstraint(
            "source IN ('heartbeat','action','offline')", name="ck_time_usage_source"
        ),
        sa.CheckConstraint("active_seconds >= 0", name="ck_time_usage_non_negative"),
    )

    op.create_table(
        "game_play_clock",
        sa.Column("user_id", UUID, sa.ForeignKey("users.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("local_date", sa.Date(), primary_key=True),
        sa.Column(
            "last_counted_at", sa.DateTime(timezone=True), nullable=False, server_default=NOW
        ),
    )

    op.create_table(
        "game_offline_batches",
        sa.Column("id", UUID, primary_key=True),
        sa.Column("user_id", UUID, sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("device_id", sa.Text(), nullable=False),
        sa.Column("payload", JSONB, nullable=False),
        sa.Column("active_seconds", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("status", sa.Text(), nullable=False, server_default=sa.text("'received'")),
        sa.Column("submitted_at", sa.DateTime(timezone=True), nullable=False, server_default=NOW),
        sa.Column("processed_at", sa.DateTime(timezone=True)),
        sa.CheckConstraint(
            "status IN ('received','processed','rejected')", name="ck_offline_batches_status"
        ),
    )
    op.create_index("ix_offline_batches_user", "game_offline_batches", ["user_id", "submitted_at"])

    # ------------------------------------------------------------ safety data
    op.create_table(
        "game_reports",
        sa.Column("id", UUID, primary_key=True),
        sa.Column(
            "reporter_id", UUID, sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False
        ),
        sa.Column(
            "target_user_id", UUID, sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False
        ),
        sa.Column("session_id", UUID, sa.ForeignKey("game_sessions.id", ondelete="SET NULL")),
        sa.Column("category", sa.Text(), nullable=False),
        sa.Column("note", sa.Text()),
        sa.Column("status", sa.Text(), nullable=False, server_default=sa.text("'open'")),
        sa.Column("resolved_at", sa.DateTime(timezone=True)),
        sa.Column("resolved_by", UUID, sa.ForeignKey("users.id", ondelete="SET NULL")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=NOW),
        sa.CheckConstraint(
            "status IN ('open','reviewing','resolved','dismissed')", name="ck_reports_status"
        ),
    )
    op.create_index("ix_reports_status", "game_reports", ["status", "created_at"])

    op.create_table(
        "game_blocks",
        sa.Column("id", UUID, primary_key=True),
        sa.Column(
            "blocker_id", UUID, sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False
        ),
        sa.Column(
            "blocked_id", UUID, sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=NOW),
        sa.UniqueConstraint("blocker_id", "blocked_id", name="ux_blocks_pair"),
        sa.CheckConstraint("blocker_id <> blocked_id", name="ck_blocks_not_self"),
    )

    op.create_table(
        "game_notifications",
        sa.Column("id", UUID, primary_key=True),
        sa.Column("user_id", UUID, sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("kind", sa.Text(), nullable=False),
        sa.Column("payload", JSONB, nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("read_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=NOW),
    )
    op.create_index(
        "ix_notifications_unread",
        "game_notifications",
        ["user_id", "created_at"],
        postgresql_where=sa.text("read_at IS NULL"),
    )

    op.create_table(
        "fairplay_flags",
        sa.Column("id", UUID, primary_key=True),
        sa.Column("user_id", UUID, sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("flag_type", sa.Text(), nullable=False),
        sa.Column("severity", sa.SmallInteger(), nullable=False, server_default=sa.text("1")),
        sa.Column("evidence", JSONB, nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("status", sa.Text(), nullable=False, server_default=sa.text("'open'")),
        sa.Column("reviewed_by", UUID, sa.ForeignKey("users.id", ondelete="SET NULL")),
        sa.Column("reviewed_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=NOW),
        sa.CheckConstraint(
            "status IN ('open','reviewing','cleared','actioned')", name="ck_flags_status"
        ),
    )
    op.create_index("ix_flags_status", "fairplay_flags", ["status", "created_at"])

    op.create_table(
        "audit_log",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("actor_id", UUID, sa.ForeignKey("users.id", ondelete="SET NULL")),
        sa.Column("action", sa.Text(), nullable=False),
        sa.Column("target_type", sa.Text()),
        sa.Column("target_id", sa.Text()),
        sa.Column("details", JSONB, nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=NOW),
    )
    op.create_index("ix_audit_created", "audit_log", ["created_at"])
    op.create_index("ix_audit_target", "audit_log", ["target_type", "target_id"])

    # ------------------------------------------------------------ leaderboards
    op.create_table(
        "school_terms",
        sa.Column("id", UUID, primary_key=True),
        sa.Column(
            "school_id",
            UUID,
            sa.ForeignKey("schools.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("starts_on", sa.Date(), nullable=False),
        sa.Column("ends_on", sa.Date(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=NOW),
        sa.CheckConstraint("ends_on > starts_on", name="ck_terms_dates"),
        sa.UniqueConstraint("school_id", "starts_on", name="ux_terms_school_start"),
    )

    op.create_table(
        "leaderboard_periods",
        sa.Column("id", UUID, primary_key=True),
        sa.Column("period_type", sa.Text(), nullable=False),
        sa.Column("game_id", sa.Text(), sa.ForeignKey("games.id", ondelete="CASCADE")),
        sa.Column(
            "school_id",
            UUID,
            sa.ForeignKey("schools.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("age_band", sa.Text()),
        sa.Column("class_id", UUID, sa.ForeignKey("classes.id", ondelete="SET NULL")),
        sa.Column("starts_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("ends_at", sa.DateTime(timezone=True)),
        sa.Column("status", sa.Text(), nullable=False, server_default=sa.text("'open'")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=NOW),
        sa.CheckConstraint(
            "period_type IN ('daily','weekly','monthly','termly','all_time')",
            name="ck_periods_type",
        ),
        # all_time never resets: no end date, ever.
        sa.CheckConstraint(
            "(period_type = 'all_time') = (ends_at IS NULL)", name="ck_periods_all_time_no_end"
        ),
        sa.CheckConstraint("status IN ('open','closed')", name="ck_periods_status"),
        sa.UniqueConstraint(
            "period_type",
            "game_id",
            "school_id",
            "age_band",
            "starts_at",
            name="ux_periods_identity",
        ),
    )
    op.create_index(
        "ix_periods_lookup", "leaderboard_periods", ["school_id", "period_type", "status"]
    )

    op.create_table(
        "leaderboard_entries",
        sa.Column(
            "period_id",
            UUID,
            sa.ForeignKey("leaderboard_periods.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("user_id", UUID, sa.ForeignKey("users.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("game_id", sa.Text(), sa.ForeignKey("games.id", ondelete="CASCADE")),
        sa.Column("xp_total", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("rank", sa.Integer()),
        sa.Column("sessions_count", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=NOW),
    )
    op.create_index(
        "ix_entries_ranking",
        "leaderboard_entries",
        ["period_id", "xp_total"],
        postgresql_ops={"xp_total": "DESC"},
    )

    # --------------------------------------------------------------- settings
    op.create_table(
        "platform_settings",
        sa.Column("key", sa.Text(), primary_key=True),
        sa.Column("value", JSONB, nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=NOW),
    )

    op.create_table(
        "school_game_settings",
        sa.Column(
            "school_id",
            UUID,
            sa.ForeignKey("schools.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column(
            "game_id", sa.Text(), sa.ForeignKey("games.id", ondelete="CASCADE"), primary_key=True
        ),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("daily_limit_minutes", sa.Integer()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=NOW),
    )

    # ------------------------------------------------------- append-only guard
    op.execute(
        """
        CREATE OR REPLACE FUNCTION reject_append_only_mutation() RETURNS trigger AS $$
        BEGIN
            -- One narrow, documented exception: a result may be *retired* by
            -- setting superseded_by once, because the correction chain needs
            -- the old row to point forward. Every other column must be
            -- untouched, and only a live row can be retired — so history is
            -- never rewritten, only marked as superseded.
            IF TG_OP = 'UPDATE' AND TG_TABLE_NAME = 'game_results' THEN
                IF OLD.superseded_by IS NULL
                   AND NEW.superseded_by IS NOT NULL
                   AND NEW.id = OLD.id
                   AND NEW.session_id = OLD.session_id
                   AND NEW.user_id = OLD.user_id
                   AND NEW.outcome = OLD.outcome
                   AND NEW.score = OLD.score
                   AND NEW.details = OLD.details
                   AND NEW.leaderboard_eligible = OLD.leaderboard_eligible
                   AND NEW.supersedes_id IS NOT DISTINCT FROM OLD.supersedes_id
                   AND NEW.created_at = OLD.created_at
                THEN
                    RETURN NEW;
                END IF;
            END IF;

            RAISE EXCEPTION '% is append-only: write a new row instead of %',
                TG_TABLE_NAME, TG_OP
                USING ERRCODE = 'integrity_constraint_violation';
        END;
        $$ LANGUAGE plpgsql;
        """
    )
    for table in ("game_moves", "game_results", "game_xp_ledger"):
        op.execute(
            f"""
            CREATE TRIGGER {table}_append_only
            BEFORE UPDATE OR DELETE ON {table}
            FOR EACH ROW EXECUTE FUNCTION reject_append_only_mutation();
            """
        )

    # --------------------------------------------------------- default config
    op.execute(
        """
        INSERT INTO games (id, name, summary, is_live, enabled, min_players, max_players) VALUES
          ('word_scramble', 'Word Scramble',
           'Make a word from mixed-up letters.', false, false, 1, 1),
          ('number_guess', 'Number Guess',
           'Find the secret number. We say higher or lower.', false, false, 1, 1),
          ('checkers', 'Checkers',
           'Play draughts against a classmate.', true, false, 2, 2)
        ON CONFLICT (id) DO NOTHING
        """
    )
    op.execute(
        """
        INSERT INTO platform_settings (key, value) VALUES
          ('daily_limit_minutes', '120'::jsonb),
          ('daily_limit_ceiling_minutes', '240'::jsonb),
          ('daily_xp_cap', '60'::jsonb),
          ('live_min_remaining_seconds', '900'::jsonb),
          ('leaderboard_eligible_min_sessions', '3'::jsonb),
          ('period_types_enabled', '["daily","weekly","termly","all_time"]'::jsonb)
        ON CONFLICT (key) DO NOTHING
        """
    )


def downgrade() -> None:
    for table in ("game_moves", "game_results", "game_xp_ledger"):
        op.execute(f"DROP TRIGGER IF EXISTS {table}_append_only ON {table}")
    op.execute("DROP FUNCTION IF EXISTS reject_append_only_mutation()")

    op.drop_table("school_game_settings")
    op.drop_table("platform_settings")
    op.drop_index("ix_entries_ranking", table_name="leaderboard_entries")
    op.drop_table("leaderboard_entries")
    op.drop_index("ix_periods_lookup", table_name="leaderboard_periods")
    op.drop_table("leaderboard_periods")
    op.drop_table("school_terms")
    op.drop_index("ix_audit_target", table_name="audit_log")
    op.drop_index("ix_audit_created", table_name="audit_log")
    op.drop_table("audit_log")
    op.drop_index("ix_flags_status", table_name="fairplay_flags")
    op.drop_table("fairplay_flags")
    op.execute("DROP INDEX IF EXISTS ix_notifications_unread")
    op.execute("DROP TABLE IF EXISTS game_notifications")
    op.execute("DROP TABLE IF EXISTS game_blocks")
    op.execute("DROP INDEX IF EXISTS ix_reports_status")
    op.execute("DROP TABLE IF EXISTS game_reports")
    op.drop_index("ix_offline_batches_user", table_name="game_offline_batches")
    op.drop_table("game_offline_batches")
    op.drop_table("game_play_clock")
    op.drop_table("game_time_usage")
    op.drop_table("game_pair_daily_counts")
    op.drop_table("game_xp_daily_totals")
    op.drop_index("ix_xp_user_date", table_name="game_xp_ledger")
    op.drop_index("ix_xp_school_band_created", table_name="game_xp_ledger")
    op.drop_table("game_xp_ledger")
    op.drop_index("ix_lockouts_active", table_name="game_lockouts")
    op.drop_table("game_lockouts")
    op.drop_index("ix_access_policies_scope", table_name="game_access_policies")
    op.drop_table("game_access_policies")
    # 0014 replaced these placeholders with real tables and already removed them
    # on the way down, so tear-down must tolerate "gone". Without IF EXISTS a
    # full ``migrate --revision base`` stops here.
    op.execute("DROP INDEX IF EXISTS ix_invitations_invitee")
    op.execute("DROP INDEX IF EXISTS ix_invitations_active")
    op.execute("DROP TABLE IF EXISTS game_invitations")
    op.drop_index("ix_results_user_created", table_name="game_results")
    op.drop_index("ux_results_live", table_name="game_results")
    op.drop_table("game_results")
    op.drop_table("game_moves")
    op.drop_index("ix_participants_user", table_name="game_participants")
    op.drop_table("game_participants")
    op.drop_index("ix_game_sessions_parent", table_name="game_sessions")
    op.drop_index("ix_game_sessions_school_status", table_name="game_sessions")
    op.drop_index("ix_game_sessions_user_created", table_name="game_sessions")
    op.drop_table("game_sessions")
    op.drop_index("ix_content_items_pack", table_name="game_content_items")
    op.drop_table("game_content_items")
    op.drop_index("ix_content_packs_published", table_name="game_content_packs")
    op.drop_table("game_content_packs")
    op.drop_table("game_versions")
    op.drop_table("games")
