"""WebSocket gateway and the single-use ticket that opens it (P8-T01, T02, T05).

**The ticket, not the cookie.** ``POST /api/ws/ticket`` is an ordinary
authenticated REST call; it returns 32 random bytes that work once, for thirty
seconds, for one user and one match (``CacheClient.set_nx``). The socket then
carries the ticket and nothing else, which is why it does not have to be
same-origin, and why a ticket copied out of a log is already dead.

**Tickets are not bound to an IP.** A school NAT, or a phone switching from wifi
to mobile mid-lesson, would otherwise drop a legitimate player (P8-T01).

**One rule, one place.** Every decision lives in ``services.live``; this file
parses, authorises, calls, replies (P8-T02, T03). A "poke" event means "your
snapshot is stale" and each socket rebuilds *its own* — so one player's legal
moves never end up on the other player's screen.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import secrets
import uuid
from typing import Any

from fastapi import APIRouter, Request, WebSocket, WebSocketDisconnect
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.cache import CacheClient
from app.core.db import get_sessionmaker
from app.core.errors import AppError, NotFoundError, UnauthorizedError
from app.core.logging import get_logger
from app.core.origin import allowed_origins
from app.core.rate_limit import get_cache
from app.games import repository as repo
from app.games.schemas import TicketIn, TicketOut
from app.games.services import hub, live
from app.games.services import sessions as lifecycle
from app.identity.deps import ActorDep, SessionDep
from app.identity.models import User, UserStatus
from app.identity.service import Actor

log = get_logger(__name__)

# Two routers on purpose: tickets are an ordinary API call under /api, while
# the socket must live at /ws so the reverse proxy can upgrade it.
router = APIRouter(prefix="/ws", tags=["realtime"])
socket_router = APIRouter(tags=["realtime"])

TICKET_TTL_SECONDS = 30
PRESENCE_TTL_SECONDS = 45
MAX_MESSAGES_PER_SECOND = 10
MAX_MESSAGES_PER_TEN_SECONDS = 50
CLOSE_UNAUTHORISED = 4401
CLOSE_TOO_BIG = 4400

CLIENT_MESSAGES = {
    "match.join",
    "move.submit",
    "match.resign",
    "draw.offer",
    "draw.accept",
    "draw.decline",
    "ping",
}


def ticket_key(ticket: str) -> str:
    """Only the hash is stored: the cache never holds a usable ticket."""
    return f"ws:ticket:{hashlib.sha256(ticket.encode()).hexdigest()}"


async def issue_ticket(cache: CacheClient, *, user_id: uuid.UUID, session_id: uuid.UUID) -> str:
    ticket = secrets.token_urlsafe(32)
    stored = await cache.set_nx(
        ticket_key(ticket),
        json.dumps({"user_id": str(user_id), "session_id": str(session_id)}),
        TICKET_TTL_SECONDS,
    )
    if not stored:  # pragma: no cover - a 32-byte collision is not a real case
        raise AppError("Please try again.", code="ticket_failed", status_code=503)
    return ticket


async def consume_ticket(cache: CacheClient, ticket: str) -> tuple[uuid.UUID, uuid.UUID] | None:
    """Read and delete together: a ticket is good for one handshake."""
    key = ticket_key(ticket)
    raw = await cache.get(key)
    await cache.delete(key)
    if raw is None:
        return None
    try:
        data = json.loads(raw)
        return uuid.UUID(data["user_id"]), uuid.UUID(data["session_id"])
    except (KeyError, ValueError):
        return None


async def _acting_user(session: AsyncSession, actor: Actor) -> User:
    user = await session.get(User, actor.id)
    if user is None:  # pragma: no cover - the token already proved they exist
        raise UnauthorizedError("Please sign in again.")
    return user


@router.post("/ticket", status_code=201)
async def create_ticket(
    body: TicketIn,
    request: Request,
    session: SessionDep,
    actor: ActorDep,
) -> TicketOut:
    """One socket, one match, thirty seconds (P8-T01)."""
    user = await _acting_user(session, actor)
    row = await repo.get_session(session, body.session_id)
    if row is None or row.mode != "live" or row.school_id != user.school_id:
        raise NotFoundError("That match was not found.")
    if await repo.get_participant(session, row.id, user.id) is None:
        raise NotFoundError("That match was not found.")

    ticket = await issue_ticket(get_cache(request), user_id=user.id, session_id=row.id)
    return TicketOut(ticket=ticket, expires_in=TICKET_TTL_SECONDS)


# ------------------------------------------------------------------ the socket
@socket_router.websocket("/ws/games")
async def games_socket(websocket: WebSocket, ticket: str | None = None) -> None:
    if origin_refused(websocket) or not ticket:
        await websocket.close(code=CLOSE_UNAUTHORISED)
        return

    cache: CacheClient = websocket.app.state.cache
    consumed = await consume_ticket(cache, ticket)
    if consumed is None:
        await websocket.close(code=CLOSE_UNAUTHORISED)
        return
    user_id, session_id = consumed

    maker = get_sessionmaker()
    async with maker() as session:
        user = await session.get(User, user_id)
        row = await repo.get_session(session, session_id)
        authorised = (
            user is not None
            and user.status is UserStatus.active
            and row is not None
            and row.mode == "live"
            and row.school_id == user.school_id
            and await repo.get_participant(session, row.id, user.id) is not None
        )
        if not authorised or user is None or row is None:
            await websocket.close(code=CLOSE_UNAUTHORISED)
            return

        await websocket.accept()
        connection = hub.Connection(user_id=user.id, session_id=row.id, conn_id=uuid.uuid4().hex)
        replaced = hub.HUB.register(connection)
        if replaced is not None:
            log.info("ws.replaced", extra={"user_id": str(user.id)})

        await _touch_presence(cache, user.id, "in_match", row.id)
        await live.join(session, user=user, session_id=row.id)
        snapshot = await live.snapshot(session, row=row, user=user)
        await _send(websocket, {"type": "match.state", **snapshot})
        await hub.publish(cache, row.id, {"type": "poke"})

    seq = {"n": 1}
    tasks: set[asyncio.Task[None]] = set()
    try:
        tasks = {
            asyncio.create_task(
                _receive(websocket, cache=cache, user_id=user_id, session_id=session_id)
            ),
            asyncio.create_task(
                _pump(
                    websocket,
                    cache=cache,
                    user_id=user_id,
                    session_id=session_id,
                    seq=seq,
                )
            ),
        }
        done, _pending = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
        for task in done:
            exception = task.exception()
            if exception is not None and not isinstance(exception, WebSocketDisconnect):
                log.info("ws.task_error", extra={"route": str(exception)[:120]})
    finally:
        # The other half stops with the first: a socket killed mid-send leaves
        # the surviving task blocked on a frame that will never come, and its
        # exception would otherwise be logged as "never retrieved" — noise that
        # hides a real failure in the same log.
        for task in tasks:
            if not task.done():
                task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
        hub.HUB.forget(connection.conn_id)
        hub.HUB.forget(connection.conn_id)
        # A reconnect registers the new socket before the old one finishes
        # closing, and React's development double-mount does the same. Leaving
        # unconditionally then marked a player "away" while their new socket
        # was already open, so the match sat in `ready` forever and the clocks
        # never started. Only the last socket out marks you away.
        still_here = any(conn.user_id == user_id for conn in hub.HUB.connections(session_id))
        if not still_here:
            async with maker() as closing:
                closing_user = await closing.get(User, user_id)
                closing_row = await repo.get_session(closing, session_id)
                if closing_user is not None and closing_row is not None:
                    await live.leave(closing, user=closing_user, session_id=session_id)
            await _touch_presence(cache, user_id, "available", None)
        await hub.publish(cache, session_id, {"type": "poke"})
        log.info("ws.closed", extra={"user_id": str(user_id), "session_id": str(session_id)})


async def _send(websocket: WebSocket, event: dict[str, Any]) -> bool:
    """One frame, or False when the peer has already gone.

    A client that dies mid-frame is normal on a school network. Starlette raises
    rather than returning, so a send is guarded here instead of at each of the
    dozen call sites; the pump then exits on its own next frame.
    """
    try:
        await websocket.send_text(json.dumps(hub.frame(event), separators=(",", ":")))
        return True
    except (WebSocketDisconnect, RuntimeError):
        return False


async def _pump(
    websocket: WebSocket,
    *,
    cache: CacheClient,
    user_id: uuid.UUID,
    session_id: uuid.UUID,
    seq: dict[str, int],
) -> None:
    """Everything published for this match, tailored to this player."""
    maker = get_sessionmaker()
    async for raw in cache.subscribe(hub.channel_for(session_id)):
        try:
            event = json.loads(raw)
        except ValueError:  # pragma: no cover - we publish our own JSON only
            continue
        if event.get("type") != "poke":
            await _send(websocket, {**event, "seq": seq["n"]})
            seq["n"] += 1
            continue

        async with maker() as session:
            row = await repo.get_session(session, session_id)
            user = await session.get(User, user_id)
            if row is None or user is None:
                return
            try:
                snapshot = await live.snapshot(session, row=row, user=user)
            except NotFoundError:
                return
        await _send(websocket, {"type": "match.state", **snapshot, "seq": seq["n"]})
        seq["n"] += 1


async def _receive(
    websocket: WebSocket, *, cache: CacheClient, user_id: uuid.UUID, session_id: uuid.UUID
) -> None:
    """Client intents. Each one is a call into the service, nothing more."""
    maker = get_sessionmaker()
    while True:
        raw = await websocket.receive_text()
        if len(raw.encode()) > hub.MAX_MESSAGE_BYTES:
            await websocket.send_text(
                json.dumps({"type": "error", "v": 1, "code": "message_too_large"})
            )
            await websocket.close(code=CLOSE_TOO_BIG)
            return

        try:
            message = json.loads(raw)
        except ValueError:
            await _send(websocket, {"type": "error", "code": "bad_message"})
            continue
        if not isinstance(message, dict) or message.get("type") not in CLIENT_MESSAGES:
            await _send(websocket, {"type": "error", "code": "unknown_type"})
            continue

        kind = message["type"]
        if not await _within_rate(cache, user_id):
            await _send(websocket, {"type": "error", "code": "rate_limited"})
            continue

        async with maker() as session:
            user = await session.get(User, user_id)
            row = await repo.get_session(session, session_id)
            if user is None or row is None:
                await websocket.close(code=CLOSE_UNAUTHORISED)
                return

            try:
                if kind == "ping":
                    await _touch_presence(cache, user.id, "in_match", session_id)
                    await lifecycle.record_action(session, user=user, session_id=session_id)
                    snapshot = await live.snapshot(session, row=row, user=user)
                    await _send(
                        websocket,
                        {
                            "type": "clock.sync",
                            "clock_ms": snapshot["clock_ms"],
                            "move_number": snapshot["move_number"],
                            "status": snapshot["status"],
                        },
                    )
                elif kind == "match.join":
                    await live.join(session, user=user, session_id=session_id)
                    await hub.publish(cache, session_id, {"type": "poke"})
                elif kind == "move.submit":
                    snapshot, events = await live.submit(
                        session,
                        user=user,
                        session_id=session_id,
                        client_move_id=str(message.get("client_move_id") or ""),
                        expected_move_number=int(message.get("expected_move_number") or 0),
                        move_key=str(message.get("move") or ""),
                    )
                    await _send(websocket, {"type": "match.state", **snapshot})
                    for event in events:
                        await hub.publish(cache, session_id, event)
                    await hub.publish(cache, session_id, {"type": "poke"})
                elif kind == "match.resign":
                    snapshot = await live.resign(session, user=user, session_id=session_id)
                    await _send(websocket, {"type": "match.state", **snapshot})
                    await hub.publish(cache, session_id, {"type": "poke"})
                elif kind == "draw.offer":
                    snapshot = await live.offer_draw(session, user=user, session_id=session_id)
                    await _send(websocket, {"type": "match.state", **snapshot})
                    await hub.publish(cache, session_id, {"type": "poke"})
                elif kind == "draw.accept":
                    snapshot = await live.accept_draw(session, user=user, session_id=session_id)
                    await _send(websocket, {"type": "match.state", **snapshot})
                    await hub.publish(cache, session_id, {"type": "poke"})
                elif kind == "draw.decline":
                    snapshot = await live.decline_draw(session, user=user, session_id=session_id)
                    await _send(websocket, {"type": "match.state", **snapshot})
                    await hub.publish(cache, session_id, {"type": "poke"})
            except AppError as refused:
                await _send(
                    websocket,
                    {
                        "type": "move.rejected" if kind == "move.submit" else "error",
                        "code": refused.code,
                        "message": refused.message,
                    },
                )


async def _within_rate(cache: CacheClient, user_id: uuid.UUID) -> bool:
    per_second = await cache.incr_window(f"ws:msg:1s:{user_id}", 1)
    if per_second > MAX_MESSAGES_PER_SECOND:
        return False
    return await cache.incr_window(f"ws:msg:10s:{user_id}", 10) <= MAX_MESSAGES_PER_TEN_SECONDS


async def _touch_presence(
    cache: CacheClient, user_id: uuid.UUID, status: str, session_id: uuid.UUID | None
) -> None:
    """P8-T04: 45 s keys, refreshed by ping. Never a second REST heartbeat."""
    await cache.set(
        f"presence:{user_id}",
        json.dumps({"status": status, "session_id": str(session_id) if session_id else None}),
        PRESENCE_TTL_SECONDS,
    )


def origin_refused(websocket: WebSocket) -> bool:
    """Refuse a handshake from a page this app did not serve (P8-T01).

    The ticket proves who you are; this stops a page on another origin from
    driving a school laptop it did not load. A browser always sends Origin on a
    WebSocket handshake, so a missing one is treated as a refusal.
    """
    origin = websocket.headers.get("origin")
    if not origin:
        return True
    settings = getattr(websocket.app.state, "settings", None)
    if settings is None:
        return True
    # The same list the REST check uses, so the two can never drift apart.
    return origin.rstrip("/") not in allowed_origins(settings)
