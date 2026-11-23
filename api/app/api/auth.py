"""Authentication routes (P1-T02, D-19).

Thin by design: parse, call the service, set or clear the cookies, return the
caller's own profile. No rule lives here — the session rules are in
``app.identity.service``.

Cookies are the only place a token appears. Nothing is returned in the JSON
body, so a stolen response body is worthless and no token ever reaches
JavaScript.
"""

from __future__ import annotations

import datetime as dt
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from fastapi import APIRouter, Depends, Request, Response
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import UnauthorizedError
from app.identity.deps import ActorDep, SessionDep, SettingsDep, login_rate_limit
from app.identity.models import School, User
from app.identity.schemas import AgeBandOut, LoginIn, MeOut, SchoolOut, SelfProfile
from app.identity.security import (
    REFRESH_COOKIE,
    clear_session_cookies,
    set_session_cookies,
)
from app.identity.service import (
    authenticate,
    get_age_band,
    revoke_session_by_token,
    rotate_refresh_token,
)

router = APIRouter(prefix="/auth", tags=["auth"])


def school_today(school: School, now: dt.datetime | None = None) -> dt.date:
    """The school's calendar date. Never the server's own zone (P3-T03)."""
    moment = now or dt.datetime.now(dt.UTC)
    try:
        return moment.astimezone(ZoneInfo(school.timezone)).date()
    except ZoneInfoNotFoundError:
        return moment.date()


async def me_payload(session: AsyncSession, user: User, school: School) -> MeOut:
    band = await get_age_band(
        session, date_of_birth=user.date_of_birth, on_date=school_today(school)
    )
    return MeOut(
        user=SelfProfile(
            id=user.id,
            preferred_name=user.preferred_name,
            real_name=user.real_name,
            avatar_key=user.avatar_key,
            role=user.role.value,
            status=user.status.value,
            school_id=user.school_id,
            date_of_birth=user.date_of_birth,
        ),
        school=SchoolOut(
            id=school.id,
            name=school.name,
            timezone=school.timezone,
            leaderboards_enabled=school.leaderboards_enabled,
        ),
        age_band=AgeBandOut(id=band.id, label=band.label) if band else None,
    )


@router.post("/login", dependencies=[Depends(login_rate_limit)])
async def login(
    payload: LoginIn,
    request: Request,
    response: Response,
    session: SessionDep,
    settings: SettingsDep,
) -> MeOut:
    tokens = await authenticate(
        session,
        code=payload.code,
        pin=payload.pin,
        ip=request.client.host if request.client else None,
        settings=settings,
    )
    school = await session.get(School, tokens.user.school_id)
    if school is None:  # pragma: no cover - a user cannot exist without a school
        raise UnauthorizedError("Please sign in again.")

    set_session_cookies(
        response,
        access_token=tokens.access_token,
        refresh_token=tokens.refresh_token,
        settings=settings,
    )
    return await me_payload(session, tokens.user, school)


@router.post("/refresh")
async def refresh(
    request: Request,
    response: Response,
    session: SessionDep,
    settings: SettingsDep,
) -> MeOut:
    raw = request.cookies.get(REFRESH_COOKIE)
    if not raw:
        raise UnauthorizedError("Please sign in again.")

    try:
        tokens = await rotate_refresh_token(
            session,
            raw_refresh=raw,
            settings=settings,
            ip=request.client.host if request.client else None,
        )
    except UnauthorizedError:
        clear_session_cookies(response, settings)
        raise

    school = await session.get(School, tokens.user.school_id)
    if school is None:  # pragma: no cover
        raise UnauthorizedError("Please sign in again.")

    set_session_cookies(
        response,
        access_token=tokens.access_token,
        refresh_token=tokens.refresh_token,
        settings=settings,
    )
    return await me_payload(session, tokens.user, school)


@router.post("/logout", status_code=204)
async def logout(
    request: Request,
    response: Response,
    session: SessionDep,
    settings: SettingsDep,
) -> Response:
    raw = request.cookies.get(REFRESH_COOKIE)
    if raw:
        await revoke_session_by_token(session, raw_refresh=raw, reason="logout")
    clear_session_cookies(response, settings)
    response.status_code = 204
    return response


@router.get("/me")
async def me(session: SessionDep, actor: ActorDep) -> MeOut:
    user = await session.get(User, actor.id)
    school = await session.get(School, actor.school_id)
    if user is None or school is None:
        raise UnauthorizedError("Please sign in again.")
    return await me_payload(session, user, school)
