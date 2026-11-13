"""Health/readiness and the error envelope (P0-T04).

``/ready`` is the check the Phase 0 Definition of Done runs through the Next
rewrite; here it is exercised directly against the ASGI app.
"""

from __future__ import annotations

import pytest
from app.core.errors import error_body
from app.main import create_app
from httpx import ASGITransport, AsyncClient


@pytest.fixture
async def client():
    app = create_app()
    async with app.router.lifespan_context(app):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as http:
            yield http


async def test_health_is_dependency_free(client: AsyncClient) -> None:
    # Everything public lives under /api (D-19: one browser origin).
    response = await client.get("/api/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


@pytest.mark.db
async def test_ready_reports_database_and_cache(client: AsyncClient) -> None:
    response = await client.get("/api/ready")
    body = response.json()

    if body["checks"]["database"] == "down":
        pytest.skip("Postgres not reachable: start the local cluster (README)")

    assert response.status_code == 200
    assert body["status"] == "ready"
    # No Redis in dev: the in-memory implementation must identify itself.
    assert body["checks"]["cache"] in {"memory", "redis"}


async def test_request_id_header_is_echoed(client: AsyncClient) -> None:
    response = await client.get("/api/health", headers={"X-Request-ID": "abc123"})
    assert response.headers["X-Request-ID"] == "abc123"


async def test_error_envelope_shape() -> None:
    body = error_body("limit_reached", "You are done for today.", {"remaining_seconds": 0})
    assert set(body) == {"error"}
    error = body["error"]
    assert set(error) == {"code", "message", "details", "request_id"}
    assert error["code"] == "limit_reached"
