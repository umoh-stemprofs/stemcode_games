"""Live Checkers over HTTP (P8-T09 .. T13, T18).

The socket carries the fast path, but every intent here is the **same service
call** the socket makes. Two reasons that matters:

- a tab that reconnects after a refresh can re-read its match with one GET, and
  a move queued while the socket was down can still be sent;
- the rules are testable without a WebSocket, which keeps the tests about the
  game rather than about the transport.

Nothing here decides a rule. Authorisation and the 15-minute bar are checked by
``services.live``; this file parses and returns.
"""

from __future__ import annotations

import datetime as dt
import uuid
from typing import Annotated
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.cache import CacheClient
from app.core.errors import AppError, NotFoundError, UnauthorizedError
from app.core.rate_limit import check_user_limit, get_cache
from app.games import repository as repo
from app.games.domain import invites as invite_rules
from app.games.schemas import (
    LiveAcceptIn,
    LiveCreatedOut,
    LiveCreateIn,
    LiveMoveIn,
    LiveStateOut,
    PresenceRowOut,
)
from app.games.services import access, live
from app.identity.deps import ActorDep, SessionDep
from app.identity.models import User, UserStatus
from app.identity.service import Actor

router = APIRouter(prefix="/games/live", tags=["games-live"])

CacheDep = Annotated[CacheClient, Depends(get_cache)]


async def _acting_user(session: AsyncSession, actor: Actor) -> User:
    user = await session.get(User, actor.id)
    if user is None:  # pragma: no cover - the token already proved they exist
        raise UnauthorizedError("Please sign in again.")
    return user


def _clock(at: dt.datetime, timezone: str) -> str:
    local = at.astimezone(ZoneInfo(timezone))
    hour = local.hour % 12 or 12
    suffix = "am" if local.hour < 12 else "pm"
    return f"{hour}:{local.minute:02d} {suffix}"


@router.post("", status_code=201)
async def create_match(
    body: LiveCreateIn,
    session: SessionDep,
    actor: ActorDep,
    cache: CacheDep,
) -> LiveCreatedOut:
    """Open a match and invite somebody (P8-T09)."""
    user = await _acting_user(session, actor)
    # P10-T06: the same ten-an-hour allowance the challenge invite shares.
    await check_user_limit(
        cache, key="invite:user", user_id=user.id, limit=10, window_seconds=3600
    )
    invitee = None
    if body.invitee_id is not None:
        if body.invitee_id == user.id:
            raise AppError("That is your own invite.", code="invite_own", status_code=400)
        invitee = await session.get(User, body.invitee_id)
        # Another school's learner is not a person you can invite, and is not
        # told that you tried.
        if (
            invitee is None
            or invitee.school_id != user.school_id
            or invitee.status is not UserStatus.active
        ):
            raise NotFoundError("That learner was not found.")
    row, invitation, code, link_token = await live.create(
        session,
        user=user,
        clock_ms=body.clock_ms,
        increment_ms=body.increment_ms,
        with_code=body.with_code,
        with_link=body.with_link,
        invitee=invitee,
    )
    timezone = await access.school_timezone(session, user.school_id)
    return LiveCreatedOut(
        session_id=row.id,
        game_name=live.GAME_NAME,
        invitation_id=invitation.id,
        code=code,
        formatted_code=invite_rules.format_code(code) if code else None,
        join_path=f"/games/join?t={link_token}" if link_token else None,
        expires_sentence=f"This invite stops working at {_clock(invitation.expires_at, timezone)}.",
    )


@router.post("/accept")
async def accept_match(body: LiveAcceptIn, session: SessionDep, actor: ActorDep) -> LiveStateOut:
    """Take the second seat, by inbox row, code, or link."""
    user = await _acting_user(session, actor)
    row = await live.accept(
        session,
        user=user,
        invitation_id=body.invitation_id,
        code=body.code,
        token=body.token,
    )
    return LiveStateOut(**await live.snapshot(session, row=row, user=user))


@router.get("/{session_id}")
async def read_match(session_id: uuid.UUID, session: SessionDep, actor: ActorDep) -> LiveStateOut:
    """A refreshed tab's snapshot, including clocks and whose turn it is."""
    user = await _acting_user(session, actor)
    row = await repo.get_session(session, session_id)
    if row is None:
        raise NotFoundError("That match was not found.")
    return LiveStateOut(**await live.snapshot(session, row=row, user=user))


@router.post("/{session_id}/join")
async def join_match(session_id: uuid.UUID, session: SessionDep, actor: ActorDep) -> LiveStateOut:
    """Mark this player present without a socket (the REST fallback)."""
    user = await _acting_user(session, actor)
    return LiveStateOut(**await live.join(session, user=user, session_id=session_id))


@router.post("/{session_id}/moves")
async def submit_move(
    session_id: uuid.UUID,
    body: LiveMoveIn,
    session: SessionDep,
    actor: ActorDep,
    cache: CacheDep,
) -> LiveStateOut:
    """The same call the socket makes, for a tab whose socket is down."""
    user = await _acting_user(session, actor)
    # P10-T06: the REST fallback gets the same ceiling the socket already has
    # (10 frames per 10 seconds), or it would be the way around it.
    await check_user_limit(
        cache, key="live:move", user_id=user.id, limit=60, window_seconds=60
    )
    state, _events = await live.submit(
        session,
        user=user,
        session_id=session_id,
        client_move_id=body.client_move_id,
        expected_move_number=body.expected_move_number,
        move_key=body.move,
    )
    return LiveStateOut(**state)


@router.post("/{session_id}/resign")
async def resign_match(session_id: uuid.UUID, session: SessionDep, actor: ActorDep) -> LiveStateOut:
    user = await _acting_user(session, actor)
    return LiveStateOut(**await live.resign(session, user=user, session_id=session_id))


@router.post("/{session_id}/draw/offer")
async def offer_draw(session_id: uuid.UUID, session: SessionDep, actor: ActorDep) -> LiveStateOut:
    user = await _acting_user(session, actor)
    return LiveStateOut(**await live.offer_draw(session, user=user, session_id=session_id))


@router.post("/{session_id}/draw/accept")
async def accept_draw(session_id: uuid.UUID, session: SessionDep, actor: ActorDep) -> LiveStateOut:
    user = await _acting_user(session, actor)
    return LiveStateOut(**await live.accept_draw(session, user=user, session_id=session_id))


@router.post("/{session_id}/draw/decline")
async def decline_draw(session_id: uuid.UUID, session: SessionDep, actor: ActorDep) -> LiveStateOut:
    user = await _acting_user(session, actor)
    return LiveStateOut(**await live.decline_draw(session, user=user, session_id=session_id))


@router.post("/{session_id}/rematch", status_code=201)
async def rematch(
    session_id: uuid.UUID,
    session: SessionDep,
    actor: ActorDep,
    cache: CacheDep,
) -> LiveCreatedOut:
    """A new match with the same pair, colours swapped (P8-T13)."""
    user = await _acting_user(session, actor)
    # A rematch sends an invite too, so it draws on the same hourly allowance.
    await check_user_limit(
        cache, key="invite:user", user_id=user.id, limit=10, window_seconds=3600
    )
    row, invitation, code, link_token = await live.rematch(
        session, user=user, session_id=session_id
    )
    timezone = await access.school_timezone(session, user.school_id)
    return LiveCreatedOut(
        session_id=row.id,
        game_name=live.GAME_NAME,
        invitation_id=invitation.id,
        code=code,
        formatted_code=invite_rules.format_code(code) if code else None,
        join_path=f"/games/join?t={link_token}" if link_token else None,
        expires_sentence=f"This invite stops working at {_clock(invitation.expires_at, timezone)}.",
    )


# Presence lives beside the matches it describes, but not under /live/{id}.
presence_router = APIRouter(prefix="/games", tags=["games-live"])


@presence_router.get("/presence", response_model=list[PresenceRowOut])
async def presence(session: SessionDep, actor: ActorDep, cache: CacheDep) -> list[PresenceRowOut]:
    """Classmates you may challenge, with a reason when you may not (P8-T04)."""
    user = await _acting_user(session, actor)
    rows = await live.presence(session, user=user, cache=cache)
    return [PresenceRowOut(**row) for row in rows]


@presence_router.post("/presence", status_code=204)
async def say_hello(session: SessionDep, actor: ActorDep, cache: CacheDep) -> None:
    """Say that this learner's browser is open, so the roster can show a dot.

    No body and no state kept on the server: one short-lived cache key per
    learner, which expires on its own when the tab closes.
    """
    user = await _acting_user(session, actor)
    await live.mark_online(cache, user_id=user.id)
