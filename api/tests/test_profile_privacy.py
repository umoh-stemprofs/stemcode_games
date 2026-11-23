"""The privacy gate (P1-T05, Phase 1 DoD).

Two layers, because one is easy to bypass:

1. **Schema scan** — every schema a learner can receive about another person is
   inspected by name. Adding ``real_name`` to one of them fails here, before
   anyone ships it.
2. **Response scan** — the actual JSON, so a hand-built dict cannot slip past
   the schema list.
"""

from __future__ import annotations

import inspect

from app.identity.schemas import (
    FORBIDDEN_PUBLIC_FIELDS,
    LEARNER_FACING_MODELS,
)
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from tests.factories import build_world, login


def test_learner_facing_schemas_carry_no_sensitive_fields() -> None:
    offenders: dict[str, set[str]] = {}
    for model in LEARNER_FACING_MODELS:
        leaked = set(model.model_fields) & FORBIDDEN_PUBLIC_FIELDS
        if leaked:
            offenders[model.__name__] = leaked
    assert offenders == {}, f"sensitive fields in learner-facing schemas: {offenders}"


def test_every_public_schema_is_registered() -> None:
    """A ``Public*`` schema that is not in the scan list is a silent hole."""
    import app.identity.schemas as schemas

    registered = set(LEARNER_FACING_MODELS)
    unregistered = [
        obj
        for name, obj in inspect.getmembers(schemas, inspect.isclass)
        if issubclass(obj, BaseModel)
        and obj.__module__ == schemas.__name__
        and name.startswith("Public")
        and obj not in registered
    ]
    assert unregistered == [], f"register these in LEARNER_FACING_MODELS: {unregistered}"


async def test_profile_response_has_only_public_keys(client, db_session: AsyncSession) -> None:
    world = await build_world(db_session)
    await login(client, world.learner_a)

    body = (await client.get(f"/api/profiles/{world.learner_a2.id}/public")).json()
    assert set(body) == {"id", "preferred_name", "avatar_key"}


async def test_roster_response_has_only_public_keys(client, db_session: AsyncSession) -> None:
    world = await build_world(db_session)
    await login(client, world.learner_a)

    body = (await client.get(f"/api/classes/{world.class_a.id}/members")).json()
    allowed = {"id", "preferred_name", "avatar_key"}
    for member in body["members"]:
        assert set(member) <= allowed


async def test_no_learner_facing_response_mentions_a_real_name(
    client, db_session: AsyncSession
) -> None:
    world = await build_world(db_session)
    await login(client, world.learner_a)

    real_names = [
        world.learner_a.real_name,
        world.learner_a2.real_name,
        world.coach_a.real_name,
    ]
    for path in (
        "/api/classes",
        f"/api/classes/{world.class_a.id}/members",
        f"/api/profiles/{world.learner_a2.id}/public",
        f"/api/profiles/{world.coach_a.id}/public",
    ):
        text = (await client.get(path)).text
        for name in real_names:
            assert name not in text, f"{name} leaked from {path}"
