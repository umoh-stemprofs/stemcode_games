"""Liveness and readiness probes (P0-T04).

``/health`` never touches dependencies: it answers "is this process alive".
``/ready`` checks Postgres and the cache and reports which is which, so a
developer can see ``cache: memory`` on the no-Docker path (P0-T03b).
"""

from __future__ import annotations

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from app.core.db import ping_db

router = APIRouter(tags=["health"])


@router.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


@router.get("/ready")
async def ready(request: Request) -> JSONResponse:
    database_ok = await ping_db()
    cache = request.app.state.cache
    cache_ok = await cache.ping()

    body = {
        "status": "ready" if (database_ok and cache_ok) else "not_ready",
        "checks": {
            "database": "up" if database_ok else "down",
            "cache": cache.backend if cache_ok else "down",
        },
    }
    return JSONResponse(status_code=200 if body["status"] == "ready" else 503, content=body)
