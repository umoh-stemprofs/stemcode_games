"""Challenge mode: one seed, two attempts, one comparison (P7-T05, D-28).

A challenge is not a race and not a shared screen. It is **one puzzle set played
twice**, so the whole design follows from three sentences:

- **One parent, two children.** The parent holds the seed and the config and is
  never played. Each player gets their own `solo` child with the same seed, so
  each has their own clock, their own moves and their own result — and neither
  can see or disturb the other.
- **The clock is the acceptance, not the invite.** An invitation expires in a
  day; the two attempts then get 24 hours from the moment it is accepted. A
  learner who opens the invite with two minutes left in the lesson is not
  punished for it.
- **The result is a comparison.** Whichever child happens to finish first does
  not win anything: both scores are compared when both are in, or when the
  window closes. A player who never turns up does not get a result at all, and
  the player who did keeps the result they earned.

Nothing here reveals a seed, a word or a score to the other player before the
comparison (D-25). The seats are addressed by id, and the sentences come from
`domain.invites`.
"""

from __future__ import annotations

import datetime as dt
import secrets
import uuid
from dataclasses import dataclass
from typing import Any
from zoneinfo import ZoneInfo

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import AppError, ConflictError, NotFoundError
from app.games import repository as repo
from app.games.domain import invites as invite_rules
from app.games.models import GameInvitation, GameResult, GameSession
from app.games.services import access, rounds, xp
from app.games.services import sessions as lifecycle
from app.identity.models import User

# Challenges exist for the two turn-based solo games. Live multiplayer games
# get their own matching in Phase 8, so offering a challenge here would promise
# something this build cannot keep.
CHALLENGE_GAMES = frozenset({"word_scramble", "number_guess"})

# One pair, one day. Enough for a lesson, not enough for a pair to grind the
# board by replaying each other.
DEFAULT_PAIR_CAP = 3

GAME_NAMES = {
    "word_scramble": "Word Scramble",
    "number_guess": "Number Guess",
    # Checkers is live-only, but its invitations share this inbox, and a pending
    # invite that says "this game" is a sentence a child cannot act on.
    "checkers": "Checkers",
}

# One sentence for every way a code can fail. Saying which way failed would
# answer "does this code exist?" for anyone guessing (P7-T04).
BAD_INVITE = "That code did not work."


@dataclass(frozen=True, slots=True)
class Created:
    """What the invite sheet needs, in one response."""

    parent: GameSession
    invitation: GameInvitation
    code: str | None
    link_token: str | None


@dataclass(frozen=True, slots=True)
class Accepted:
    """The child session the accepting learner should now play."""

    parent: GameSession
    child: GameSession


def _now() -> dt.datetime:
    return dt.datetime.now(dt.UTC)


def _name(user: User) -> str:
    return user.preferred_name or user.real_name


def game_name(game_id: str) -> str:
    return GAME_NAMES.get(game_id, "this game")


def _ordered(a: uuid.UUID, b: uuid.UUID) -> tuple[uuid.UUID, uuid.UUID]:
    return (a, b) if str(a) < str(b) else (b, a)


async def _pair_cap(session: AsyncSession) -> int:
    from app.games.services.access import _setting_int

    return await _setting_int(session, "challenge.pair_daily_cap", DEFAULT_PAIR_CAP)


# ------------------------------------------------------------------- creating
async def create(
    session: AsyncSession,
    *,
    user: User,
    game_id: str,
    difficulty: int,
    invitee: User | None = None,
    with_code: bool = True,
    with_link: bool = True,
    now: dt.datetime | None = None,
) -> Created:
    """Open a challenge and invite somebody to it.

    The inviter's own attempt exists from this moment, so \"play now\" on the
    sheet is one tap away. The other attempt exists too, waiting for the person
    who accepts: both must come from the same seed, and building the second one
    later would risk a different set of words.
    """
    now = now or _now()
    if game_id not in CHALLENGE_GAMES:
        raise AppError(
            "You cannot invite a friend to this game yet.",
            code="challenge_not_supported",
            status_code=400,
        )
    if invitee is not None:
        if invitee.id == user.id:
            raise AppError(
                "Pick a friend, not yourself.",
                code="challenge_self",
                status_code=400,
            )
        if invitee.school_id != user.school_id:
            raise NotFoundError("That learner was not found.")
        if await repo.block_exists_between(session, a=user.id, b=invitee.id):
            # A block is silent: the blocked learner is never told they were
            # blocked, so this is the same "not found" they already see (P7-T08).
            raise NotFoundError("That learner was not found.")
        cap = await _pair_cap(session)
        small, large = _ordered(user.id, invitee.id)
        timezone = await access.school_timezone(session, user.school_id)
        today = now.astimezone(ZoneInfo(timezone)).date()
        played = await repo.pair_count(
            session, user_id=small, other_user_id=large, local_date=today
        )
        if played >= cap:
            raise AppError(
                "You have played with this friend enough today.",
                code="challenge_pair_cap",
                status_code=409,
            )

    timezone = await access.school_timezone(session, user.school_id)
    local_date = now.astimezone(ZoneInfo(timezone)).date()

    # One seed for the whole challenge: this is what makes the two attempts
    # comparable (D-28). It is never serialised (D-25).
    seed = secrets.randbits(63)
    built = await rounds.build(
        session,
        user=user,
        game_id=game_id,
        difficulty=difficulty,
        seed=seed,
        local_date=local_date,
    )

    parent = await repo.create_session(
        session,
        game_id=game_id,
        mode="challenge",
        status="created",
        seed=seed,
        school_id=user.school_id,
        created_by=user.id,
        content_pack_id=built.content_pack_id,
        config=dict(built.config),
    )

    seat_one = await _child(
        session,
        parent=parent,
        seed=seed,
        config=built.config,
        content_pack_id=built.content_pack_id,
        player=user,
        school_id=user.school_id,
    )
    seat_two = await _child(
        session,
        parent=parent,
        seed=seed,
        config=built.config,
        content_pack_id=built.content_pack_id,
        player=None,
        school_id=user.school_id,
    )

    # The parent carries who sits where. The children cannot: seat two has no
    # player until somebody accepts.
    cfg = dict(parent.config)
    cfg["seats"] = {"1": str(seat_one.id), "2": str(seat_two.id)}
    parent.config = cfg
    await session.flush()

    await repo.add_participant(
        session,
        session_id=parent.id,
        user_id=user.id,
        seat=1,
        age_band_snapshot=built.age_band,
        class_id_snapshot=next(
            iter(sorted(await access.class_ids_for(session, user.id), key=str)), None
        ),
        counts_as_active=False,
    )

    code = None
    link_token = None
    if with_code:
        code = invite_rules.generate_code()
    if with_link:
        link_token = invite_rules.generate_token()

    invitation = await repo.create_invitation(
        session,
        game_id=game_id,
        session_id=parent.id,
        inviter_id=user.id,
        invitee_id=invitee.id if invitee is not None else None,
        code_hash=invite_rules.hash_secret(code) if code else None,
        token_hash=invite_rules.hash_secret(link_token) if link_token else None,
        status="pending",
        expires_at=invite_rules.invite_expiry(now),
    )

    if invitee is not None:
        await repo.add_notification(
            session,
            user_id=invitee.id,
            kind="invite",
            invitation_id=invitation.id,
            body=invite_rules.invite_sentence(game_name(game_id), _name(user)),
        )

    await session.commit()
    return Created(parent=parent, invitation=invitation, code=code, link_token=link_token)


async def _child(
    session: AsyncSession,
    *,
    parent: GameSession,
    seed: int,
    config: dict[str, Any],
    content_pack_id: uuid.UUID | None,
    player: User | None,
    school_id: uuid.UUID,
) -> GameSession:
    """One attempt. Identical seed and config to its sibling, by construction."""
    row = await repo.create_session(
        session,
        game_id=parent.game_id,
        mode="solo",
        status="created",
        seed=seed,
        school_id=school_id,
        created_by=parent.created_by,
        parent_session_id=parent.id,
        content_pack_id=content_pack_id,
        config=dict(config),
    )
    if player is not None:
        await repo.add_participant(
            session,
            session_id=row.id,
            user_id=player.id,
            seat=1,
            attempt_status="not_started",
        )
    return row


# ----------------------------------------------------------------- accepting
async def accept(
    session: AsyncSession,
    *,
    user: User,
    invitation_id: uuid.UUID | None = None,
    code: str | None = None,
    token: str | None = None,
    now: dt.datetime | None = None,
) -> Accepted:
    """Claim a seat (P7-T03). Every refusal is the same sentence."""
    now = now or _now()

    invitation: GameInvitation | None = None
    if invitation_id is not None:
        invitation = await repo.get_invitation(session, invitation_id)
    elif code:
        normalised = invite_rules.normalise_code(code)
        if normalised is not None:
            invitation = await repo.invitation_by_code_hash(
                session, code_hash=invite_rules.hash_secret(normalised)
            )
    elif token:
        invitation = await repo.invitation_by_token_hash(
            session, token_hash=invite_rules.hash_secret(token)
        )

    if invitation is None:
        raise NotFoundError(BAD_INVITE, code="invite_not_found")
    if invitation.status != "pending":
        raise NotFoundError(BAD_INVITE, code="invite_not_found")
    if invitation.expires_at <= now:
        raise NotFoundError(BAD_INVITE, code="invite_not_found")
    if invitation.inviter_id == user.id:
        raise AppError("That is your own invite.", code="invite_own", status_code=400)
    if invitation.invitee_id is not None and invitation.invitee_id != user.id:
        # A roster tap names one learner. Showing it to anybody else would
        # reveal who was picked by whom.
        raise NotFoundError(BAD_INVITE, code="invite_not_found")

    inviter = await session.get(User, invitation.inviter_id)
    if inviter is None or inviter.school_id != user.school_id:
        # Cross-school invite: same generic sentence, so a code cannot be used
        # to learn which school it came from (P7-T04).
        raise NotFoundError(BAD_INVITE, code="invite_not_found")
    if await repo.block_exists_between(session, a=user.id, b=inviter.id):
        raise NotFoundError(BAD_INVITE, code="invite_not_found")

    # D-26: one open play per learner. Accepting with another game open would
    # create a seat the learner cannot sit in.
    if await repo.active_session_for_user(session, user.id) is not None:
        raise ConflictError("You have a game open somewhere else.", code="another_session_active")

    parent = await repo.get_session(session, invitation.session_id)
    if parent is None or parent.mode != "challenge":
        raise NotFoundError(BAD_INVITE, code="invite_not_found")
    if parent.status not in ("created", "active", "paused"):
        raise AppError("That challenge has ended.", code="challenge_ended", status_code=409)

    seats = dict(parent.config).get("seats") or {}
    seat_two_id = seats.get("2")
    if not isinstance(seat_two_id, str):
        raise NotFoundError(BAD_INVITE, code="invite_not_found")
    child = await repo.get_session(session, uuid.UUID(seat_two_id))
    if child is None:
        raise NotFoundError(BAD_INVITE, code="invite_not_found")

    # One atomic claim: two learners racing for the last seat get one winner.
    claimed = await repo.accept_invitation(
        session, invitation_id=invitation.id, user_id=user.id, now=now
    )
    if not claimed:
        raise NotFoundError(BAD_INVITE, code="invite_not_found")

    await repo.add_participant(
        session,
        session_id=child.id,
        user_id=user.id,
        seat=1,
        attempt_status="not_started",
    )
    await repo.add_participant(
        session,
        session_id=parent.id,
        user_id=user.id,
        seat=2,
        counts_as_active=False,
    )

    # The 24-hour window starts here, not at the invite (P7-T05).
    cfg = dict(parent.config)
    cfg["accepted_at"] = now.isoformat()
    cfg["deadline"] = invite_rules.challenge_deadline(now).isoformat()
    parent.config = cfg

    if parent.status == "created":
        parent.status = "active"

    # The pair count belongs to the pair, not to who invited whom.
    small, large = _ordered(user.id, inviter.id)
    timezone = await access.school_timezone(session, user.school_id)
    local_date = now.astimezone(ZoneInfo(timezone)).date()
    await repo.bump_pair_count(session, user_id=small, other_user_id=large, local_date=local_date)

    await session.commit()
    return Accepted(parent=parent, child=child)


async def start(
    session: AsyncSession, *, user: User, parent_id: uuid.UUID, now: dt.datetime | None = None
) -> GameSession:
    """The player's own attempt, ready to be started by the normal play path."""
    now = now or _now()
    parent = await repo.get_session(session, parent_id)
    if parent is None or parent.school_id != user.school_id or parent.mode != "challenge":
        raise NotFoundError("That game was not found.")

    child = await child_for(session, parent=parent, user_id=user.id)
    if child is None:
        raise AppError("That challenge is not yours.", code="not_your_challenge", status_code=403)
    if child.status == "finished":
        raise AppError("That game has ended.", code="session_ended", status_code=409)
    if child.status == "expired":
        raise AppError("That challenge has ended.", code="challenge_ended", status_code=409)

    # Phase 3 decides whether this learner may play at all, and this is where a
    # learner over their time limit is refused — the invitation stays valid
    # (P7-T11).
    await lifecycle.start_play(session, user=user, session_id=child.id, now=now)
    return child


async def child_for(
    session: AsyncSession, *, parent: GameSession, user_id: uuid.UUID
) -> GameSession | None:
    """Which of the two attempts belongs to this learner."""
    for child in await repo.child_sessions(session, parent_id=parent.id):
        participant = await repo.get_participant(session, child.id, user_id)
        if participant is not None:
            return child
    return None


async def my_turns(session: AsyncSession, *, user: User) -> list[dict[str, Any]]:
    """Challenges where this learner still owes a turn, oldest first.

    One row per game, ready for a single button: the name to say, the sentence
    to read, and the parent to open. Keeping this list means a challenge is not
    lost because the tab was closed after sending the invite.
    """
    out: list[dict[str, Any]] = []
    for child in await repo.open_challenge_children(session, user_id=user.id):
        parent_id = child.parent_session_id
        if parent_id is None:  # pragma: no cover - the query already excludes these
            continue
        parent = await repo.get_session(session, parent_id)
        if parent is None or parent.status not in ("created", "active", "paused"):
            continue
        opponent_name: str | None = None
        for other in await repo.child_sessions(session, parent_id=parent.id):
            if other.id == child.id:
                continue
            rows = await repo.list_participants(session, other.id)
            if rows:
                other_user = await session.get(User, rows[0].user_id)
                if other_user is not None:
                    opponent_name = _name(other_user)
        out.append(
            {
                "parent_id": parent.id,
                "game_id": parent.game_id,
                "game_name": game_name(parent.game_id),
                "opponent_name": opponent_name,
                "sentence": (
                    f"Your {game_name(parent.game_id)} with {opponent_name} is waiting."
                    if opponent_name
                    else f"Your {game_name(parent.game_id)} is waiting."
                ),
            }
        )
    return out


async def summary_for(session: AsyncSession, *, child: GameSession) -> dict[str, Any] | None:
    """What one player may know about their own challenge (P7-T05, D-25).

    Nothing about the other attempt is revealed before both are in: an early
    score would tell the second player what to beat, and the comparison is the
    whole point. Until then the screen shows one sentence and no numbers.
    """
    if child.parent_session_id is None:
        return None
    parent = await repo.get_session(session, child.parent_session_id)
    if parent is None:
        return None

    mine = await repo.list_participants(session, child.id)
    my_result = (
        await repo.live_result(session, session_id=child.id, user_id=mine[0].user_id)
        if mine
        else None
    )

    opponent: User | None = None
    opponent_result = None
    for other in await repo.child_sessions(session, parent_id=parent.id):
        if other.id == child.id:
            continue
        rows = await repo.list_participants(session, other.id)
        if not rows:
            continue
        opponent = await session.get(User, rows[0].user_id)
        opponent_result = await repo.live_result(
            session, session_id=other.id, user_id=rows[0].user_id
        )

    name = _name(opponent) if opponent is not None else None
    base = {
        "parent_id": parent.id,
        "opponent_id": opponent.id if opponent is not None else None,
        "opponent_name": name,
    }

    if my_result is None or opponent_result is None:
        if parent.status == "finished":
            return {
                **base,
                "outcome": None,
                "settled": True,
                "sentence": (
                    f"{name} did not play in time."
                    if name
                    else "The other player did not play in time."
                ),
            }
        return {
            **base,
            "outcome": None,
            "settled": False,
            "sentence": (
                f"Waiting for {name} to play." if name else "Waiting for the other player."
            ),
        }

    outcome = invite_rules.compare_scores(int(my_result.score), int(opponent_result.score))
    return {
        **base,
        "outcome": outcome,
        "settled": True,
        "sentence": invite_rules.result_sentence(
            game_name(parent.game_id), outcome, name or "The other player"
        ),
    }


# ------------------------------------------------------------------ settling
async def apply(
    session: AsyncSession, *, child: GameSession, now: dt.datetime | None = None
) -> bool:
    """Called when an attempt finishes. Settles the challenge if it can.

    Returns whether this call closed the challenge, which is what a test wants
    to know; the caller does not have to care.
    """
    if child.parent_session_id is None:
        return False
    return await _settle(session, parent_id=child.parent_session_id, now=now or _now())


async def close_after_quit(session: AsyncSession, *, child: GameSession, now: dt.datetime) -> None:
    """A resigned attempt ends the wait for the other player (P7-T05).

    Without this, quitting would leave the other learner waiting out the full
    24-hour window for a player who already left. Closing the window now lets
    the normal comparison run: the finisher keeps the result they earned, and
    the player who walked away gets nothing.
    """
    parent_id = child.parent_session_id
    if parent_id is None:
        return
    parent = await repo.get_session(session, parent_id)
    if parent is None or parent.status == "finished":
        return
    cfg = dict(parent.config)
    cfg["deadline"] = now.isoformat()
    parent.config = cfg
    await session.flush()
    await _settle(session, parent_id=parent.id, now=now)


async def _settle(session: AsyncSession, *, parent_id: uuid.UUID, now: dt.datetime) -> bool:
    parent = await repo.get_session(session, parent_id)
    if parent is None or parent.status == "finished":
        return False

    cfg = dict(parent.config)
    deadline_raw = cfg.get("deadline")
    deadline = dt.datetime.fromisoformat(deadline_raw) if isinstance(deadline_raw, str) else None

    seats: list[tuple[GameSession, User, Any]] = []
    for child in await repo.child_sessions(session, parent_id=parent.id):
        participants = await repo.list_participants(session, child.id)
        if not participants:
            # Nobody accepted this seat: there is no attempt to compare.
            continue
        participant = participants[0]
        player = await session.get(User, participant.user_id)
        if player is None:
            continue
        seats.append(
            (
                child,
                player,
                await repo.live_result(session, session_id=child.id, user_id=participant.user_id),
            )
        )

    if len(seats) < 2:
        # Still waiting for somebody to accept. Only the invite expiry applies.
        return False

    # Read before the loop below rewrites a seat to `expired`: a learner who
    # quit should be described as having stopped, not as having run out of
    # time, and the order seats come back in must not change the sentence.
    walked_away = {
        child.id
        for child, _player, result in seats
        if result is None and child.status == "abandoned"
    }

    finished = [seat for seat in seats if seat[2] is not None]
    expired = deadline is not None and now >= deadline

    if len(finished) < 2 and not expired:
        return False

    parent.status = "finished"
    parent.ended_at = now

    if len(finished) < 2:
        # The window closed with an attempt missing. The finisher keeps the
        # result they earned and gets no win bonus; the absentee gets nothing.
        for child, player, result in seats:
            if result is None:
                await repo.set_attempt_status(session, child.id, player.id, status="expired")
                child.status = "expired"
                child.ended_at = now
                continue
            other = next(seat for seat in seats if seat[0].id != child.id)
            # Say what actually happened: a learner who tapped "quit" did not
            # run out of time, and the sentence should not blame their clock.
            body = (
                f"{_name(other[1])} stopped playing."
                if other[0].id in walked_away
                else f"{_name(other[1])} did not play in time."
            )
            await repo.add_notification(
                session,
                user_id=player.id,
                kind="challenge_result",
                session_id=child.id,
                body=body,
            )
        await session.flush()
        return True

    (child_a, player_a, result_a), (child_b, player_b, result_b) = finished[0], finished[1]
    outcome_a = invite_rules.compare_scores(int(result_a.score), int(result_b.score))
    outcomes = {
        player_a.id: (child_a, result_a, outcome_a, player_b, result_b),
        player_b.id: (
            child_b,
            result_b,
            invite_rules.compare_scores(int(result_b.score), int(result_a.score)),
            player_a,
            result_a,
        ),
    }

    for _player_id, (child, result, outcome, opponent, opponent_result) in outcomes.items():
        # A new row pointing back at the completed one: the history stays
        # readable and the append-only trigger is satisfied (P2-T03).
        replacement = GameResult(
            session_id=child.id,
            user_id=result.user_id,
            outcome=outcome,
            score=result.score,
            details={
                **dict(result.details or {}),
                "challenge": {
                    "parent_id": str(parent.id),
                    "opponent_id": str(opponent.id),
                    "opponent_score": int(opponent_result.score),
                    "outcome": outcome,
                },
            },
            leaderboard_eligible=bool(result.leaderboard_eligible),
        )
        await repo.supersede_result(session, old_result_id=result.id, new_result=replacement)

    for player, (child, result, outcome, opponent, _other_result) in (
        (player_a, outcomes[player_a.id]),
        (player_b, outcomes[player_b.id]),
    ):
        if outcome == "win" and bool(result.leaderboard_eligible):
            await xp.award_challenge_win(session, game_row=child, user=player, now=now)
        await repo.add_notification(
            session,
            user_id=player.id,
            kind="challenge_result",
            session_id=child.id,
            body=invite_rules.result_sentence(game_name(parent.game_id), outcome, _name(opponent)),
        )

    await session.flush()
    return True


async def sweep(session: AsyncSession, *, now: dt.datetime | None = None) -> dict[str, int]:
    """The minute job (P7-T10): expire invites, close overdue challenges."""
    now = now or _now()
    expired_invites = await repo.expire_overdue_invitations(session, now=now)
    await session.commit()

    settled = 0
    for parent in await repo.open_challenges(session):
        raw = dict(parent.config).get("deadline")
        if not isinstance(raw, str):
            continue
        # Compared in Python: a JSONB timestamp read by the database would drag
        # its text format into the rule, and this job runs once a minute over a
        # handful of open challenges.
        if dt.datetime.fromisoformat(raw) <= now:
            if await _settle(session, parent_id=parent.id, now=now):
                settled += 1
                await session.commit()
    return {"invites_expired": expired_invites, "challenges_settled": settled}


# --------------------------------------------------------------------- inbox
async def inbox(session: AsyncSession, *, user: User, now: dt.datetime | None = None) -> dict:
    """Pending invitations and recent challenge news, in words a child reads."""
    now = now or _now()
    rows = await repo.invitations_for_invitee(session, user_id=user.id, now=now)
    invites = []
    for row in rows:
        inviter = await session.get(User, row.inviter_id)
        parent = await repo.get_session(session, row.session_id)
        if inviter is None or parent is None:
            continue
        invites.append(
            {
                "invitation_id": str(row.id),
                "game_id": row.game_id,
                "game_name": game_name(row.game_id),
                "inviter_name": _name(inviter),
                "sentence": invite_rules.invite_sentence(game_name(row.game_id), _name(inviter)),
                # A live match invite is accepted into the match itself, not
                # into a challenge child (P8-T09).
                "live": parent.mode == "live",
            }
        )

    notifications = [
        {
            "id": str(row.id),
            "kind": row.kind,
            "body": row.body,
            "invitation_id": str(row.invitation_id) if row.invitation_id else None,
            "session_id": str(row.session_id) if row.session_id else None,
            "unread": row.read_at is None,
        }
        for row in await repo.notifications_for(session, user_id=user.id)
    ]
    return {
        "invites": invites,
        "notifications": notifications,
        "unread": await repo.unread_notifications(session, user_id=user.id),
    }
