"""The security basics an audit looks at first (P11-T01, P10-T06).

Three promises, all cheap to state and easy to lose:

- **A write from another page is refused.** The session is a cookie, and a
  browser attaches a cookie to a cross-site form post. The check lives in front
  of every router so a new endpoint cannot forget it.
- **An honest write is not refused.** No `Origin` is a test client, a script or
  a same-origin post; refusing those would break curl and every test without
  closing a real hole.
- **A person cannot flood a queue.** Reporting and inviting are counted per
  learner, not per browser, so two tabs do not buy two allowances.
"""

from __future__ import annotations

import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from tests.factories import PIN, build_world, login

CROSS_SITE = {"origin": "https://evil.example"}
SAME_SITE = {"origin": "http://localhost:3000"}


async def test_a_write_from_another_page_is_refused(client) -> None:
    """The refusal happens before the router, so no account is needed."""

    refused = await client.post(
        "/api/auth/login",
        json={"code": "A-1001", "pin": "0000"},
        headers=CROSS_SITE,
    )

    assert refused.status_code == 403, refused.text
    assert refused.json()["error"]["code"] == "bad_origin"
    # One sentence, no internals, and no hint about the account.
    assert "another page" in refused.json()["error"]["message"]


async def test_a_write_without_an_origin_is_allowed(client, db_session: AsyncSession) -> None:
    """curl and the tests send no Origin; that is not evidence of an attack."""

    world = await build_world(db_session)
    signed_in = await login(client, world.learner_a)
    assert signed_in.status_code == 200, signed_in.text


async def test_a_write_from_this_app_is_allowed(client, db_session: AsyncSession) -> None:
    """The dev server's own origin is the one the browser actually uses."""

    world = await build_world(db_session)
    signed_in = await client.post(
        "/api/auth/login",
        json={"code": world.learner_a.student_code, "pin": PIN},
        headers=SAME_SITE,
    )
    assert signed_in.status_code == 200, signed_in.text


async def test_reading_is_never_blocked_by_origin(client) -> None:
    """Only unsafe methods are checked: a GET cannot spend or change anything."""

    read = await client.get("/api/health", headers=CROSS_SITE)
    assert read.status_code == 200, read.text


async def test_the_eleventh_report_in_a_day_is_refused(
    client, db_session: AsyncSession
) -> None:
    """P10-T06: ten reports a day, counted on the learner, not the browser."""

    world = await build_world(db_session)
    await login(client, world.learner_a)
    body = {"reported_id": str(world.learner_a2.id), "reason": "other"}

    for _ in range(10):
        sent = await client.post("/api/games/reports", json=body)
        assert sent.status_code == 201, sent.text

    refused = await client.post("/api/games/reports", json=body)
    assert refused.status_code == 429, refused.text
    assert refused.json()["error"]["code"] == "rate_limited"


async def test_starting_games_is_capped_at_thirty_an_hour(
    client, db_session: AsyncSession
) -> None:
    """P10-T06: session create.

    Every attempt counts, including one refused because a game is already open:
    a script that starts and quits in a loop must run out even though each
    individual start looks ordinary.
    """
    world = await build_world(db_session)
    await login(client, world.learner_a)
    body = {"difficulty": 1}

    for _ in range(30):
        await client.post("/api/games/number_guess/sessions", json=body)

    refused = await client.post("/api/games/number_guess/sessions", json=body)
    assert refused.status_code == 429, refused.text
    assert refused.json()["error"]["code"] == "rate_limited"


async def test_actions_are_capped_at_sixty_a_minute(client, db_session: AsyncSession) -> None:
    """P10-T06: action submit, which is the one a guess script would hammer."""

    world = await build_world(db_session)
    await login(client, world.learner_a)
    started = await client.post("/api/games/number_guess/sessions", json={"difficulty": 1})
    assert started.status_code == 201, started.text
    session_id = started.json()["session_id"]

    for _ in range(60):
        await client.post(
            f"/api/games/sessions/{session_id}/actions",
            json={
                "client_move_id": uuid.uuid4().hex,
                "type": "skip",
            },
        )

    refused = await client.post(
        f"/api/games/sessions/{session_id}/actions",
        json={"client_move_id": uuid.uuid4().hex, "type": "skip"},
    )
    assert refused.status_code == 429, refused.text
    assert refused.json()["error"]["code"] == "rate_limited"


async def test_every_answer_carries_the_security_headers(client) -> None:
    """P11-T01: a response with no headers is a browser deciding for itself."""

    response = await client.get("/api/health")

    assert response.headers["x-content-type-options"] == "nosniff"
    assert response.headers["x-frame-options"] == "DENY"
    assert "frame-ancestors 'none'" in response.headers["content-security-policy"]
    assert response.headers["permissions-policy"].startswith("camera=()")
    assert response.headers["referrer-policy"] == "no-referrer"
    # Dev is plain HTTP; HSTS there would be a promise the app cannot keep.
    assert "strict-transport-security" not in response.headers


async def test_a_refused_origin_still_gets_the_headers(client) -> None:
    """The early 403 leaves through its own path, so it is checked separately."""

    refused = await client.post("/api/games/invites", json={}, headers=CROSS_SITE)

    assert refused.status_code == 403
    assert refused.headers["x-content-type-options"] == "nosniff"
    assert refused.headers["x-frame-options"] == "DENY"


async def test_api_docs_are_closed_and_hsts_is_on_in_production(monkeypatch) -> None:
    """The endpoint map is for developers; a deployed app does not publish it."""

    import app.main as main_module
    import httpx
    from app.core.config import Settings

    prod = Settings(
        app_env="prod",
        database_url="postgresql+asyncpg://postgres@127.0.0.1:5433/stem_games",
        redis_url="redis://127.0.0.1:6379/0",
        secret_key="test-only-secret-key-0123456789abcdefghij",
        app_base_url="https://games.example.org",
    )
    monkeypatch.setattr(main_module, "get_settings", lambda: prod)

    production_app = main_module.create_app()
    transport = httpx.ASGITransport(app=production_app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as http:
        assert (await http.get("/api/docs")).status_code == 404
        assert (await http.get("/api/openapi.json")).status_code == 404

    assert main_module.security_headers(prod)["Strict-Transport-Security"].startswith(
        "max-age=31536000"
    )


DEPLOYED = {
    "database_url": "postgresql+asyncpg://postgres@127.0.0.1:5433/stem_games",
    "redis_url": "redis://127.0.0.1:6379/0",
    "secret_key": "test-only-secret-key-0123456789abcdefghij",
    "app_base_url": "https://games.example.org",
}
LOCAL = {
    "database_url": "postgresql+asyncpg://postgres@127.0.0.1:5433/stem_games",
    "secret_key": "test-only-secret-key-0123456789abcdefghij",
}


def test_a_deployed_app_refuses_to_boot_without_a_public_base_url() -> None:
    """P11-T08: a loopback default in production is a broken app, not a safe one."""

    import pytest
    from app.core.config import Settings
    from pydantic import ValidationError

    # With it set, both deployed environments boot.
    for env in ("staging", "prod"):
        assert Settings(app_env=env, **DEPLOYED).app_base_url == "https://games.example.org"

    for env in ("staging", "prod"):
        with pytest.raises(ValidationError, match="APP_BASE_URL"):
            Settings(app_env=env, **{**DEPLOYED, "app_base_url": None})


def test_a_relative_base_url_is_refused() -> None:
    """It is compared with an ``Origin`` header, so it must be absolute."""

    import pytest
    from app.core.config import Settings
    from pydantic import ValidationError

    with pytest.raises(ValidationError, match="absolute"):
        Settings(app_env="dev", **{**LOCAL, "app_base_url": "/games"})

    # A trailing slash is normalised away instead of creating a second entry.
    slashed = Settings(app_env="dev", **{**LOCAL, "app_base_url": "http://localhost:3000/"})
    assert slashed.app_base_url == "http://localhost:3000"


def test_loopback_origins_are_refused_once_deployed() -> None:
    """The dev server's own origins stop being trustworthy off the developer's box."""

    from app.core.config import Settings
    from app.core.origin import allowed_origins, origin_refused

    dev = Settings(app_env="dev", **LOCAL)
    assert not origin_refused("POST", "http://localhost:3000", settings=dev)

    prod = Settings(app_env="prod", **DEPLOYED)
    assert allowed_origins(prod) == {"https://games.example.org"}
    assert origin_refused("POST", "http://localhost:3000", settings=prod)
    assert not origin_refused("POST", "https://games.example.org", settings=prod)
