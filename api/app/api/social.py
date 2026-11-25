"""Invitations, the friends roster and the inbox (P7-T02 .. P7-T09).

Thin, like every router: parse, authorise, call the service, return. The rules —
expiry, one seat, blocks, the pair cap, the comparison — live in
``services.challenge`` and ``domain.invites``.

Two things only exist here because they are HTTP concerns:

- the **link cookie**. ``/games/join?t=…`` is a page, so the page strips the
  token into an httpOnly cookie; this router reads it back, so the token never
  appears in a URL that ends up in a ``Referer`` header (P7-T02).
- the **school clock** used in "This code stops working at 3:15." A child reads
  a time; a countdown number is a thing to worry about.
"""

from __future__ import annotations

import datetime as dt
import uuid
from typing import Annotated
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Cookie, Depends, Request, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.cache import CacheClient
from app.core.config import get_settings
from app.core.errors import AppError, NotFoundError, RateLimitedError, UnauthorizedError
from app.core.rate_limit import check_user_limit, client_ip, get_cache
from app.games import repository as repo
from app.games.domain import invites as invite_rules
from app.games.models import GameInvitation
from app.games.schemas import (
    AdminReportOut,
    BlockIn,
    ChallengeIn,
    ChallengeOut,
    ChallengeResultOut,
    ChallengeStartOut,
    FriendOut,
    InboxOut,
    InviteAcceptedOut,
    InviteAcceptIn,
    MyTurnOut,
    NoteOut,
    PlayOut,
    ReportIn,
    ReportOut,
)
from app.games.services import access, challenge, live, play
from app.identity.deps import ActorDep, CacheDep, SessionDep, require_roles
from app.identity.models import Role, User
from app.identity.service import Actor

router = APIRouter(prefix="/games", tags=["games-social"])

LINK_COOKIE = "invite_token"

# P7-T04. Five wrong codes per learner and thirty per machine in ten minutes is
# far more than a child needs to mistype "ABCD EFGH", and far fewer than
# guessing a code needs (31^8 possibilities). Only *failures* count, so a learner
# who joins five friends in one lesson is never slowed down.
CODE_TRIES_PER_USER = 5
CODE_TRIES_PER_IP = 30
CODE_TRIES_WINDOW_SECONDS = 10 * 60

# One fixed sentence per reason: the admin list never shows a raw code (rule 5).
REPORT_SENTENCES = {
    "bullying": "Unkind words or bullying.",
    "cheating": "Cheating.",
    "inappropriate_name": "A name that is not kind.",
    "other": "Something else.",
}

StaffActor = Annotated[Actor, Depends(require_roles(Role.coach, Role.school_admin))]


async def _acting_user(session: AsyncSession, actor: Actor) -> User:
    user = await session.get(User, actor.id)
    if user is None:  # pragma: no cover - the token already proved they exist
        raise UnauthorizedError("Please sign in again.")
    return user


def _display_name(user: User) -> str:
    return user.preferred_name or user.real_name


def _try_keys(request: Request, user: User) -> tuple[tuple[str, int], ...]:
    return (
        (f"ratelimit:code:user:{user.id}", CODE_TRIES_PER_USER),
        (f"ratelimit:code:ip:{client_ip(request)}", CODE_TRIES_PER_IP),
    )


async def _refuse_after_too_many_tries(cache: CacheClient, request: Request, user: User) -> None:
    """Block before the code is even looked at, so guessing gains nothing."""
    if not get_settings().rate_limit_enabled:
        return
    for key, limit in _try_keys(request, user):
        raw = await cache.get(key)
        if raw is not None and int(raw) >= limit:
            raise RateLimitedError(
                "Too many tries. Please wait a moment and try again.",
                headers={"Retry-After": str(CODE_TRIES_WINDOW_SECONDS)},
            )


async def _count_failed_try(cache: CacheClient, request: Request, user: User) -> None:
    if not get_settings().rate_limit_enabled:
        return
    for key, _limit in _try_keys(request, user):
        await cache.incr_window(key, CODE_TRIES_WINDOW_SECONDS)


def _clock(at: dt.datetime, timezone: str) -> str:
    """3:15 pm, in the school's own clock (never a countdown)."""
    local = at.astimezone(ZoneInfo(timezone))
    hour = local.hour % 12 or 12
    suffix = "am" if local.hour < 12 else "pm"
    return f"{hour}:{local.minute:02d} {suffix}"


# --------------------------------------------------------------------- roster
@router.get("/friends")
async def friends(
    session: SessionDep, actor: ActorDep, cache: CacheDep
) -> list[FriendOut]:
    """Classmates you can tap to invite (P7-T06: avatars first).

    A learner whose browser is open is marked ``online`` and listed first: the
    useful names are the ones that can answer a challenge now.
    """
    user = await _acting_user(session, actor)
    rows = await repo.classmates(session, user_id=user.id, school_id=user.school_id)
    hidden = await repo.blocked_user_ids(session, user_id=user.id)
    out: list[FriendOut] = []
    for row in rows:
        if row.id in hidden:
            continue
        online = await cache.get(live.online_key(row.id)) is not None
        out.append(
            FriendOut(
                id=row.id,
                name=_display_name(row),
                avatar_key=row.avatar_key or "",
                online=online,
                can_invite=True,
                sentence="Tap to send an invite.",
            )
        )
    out.sort(key=lambda friend: (not friend.online, friend.name))
    return out


# ------------------------------------------------------------------ challenges
@router.post("/challenges", status_code=201)
async def create_challenge(
    body: ChallengeIn,
    request: Request,
    session: SessionDep,
    actor: ActorDep,
) -> ChallengeOut:
    """Open a challenge and invite somebody: a roster tap, a code, a link."""
    user = await _acting_user(session, actor)
    # P10-T06: ten invitations an hour. A learner who wants a game sends one;
    # ten is already more than a lesson has room for.
    await check_user_limit(
        get_cache(request), key="invite:user", user_id=user.id, limit=10, window_seconds=3600
    )
    invitee: User | None = None
    if body.invitee_id is not None:
        invitee = await session.get(User, body.invitee_id)
        if invitee is None:
            raise NotFoundError("That learner was not found.")

    created = await challenge.create(
        session,
        user=user,
        game_id=body.game_id,
        difficulty=body.difficulty,
        invitee=invitee,
        with_code=body.with_code,
        with_link=body.with_link,
    )
    timezone = await access.school_timezone(session, user.school_id)
    return ChallengeOut(
        parent_id=created.parent.id,
        invitation_id=created.invitation.id,
        game_id=created.parent.game_id,
        game_name=challenge.game_name(created.parent.game_id),
        code=created.code,
        formatted_code=invite_rules.format_code(created.code) if created.code else None,
        join_path=f"/games/join?t={created.link_token}" if created.link_token else None,
        expires_sentence=(
            f"This code stops working at {_clock(created.invitation.expires_at, timezone)}."
        ),
        invitee_name=_display_name(invitee) if invitee is not None else None,
    )


@router.post("/challenges/{parent_id}/start")
async def start_challenge(
    parent_id: uuid.UUID, session: SessionDep, actor: ActorDep
) -> ChallengeStartOut:
    """Start your own attempt at a challenge: the normal play state follows."""
    user = await _acting_user(session, actor)
    child = await challenge.start(session, user=user, parent_id=parent_id)
    state = await play.get_state(session, user=user, session_id=child.id)
    return ChallengeStartOut(parent_id=parent_id, **PlayOut.model_validate(state).model_dump())


# ---------------------------------------------------------------- my own turn
@router.get("/challenges/mine")
async def my_challenges(session: SessionDep, actor: ActorDep) -> list[MyTurnOut]:
    """The challenges you still owe a turn in, so a closed tab loses nothing."""
    user = await _acting_user(session, actor)
    rows = await challenge.my_turns(session, user=user)
    return [MyTurnOut(**row) for row in rows]


# ------------------------------------------------------------ end-of-game view
@router.get("/sessions/{session_id}/challenge")
async def challenge_result(
    session_id: uuid.UUID, session: SessionDep, actor: ActorDep
) -> ChallengeResultOut | None:
    """The one sentence the end screen shows: who you played, and who won.

    ``null`` means this was a solo game, not a challenge, which is the common
    case and costs one request when the game ends.
    """
    user = await _acting_user(session, actor)
    row = await repo.get_session(session, session_id)
    if row is None or row.school_id != user.school_id:
        raise NotFoundError("That game was not found.")
    if await repo.get_participant(session, row.id, user.id) is None:
        raise NotFoundError("That game was not found.")

    summary = await challenge.summary_for(session, child=row)
    if summary is None:
        return None
    return ChallengeResultOut(**summary)


# --------------------------------------------------------------------- invites
@router.post("/invites/accept")
async def accept_invite(
    body: InviteAcceptIn,
    request: Request,
    session: SessionDep,
    actor: ActorDep,
) -> InviteAcceptedOut:
    """Claim a seat by inbox row, typed code, or link token."""
    user = await _acting_user(session, actor)

    # A typed code is guessable, so it is counted (P7-T04). The inbox tap and
    # the link carry ids and 32 random bytes, which are not.
    typed_code = body.invitation_id is None and bool(body.code)
    cache = get_cache(request)
    if typed_code:
        await _refuse_after_too_many_tries(cache, request, user)

    # A live match invite is not a challenge: two doors, one sentence when
    # neither opens. The row is read here only to choose the door.
    invitation = await _locate_invitation(
        session, invitation_id=body.invitation_id, code=body.code, token=body.token
    )
    if invitation is not None:
        session_row = await repo.get_session(session, invitation.session_id)
        if session_row is not None and session_row.mode == "live":
            try:
                seat = await live.accept(
                    session,
                    user=user,
                    invitation_id=invitation.id,
                    now=dt.datetime.now(dt.UTC),
                )
            except NotFoundError as refused:
                if typed_code and refused.code == "invite_not_found":
                    await _count_failed_try(cache, request, user)
                raise
            return InviteAcceptedOut(
                session_id=seat.id,
                game_id=live.GAME_ID,
                game_name=live.GAME_NAME,
                live=True,
            )

    try:
        accepted = await challenge.accept(
            session,
            user=user,
            invitation_id=body.invitation_id,
            code=body.code,
            token=body.token,
        )
    except NotFoundError as refused:
        # Every rejection of a code looks the same, so only "no such seat" is
        # counted: a learner over their time limit is not a wrong guess.
        if typed_code and refused.code == "invite_not_found":
            await _count_failed_try(cache, request, user)
        raise
    return InviteAcceptedOut(
        parent_id=accepted.parent.id,
        session_id=accepted.child.id,
        game_id=accepted.parent.game_id,
        game_name=challenge.game_name(accepted.parent.game_id),
    )


async def _locate_invitation(
    session: AsyncSession,
    *,
    invitation_id: uuid.UUID | None,
    code: str | None,
    token: str | None,
) -> GameInvitation | None:
    """The invitation this intent names, or ``None``. No rule is applied here."""
    if invitation_id is not None:
        return await repo.get_invitation(session, invitation_id)
    if code:
        normalised = invite_rules.normalise_code(code)
        if normalised is None:
            return None
        return await repo.invitation_by_code_hash(
            session, code_hash=invite_rules.hash_secret(normalised)
        )
    if token:
        return await repo.invitation_by_token_hash(
            session, token_hash=invite_rules.hash_secret(token)
        )
    return None


@router.post("/invites/pending")
async def accept_from_cookie(
    session: SessionDep,
    actor: ActorDep,
    response: Response,
    invite_token: Annotated[str | None, Cookie(alias=LINK_COOKIE)] = None,
) -> InviteAcceptedOut:
    """Consume the link token the join page left in an httpOnly cookie.

    The cookie is cleared whatever happens: a token is good once, and leaving it
    behind would make the next sign-in on a shared laptop join a stranger's game.
    """
    response.delete_cookie(LINK_COOKIE, path="/")
    if not invite_token:
        raise NotFoundError(challenge.BAD_INVITE, code="invite_not_found")
    user = await _acting_user(session, actor)
    accepted = await challenge.accept(session, user=user, token=invite_token)
    return InviteAcceptedOut(
        parent_id=accepted.parent.id,
        session_id=accepted.child.id,
        game_id=accepted.parent.game_id,
        game_name=challenge.game_name(accepted.parent.game_id),
    )


@router.post("/invites/{invitation_id}/decline", status_code=status.HTTP_204_NO_CONTENT)
async def decline_invite(invitation_id: uuid.UUID, session: SessionDep, actor: ActorDep) -> None:
    """\"No thanks\" — a decline is silent, like a block (never a notification)."""
    user = await _acting_user(session, actor)
    row = await repo.get_invitation(session, invitation_id)
    if row is None or row.invitee_id != user.id or row.status != "pending":
        raise NotFoundError("That invite was not found.")
    await repo.set_invitation_status(session, invitation_id=row.id, status="declined")
    await session.commit()


# ----------------------------------------------------------------------- inbox
@router.get("/inbox")
async def inbox(session: SessionDep, actor: ActorDep) -> InboxOut:
    """Pending invites and challenge news. No email, no SMS (P7-T07)."""
    user = await _acting_user(session, actor)
    data = await challenge.inbox(session, user=user)
    return InboxOut(
        invites=data["invites"],
        notifications=[NoteOut(**row) for row in data["notifications"]],
        unread=data["unread"],
    )


@router.post("/inbox/read", status_code=status.HTTP_204_NO_CONTENT)
async def mark_read(session: SessionDep, actor: ActorDep) -> None:
    user = await _acting_user(session, actor)
    await repo.mark_notifications_read(session, user_id=user.id, now=dt.datetime.now(dt.UTC))
    await session.commit()


# ---------------------------------------------------------------------- blocks
@router.post("/blocks", status_code=status.HTTP_204_NO_CONTENT)
async def add_block(body: BlockIn, session: SessionDep, actor: ActorDep) -> None:
    """Block or mute. The other learner is never told (P7-T08)."""
    user = await _acting_user(session, actor)
    if body.user_id == user.id:
        raise AppError("You cannot block yourself.", code="block_self", status_code=400)
    other = await session.get(User, body.user_id)
    if other is None or other.school_id != user.school_id:
        raise NotFoundError("That learner was not found.")
    await repo.add_block(session, blocker_id=user.id, blocked_id=other.id, type_=body.type)
    await session.commit()


@router.delete("/blocks/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
async def remove_block(user_id: uuid.UUID, session: SessionDep, actor: ActorDep) -> None:
    user = await _acting_user(session, actor)
    await repo.remove_block(session, blocker_id=user.id, blocked_id=user_id)
    await session.commit()


# --------------------------------------------------------------------- reports
@router.post("/reports", status_code=201)
async def report(
    body: ReportIn,
    request: Request,
    session: SessionDep,
    actor: ActorDep,
) -> ReportOut:
    """The minimum report: a reason, an optional note, and the admin's list."""
    user = await _acting_user(session, actor)
    # P10-T06: ten reports a day. Enough for a bad afternoon, not enough to bury
    # a school admin's queue.
    await check_user_limit(
        get_cache(request), key="report:user", user_id=user.id, limit=10, window_seconds=86_400
    )
    if body.reported_id == user.id:
        raise AppError("You cannot report yourself.", code="report_self", status_code=400)
    other = await session.get(User, body.reported_id)
    if other is None or other.school_id != user.school_id:
        raise NotFoundError("That learner was not found.")
    row = await repo.add_report(
        session,
        reporter_id=user.id,
        reported_id=other.id,
        session_id=body.session_id,
        reason=body.reason,
        note=body.note,
    )
    await session.commit()
    return ReportOut.model_validate(
        {
            "id": row.id,
            "reported_id": row.reported_id,
            "reason": row.reason,
            "note": row.note,
            "status": row.status,
            "created_at": row.created_at,
        }
    )


@router.get("/reports")
async def list_reports(session: SessionDep, actor: StaffActor) -> list[AdminReportOut]:
    """The school admin's list. P10 deepens the workflow, not this endpoint."""
    rows = await repo.reports_for_school(session, school_id=actor.school_id)
    out: list[AdminReportOut] = []
    for row in rows:
        reported = await session.get(User, row.reported_id)
        reporter = await session.get(User, row.reporter_id)
        out.append(
            AdminReportOut(
                id=row.id,
                reported_id=row.reported_id,
                reason=row.reason,
                note=row.note,
                status=row.status,
                created_at=row.created_at,
                reported_name=_display_name(reported) if reported else "A learner",
                reporter_name=(_display_name(reporter) if reporter else "A classmate"),
                reason_sentence=REPORT_SENTENCES.get(row.reason, "Something was reported."),
            )
        )
    return out
