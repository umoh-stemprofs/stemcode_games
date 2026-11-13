"""FastAPI application factory (P0-T04).

Composition only: settings, logging, cache/queue wiring, error envelope, and
the health probes. Feature routers arrive in later phases.
"""

from __future__ import annotations

import time
import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI, Request, Response
from fastapi.responses import JSONResponse

from app.api.health import router as health_router
from app.core.cache import build_cache
from app.core.config import get_settings
from app.core.db import dispose_engines
from app.core.errors import AppError, app_error_handler, unhandled_error_handler
from app.core.logging import configure_logging, get_logger, request_id_var
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

    log.info(
        "app.started",
        extra={"route": "startup", "status": 0, "session_id": settings.app_env},
    )
    try:
        yield
    finally:
        await app.state.queue.aclose()
        await app.state.cache.aclose()
        await dispose_engines()
        log.info("app.stopped", extra={"route": "shutdown"})


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(
        title="STEM Code V2 Games API",
        version=VERSION,
        lifespan=lifespan,
        # Docs are useful in dev; the proxy is expected to hide them in prod.
        docs_url="/api/docs",
        redoc_url=None,
        openapi_url="/api/openapi.json",
    )

    app.add_exception_handler(AppError, app_error_handler)
    app.add_exception_handler(Exception, unhandled_error_handler)

    @app.middleware("http")
    async def request_context(request: Request, call_next: Any) -> Response:
        request_id = request.headers.get("x-request-id") or uuid.uuid4().hex
        token = request_id_var.set(request_id)
        started = time.perf_counter()
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
        response.headers["Referrer-Policy"] = "no-referrer"
        return response

    # Everything public lives under /api so the browser only ever sees one
    # origin: the dev rewrite and the production proxy both forward /api/*
    # unchanged (D-19).
    app.include_router(health_router, prefix="/api")

    @app.get("/", include_in_schema=False)
    async def root() -> JSONResponse:
        return JSONResponse(
            {
                "service": "stem-games-api",
                "version": VERSION,
                "env": settings.app_env,
                "docs": "/api/docs",
            }
        )

    return app


app = create_app()
