"""Standard error envelope: ``{error: {code, message, details, request_id}}``.

Two rules from the plan (P0-T04, Appendix B):
- Clients get stable machine codes and a short human message.
- Nothing sensitive goes into the envelope: no seeds, answers, tokens, or names.
"""

from __future__ import annotations

from typing import Any

from fastapi import Request
from fastapi.responses import JSONResponse

from app.core.logging import get_logger, request_id_var

log = get_logger(__name__)


class AppError(Exception):
    """Base class for expected, typed application failures."""

    status_code: int = 400
    code: str = "bad_request"

    def __init__(
        self,
        message: str,
        *,
        code: str | None = None,
        status_code: int | None = None,
        details: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
    ) -> None:
        super().__init__(message)
        self.message = message
        if code is not None:
            self.code = code
        if status_code is not None:
            self.status_code = status_code
        self.details = details or {}
        self.headers = headers or {}


class UnauthorizedError(AppError):
    status_code = 401
    code = "unauthenticated"


class ForbiddenError(AppError):
    status_code = 403
    code = "forbidden"


class ConflictError(AppError):
    status_code = 409
    code = "conflict"


class NotFoundError(AppError):
    status_code = 404
    code = "not_found"


class RateLimitedError(AppError):
    status_code = 429
    code = "rate_limited"


class UnavailableError(AppError):
    status_code = 503
    code = "unavailable"


def error_body(
    code: str,
    message: str,
    details: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "error": {
            "code": code,
            "message": message,
            "details": details or {},
            "request_id": request_id_var.get(),
        }
    }


async def app_error_handler(_request: Request, exc: Exception) -> JSONResponse:
    assert isinstance(exc, AppError)  # noqa: S101 - handler is registered for AppError only
    if exc.status_code >= 500:
        log.error("app_error", extra={"status": exc.status_code}, exc_info=exc)
    return JSONResponse(
        status_code=exc.status_code,
        content=error_body(exc.code, exc.message, exc.details),
        headers=exc.headers or None,
    )


async def unhandled_error_handler(_request: Request, exc: Exception) -> JSONResponse:
    # Log the real cause; return a generic message so internals never leak.
    log.error("unhandled_error", exc_info=exc)
    return JSONResponse(
        status_code=500,
        content=error_body("internal_error", "Something went wrong. Please try again."),
    )
