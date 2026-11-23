"""XP, leaderboards and the school term calendar (P5-T06, P5-T09).

Routers stay thin: every decision — which boards exist, who may read all-time,
what a learner's rank is — comes from ``services/leaderboards`` and
``services/xp``, so no endpoint can drift from the rules.
"""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy import select

from app.core.errors import AppError
from app.games.models import SchoolTerm
from app.games.schemas import (
    BoardChaseOut,
    BoardEntryOut,
    BoardOut,
    CoachBoardOut,
    EngagementOut,
    MeXpOut,
    StudentGameXpOut,
    StudentXpOut,
    TermIn,
    TermOut,
)
from app.games.services import engagement, xp
from app.games.services import leaderboards as boards
from app.identity.deps import ActorDep, SessionDep, require_roles
from app.identity.models import Role
from app.identity.service import Actor

xp_router = APIRouter(prefix="/me", tags=["xp"])
board_router = APIRouter(prefix="/leaderboards", tags=["leaderboards"])
term_router = APIRouter(prefix="/school", tags=["school"])

AdminActor = Annotated[Actor, Depends(require_roles(Role.school_admin))]
StaffActor = Annotated[Actor, Depends(require_roles(Role.coach, Role.school_admin))]


@xp_router.get("/xp")
async def my_xp(session: SessionDep, actor: ActorDep) -> MeXpOut:
    return MeXpOut.model_validate(await xp.summary(session, actor=actor))


@xp_router.get("/engagement")
async def my_engagement(session: SessionDep, actor: ActorDep) -> EngagementOut:
    """Streak, today's quest, badges, bests and the level ring — one call.

    Everything here is derived from results the server wrote; the browser has no
    way to add a day to the streak or finish a quest itself.
    """
    return EngagementOut.model_validate(await engagement.overview(session, actor=actor))


def _entry_out(row: boards.BoardEntry) -> BoardEntryOut:
    return BoardEntryOut(
        rank=row.rank,
        preferred_name=row.preferred_name,
        avatar_key=row.avatar_key,
        xp_total=row.xp_total,
        sessions_count=row.sessions_count,
        is_me=row.is_me,
    )


def _board_out(board: boards.Board) -> BoardOut:
    return BoardOut(
        period=board.period_type,
        starts_at=board.starts_at,
        ends_at=board.ends_at,
        entries=[_entry_out(row) for row in board.entries],
        me=None if board.me is None else _entry_out(board.me),
        me_eligible=board.me_eligible,
        min_sessions=board.min_sessions,
        chase=None
        if board.chase is None
        else BoardChaseOut(preferred_name=board.chase.preferred_name, xp_gap=board.chase.xp_gap),
        to_join=board.to_join,
    )


@board_router.get("/{period}")
async def read_board(
    period: str,
    session: SessionDep,
    actor: ActorDep,
    game: str | None = None,
    class_id: uuid.UUID | None = None,
    age_band: str | None = None,
) -> BoardOut:
    board = await boards.board(
        session,
        actor=actor,
        period_type=period,
        game_id=game,
        class_id=class_id,
        age_band=age_band,
    )
    return _board_out(board)


@board_router.get("/{period}/me")
async def read_my_row(
    period: str,
    session: SessionDep,
    actor: ActorDep,
    game: str | None = None,
    class_id: uuid.UUID | None = None,
    age_band: str | None = None,
) -> BoardOut:
    """The caller's own row, even when they are outside the top ten."""
    board = await boards.board(
        session,
        actor=actor,
        period_type=period,
        game_id=game,
        class_id=class_id,
        age_band=age_band,
    )
    return _board_out(board)


@board_router.get("/{period}/students")
async def read_students(
    period: str,
    session: SessionDep,
    actor: StaffActor,
    class_id: uuid.UUID | None = None,
    age_band: str | None = None,
) -> CoachBoardOut:
    """A coach's class with each learner's XP split by game (P5-T11)."""
    board = await boards.coach_breakdown(
        session, actor=actor, period_type=period, class_id=class_id, age_band=age_band
    )
    return CoachBoardOut(
        period=board.period_type,
        starts_at=board.starts_at,
        ends_at=board.ends_at,
        students=[
            StudentXpOut(
                preferred_name=student.preferred_name,
                avatar_key=student.avatar_key,
                xp_total=student.xp_total,
                sessions_count=student.sessions_count,
                games=[
                    StudentGameXpOut(
                        game_id=game.game_id,
                        xp_total=game.xp_total,
                        sessions_count=game.sessions_count,
                    )
                    for game in student.games
                ],
            )
            for student in board.students
        ],
    )


@term_router.get("/terms")
async def list_terms(session: SessionDep, actor: ActorDep) -> list[TermOut]:
    rows = (
        (
            await session.execute(
                select(SchoolTerm)
                .where(SchoolTerm.school_id == actor.school_id)
                .order_by(SchoolTerm.starts_on.desc())
            )
        )
        .scalars()
        .all()
    )
    return [
        TermOut(id=row.id, name=row.name, starts_on=row.starts_on, ends_on=row.ends_on)
        for row in rows
    ]


@term_router.post("/terms", status_code=201)
async def add_term(body: TermIn, session: SessionDep, actor: AdminActor) -> TermOut:
    """Term dates are the school admin's to set; the termly board needs them."""
    if body.ends_on <= body.starts_on:
        raise AppError("The last day must be after the first day.", code="term_invalid")
    term = SchoolTerm(
        school_id=actor.school_id,
        name=body.name.strip(),
        starts_on=body.starts_on,
        ends_on=body.ends_on,
    )
    session.add(term)
    await session.commit()
    return TermOut(id=term.id, name=term.name, starts_on=term.starts_on, ends_on=term.ends_on)
