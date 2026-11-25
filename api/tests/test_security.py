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
