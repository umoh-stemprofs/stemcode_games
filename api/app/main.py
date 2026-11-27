"""FastAPI application factory (P0-T04).

Composition only: settings, logging, cache/queue wiring, error envelope, and
the health probes. Feature routers arrive in later phases.
"""

from __future__ import annotations

import asyncio
import time
import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI, Request, Response
from fastapi.responses import JSONResponse

from app.api.auth import router as auth_router
from app.api.classes import router as classes_router
from app.api.content import router as content_router
from app.api.games import router as games_router
from app.api.health import router as health_router
from app.api.leaderboards import board_router, term_router, xp_router
from app.api.live import presence_router as presence_router
from app.api.live import router as live_router
from app.api.profiles import router as profiles_router
from app.api.realtime import router as realtime_router
from app.api.realtime import socket_router
from app.api.social import router as social_router
from app.api.testing import router as testing_router
from app.core.cache import build_cache
from app.core.config import get_settings
from app.core.db import dispose_engines
from app.core.errors import AppError, app_error_handler, error_body, unhandled_error_handler
from app.core.logging import configure_logging, get_logger, request_id_var
from app.core.origin import origin_refused
from app.core.queue import build_queue

log = get_logger(__name__)

VERSION = "0.1.0"


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    settings = get_settings()
    configure_logging(settings.log_level)

    app.state.cache = build_cache(settings)
    app.state.queue = build_queue(settings)

    if settings.uses_memory_cache:
        # Loud, once, at startup: this is the dev-only path (D-34).
        log.warning(
            "cache.in_memory_dev_only",
            extra={"route": "startup", "status": 0},
        )

    # Local development has no worker and no Redis, so the sweeps that end a
    # silent session would never run and a closed tab would hold a seat forever
    # (D-34). The production worker remains the only runner outside `dev`.
    sweeps: asyncio.Task[None] | None = None
    if settings.app_env == "dev":
        from app.jobs import scheduler

        sweeps = scheduler.start()

    log.info(
        "app.started",
        extra={"route": "startup", "status": 0, "session_id": settings.app_env},
    )
    try:
        yield
    finally:
        from app.jobs import scheduler

        await scheduler.stop(sweeps)
        await app.state.queue.aclose()
        await app.state.cache.aclose()
        await dispose_engines()
        log.info("app.stopped", extra={"route": "shutdown"})


def security_headers(settings: Any) -> dict[str, str]:
    """Response headers every answer carries (P11-T01).

    The API serves JSON, so a strict ``default-src 'none'`` costs nothing and
    stops a stray HTML response from loading anything. The framing headers are
    the belt to the cookie's braces: nothing may put the app in a frame.
    HSTS is only meaningful over TLS, so it is sent only where the deployment
    terminates TLS (staging and prod).
    """

    headers = {
        "X-Content-Type-Options": "nosniff",
        "X-Frame-Options": "DENY",
        "Content-Security-Policy": "default-src 'none'; frame-ancestors 'none'; base-uri 'none'",
        "Permissions-Policy": "camera=(), microphone=(), geolocation=()",
        "Referrer-Policy": "no-referrer",
    }
    if settings.is_production:
        headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
    return headers


def create_app() -> FastAPI:
    settings = get_settings()
    # Docs describe every endpoint and every field; that is a map for an
    # attacker and no help to a learner. Open in dev/test, gone everywhere the
    # app is deployed, instead of hoping the proxy remembers to hide them.
    app = FastAPI(
        title="STEM Code V2 Games API",
        version=VERSION,
        lifespan=lifespan,
        docs_url=None if settings.is_production else "/api/docs",
        redoc_url=None,
        openapi_url=None if settings.is_production else "/api/openapi.json",
    )

    app.add_exception_handler(AppError, app_error_handler)
    app.add_exception_handler(Exception, unhandled_error_handler)

    @app.middleware("http")
    async def request_context(request: Request, call_next: Any) -> Response:
        request_id = request.headers.get("x-request-id") or uuid.uuid4().hex
        token = request_id_var.set(request_id)
        started = time.perf_counter()

        # P11-T01: a cookie is attached to a cross-site POST by the browser, so
        # the write itself must prove it came from this app. Checked here, in
        # front of every route, because a new router should not have to remember.
        if origin_refused(
            request.method, request.headers.get("origin"), settings=get_settings()
        ):
            log.info(
                "http.refused_origin",
                extra={"method": request.method, "route": request.url.path, "status": 403},
            )
            request_id_var.reset(token)
            return JSONResponse(
                status_code=403,
                content=error_body(
                    "bad_origin",
                    "That request came from another page.",
                ),
                headers={**security_headers(settings), "X-Request-ID": request_id},
            )

        try:
            response: Response = await call_next(request)
        finally:
            duration_ms = round((time.perf_counter() - started) * 1000, 1)
            log.info(
                "http.request",
                extra={
                    "method": request.method,
                    "route": request.url.path,
                    "duration_ms": duration_ms,
                },
            )
            request_id_var.reset(token)
        response.headers["X-Request-ID"] = request_id
        for key, value in security_headers(settings).items():
            response.headers[key] = value
        return response

    # Everything public lives under /api so the browser only ever sees one
    # origin: the dev rewrite and the production proxy both forward /api/*
    # unchanged (D-19).
    app.include_router(health_router, prefix="/api")
    app.include_router(auth_router, prefix="/api")
    app.include_router(profiles_router, prefix="/api")
    app.include_router(classes_router, prefix="/api")
    app.include_router(games_router, prefix="/api")
    app.include_router(social_router, prefix="/api")
    app.include_router(live_router, prefix="/api")
    app.include_router(presence_router, prefix="/api")
    app.include_router(realtime_router, prefix="/api")
    app.include_router(socket_router)
    app.include_router(content_router, prefix="/api")
    app.include_router(xp_router, prefix="/api")
    app.include_router(board_router, prefix="/api")
    app.include_router(term_router, prefix="/api")
    app.include_router(testing_router, prefix="/api")

    # The gateway is the one route outside /api: a browser cannot upgrade a
    # connection through the dev rewrite, so /ws goes straight to this process
    # in development and through the reverse proxy in production (P8-T01).
    app.state.settings = settings

    @app.get("/", include_in_schema=False)
    async def root() -> JSONResponse:
        return JSONResponse(
            {
                "service": "stem-games-api",
                "version": VERSION,
                "env": settings.app_env,
                # No pointer to a route that is closed in this environment.
                **({} if settings.is_production else {"docs": "/api/docs"}),
            }
        )

    return app


app = create_app()
