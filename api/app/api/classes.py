"""Class and roster read endpoints (P1-T03 scopes).

Two rules, both enforced in the service layer:

- a class outside the caller's school is a 404;
- a coach sees only classes assigned to them, and a learner only classes they
  belong to.

Rosters are returned as public projections, so a learner never receives a
classmate's real name even though the roster is the same endpoint a coach uses.
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter

from app.identity.deps import ActorDep, SessionDep
from app.identity.schemas import ClassMembersOut, ClassOut, PublicProfile
from app.identity.service import class_members, visible_class, visible_classes

router = APIRouter(prefix="/classes", tags=["classes"])


@router.get("")
async def list_classes(session: SessionDep, actor: ActorDep) -> list[ClassOut]:
    classes = await visible_classes(session, actor=actor)
    return [ClassOut(id=c.id, name=c.name, grade=c.grade) for c in classes]


@router.get("/{class_id}/members")
async def list_members(
    class_id: uuid.UUID,
    session: SessionDep,
    actor: ActorDep,
) -> ClassMembersOut:
    klass = await visible_class(session, actor=actor, class_id=class_id)
    members = await class_members(session, actor=actor, class_id=class_id)
    return ClassMembersOut.model_validate(
        {
            "class": ClassOut(id=klass.id, name=klass.name, grade=klass.grade),
            "members": [
                PublicProfile(id=m.id, preferred_name=m.preferred_name, avatar_key=m.avatar_key)
                for m in members
            ],
        }
    )
