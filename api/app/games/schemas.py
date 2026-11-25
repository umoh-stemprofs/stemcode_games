"""Request and response models for the games API (Phase 3).

Same rules as the identity schemas: unknown fields are rejected, and nothing
here carries a ``seed`` (D-25) or another player's real name.

The heartbeat body is deliberately tiny. There is no field for "how long I
played", because the server would ignore it (P3-T04): a duration supplied by
the client is a duration supplied by an attacker.
"""

from __future__ import annotations

import datetime as dt
import uuid
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class _Strict(BaseModel):
    model_config = ConfigDict(from_attributes=True, extra="forbid")


class AccessOut(_Strict):
    allowed: bool
    reason: str
    limit_minutes: int
    limit_source: str
    used_seconds: int
    remaining_seconds: int
    locked_until: dt.datetime | None = None
    lockout_reason: str | None = None
    local_date: dt.date
    resets_at: dt.datetime
    server_time: dt.datetime


class HeartbeatIn(_Strict):
    visible: bool = True
    # Advisory only: it never adds time. Kept so the client can explain a
    # pause the server already decided on.
    last_input_age_s: int | None = Field(default=None, ge=0, le=86_400)


class PlayStateOut(_Strict):
    remaining_seconds: int
    used_seconds: int
    limit_minutes: int
    paused: bool
    ended: bool
    ended_reason: str | None = None


class GameSummaryOut(_Strict):
    id: str
    name: str
    summary: str
    is_live: bool


class ActiveSessionOut(_Strict):
    session_id: uuid.UUID | None = None
    game_id: str | None = None


class CreateSessionIn(_Strict):
    difficulty: int = Field(ge=1, le=3, default=1)


class ActionIn(_Strict):
    client_move_id: str = Field(min_length=1, max_length=64)
    # "guess" belongs to Number Guess (P6-T02); the endpoint stays generic.
    type: Literal["round_seen", "answer", "hint", "skip", "guess"]
    value: str | None = Field(default=None, max_length=40)


class RoundOut(_Strict):
    """One round, whichever game it belongs to.

    The two games fill different halves of this model, and neither ever carries
    an answer or a secret: Word Scramble sends letters and a clue (P4-T10),
    Number Guess sends the window and how many tries are left (P6-T03).
    """

    number: int
    time_left_ms: int
    round_seconds: int
    # Word Scramble
    letters: str = ""
    clue: str | None = None
    clue_image_key: str | None = None
    clue_audio_key: str | None = None
    revealed: str | None = None
    tries_left: int = 0
    # Number Guess
    low: int | None = None
    high: int | None = None
    range_low: int | None = None
    range_high: int | None = None
    # Number Guess only: 1-50, 1-200 or 1-1000. The screen chooses its entry
    # control from this rather than inferring the band from the range width.
    difficulty: int | None = None
    tries_total: int | None = None
    feedback: str | None = None
    message: str | None = None
    guesses: list[int] = Field(default_factory=list)


class OfflineItemOut(_Strict):
    """One downloadable puzzle.

    This is the only response that carries an answer, and only because an
    offline round has no server to check against. It carries no session and no
    seed, so a downloaded word can never be scored or ranked (P9-T02).
    """

    id: str
    answer: str
    alt_answers: list[str] = Field(default_factory=list)
    clue: str | None = None
    clue_image_key: str | None = None
    clue_audio_key: str | None = None
    difficulty: int


class OfflinePackOut(_Strict):
    game_id: str
    locale: str
    age_band: str
    difficulty: int
    pack_version: str
    item_count: int
    generated_at: dt.datetime
    items: list[OfflineItemOut]


class XpAwardOut(_Strict):
    """The post-game summary: what this game paid, and room left today.

    Awarded, not requested: a capped award shows the number the learner
    actually got (P5-T10).
    """

    awarded: int
    today: int
    daily_cap: int


class PlayOut(_Strict):
    session_id: uuid.UUID
    game_id: str
    status: str
    round: RoundOut | None = None
    round_index: int
    rounds_total: int
    score: int
    scores: list[int]
    finished: bool
    xp: XpAwardOut | None = None
    # The learner's best for this game, and whether this game beat it. Null for
    # games without a scored best (Checkers) — better empty than a fake number.
    best: str | None = None
    best_is_new: bool = False
    # One sentence about what just happened, in plain language (Appendix D).
    message: str | None = None


class MeXpOut(_Strict):
    """Profile XP is presentation only: no grade or badge may read it (P5-T05)."""

    learning_xp_total: int
    game_xp_total: int
    profile_xp_total: int
    game_xp_today: int
    daily_cap: int


class StreakOut(_Strict):
    """Consecutive school-local days with a finished game (P6 engagement)."""

    current: int
    longest: int
    played_today: bool
    last_played_on: dt.date | None = None


class QuestOut(_Strict):
    id: str
    title: str
    target: int
    progress: int
    completed: bool
    reward_xp: int


class BadgeOut(_Strict):
    """A badge is a gameplay fact; ``earned_on`` is null until it is theirs."""

    id: str
    title: str
    sentence: str
    hint: str
    earned_on: dt.date | None = None


class BestOut(_Strict):
    game_id: str
    name: str
    value: str
    played: int


class LevelOut(_Strict):
    """Presentational only — never a grade, never an eligibility input."""

    number: int
    xp_into: int
    xp_span: int
    xp_to_next: int
    profile_xp: int


class EngagementOut(_Strict):
    streak: StreakOut
    quest: QuestOut
    badges: list[BadgeOut]
    bests: list[BestOut]
    level: LevelOut


class BoardChaseOut(_Strict):
    """The learner one place above: the near-miss nudge."""

    preferred_name: str
    xp_gap: int


class BoardEntryOut(_Strict):
    """Masked identity only: preferred name and avatar (D-15)."""

    rank: int
    preferred_name: str
    avatar_key: str
    xp_total: int
    sessions_count: int
    is_me: bool


class BoardOut(_Strict):
    period: str
    starts_at: dt.datetime
    ends_at: dt.datetime | None = None
    entries: list[BoardEntryOut]
    me: BoardEntryOut | None = None
    # False when the learner has not reached the D-14 minimum yet; the UI says
    # "not enough activity yet" rather than showing a lonely zero.
    me_eligible: bool
    min_sessions: int
    # Near-miss nudges for a learner, both null for staff or the top of a board.
    chase: BoardChaseOut | None = None
    to_join: int | None = None


class StudentGameXpOut(_Strict):
    """One game inside a learner's breakdown (P5-T11)."""

    game_id: str
    xp_total: int
    sessions_count: int


class StudentXpOut(_Strict):
    """A coach's view of one learner: total plus where it came from.

    Auditable by construction: the same numbers a school admin can reconcile
    against the ledger. Identity stays masked (D-15).
    """

    preferred_name: str
    avatar_key: str
    xp_total: int
    sessions_count: int
    games: list[StudentGameXpOut]


class CoachBoardOut(_Strict):
    period: str
    starts_at: dt.datetime
    ends_at: dt.datetime | None = None
    students: list[StudentXpOut]


class TermIn(_Strict):
    name: str = Field(min_length=1, max_length=60)
    starts_on: dt.date
    ends_on: dt.date


class TermOut(_Strict):
    id: uuid.UUID
    name: str
    starts_on: dt.date
    ends_on: dt.date


class MemberAccessOut(_Strict):
    user_id: uuid.UUID
    preferred_name: str
    avatar_key: str
    limit_minutes: int
    limit_source: str
    used_seconds: int
    remaining_seconds: int
    locked_until: dt.datetime | None = None
    lockout_reason: str | None = None


class ClassAccessOut(_Strict):
    class_id: uuid.UUID
    class_name: str
    members: list[MemberAccessOut]


class PolicyIn(_Strict):
    scope_type: Literal["platform", "school", "class", "student"]
    scope_id: uuid.UUID | None = None
    daily_limit_minutes: int = Field(ge=0, le=1_440)
    reason: str = Field(min_length=1, max_length=500)
    valid_until: dt.datetime | None = None


class PolicyOut(_Strict):
    id: uuid.UUID
    scope_type: str
    scope_id: uuid.UUID | None = None
    daily_limit_minutes: int
    valid_from: dt.datetime
    valid_until: dt.datetime | None = None
    reason: str
    set_by: uuid.UUID
    created_at: dt.datetime


class LockoutIn(_Strict):
    scope_type: Literal["class", "student"]
    scope_id: uuid.UUID
    reason: str = Field(min_length=1, max_length=500)
    expires_at: dt.datetime


class LockoutOut(_Strict):
    id: uuid.UUID
    scope_type: str
    scope_id: uuid.UUID
    reason: str
    starts_at: dt.datetime
    expires_at: dt.datetime
    revoked_at: dt.datetime | None = None
    created_at: dt.datetime


# ------------------------------------------------------------ content workflow
class PackSummaryOut(_Strict):
    id: uuid.UUID
    game_id: str
    version: int
    locale: str
    age_band: str
    status: str
    author_id: uuid.UUID | None = None
    reviewer_id: uuid.UUID | None = None
    review_note: str | None = None
    source: str | None = None
    published_at: dt.datetime | None = None
    created_at: dt.datetime
    item_count: int
    live_count: int
    draft_count: int
    per_level: dict[int, int]
    problems: int


class ContentItemOut(_Strict):
    id: uuid.UUID
    answer: str
    clue: str | None = None
    alt_answers: list[str]
    difficulty: int
    problems: list[str]
    # What the tiles look like. Not the session scramble (that needs the seed,
    # D-25), just an honest preview for the author.
    scrambled: str
    # draft | live | retired (D-38)
    status: str
    published_at: dt.datetime | None = None


class PackDetailOut(_Strict):
    pack: PackSummaryOut
    items: list[ContentItemOut]
    can_edit: bool
    can_review: bool
    can_publish: bool


class PackCreateIn(_Strict):
    age_band: str
    # Copy the words of an existing pack into the new draft, so editing a
    # 150-word pack does not mean retyping it.
    copy_from: uuid.UUID | None = None


class ContentItemIn(_Strict):
    answer: str = Field(min_length=1, max_length=40)
    clue: str | None = Field(default=None, max_length=200)
    difficulty: int = Field(ge=1, le=3, default=1)
    alt_answers: list[str] = Field(default_factory=list)
    # Save even though validation complains: a draft is allowed to be untidy.
    allow_problems: bool = False


class ImportIn(_Strict):
    text: str = Field(min_length=1, max_length=200_000)


class ImportRowOut(_Strict):
    line: int
    answer: str
    ok: bool
    message: str | None = None


class ImportReportOut(_Strict):
    added: int
    rows: list[ImportRowOut]


class PublishReadyOut(_Strict):
    published: int


class BlockedWordOut(_Strict):
    word: str
    # True for an entry that ships with the code and cannot be removed here.
    built_in: bool
    added_by: str | None = None
    created_at: dt.datetime | None = None


class BlockedWordIn(_Strict):
    word: str = Field(min_length=1, max_length=40)


# ------------------------------------------------------------------ challenges
class FriendOut(_Strict):
    """One avatar in the "play with a friend" sheet (P7-T06)."""

    id: uuid.UUID
    name: str
    avatar_key: str = ""
    # True when that learner's browser is open right now.
    online: bool = False
    # True when a tap will work. The sentence says why when it will not.
    can_invite: bool
    sentence: str


class ChallengeIn(_Strict):
    game_id: str
    difficulty: int = Field(ge=1, le=3, default=1)
    # A roster tap names the learner; with none, the invite is a code/link.
    invitee_id: uuid.UUID | None = None
    with_code: bool = True
    with_link: bool = True


class ChallengeOut(_Strict):
    parent_id: uuid.UUID
    invitation_id: uuid.UUID
    game_id: str
    game_name: str
    # Plaintext, once. Nothing can read it back afterwards (D-31).
    code: str | None = None
    formatted_code: str | None = None
    join_path: str | None = None
    # "This code stops working at 3:15." — a clock time, never a countdown.
    expires_sentence: str
    invitee_name: str | None = None


class ChallengeStartOut(PlayOut):
    parent_id: uuid.UUID


class InviteAcceptIn(_Strict):
    invitation_id: uuid.UUID | None = None
    code: str | None = Field(default=None, max_length=20)
    token: str | None = Field(default=None, max_length=128)


class InviteAcceptedOut(_Strict):
    """Where the accepted seat is. A challenge has a parent to start; a live
    match is already the thing you join, so it has no parent (P8-T09)."""

    parent_id: uuid.UUID | None = None
    session_id: uuid.UUID
    game_id: str
    game_name: str
    live: bool = False


class InviteOut(_Strict):
    invitation_id: uuid.UUID
    game_id: str
    game_name: str
    inviter_name: str
    sentence: str
    live: bool = False


class NoteOut(_Strict):
    id: uuid.UUID
    kind: str
    body: str
    invitation_id: uuid.UUID | None = None
    session_id: uuid.UUID | None = None
    unread: bool


class InboxOut(_Strict):
    invites: list[InviteOut]
    notifications: list[NoteOut]
    unread: int


class BlockIn(_Strict):
    user_id: uuid.UUID
    type: Literal["block", "mute"] = "block"


class ReportIn(_Strict):
    reported_id: uuid.UUID
    reason: Literal["bullying", "cheating", "inappropriate_name", "other"]
    note: str | None = Field(default=None, max_length=300)
    session_id: uuid.UUID | None = None


class ReportOut(_Strict):
    id: uuid.UUID
    reported_id: uuid.UUID
    reason: str
    note: str | None = None
    status: str
    created_at: dt.datetime


class AdminReportOut(ReportOut):
    """The school admin's list also shows who is who, in plain names (P7-T09)."""

    reported_name: str
    reporter_name: str
    reason_sentence: str


class MyTurnOut(_Strict):
    """A challenge where this learner still owes a turn (P7-T06)."""

    parent_id: uuid.UUID
    game_id: str
    game_name: str
    opponent_name: str | None = None
    sentence: str


class ChallengeResultOut(_Strict):
    """One player's own challenge, for their end screen (P7-T05).

    No secret reaches this shape: no seed, no word, no other score until both
    attempts are in (D-25).
    """

    parent_id: uuid.UUID
    opponent_id: uuid.UUID | None = None
    opponent_name: str | None = None
    outcome: Literal["win", "loss", "draw"] | None = None
    settled: bool
    sentence: str


# ------------------------------------------------------------------- live (P8)
class TicketIn(_Strict):
    session_id: uuid.UUID


class TicketOut(_Strict):
    """A single-use key for one socket. Never logged, never stored client-side."""

    ticket: str
    expires_in: int


class LiveCreateIn(_Strict):
    clock_ms: int | None = Field(default=None, ge=60_000, le=1_800_000)
    increment_ms: int | None = Field(default=None, ge=0, le=30_000)
    with_code: bool = True
    with_link: bool = True
    # Picking a classmate from the roster: the invite goes straight to their
    # inbox, which is the shortest way into a match (P8-T09).
    invitee_id: uuid.UUID | None = None


class LiveCreatedOut(_Strict):
    session_id: uuid.UUID
    game_name: str
    invitation_id: uuid.UUID
    code: str | None = None
    formatted_code: str | None = None
    join_path: str | None = None
    expires_sentence: str


class LiveAcceptIn(_Strict):
    invitation_id: uuid.UUID | None = None
    code: str | None = None
    token: str | None = None


class LiveMoveIn(_Strict):
    client_move_id: str = Field(min_length=8, max_length=64)
    expected_move_number: int = Field(ge=1)
    move: str = Field(min_length=3, max_length=64)


class LiveStateOut(_Strict):
    """One player's view of a match: no seed, no opponent legal moves (D-25)."""

    session_id: uuid.UUID
    game_id: str
    status: str
    seat: Literal["white", "black"]
    side_to_move: Literal["white", "black"]
    your_turn: bool
    board: list[int]
    legal_moves: list[dict[str, object]]
    move_number: int
    clock_ms: dict[str, int]
    increment_ms: int
    moves_by: dict[str, int]
    captures: dict[str, int]
    opponent: dict[str, object]
    you_connected: bool
    draw_offer_from: str | None = None
    draw_offered_at: str | None = None
    outcome: dict[str, object] | None = None
    moves_since_progress: int


class PresenceRowOut(_Strict):
    user_id: uuid.UUID
    name: str
    avatar_key: str
    status: Literal["available", "in_match", "busy"]
    # True when that learner's browser is open right now, so the roster can put
    # them first and show a dot. Never a claim that they are free to play.
    online: bool = False
    # The invite this learner sent me, when there is one. The roster then offers
    # "join their match" instead of "invite them", which is the difference
    # between a greyed-out tile and a seat.
    invitation_id: uuid.UUID | None = None
    sentence: str
