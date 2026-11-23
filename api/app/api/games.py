"""Games access, play-time and lockout endpoints (P3-T04, P3-T06, P3-T09).

Routers stay thin: parse, authorise, call a service, return. Every decision —
the limit, the lockout, whether another tab is open, when the day resets —
comes from ``app.games.services.access``, so no endpoint can drift from it.
"""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import UnauthorizedError
from app.games import repository as repo
from app.games.schemas import (
    AccessOut,
    ActionIn,
    ActiveSessionOut,
    ClassAccessOut,
    CreateSessionIn,
    GameSummaryOut,
    HeartbeatIn,
    LockoutIn,
    LockoutOut,
    MemberAccessOut,
    OfflineItemOut,
    OfflinePackOut,
    PlayOut,
    PlayStateOut,
    PolicyIn,
    PolicyOut,
)
from app.games.services import access, engagement, offline, play, sessions
from app.identity.deps import ActorDep, SessionDep, require_roles
from app.identity.models import Role, User
from app.identity.service import Actor, visible_class

router = APIRouter(prefix="/games", tags=["games"])

StaffActor = Annotated[Actor, Depends(require_roles(Role.coach, Role.school_admin))]


async def _acting_user(session: AsyncSession, actor: Actor) -> User:
    user = await session.get(User, actor.id)
    if user is None:  # pragma: no cover - the token already proved they exist
        raise UnauthorizedError("Please sign in again.")
    return user


async def _access_out(session: AsyncSession, user: User) -> AccessOut:
    state = await access.access_for(session, user=user)
    return AccessOut.model_validate(state)


async def _play_out(
    session: AsyncSession, user: User, state: object
) -> PlayOut:
    """A play view, plus the personal best once the game has ended.

    Kept in the router because it is presentation: the service that finished the
    game already wrote the result the comparison is made from.
    """
    out = PlayOut.model_validate(state)
    if out.finished:
        best = await engagement.best_for_finished(
            session, user_id=user.id, session_id=out.session_id, game_id=out.game_id
        )
        if best is not None:
            out.best, out.best_is_new = best
    return out


@router.get("/access")
async def get_access(session: SessionDep, actor: ActorDep) -> AccessOut:
    """The one call the hub needs: may I play, how long is left, when does it reset."""
    return await _access_out(session, await _acting_user(session, actor))


@router.post("/sessions/{session_id}/start")
async def start_session(session_id: uuid.UUID, session: SessionDep, actor: ActorDep) -> AccessOut:
    user = await _acting_user(session, actor)
    state = await sessions.start_play(session, user=user, session_id=session_id)
    return AccessOut.model_validate(state)


@router.post("/sessions/{session_id}/heartbeat")
async def heartbeat(
    session_id: uuid.UUID,
    body: HeartbeatIn,
    session: SessionDep,
    actor: ActorDep,
) -> PlayStateOut:
    user = await _acting_user(session, actor)
    state = await sessions.heartbeat(
        session, user=user, session_id=session_id, visible=body.visible
    )
    return PlayStateOut.model_validate(state)


@router.post("/sessions/{session_id}/pause", status_code=204)
async def pause_session(session_id: uuid.UUID, session: SessionDep, actor: ActorDep) -> None:
    user = await _acting_user(session, actor)
    await sessions.pause(session, user=user, session_id=session_id)


@router.post("/sessions/{session_id}/quit", status_code=204)
async def quit_session(session_id: uuid.UUID, session: SessionDep, actor: ActorDep) -> None:
    """End a game for good. The learner keeps no result and loses no seat.

    One call covers every game mode: a solo attempt, a challenge turn, and —
    from Phase 8 — a live match, where ending the session is also what tells
    the other end to close its socket.
    """
    user = await _acting_user(session, actor)
    await sessions.quit(session, user=user, session_id=session_id)


@router.get("/classes/{class_id}/access")
async def class_access(
    class_id: uuid.UUID, session: SessionDep, actor: StaffActor
) -> ClassAccessOut:
    """The coach's table: every learner, the time they have, any pause on them."""
    klass = await visible_class(session, actor=actor, class_id=class_id)
    rows = await access.class_access_table(session, actor=actor, class_id=class_id)
    return ClassAccessOut(
        class_id=klass.id,
        class_name=klass.name,
        members=[MemberAccessOut.model_validate(row) for row in rows],
    )


@router.get("/offline/packs")
async def offline_pack(
    session: SessionDep,
    actor: ActorDep,
    game: Annotated[str, Query(min_length=1, max_length=40)],
    difficulty: Annotated[int, Query(ge=1, le=3)] = 1,
) -> OfflinePackOut:
    """One level of words this learner may play with no connection (P9-T02).

    The learner is the scope: the band comes from their birthday, so a client
    cannot ask for a younger child's words. What comes back is content only.
    """
    pack = await offline.pack_for(
        session,
        user=await _acting_user(session, actor),
        game_id=game,
        difficulty=difficulty,
    )
    return OfflinePackOut(
        game_id=pack.game_id,
        locale=pack.locale,
        age_band=pack.age_band,
        difficulty=pack.difficulty,
        pack_version=pack.pack_version,
        item_count=pack.item_count,
        generated_at=pack.generated_at,
        items=[
            OfflineItemOut(
                id=item.id,
                answer=item.answer,
                alt_answers=list(item.alt_answers),
                clue=item.clue,
                clue_image_key=item.clue_image_key,
                clue_audio_key=item.clue_audio_key,
                difficulty=item.difficulty,
            )
            for item in pack.items
        ],
    )


@router.get("/catalog")
async def catalog(session: SessionDep, actor: ActorDep) -> list[GameSummaryOut]:
    """Games a learner may open. Disabled games are not listed at all."""
    rows = await repo.list_games(session, enabled_only=True)
    return [
        GameSummaryOut(id=row.id, name=row.name, summary=row.summary, is_live=row.is_live)
        for row in rows
    ]


@router.get("/sessions/active")
async def active_session(session: SessionDep, actor: ActorDep) -> ActiveSessionOut:
    """The session a refreshed tab should return to, if there is one."""
    user = await _acting_user(session, actor)
    row = await repo.active_session_for_user(session, user.id)
    if row is None:
        return ActiveSessionOut()
    return ActiveSessionOut(session_id=row.id, game_id=row.game_id)


# ---------------------------------------------------------------- word scramble
@router.post("/{game_id}/sessions", status_code=201)
async def create_session(
    game_id: str, body: CreateSessionIn, session: SessionDep, actor: ActorDep
) -> PlayOut:
    """Open a session and start its clock. Refuses if one is already open.

    Generic by design: Phase 6 and Phase 8 add games to the registry, not
    endpoints to this file.
    """
    from app.core.errors import NotFoundError
    from app.games.registry import HANDLERS

    if game_id not in HANDLERS:
        raise NotFoundError("That game was not found.")
    user = await _acting_user(session, actor)
    row = await play.create_solo(session, user=user, game_id=game_id, difficulty=body.difficulty)
    state = await play.get_state(session, user=user, session_id=row.id)
    return await _play_out(session, user, state)


@router.get("/sessions/{session_id}")
async def read_session(session_id: uuid.UUID, session: SessionDep, actor: ActorDep) -> PlayOut:
    """State for a refreshed tab, including the time left this instant."""
    user = await _acting_user(session, actor)
    state = await play.get_state(session, user=user, session_id=session_id)
    return await _play_out(session, user, state)


@router.post("/sessions/{session_id}/actions")
async def submit_action(
    session_id: uuid.UUID,
    body: ActionIn,
    session: SessionDep,
    actor: ActorDep,
) -> PlayOut:
    """One move. A repeated ``client_move_id`` returns the same state."""
    user = await _acting_user(session, actor)
    state = await play.submit_action(
        session,
        user=user,
        session_id=session_id,
        client_move_id=body.client_move_id,
        action=body.type,
        value=body.value,
    )
    return await _play_out(session, user, state)


# ------------------------------------------------------------------- limits
@router.get("/limits")
async def list_limits(session: SessionDep, actor: StaffActor) -> list[PolicyOut]:
    rows = await access.list_policies(session, actor=actor)
    return [PolicyOut.model_validate(row) for row in rows]


@router.post("/limits", status_code=201)
async def set_limit(body: PolicyIn, session: SessionDep, actor: StaffActor) -> PolicyOut:
    row = await access.set_limit(
        session,
        actor=actor,
        change=access.PolicyChange(
            scope_type=body.scope_type,
            scope_id=body.scope_id,
            daily_limit_minutes=body.daily_limit_minutes,
            reason=body.reason,
            valid_until=body.valid_until,
        ),
    )
    return PolicyOut.model_validate(row)


# ------------------------------------------------------------------ lockouts
@router.get("/lockouts")
async def list_lockouts(session: SessionDep, actor: StaffActor) -> list[LockoutOut]:
    rows = await access.list_lockouts(session, actor=actor)
    return [LockoutOut.model_validate(row) for row in rows]


@router.post("/lockouts", status_code=201)
async def create_lockout(body: LockoutIn, session: SessionDep, actor: StaffActor) -> LockoutOut:
    row = await access.lock_out(
        session,
        actor=actor,
        scope_type=body.scope_type,
        scope_id=body.scope_id,
        reason=body.reason,
        expires_at=body.expires_at,
    )
    return LockoutOut.model_validate(row)


@router.post("/lockouts/{lockout_id}/revoke")
async def revoke_lockout(
    lockout_id: uuid.UUID, session: SessionDep, actor: StaffActor
) -> LockoutOut:
    row = await access.revoke_lockout(session, actor=actor, lockout_id=lockout_id)
    return LockoutOut.model_validate(row)
