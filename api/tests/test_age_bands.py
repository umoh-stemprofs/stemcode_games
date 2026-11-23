"""Age bands (P1-T04, D-22).

A band is computed on a date and snapshotted onto rows later. These tests pin
the boundary behaviour, because an off-by-one here silently puts a 10-year-old
in the 11-13 band and changes which content they may see.
"""

from __future__ import annotations

import datetime as dt

import pytest
from app.identity.service import age_on, get_age_band
from sqlalchemy.ext.asyncio import AsyncSession


def test_age_on_counts_whole_years_only() -> None:
    dob = dt.date(2015, 8, 20)
    assert age_on(dob, dt.date(2025, 8, 19)) == 9
    assert age_on(dob, dt.date(2025, 8, 20)) == 10
    assert age_on(dob, dt.date(2026, 1, 1)) == 10


@pytest.mark.parametrize(
    ("on_date", "expected"),
    [
        (dt.date(2026, 1, 1), "8-10"),  # 10 years old
        (dt.date(2028, 1, 1), "11-13"),  # 12
        (dt.date(2031, 1, 1), "14-16"),  # 15
        (dt.date(2034, 1, 1), "17+"),  # 18
    ],
)
async def test_band_boundaries(db_session: AsyncSession, on_date: dt.date, expected: str) -> None:
    band = await get_age_band(db_session, date_of_birth=dt.date(2015, 2, 3), on_date=on_date)
    assert band is not None
    assert band.id == expected


async def test_under_eight_has_no_band(db_session: AsyncSession) -> None:
    band = await get_age_band(
        db_session, date_of_birth=dt.date(2020, 1, 1), on_date=dt.date(2026, 1, 1)
    )
    assert band is None


async def test_seventeen_plus_is_open_ended(db_session: AsyncSession) -> None:
    band = await get_age_band(
        db_session, date_of_birth=dt.date(1990, 5, 5), on_date=dt.date(2026, 1, 1)
    )
    assert band is not None
    assert band.id == "17+"
    assert band.max_age is None
