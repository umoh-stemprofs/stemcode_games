"""Public profile projection (P1-T05).

The only endpoint through which one learner can ever see another. It returns
``PublicProfile`` — preferred name and avatar — and nothing else, by
construction: the schema has no other fields to leak.

Someone in another school is a 404, not a 403 (Phase 1 DoD).
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter

from app.identity.deps import ActorDep, SessionDep
from app.identity.schemas import PublicProfile
from app.identity.service import require_same_school_user

router = APIRouter(prefix="/profiles", tags=["profiles"])


@router.get("/{user_id}/public")
async def public_profile(
    user_id: uuid.UUID,
    session: SessionDep,
    actor: ActorDep,
) -> PublicProfile:
    user = await require_same_school_user(session, actor=actor, user_id=user_id)
    return PublicProfile(id=user.id, preferred_name=user.preferred_name, avatar_key=user.avatar_key)
