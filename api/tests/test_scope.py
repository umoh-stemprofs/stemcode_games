"""School and class isolation (Phase 1 DoD, P1-T03).

The rule under test: a resource in another school is *not found*, never
*forbidden* — a 403 would confirm that the id exists somewhere.
"""

from __future__ import annotations

import uuid

from app.identity.models import Role
from sqlalchemy.ext.asyncio import AsyncSession

from tests.factories import build_world, login, make_class, make_school, make_user


async def test_learner_cannot_read_a_profile_from_another_school(
    client, db_session: AsyncSession
) -> None:
    world = await build_world(db_session)
    await login(client, world.learner_a)

    response = await client.get(f"/api/profiles/{world.learner_b.id}/public")

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "not_found"
    # Nothing about the other learner leaks, not even their existence.
    assert "Beta" not in response.text


async def test_learner_cannot_read_another_schools_class(client, db_session: AsyncSession) -> None:
    world = await build_world(db_session)
    await login(client, world.learner_a)

    response = await client.get(f"/api/classes/{world.class_b.id}/members")

    assert response.status_code == 404


async def test_coach_cannot_read_a_class_they_are_not_assigned_to(
    client, db_session: AsyncSession
) -> None:
    world = await build_world(db_session)
    await login(client, world.coach_a)

    allowed = await client.get(f"/api/classes/{world.class_a.id}/members")
    assert allowed.status_code == 200

    # class_unassigned is in the same school, but this coach does not own it.
    denied = await client.get(f"/api/classes/{world.class_unassigned.id}/members")
    assert denied.status_code == 404


async def test_class_list_is_scoped_for_every_role(client, db_session: AsyncSession) -> None:
    world = await build_world(db_session)

    await login(client, world.learner_a)
    learner_classes = await client.get("/api/classes")
    assert [c["name"] for c in learner_classes.json()] == ["Year 5A"]
    await client.post("/api/auth/logout")

    await login(client, world.coach_a)
    coach_classes = await client.get("/api/classes")
    assert [c["name"] for c in coach_classes.json()] == ["Year 5A"]
    await client.post("/api/auth/logout")

    await login(client, world.admin_a)
    admin_classes = await client.get("/api/classes")
    assert sorted(c["name"] for c in admin_classes.json()) == ["Year 5A", "Year 6A"]


async def test_learner_roster_has_no_real_names(client, db_session: AsyncSession) -> None:
    world = await build_world(db_session)
    await login(client, world.learner_a)

    response = await client.get(f"/api/classes/{world.class_a.id}/members")
    assert response.status_code == 200

    body = response.json()
    assert len(body["members"]) == 2
    for member in body["members"]:
        assert set(member) == {"id", "preferred_name", "avatar_key"}
    assert "Amara Okoro" not in response.text
    assert "Bayo Ade" not in response.text


async def test_public_profile_exposes_only_two_fields(client, db_session: AsyncSession) -> None:
    world = await build_world(db_session)
    await login(client, world.learner_a)

    response = await client.get(f"/api/profiles/{world.learner_a2.id}/public")
    assert response.status_code == 200
    assert response.json() == {
        "id": str(world.learner_a2.id),
        "preferred_name": "Bayo",
        "avatar_key": "panda",
    }


async def test_unknown_profile_is_the_same_404_as_a_foreign_one(
    client, db_session: AsyncSession
) -> None:
    world = await build_world(db_session)
    await login(client, world.learner_a)

    missing = await client.get(f"/api/profiles/{uuid.uuid4()}/public")
    foreign = await client.get(f"/api/profiles/{world.learner_b.id}/public")

    assert missing.status_code == foreign.status_code == 404
    # Same code and sentence: the body must not tell the two apart.
    assert missing.json()["error"]["code"] == foreign.json()["error"]["code"]
    assert missing.json()["error"]["message"] == foreign.json()["error"]["message"]


async def test_a_coach_from_another_school_cannot_read_the_roster(
    client, db_session: AsyncSession
) -> None:
    world = await build_world(db_session)
    await login(client, world.coach_b)

    response = await client.get(f"/api/classes/{world.class_a.id}/members")
    assert response.status_code == 404


async def test_admins_are_scoped_to_their_own_school(client, db_session: AsyncSession) -> None:
    world = await build_world(db_session)
    extra = await make_class(db_session, school=world.school_b, name="Beta Only")
    await login(client, world.admin_a)

    response = await client.get(f"/api/classes/{extra.id}/members")
    assert response.status_code == 404


async def test_testing_endpoint_is_scoped_to_the_callers_school(
    client, db_session: AsyncSession
) -> None:
    world = await build_world(db_session)
    await login(client, world.admin_a)

    ok = await client.post(
        "/api/testing/learning-xp",
        json={"user_id": str(world.learner_a.id), "amount": 10, "reason": "lesson"},
    )
    assert ok.status_code == 200

    foreign = await client.post(
        "/api/testing/learning-xp",
        json={"user_id": str(world.learner_b.id), "amount": 10, "reason": "lesson"},
    )
    assert foreign.status_code == 404


async def test_learner_cannot_use_the_testing_endpoint(client, db_session: AsyncSession) -> None:
    world = await build_world(db_session)
    await login(client, world.learner_a)

    response = await client.post(
        "/api/testing/learning-xp",
        json={"user_id": str(world.learner_a.id), "amount": 10, "reason": "lesson"},
    )
    assert response.status_code == 403


async def test_new_endpoints_start_locked(client, db_session: AsyncSession) -> None:
    """A guard exists even where no data does: no cookie, no access."""
    school = await make_school(db_session, "Empty School")
    await make_user(db_session, school=school, role=Role.school_admin, code="EMPTY-ADMIN")

    for path in ("/api/auth/me", "/api/classes", f"/api/profiles/{uuid.uuid4()}/public"):
        response = await client.get(path)
        assert response.status_code == 401, path
