"""Identity request/response schemas (P1-T05).

The privacy rule is structural, not a habit: anything a learner can receive
about **another** person is a ``PublicProfile``, which has no field that could
carry a real name, an email, a birth date, or a role. ``LEARNER_FACING_MODELS``
lists every schema that can be shown to a learner, and
``tests/test_profile_privacy.py`` fails the build if one of them grows a
sensitive field.

``SelfProfile`` is deliberately *not* in that list: it is only ever returned
about the caller.
"""

from __future__ import annotations

import datetime as dt
import uuid

from pydantic import BaseModel, ConfigDict, Field


class _Strict(BaseModel):
    model_config = ConfigDict(from_attributes=True, extra="forbid")


class PublicProfile(_Strict):
    """Everything another learner may ever see. Add fields with care."""

    id: uuid.UUID
    preferred_name: str
    avatar_key: str


class SelfProfile(_Strict):
    """The caller's own account, shown only to them."""

    id: uuid.UUID
    preferred_name: str
    real_name: str
    avatar_key: str
    role: str
    status: str
    school_id: uuid.UUID
    date_of_birth: dt.date


class AgeBandOut(_Strict):
    id: str
    label: str


class SchoolOut(_Strict):
    id: uuid.UUID
    name: str
    timezone: str
    leaderboards_enabled: bool


class MeOut(_Strict):
    user: SelfProfile
    school: SchoolOut
    age_band: AgeBandOut | None


class LoginIn(_Strict):
    """A student code and a PIN (0003_login_codes).

    Validation is deliberately loose about *format* and strict about length:
    rejecting a well-formed-but-unknown code here would tell an attacker which
    codes exist, and it would tell a child nothing useful.
    """

    code: str = Field(min_length=2, max_length=32)
    pin: str = Field(min_length=4, max_length=8)


class ClassOut(_Strict):
    id: uuid.UUID
    name: str
    grade: int | None


class ClassMembersOut(_Strict):
    class_info: ClassOut = Field(alias="class")
    members: list[PublicProfile]


class LearningXpIn(_Strict):
    user_id: uuid.UUID
    amount: int = Field(ge=-1000, le=1000)
    reason: str = Field(min_length=1, max_length=64)


# Every schema that may be rendered to a learner about somebody else.
LEARNER_FACING_MODELS: tuple[type[BaseModel], ...] = (
    PublicProfile,
    ClassOut,
    ClassMembersOut,
    AgeBandOut,
)

# Field names that must never appear in a learner-facing schema.
FORBIDDEN_PUBLIC_FIELDS = frozenset(
    {
        "real_name",
        "email",
        "username",
        "password",
        "password_hash",
        "date_of_birth",
        "locked_until",
        "failed_login_count",
        "refresh_token_hash",
        "created_ip",
    }
)
