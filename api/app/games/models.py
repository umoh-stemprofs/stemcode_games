"""Games ORM models (P2-T02, P2-T06).

Mirrors migration ``0004_games_model``. Only the tables the services touch are
modelled here; the safety and admin tables (reports, flags, audit, notifications,
offline batches, pair counts) are created by the migration and will get models
when their phase needs them.

``GameSession.seed`` is server-private (D-25). It is stored, never serialised:
there is no schema field anywhere that carries it, and ``tests/test_phase2.py``
asserts that across every response model.
"""

from __future__ import annotations

import datetime as dt
import uuid
from typing import Any

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    SmallInteger,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base


class Game(Base):
    __tablename__ = "games"

    id: Mapped[str] = mapped_column(Text, primary_key=True)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    summary: Mapped[str] = mapped_column(Text, nullable=False)
    is_live: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    min_players: Mapped[int] = mapped_column(SmallInteger, nullable=False, default=1)
    max_players: Mapped[int] = mapped_column(SmallInteger, nullable=False, default=1)
    created_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class GameVersion(Base):
    __tablename__ = "game_versions"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    game_id: Mapped[str] = mapped_column(ForeignKey("games.id", ondelete="CASCADE"), nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    rules: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)

    __table_args__ = (UniqueConstraint("game_id", "version", name="ux_game_versions_game_version"),)


class GameSession(Base):
    __tablename__ = "game_sessions"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    game_id: Mapped[str] = mapped_column(ForeignKey("games.id"), nullable=False)
    game_version_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("game_versions.id"))
    mode: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(Text, nullable=False, default="created")
    # Server-private (D-25). Never put this in a response schema.
    seed: Mapped[int | None] = mapped_column(BigInteger)
    school_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("schools.id"), nullable=False)
    created_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"))
    parent_session_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("game_sessions.id"))
    rematch_of: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("game_sessions.id"))
    # The database enforces this foreign key; the ORM does not model content
    # packs yet, so the column is declared without a ForeignKey here.
    content_pack_id: Mapped[uuid.UUID | None] = mapped_column()
    config: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    started_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True))
    ended_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True))
    # D-10: set the first time an already-running solo session finds the day's
    # allowance used up. The session may then run until this moment, no longer.
    allowance_grace_until: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    __table_args__ = (
        CheckConstraint(
            "mode IN ('solo','challenge','live','offline_solo')",
            name="ck_game_sessions_mode",
        ),
        Index("ix_game_sessions_user_created", "created_by", "created_at"),
    )


class GamePairDailyCount(Base):
    """How many challenges one pair plays per day (P7-T05 pair cap).

    Stored with the smaller id first, always: one row per pair per day cannot
    then disagree with itself, and the pair cap check is one lookup.
    """

    __tablename__ = "game_pair_daily_counts"

    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    other_user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    local_date: Mapped[dt.date] = mapped_column(Date, primary_key=True)
    count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)


class GameParticipant(Base):
    __tablename__ = "game_participants"
    session_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("game_sessions.id", ondelete="CASCADE"), primary_key=True
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    seat: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    attempt_status: Mapped[str] = mapped_column(Text, nullable=False, default="not_started")
    # False on a challenge parent's rows: the parent is never a player's open
    # session, the child is (D-28). The D-26 index ignores these.
    counts_as_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    age_band_snapshot: Mapped[str | None] = mapped_column(Text)
    class_id_snapshot: Mapped[uuid.UUID | None] = mapped_column()
    joined_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    __table_args__ = (
        UniqueConstraint("session_id", "seat", name="ux_participants_session_seat"),
        Index("ix_participants_user", "user_id"),
        # D-26: at most one open play per learner, enforced by the database.
        Index(
            "ux_participants_one_active_play",
            "user_id",
            unique=True,
            postgresql_where=text("counts_as_active AND attempt_status = 'in_progress'"),
        ),
    )


class GameMove(Base):
    """Append-only: UPDATE and DELETE are rejected by a trigger (P2-T03)."""

    __tablename__ = "game_moves"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    session_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("game_sessions.id", ondelete="CASCADE"), nullable=False
    )
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"), nullable=False)
    move_number: Mapped[int] = mapped_column(Integer, nullable=False)
    client_move_id: Mapped[str] = mapped_column(Text, nullable=False)
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    client_ts: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True))
    server_ts: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    __table_args__ = (
        UniqueConstraint("session_id", "move_number", name="ux_moves_session_number"),
        UniqueConstraint("session_id", "client_move_id", name="ux_moves_session_client_id"),
    )


class GameResult(Base):
    """Append-only. A correction is a new row linked by ``supersedes_id``."""

    __tablename__ = "game_results"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    session_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("game_sessions.id", ondelete="CASCADE"), nullable=False
    )
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"), nullable=False)
    outcome: Mapped[str] = mapped_column(Text, nullable=False)
    score: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    details: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    leaderboard_eligible: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    supersedes_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("game_results.id", deferrable=True, initially="DEFERRED")
    )
    superseded_by: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("game_results.id", deferrable=True, initially="DEFERRED")
    )
    created_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    __table_args__ = (
        CheckConstraint(
            "outcome IN ('win','loss','draw','completed','no_contest')",
            name="ck_game_results_outcome",
        ),
        Index(
            "ux_results_live",
            "session_id",
            "user_id",
            unique=True,
            postgresql_where=text("superseded_by IS NULL"),
        ),
    )


class GameXpEntry(Base):
    """Append-only. Unique ``(session_id, user_id, reason)`` for idempotency."""

    __tablename__ = "game_xp_ledger"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"), nullable=False)
    game_id: Mapped[str | None] = mapped_column(ForeignKey("games.id"))
    session_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("game_sessions.id"))
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    requested_amount: Mapped[int] = mapped_column(Integer, nullable=False)
    awarded_amount: Mapped[int] = mapped_column(Integer, nullable=False)
    local_date: Mapped[dt.date] = mapped_column(Date, nullable=False)
    school_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("schools.id"), nullable=False)
    class_id_snapshot: Mapped[uuid.UUID | None] = mapped_column()
    age_band_snapshot: Mapped[str | None] = mapped_column(Text)
    leaderboard_eligible: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    created_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    __table_args__ = (
        UniqueConstraint("session_id", "user_id", "reason", name="ux_xp_session_user_reason"),
        Index("ix_xp_user_date", "user_id", "local_date"),
    )


class GameXpDailyTotal(Base):
    """The per-day running total, locked before it is read (P5-T02).

    Keyed by school-local date: a learner's "today" is theirs, not UTC's.
    """

    __tablename__ = "game_xp_daily_totals"

    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    local_date: Mapped[dt.date] = mapped_column(Date, primary_key=True)
    school_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("schools.id", ondelete="RESTRICT"), nullable=False
    )
    xp_total: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    updated_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class LeaderboardPeriod(Base):
    """One window of time for one school (D-35).

    Exactly one open period per ``(school, period_type)``: the dimensions live on
    the entry, so an award never has to guess which row to write (D-33).
    """

    __tablename__ = "leaderboard_periods"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    school_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("schools.id", ondelete="CASCADE"), nullable=False
    )
    period_type: Mapped[str] = mapped_column(Text, nullable=False)
    starts_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    ends_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True))
    status: Mapped[str] = mapped_column(Text, nullable=False, default="open")
    created_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    __table_args__ = (
        CheckConstraint(
            "(period_type = 'all_time') = (ends_at IS NULL)",
            name="ck_periods_all_time_no_end",
        ),
        UniqueConstraint("school_id", "period_type", "starts_at", name="ux_periods_identity"),
    )


class LeaderboardEntry(Base):
    """A projected total. Derived data: the ledger is the record (P5-T07).

    ``game_id`` NULL is the all-games row. A board reads exactly one of the two
    row sets and never sums them (D-33).
    """

    __tablename__ = "leaderboard_entries"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    period_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("leaderboard_periods.id", ondelete="CASCADE"), nullable=False
    )
    school_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("schools.id", ondelete="CASCADE"), nullable=False
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    game_id: Mapped[str | None] = mapped_column(ForeignKey("games.id", ondelete="CASCADE"))
    class_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("classes.id", ondelete="SET NULL")
    )
    age_band: Mapped[str | None] = mapped_column(Text)
    xp_total: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    sessions_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    last_award_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class LearnerStreak(Base):
    """How many school-local days in a row a learner has finished a game.

    One row per learner, advanced by the first result of a day. The date is the
    learner's own (D-07), so a streak never breaks because the server is in UTC.
    """

    __tablename__ = "learner_streaks"

    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    school_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("schools.id", ondelete="CASCADE"), nullable=False
    )
    current_days: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    longest_days: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    last_played_on: Mapped[dt.date | None] = mapped_column(Date)
    updated_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    __table_args__ = (
        CheckConstraint(
            "current_days >= 0 AND longest_days >= current_days", name="ck_streaks_shape"
        ),
    )


class LearnerBadge(Base):
    """A badge earned on a school-local day.

    Badges describe gameplay, never XP (P5-T05). The definitions live in
    ``domain/badges.py`` so a criterion cannot quietly start reading a total.
    """

    __tablename__ = "learner_badges"

    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    badge_id: Mapped[str] = mapped_column(Text, primary_key=True)
    earned_on: Mapped[dt.date] = mapped_column(Date, nullable=False)
    created_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class LearnerDailyQuest(Base):
    """Today's quest for one learner, and the XP it paid.

    ``completed_at`` and ``xp_awarded`` are the idempotency record: the bonus is
    paid once because this row says it already was.
    """

    __tablename__ = "learner_daily_quests"

    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    local_date: Mapped[dt.date] = mapped_column(Date, primary_key=True)
    quest_id: Mapped[str] = mapped_column(Text, primary_key=True)
    progress: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    target: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    completed_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True))
    xp_awarded: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    __table_args__ = (
        CheckConstraint("progress >= 0 AND target > 0", name="ck_quests_progress"),
        Index("ix_quests_user_completed", "user_id", "completed_at"),
    )


class ContentPack(Base):
    """A reviewed set of items for one game, band and locale (P4-T01)."""

    __tablename__ = "game_content_packs"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    game_id: Mapped[str] = mapped_column(ForeignKey("games.id"), nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    locale: Mapped[str] = mapped_column(Text, nullable=False)
    age_band: Mapped[str] = mapped_column(Text, nullable=False)
    difficulty: Mapped[int] = mapped_column(SmallInteger, nullable=False, default=1)
    status: Mapped[str] = mapped_column(Text, nullable=False, default="draft")
    author_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"))
    reviewer_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"))
    published_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True))
    source: Mapped[str | None] = mapped_column(Text)
    safe_language_reviewed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    curriculum_ref: Mapped[str | None] = mapped_column(Text)
    # Why a reviewer sent it back, in their own words (P4-T05).
    review_note: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    __table_args__ = (
        UniqueConstraint(
            "game_id", "version", "locale", "age_band", name="ux_content_packs_version"
        ),
    )


class ContentItem(Base):
    """One puzzle. ``payload`` holds ``{answer, alt_answers, clue, ...}``.

    A word goes live **on its own** (D-38): ``status`` is ``draft`` when it was
    typed, ``live`` once its author pressed *Make it live*, and ``retired`` when
    it was taken down. The pack is only the bucket; the word is the unit that
    children see, so the word is the unit that carries the status. Nothing is
    ever deleted once live — retiring keeps the history of what children played.
    """

    __tablename__ = "game_content_items"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    pack_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("game_content_packs.id", ondelete="CASCADE"), nullable=False
    )
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    difficulty: Mapped[int] = mapped_column(SmallInteger, nullable=False, default=1)
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    status: Mapped[str] = mapped_column(Text, nullable=False, default="draft")
    # Who last made it live, and when. Null while it is only a draft.
    published_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"))
    published_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    __table_args__ = (
        CheckConstraint("status IN ('draft','live','retired')", name="ck_content_items_status"),
        Index("ix_content_items_pack", "pack_id", "sort_order"),
        # The serving query asks for live words of one band, so give it an index.
        Index("ix_content_items_live", "status", "pack_id"),
    )


class BlockedWord(Base):
    """A word a school admin added to the safe-language list (P4-T03).

    The built-in list lives in ``domain/safe_language.py`` because it is code:
    reviewed in a commit, identical on every machine, and impossible to empty by
    accident. This table is the part that must change without a deploy — a word
    a school has actually seen a child use. Both are checked, on every route.

    ``word`` is stored already normalised (lowercase, letters only), so the
    primary key is the whole rule: adding the same word twice changes nothing.
    """

    __tablename__ = "blocked_words"

    word: Mapped[str] = mapped_column(Text, primary_key=True)
    added_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    __table_args__ = (
        CheckConstraint(
            "word = lower(word) AND word ~ '^[a-z]{2,40}$'", name="ck_blocked_words_shape"
        ),
    )


class FairplayFlag(Base):
    """A signal that one session should not count, pending review (P10-T02).

    Phase 5 needs only one thing from this table: *which sessions are off the
    boards*. A flag never changes a ledger row and never subtracts XP by itself —
    the projection and the reconcile both filter on it (D-33), so a flag takes
    effect without rewriting append-only history. ``session_id`` is nullable
    because a flag may describe a pattern across several games, not one session.
    """

    __tablename__ = "fairplay_flags"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    session_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("game_sessions.id", ondelete="CASCADE")
    )
    flag_type: Mapped[str] = mapped_column(Text, nullable=False)
    severity: Mapped[int] = mapped_column(SmallInteger, nullable=False, default=1)
    evidence: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    status: Mapped[str] = mapped_column(Text, nullable=False, default="open")
    reviewed_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"))
    reviewed_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    __table_args__ = (
        CheckConstraint(
            "status IN ('open','reviewing','cleared','actioned')", name="ck_flags_status"
        ),
    )


class SchoolTerm(Base):
    """A school's term calendar (P2-T05). Termly boards need real dates."""

    __tablename__ = "school_terms"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    school_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("schools.id", ondelete="CASCADE"), nullable=False
    )
    name: Mapped[str] = mapped_column(Text, nullable=False)
    starts_on: Mapped[dt.date] = mapped_column(Date, nullable=False)
    ends_on: Mapped[dt.date] = mapped_column(Date, nullable=False)

    __table_args__ = (UniqueConstraint("school_id", "starts_on", name="ux_terms_school_start"),)


class PlatformSetting(Base):
    __tablename__ = "platform_settings"

    key: Mapped[str] = mapped_column(Text, primary_key=True)
    value: Mapped[Any] = mapped_column(JSONB, nullable=False)


class AccessPolicy(Base):
    """A daily limit for a scope (P3-T01). Most specific winner applies."""

    __tablename__ = "game_access_policies"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    scope_type: Mapped[str] = mapped_column(Text, nullable=False)
    scope_id: Mapped[uuid.UUID | None] = mapped_column()
    daily_limit_minutes: Mapped[int] = mapped_column(Integer, nullable=False)
    valid_from: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    valid_until: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True))
    set_by: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"), nullable=False)
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    __table_args__ = (
        CheckConstraint(
            "scope_type IN ('platform','school','class','student')",
            name="ck_access_policies_scope",
        ),
        CheckConstraint("daily_limit_minutes >= 0", name="ck_access_policies_limit"),
        CheckConstraint(
            "(scope_type = 'platform' AND scope_id IS NULL)"
            " OR (scope_type <> 'platform' AND scope_id IS NOT NULL)",
            name="ck_access_policies_scope_id",
        ),
        Index("ix_access_policies_scope", "scope_type", "scope_id", "valid_from"),
    )


class GameLockout(Base):
    """A temporary stop for a class or one learner (P3-T01)."""

    __tablename__ = "game_lockouts"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    scope_type: Mapped[str] = mapped_column(Text, nullable=False)
    scope_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    starts_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    expires_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    created_by: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"), nullable=False)
    revoked_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    __table_args__ = (
        CheckConstraint("scope_type IN ('class','student')", name="ck_lockouts_scope"),
        CheckConstraint("expires_at > starts_at", name="ck_lockouts_window"),
    )


class GamePlayClock(Base):
    """One row per learner per school-local day (D-26).

    ``last_counted_at`` is the only moment time is measured from. Every
    heartbeat and every game action advances it, so two tabs cannot age the
    allowance twice and a suppressed heartbeat is still charged by the moves
    the player actually makes.
    """

    __tablename__ = "game_play_clock"

    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    local_date: Mapped[dt.date] = mapped_column(Date, primary_key=True)
    last_counted_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class GameTimeUsage(Base):
    """Accrued active seconds, split by how they were observed (P3-T05)."""

    __tablename__ = "game_time_usage"

    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    local_date: Mapped[dt.date] = mapped_column(Date, primary_key=True)
    source: Mapped[str] = mapped_column(Text, primary_key=True)
    active_seconds: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    updated_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    __table_args__ = (
        CheckConstraint("source IN ('heartbeat','action','offline')", name="ck_time_usage_source"),
        CheckConstraint("active_seconds >= 0", name="ck_time_usage_non_negative"),
    )


class SchoolGameSetting(Base):
    __tablename__ = "school_game_settings"

    school_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("schools.id", ondelete="CASCADE"), primary_key=True
    )
    game_id: Mapped[str] = mapped_column(
        ForeignKey("games.id", ondelete="CASCADE"), primary_key=True
    )
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    daily_limit_minutes: Mapped[int | None] = mapped_column(Integer)


class AuditEntry(Base):
    """Who changed what (P3-T09). Append-only in practice, not by trigger."""

    __tablename__ = "audit_log"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    actor_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"))
    action: Mapped[str] = mapped_column(Text, nullable=False)
    target_type: Mapped[str | None] = mapped_column(Text)
    target_id: Mapped[str | None] = mapped_column(Text)
    details: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    created_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class GameInvitation(Base):
    """An invitation to play (P7-T01).

    A challenge invitation points at the **parent** session (D-28). Exactly one
    of ``invitee_id`` / ``code_hash`` / ``token_hash`` identifies the invitee:

    - a roster tap names the learner directly, so the invite needs no code;
    - a code is typed by somebody in another class;
    - a link carries a token that a browser stores in a cookie.

    Only hashes are stored (D-31). The plaintext code and token exist for the
    one response that creates them and are never readable again — not by an
    admin, not by the inviter, not by a support query.
    """

    __tablename__ = "game_invitations"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    game_id: Mapped[str] = mapped_column(ForeignKey("games.id"), nullable=False)
    session_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("game_sessions.id", ondelete="CASCADE"), nullable=False
    )
    inviter_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"), nullable=False)
    invitee_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"))
    code_hash: Mapped[str | None] = mapped_column(Text)
    token_hash: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(Text, nullable=False, default="pending")
    expires_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    redeemed_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"))
    redeemed_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    __table_args__ = (
        CheckConstraint(
            "status IN ('pending','accepted','declined','expired','cancelled','revoked')",
            name="ck_invitations_status",
        ),
        CheckConstraint(
            "invitee_id IS NOT NULL OR code_hash IS NOT NULL OR token_hash IS NOT NULL",
            name="ck_invitations_reachable",
        ),
        Index("ux_invitations_code", "code_hash", unique=True),
        Index("ux_invitations_token", "token_hash", unique=True),
        Index("ix_invitations_invitee", "invitee_id", "status"),
        Index("ix_invitations_session", "session_id"),
    )


class GameNotification(Base):
    """The in-app inbox (P7-T07). One sentence and one action, no email."""

    __tablename__ = "game_notifications"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    kind: Mapped[str] = mapped_column(Text, nullable=False)
    # The row to act on: an invitation to answer, or a finished challenge.
    invitation_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("game_invitations.id", ondelete="CASCADE")
    )
    session_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("game_sessions.id"))
    body: Mapped[str] = mapped_column(Text, nullable=False)
    read_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    __table_args__ = (
        CheckConstraint("kind IN ('invite','challenge_result')", name="ck_notifications_kind"),
        Index("ix_notifications_user", "user_id", "read_at"),
    )


class GameBlock(Base):
    """Block or mute (P7-T08). A block is silent: the blocked user is never told."""

    __tablename__ = "game_blocks"

    blocker_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    blocked_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    type: Mapped[str] = mapped_column(Text, primary_key=True, default="block")
    created_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    __table_args__ = (
        CheckConstraint("type IN ('block','mute')", name="ck_blocks_type"),
        CheckConstraint("blocker_id <> blocked_id", name="ck_blocks_not_self"),
        Index("ix_blocks_blocked", "blocked_id"),
    )


class GameReport(Base):
    """The minimum report (P7-T09). P10 deepens the review workflow."""

    __tablename__ = "game_reports"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    reporter_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"), nullable=False)
    reported_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"), nullable=False)
    session_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("game_sessions.id"))
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    note: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(Text, nullable=False, default="open")
    created_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    __table_args__ = (
        CheckConstraint(
            "reason IN ('bullying','cheating','inappropriate_name','other')",
            name="ck_reports_reason",
        ),
        CheckConstraint("status IN ('open','reviewed','dismissed')", name="ck_reports_status"),
        Index("ix_reports_status", "status", "created_at"),
    )
