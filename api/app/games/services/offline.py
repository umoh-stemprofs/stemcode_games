"""Words a learner can take with them (P9-T02).

Offline play needs the puzzles themselves, not a session: the phone generates
its own seed and checks its own answers, then syncs a record that earns no XP
and never reaches a board (D-12). So this module hands out **content**, and
nothing else — no seed, no session id, no token, no clock.

The bundle does contain answers, and that is deliberate and narrow. An answer
would be a secret if it belonged to a live online round (D-25); here it belongs
to a downloadable word list that a learner could meet anyway by playing. What
makes it safe is what is *missing*: no session, so nothing here can enter a
leaderboard, a score or an XP ledger.

Everything is derived from the learner's own record. The band comes from the
birthday on the account, never from a query string, and the words come from the
same "live" set the online game draws from, so a word taken down in the coach's
Words screen is gone from the next download too.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import AppError
from app.games import repository as repo
from app.games.domain import access as access_rules
from app.games.domain import wordscramble as ws
from app.games.models import ContentItem
from app.games.services.access import school_timezone
from app.identity.models import User
from app.identity.service import get_age_band

LOCALE = "en"

# Which games can be played with no connection. Checkers is live-only until
# Phase 12, and Number Guess needs no content at all (it derives every round
# from its seed), so this set is exactly the content games.
OFFLINE_GAMES = frozenset({ws.GAME_ID})

# A pack is sized for a phone that may be on a school connection: two hundred
# words is a few tens of kilobytes and still far more than one session needs.
PACK_LIMIT = 200


@dataclass(frozen=True, slots=True)
class OfflineItem:
    id: str
    answer: str
    alt_answers: tuple[str, ...]
    clue: str | None
    clue_image_key: str | None
    clue_audio_key: str | None
    difficulty: int


@dataclass(frozen=True, slots=True)
class OfflinePack:
    game_id: str
    locale: str
    age_band: str
    difficulty: int
    # Changes whenever the live words behind this pack change, so the client
    # can say "update available" without diffing every item.
    pack_version: str
    generated_at: dt.datetime
    items: tuple[OfflineItem, ...]

    @property
    def item_count(self) -> int:
        return len(self.items)


def _normalise_game(game_id: str) -> str:
    """``word-scramble`` and ``word_scramble`` name the same game."""
    return game_id.strip().lower().replace("-", "_")


def _item(row: ContentItem) -> OfflineItem:
    payload = row.payload
    alts = payload.get("alt_answers") or []
    return OfflineItem(
        id=str(row.id),
        answer=str(payload.get("answer", "")).strip().lower(),
        alt_answers=tuple(str(a).strip().lower() for a in alts) if isinstance(alts, list) else (),
        clue=payload.get("clue") if isinstance(payload.get("clue"), str) else None,
        clue_image_key=payload.get("clue_image_key")
        if isinstance(payload.get("clue_image_key"), str)
        else None,
        clue_audio_key=payload.get("clue_audio_key")
        if isinstance(payload.get("clue_audio_key"), str)
        else None,
        difficulty=int(payload.get("difficulty", 1)),
    )


def _version(
    difficulty: int, pack_version: int, items: list[OfflineItem], rows: list[ContentItem]
) -> str:
    """A stamp, not a secret: level, pack version, size, and when it last moved.

    A word goes live on its own (D-38), so a pack's own version number does not
    move when one word changes. The newest ``published_at`` does. The level is
    part of the stamp because two levels of one band can be the same size and
    were last touched at the same second.
    """
    stamps = [row.published_at or row.created_at for row in rows]
    newest = max((s for s in stamps if s is not None), default=None)
    stamp = (
        newest.astimezone(dt.UTC).strftime("%Y%m%d%H%M") if isinstance(newest, dt.datetime) else "0"
    )
    return f"{difficulty}.{pack_version}.{len(items)}.{stamp}"


async def pack_for(
    session: AsyncSession,
    *,
    user: User,
    game_id: str,
    difficulty: int,
    now: dt.datetime | None = None,
) -> OfflinePack:
    """The download for one learner, one game, one level.

    Raises ``offline_not_available`` for a game that needs the network and
    ``not_enough_content`` when the learner's band has too few live words for a
    pack to be worth storing.
    """
    game = _normalise_game(game_id)
    if game not in OFFLINE_GAMES:
        raise AppError(
            "That game needs the internet.",
            code="offline_not_available",
            status_code=400,
        )
    if difficulty not in (1, 2, 3):
        raise AppError("Pick a level to play.", code="bad_difficulty", status_code=400)

    now = now or dt.datetime.now(dt.UTC)
    tz = await school_timezone(session, user.school_id)
    today = access_rules.local_date(now, tz)
    band = await get_age_band(session, date_of_birth=user.date_of_birth, on_date=today)
    if band is None:
        raise AppError(
            "There are no words for your year group yet.",
            code="not_enough_content",
            status_code=409,
        )

    rows = await repo.live_items(session, game_id=game, locale=LOCALE, age_band=band.id)
    playable = [row for row in rows if int(row.payload.get("difficulty", 1)) == difficulty]
    if len(playable) < ws.MIN_ITEMS_PER_PACK:
        raise AppError(
            "There are not enough words at that level yet.",
            code="not_enough_content",
            status_code=409,
        )

    kept = playable[:PACK_LIMIT]
    pack_row = await repo.serving_pack(
        session, game_id=game, locale=LOCALE, age_band=band.id
    )
    items = [_item(row) for row in kept]
    return OfflinePack(
        game_id=game,
        locale=LOCALE,
        age_band=band.id,
        difficulty=difficulty,
        pack_version=_version(
            difficulty, pack_row.version if pack_row else 0, items, kept
        ),
        generated_at=now,
        items=tuple(items),
    )
