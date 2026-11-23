"""Login, rotation, logout, and lockout (P1-T02, D-19)."""

from __future__ import annotations

import datetime as dt

from app.identity.models import AuthSession, Role, User, UserStatus
from app.identity.security import (
    ACCESS_COOKIE,
    REFRESH_COOKIE,
    hash_refresh_token,
    verify_secret,
)
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from tests.factories import PIN, build_world, login, make_school, make_user


async def test_login_sets_httponly_cookies_and_returns_self(
    client, db_session: AsyncSession
) -> None:
    world = await build_world(db_session)

    response = await login(client, world.learner_a)

    assert response.status_code == 200
    body = response.json()
    assert body["user"]["preferred_name"] == "Amara"
    assert body["user"]["role"] == "learner"
    # The caller may see their own real name; nobody else may.
    assert body["user"]["real_name"] == "Amara Okoro"
    assert body["school"]["timezone"] == "Africa/Lagos"

    cookies = response.headers.get_list("set-cookie")
    access = next(c for c in cookies if c.startswith(ACCESS_COOKIE))
    refresh = next(c for c in cookies if c.startswith(REFRESH_COOKIE))
    assert "HttpOnly" in access and "HttpOnly" in refresh
    assert "SameSite=lax" in access.replace("samesite", "SameSite")

    # No token is ever put in the JSON body.
    assert "access_token" not in response.text
    assert "refresh_token" not in response.text


async def test_me_requires_a_session(client) -> None:
    response = await client.get("/api/auth/me")
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "unauthenticated"


async def test_wrong_pin_and_unknown_code_look_identical(client, db_session: AsyncSession) -> None:
    world = await build_world(db_session)

    wrong = await login(client, world.learner_a, pin="0000")
    unknown = await client.post(
        "/api/auth/login",
        json={"code": "Z-9999", "pin": "0000"},
    )

    assert wrong.status_code == unknown.status_code == 401
    assert wrong.json()["error"]["code"] == unknown.json()["error"]["code"]
    assert wrong.json()["error"]["message"] == unknown.json()["error"]["message"]
    # A failed sign-in is its own code: the UI shows "wrong name or password",
    # not the "your session ended" sentence that `unauthenticated` means.
    assert wrong.json()["error"]["code"] == "invalid_credentials"


async def test_code_is_case_insensitive(client, db_session: AsyncSession) -> None:
    world = await build_world(db_session)
    response = await client.post(
        "/api/auth/login",
        json={"code": world.learner_a.student_code.lower(), "pin": PIN},
    )
    assert response.status_code == 200


async def test_refresh_rotates_and_reuse_revokes_the_family(
    client, db_session: AsyncSession
) -> None:
    world = await build_world(db_session)
    await login(client, world.learner_a)
    old_refresh = client.cookies.get(REFRESH_COOKIE)
    assert old_refresh

    rotated = await client.post("/api/auth/refresh")
    assert rotated.status_code == 200
    new_refresh = client.cookies.get(REFRESH_COOKIE)
    assert new_refresh and new_refresh != old_refresh

    # The old token is now revoked: replaying it is treated as theft and kills
    # every live session for that user.
    client.cookies.set(REFRESH_COOKIE, old_refresh)
    replay = await client.post("/api/auth/refresh")
    assert replay.status_code == 401

    rows = (
        (
            await db_session.execute(
                select(AuthSession).where(AuthSession.user_id == world.learner_a.id)
            )
        )
        .scalars()
        .all()
    )
    assert rows and all(row.revoked_at is not None for row in rows)
    # The rotated row keeps its own reason; the live one is killed by the replay.
    assert "reuse_detected" in {row.revoked_reason for row in rows}


async def test_logout_revokes_session_immediately(client, db_session: AsyncSession) -> None:
    world = await build_world(db_session)
    await login(client, world.learner_a)
    assert (await client.get("/api/auth/me")).status_code == 200

    logout = await client.post("/api/auth/logout")
    assert logout.status_code == 204

    # Cookies are gone, and the old refresh token is dead server-side.
    assert client.cookies.get(ACCESS_COOKIE) is None
    assert (await client.get("/api/auth/me")).status_code == 401

    row = (
        (
            await db_session.execute(
                select(AuthSession).where(AuthSession.user_id == world.learner_a.id)
            )
        )
        .scalars()
        .first()
    )
    assert row is not None and row.revoked_reason == "logout"


async def test_only_the_hash_of_a_refresh_token_is_stored(client, db_session: AsyncSession) -> None:
    world = await build_world(db_session)
    await login(client, world.learner_a)
    raw = client.cookies.get(REFRESH_COOKIE)
    assert raw

    row = (
        (
            await db_session.execute(
                select(AuthSession).where(AuthSession.user_id == world.learner_a.id)
            )
        )
        .scalars()
        .first()
    )
    assert row is not None
    assert row.refresh_token_hash == hash_refresh_token(raw)
    assert row.refresh_token_hash != raw


async def test_repeated_failures_lock_the_account(client, db_session: AsyncSession) -> None:
    world = await build_world(db_session)

    for _ in range(5):
        await login(client, world.learner_a, pin="0000")

    refreshed = await db_session.get(User, world.learner_a.id)
    assert refreshed is not None
    assert refreshed.failed_login_count >= 5
    assert refreshed.locked_until is not None

    # Even the correct password is refused while the lock holds.
    blocked = await login(client, world.learner_a)
    assert blocked.status_code == 401


async def test_lock_expires_and_counters_reset(client, db_session: AsyncSession) -> None:
    world = await build_world(db_session)
    for _ in range(5):
        await login(client, world.learner_a, pin="0000")

    user = await db_session.get(User, world.learner_a.id)
    assert user is not None
    user.locked_until = dt.datetime.now(dt.UTC) - dt.timedelta(seconds=1)
    await db_session.flush()

    ok = await login(client, world.learner_a)
    assert ok.status_code == 200
    assert user.failed_login_count == 0
    assert user.locked_until is None


async def test_suspended_user_cannot_sign_in(client, db_session: AsyncSession) -> None:
    school = await make_school(db_session, "Suspended School")
    user = await make_user(
        db_session,
        school=school,
        role=Role.learner,
        code="BLOCKED-1",
        status=UserStatus.suspended,
    )
    response = await login(client, user)
    assert response.status_code == 401


async def test_pin_is_stored_as_an_argon2id_hash(db_session: AsyncSession) -> None:
    school = await make_school(db_session, "Hash School")
    user = await make_user(db_session, school=school, role=Role.learner)
    assert user.pin_hash is not None
    assert user.pin_hash.startswith("$argon2id$")
    assert PIN not in user.pin_hash
    assert verify_secret(user.pin_hash, PIN)
    assert not verify_secret(user.pin_hash, "0000")
