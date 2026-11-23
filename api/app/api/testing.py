"""Test-only helpers (P1-T09).

The Learning XP ledger is owned by the host platform in production, so there is
no real write path here yet. This route exists so integration tests can give a
learner some Learning XP and prove that Profile XP later combines the two
ledgers without one contaminating the other.

It is **disabled outside dev/test** and answers 404 there, exactly like a route
that was never written — no hint that a stub exists.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends

from app.identity.deps import SessionDep, SettingsDep, require_roles
from app.identity.models import Role
from app.identity.schemas import LearningXpIn
from app.identity.service import Actor, record_learning_xp, require_same_school_user

router = APIRouter(prefix="/testing", tags=["testing"])


async def _dev_only(settings: SettingsDep) -> None:
    if settings.is_production:
        from app.core.errors import NotFoundError

        raise NotFoundError("Not found.")


DevOnly = Annotated[None, Depends(_dev_only)]
StaffActor = Annotated[Actor, Depends(require_roles(Role.school_admin, Role.coach))]


@router.post("/learning-xp")
async def seed_learning_xp(
    payload: LearningXpIn,
    session: SessionDep,
    _dev: DevOnly,
    actor: StaffActor,
) -> dict[str, object]:
    await require_same_school_user(session, actor=actor, user_id=payload.user_id)
    entry = await record_learning_xp(
        session, user_id=payload.user_id, amount=payload.amount, reason=payload.reason
    )
    return {"status": "ok", "id": entry.id}
