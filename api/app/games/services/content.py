"""Write words, one at a time, and make them live one at a time (D-38).

One rule shapes every function here: **a word is the unit a child sees, so a
word is the unit that has a status.**

    draft  --Make it live-->  live  --Take it down-->  retired

Typing a word never puts it in front of a child. It sits in ``draft``, where
the author reads it back. Pressing *Make it live* is the only door to the
games, and it is one word wide: a pack of 150 words is published 150 times, or
with the bulk button in one act, after the same checks.

The author may publish their own words. The safety is the **draft step and the
validator**, not a second person: a word cannot go live while it has a problem,
and a live word never changes under a child — editing one sends it back to
draft first.

The pack is only the bucket that groups words by band and version. It no longer
decides what is served; ``ContentItem.status`` does.

Validation is not re-implemented here: ``domain/wordscramble.validate_item``
decides whether a word may be published, and this module only decides *when* to
ask and what to do with the answer.
"""

from __future__ import annotations

import csv
import datetime as dt
import hashlib
import io
import random
import uuid
from dataclasses import dataclass
from zoneinfo import ZoneInfo

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import AppError, ForbiddenError, NotFoundError
from app.games import repository as repo
from app.games.domain import safe_language as ws_safe
from app.games.domain import wordscramble as ws
from app.games.models import ContentItem, ContentPack
from app.identity.models import AgeBand, ClassMember, Role, User
from app.identity.service import Actor, age_on, visible_classes

GAME_ID = "word_scramble"
LOCALE = "en"

# With three roles, content work belongs to every member of staff. It is
# platform-wide and it is words for children, so it is not a learner's job
# (D-37). Coaches write; both may make a word live or take it down.
CONTENT_ROLES = (Role.coach, Role.school_admin)

# Kept as advice for the screens: a level needs this many live words before a
# session can be built. The real check is at ``start`` (P4-T03), because words
# now go live one at a time and a half-filled level is a valid state.
MIN_ITEMS_PER_LEVEL = ws.MIN_ITEMS_PER_PACK


# ------------------------------------------------------------------ the reader
@dataclass(frozen=True, slots=True)
class PackSummary:
    id: uuid.UUID
    game_id: str
    version: int
    locale: str
    age_band: str
    status: str
    author_id: uuid.UUID | None
    reviewer_id: uuid.UUID | None
    review_note: str | None
    source: str | None
    published_at: object | None
    created_at: object
    item_count: int
    live_count: int
    draft_count: int
    per_level: dict[int, int]
    problems: int


@dataclass(frozen=True, slots=True)
class ItemView:
    id: uuid.UUID
    answer: str
    clue: str | None
    alt_answers: list[str]
    difficulty: int
    problems: list[str]
    scrambled: str
    status: str
    published_at: object | None


@dataclass(frozen=True, slots=True)
class PackDetail:
    summary: PackSummary
    items: list[ItemView]
    can_edit: bool
    can_review: bool
    can_publish: bool


def _require_reader(actor: Actor) -> None:
    if actor.role not in CONTENT_ROLES:
        raise ForbiddenError("You do not have access to this.")


def _require_contributor(actor: Actor) -> None:
    if actor.role not in CONTENT_ROLES:
        raise ForbiddenError("You do not have access to this.")


def _require_reviewer(actor: Actor) -> None:
    """Kept as the name the rest of the file reads well with.

    There is no longer a separate reviewer: publishing a word is the author's
    own act (D-38). This still checks that the caller is staff at all.
    """
    _require_contributor(actor)


# ------------------------------------------------------------------ validation
async def _youngest_band(session: AsyncSession) -> str | None:
    """The band with the smallest minimum age.

    Its items need a picture or a sound, because a text-only clue cannot be
    read by the player it is written for (Appendix D).
    """
    stmt = select(AgeBand.id).order_by(AgeBand.min_age.asc()).limit(1)
    return (await session.execute(stmt)).scalars().first()


def _difficulty(payload: dict[str, object]) -> int:
    value = payload.get("difficulty", 1)
    return int(value) if isinstance(value, int) else 1


def _problems_for(
    payload: dict[str, object], *, youngest: bool, extra: frozenset[str] = frozenset()
) -> list[str]:
    return ws.validate_item(payload, youngest_band=youngest, extra_blocked=extra)


async def _extra_blocked(session: AsyncSession) -> frozenset[str]:
    """The school's own safe-language words, read once per operation.

    Read here rather than inside the validator because that module is pure by
    rule; read **once** per request rather than per word, because a CSV import
    checks 150 rows and should not make 150 queries.
    """
    return await repo.blocked_word_values(session)


async def _item_rows(session: AsyncSession, pack_id: uuid.UUID) -> list[ContentItem]:
    return await repo.pack_items(session, pack_id)


async def _summary(
    session: AsyncSession,
    pack: ContentPack,
    *,
    youngest: str | None = None,
    extra: frozenset[str] = frozenset(),
) -> PackSummary:
    rows = await _item_rows(session, pack.id)
    per_level: dict[int, int] = {}
    problems = 0
    band_is_youngest = youngest is not None and pack.age_band == youngest
    for row in rows:
        level = _difficulty(row.payload)
        per_level[level] = per_level.get(level, 0) + 1
        if _problems_for(row.payload, youngest=band_is_youngest, extra=extra):
            problems += 1
    live = sum(1 for row in rows if row.status == "live")
    return PackSummary(
        id=pack.id,
        game_id=pack.game_id,
        version=pack.version,
        locale=pack.locale,
        age_band=pack.age_band,
        status=pack.status,
        author_id=pack.author_id,
        reviewer_id=pack.reviewer_id,
        review_note=pack.review_note,
        source=pack.source,
        published_at=pack.published_at,
        created_at=pack.created_at,
        item_count=len(rows),
        live_count=live,
        draft_count=sum(1 for row in rows if row.status == "draft"),
        per_level=per_level,
        problems=problems,
    )


def _letter_preview(answer: str) -> str:
    """The letters a child would see, shuffled the same way every time.

    Not the playable scramble (that comes from the session seed, D-25) — just
    an honest "here is what the tiles look like". Seeded from the answer, so
    the preview is stable for the author but properly mixed, unlike a rotation
    that leaves the word almost readable.
    """
    lower = answer.lower()
    if len(lower) < 2:
        return lower
    letters = list(lower)
    digest = hashlib.sha256(lower.encode()).digest()
    # Not secrecy: a stable, readable preview of the tiles (see the docstring).
    random.Random(digest).shuffle(letters)  # noqa: S311
    mixed = "".join(letters)
    return mixed if mixed != lower else lower[1:] + lower[0]


async def _detail(
    session: AsyncSession,
    actor: Actor,
    pack: ContentPack,
    *,
    youngest: str | None,
    extra: frozenset[str] = frozenset(),
) -> PackDetail:
    rows = await _item_rows(session, pack.id)
    band_is_youngest = youngest is not None and pack.age_band == youngest
    items = [
        ItemView(
            id=row.id,
            answer=str(row.payload.get("answer", "")),
            clue=row.payload.get("clue") if isinstance(row.payload.get("clue"), str) else None,
            alt_answers=[str(a) for a in (row.payload.get("alt_answers") or [])],
            difficulty=_difficulty(row.payload),
            problems=_problems_for(row.payload, youngest=band_is_youngest, extra=extra),
            scrambled=_letter_preview(str(row.payload.get("answer", ""))),
            status=row.status,
            published_at=row.published_at,
        )
        for row in rows
    ]
    open_for_work = pack.status != "retired"
    return PackDetail(
        summary=await _summary(session, pack, youngest=youngest, extra=extra),
        items=items,
        can_edit=actor.role in CONTENT_ROLES and open_for_work,
        can_review=actor.role in CONTENT_ROLES and open_for_work,
        can_publish=actor.role in CONTENT_ROLES and open_for_work,
    )


async def _pack(session: AsyncSession, pack_id: uuid.UUID) -> ContentPack:
    pack = await session.get(ContentPack, pack_id)
    if pack is None:
        raise NotFoundError("That pack was not found.")
    return pack


# ----------------------------------------------------------------------- read
async def list_packs(session: AsyncSession, *, actor: Actor) -> list[PackSummary]:
    _require_reader(actor)
    youngest = await _youngest_band(session)
    packs = await repo.list_content_packs(session, game_id=GAME_ID)
    extra = await _extra_blocked(session)
    return [await _summary(session, pack, youngest=youngest, extra=extra) for pack in packs]


async def pack_detail(session: AsyncSession, *, actor: Actor, pack_id: uuid.UUID) -> PackDetail:
    _require_reader(actor)
    pack = await _pack(session, pack_id)
    return await _detail(
        session,
        actor,
        pack,
        youngest=await _youngest_band(session),
        extra=await _extra_blocked(session),
    )


# ---------------------------------------------------------------------- write
async def create_draft(
    session: AsyncSession,
    *,
    actor: Actor,
    age_band: str,
    copy_from: uuid.UUID | None = None,
) -> ContentPack:
    """A new draft version, optionally carrying an existing pack's words.

    Copying matters: without it, "add ten words" to a 150-word pack would mean
    retyping 150 words, and nobody would ever do it.
    """
    _require_contributor(actor)
    band = await session.get(AgeBand, age_band)
    if band is None:
        raise AppError("That age group was not found.", code="unknown_age_band", status_code=400)

    version = await repo.next_content_version(
        session, game_id=GAME_ID, locale=LOCALE, age_band=age_band
    )
    pack = await repo.create_content_pack(
        session,
        game_id=GAME_ID,
        version=version,
        locale=LOCALE,
        age_band=age_band,
        difficulty=1,
        status="draft",
        author_id=actor.id,
        source="original",
    )

    if copy_from is not None:
        source = await session.get(ContentPack, copy_from)
        if source is None:
            raise NotFoundError("That pack was not found.")
        if source.age_band != age_band:
            raise AppError(
                "Words can only be copied within the same age group.",
                code="band_mismatch",
                status_code=400,
            )
        await repo.copy_content_items(session, from_pack=source.id, to_pack=pack.id)

    await repo.audit(
        session,
        actor_id=actor.id,
        action="content.pack_create",
        target_type="content_pack",
        target_id=str(pack.id),
        details={
            "version": version,
            "age_band": age_band,
            "copied_from": str(copy_from) if copy_from else None,
        },
    )
    await session.commit()
    return pack


async def add_item(
    session: AsyncSession,
    *,
    actor: Actor,
    pack_id: uuid.UUID,
    answer: str,
    clue: str | None,
    difficulty: int,
    alt_answers: list[str] | None = None,
    allow_problems: bool = False,
) -> ContentItem:
    """Add one word to a draft.

    A word that fails validation is refused with its reasons, unless the author
    explicitly saves it anyway — a draft is a work in progress, and blocking
    save-on-every-keystroke would make the editor useless.
    """
    _require_contributor(actor)
    pack = await _pack(session, pack_id)
    if pack.status == "retired":
        raise AppError(
            "These words are closed. Start a new set instead.",
            code="pack_retired",
            status_code=409,
        )

    payload: dict[str, object] = {
        "answer": answer.strip().lower(),
        "clue": (clue or "").strip() or None,
        "alt_answers": [a.strip().lower() for a in (alt_answers or []) if a.strip()],
        "difficulty": difficulty,
    }

    problems = _problems_for(
        payload,
        youngest=pack.age_band == await _youngest_band(session),
        extra=await _extra_blocked(session),
    )
    if await repo.content_answer_exists(session, pack_id=pack.id, answer=str(payload["answer"])):
        problems.append("That word is already in this pack.")
    if problems and not allow_problems:
        raise AppError(
            problems[0], code="item_invalid", status_code=422, details={"problems": problems}
        )

    count = await repo.count_content_items(session, pack.id)
    # Added words start as drafts: typing a word is never the same act as
    # showing it to a child (D-38).
    row = await repo.add_content_item(
        session, pack_id=pack.id, payload=payload, difficulty=difficulty, sort_order=count
    )
    await repo.audit(
        session,
        actor_id=actor.id,
        action="content.item_add",
        target_type="content_item",
        target_id=str(row.id),
        details={"pack_id": str(pack.id)},
    )
    await session.commit()
    return row


async def update_item(
    session: AsyncSession,
    *,
    actor: Actor,
    pack_id: uuid.UUID,
    item_id: uuid.UUID,
    answer: str,
    clue: str | None,
    difficulty: int,
    alt_answers: list[str] | None = None,
) -> ContentItem:
    _require_contributor(actor)
    pack = await _pack(session, pack_id)
    if pack.status == "retired":
        raise AppError(
            "These words are closed. Start a new set instead.",
            code="pack_retired",
            status_code=409,
        )
    row = await session.get(ContentItem, item_id)
    if row is None or row.pack_id != pack.id:
        raise NotFoundError("That word was not found.")

    payload: dict[str, object] = {
        "answer": answer.strip().lower(),
        "clue": (clue or "").strip() or None,
        "alt_answers": [a.strip().lower() for a in (alt_answers or []) if a.strip()],
        "difficulty": difficulty,
    }
    problems = _problems_for(
        payload,
        youngest=pack.age_band == await _youngest_band(session),
        extra=await _extra_blocked(session),
    )
    if problems:
        raise AppError(
            problems[0], code="item_invalid", status_code=422, details={"problems": problems}
        )
    row.payload = payload
    row.difficulty = difficulty
    # Changing a live word sends it back to draft: the word children are
    # playing must not change under them mid-round (D-38).
    was_live = row.status == "live"
    if was_live:
        row.status = "draft"
        row.published_at = None
        row.published_by = None
    await repo.audit(
        session,
        actor_id=actor.id,
        action="content.item_update",
        target_type="content_item",
        target_id=str(row.id),
        details={"pack_id": str(pack.id), "sent_back_to_draft": was_live},
    )
    await session.commit()
    return row


async def delete_item(
    session: AsyncSession, *, actor: Actor, pack_id: uuid.UUID, item_id: uuid.UUID
) -> None:
    _require_contributor(actor)
    pack = await _pack(session, pack_id)
    if pack.status == "retired":
        raise AppError(
            "These words are closed. Start a new set instead.",
            code="pack_retired",
            status_code=409,
        )
    row = await session.get(ContentItem, item_id)
    if row is None or row.pack_id != pack.id:
        raise NotFoundError("That word was not found.")
    if row.status != "draft":
        raise AppError(
            "A word that has been live cannot be deleted. Take it down instead.",
            code="item_not_draft",
            status_code=409,
        )
    await session.delete(row)
    await repo.audit(
        session,
        actor_id=actor.id,
        action="content.item_delete",
        target_type="content_item",
        target_id=str(item_id),
        details={"pack_id": str(pack.id)},
    )
    await session.commit()


# ----------------------------------------------------------------- CSV import
@dataclass(frozen=True, slots=True)
class ImportRow:
    line: int
    answer: str
    ok: bool
    message: str | None


@dataclass(frozen=True, slots=True)
class ImportReport:
    added: int
    rows: list[ImportRow]


async def import_csv(
    session: AsyncSession, *, actor: Actor, pack_id: uuid.UUID, text: str
) -> ImportReport:
    """``answer, clue, difficulty`` one per line, with a per-row report.

    A bulk paste that silently drops half its rows is worse than no import at
    all: the author cannot tell what arrived. Every row gets its own line in
    the report, and the good rows are kept.
    """
    _require_contributor(actor)
    pack = await _pack(session, pack_id)
    if pack.status == "retired":
        raise AppError(
            "These words are closed. Start a new set instead.",
            code="pack_retired",
            status_code=409,
        )

    youngest = pack.age_band == await _youngest_band(session)
    extra = await _extra_blocked(session)
    results: list[ImportRow] = []
    added = 0
    existing = await repo.content_answers(session, pack.id)
    base = await repo.count_content_items(session, pack.id)

    reader = csv.reader(io.StringIO(text))
    for line_number, row in enumerate(reader, start=1):
        if not row or all(not cell.strip() for cell in row):
            continue
        answer = (row[0] if len(row) > 0 else "").strip().lower()
        clue = (row[1] if len(row) > 1 else "").strip() or None
        raw_level = (row[2] if len(row) > 2 else "1").strip() or "1"
        try:
            difficulty = int(raw_level)
        except ValueError:
            results.append(ImportRow(line_number, answer, False, "The level must be 1, 2 or 3."))
            continue

        payload: dict[str, object] = {
            "answer": answer,
            "clue": clue,
            "alt_answers": [],
            "difficulty": difficulty,
        }
        problems = _problems_for(payload, youngest=youngest, extra=extra)
        if answer in existing:
            problems.append("That word is already in this pack.")
        if problems:
            results.append(ImportRow(line_number, answer, False, problems[0]))
            continue

        await repo.add_content_item(
            session,
            pack_id=pack.id,
            payload=payload,
            difficulty=difficulty,
            sort_order=base + added,
        )
        existing.add(answer)
        added += 1
        results.append(ImportRow(line_number, answer, True, None))

    await repo.audit(
        session,
        actor_id=actor.id,
        action="content.import",
        target_type="content_pack",
        target_id=str(pack.id),
        details={"added": added, "rejected": sum(1 for r in results if not r.ok)},
    )
    await session.commit()
    return ImportReport(added=added, rows=results)


# ------------------------------------------------------------------- workflow
async def publish_item(
    session: AsyncSession, *, actor: Actor, pack_id: uuid.UUID, item_id: uuid.UUID
) -> ContentItem:
    """Make **one** word live (D-38).

    Three things must hold, and each has its own sentence so the author knows
    what to do next:

    * the word has no problems (the validator decides, not this function);
    * the same word is not already live in this band, or a learner could be
      given the same answer twice in one round;
    * the pack has not been retired.
    """
    _require_contributor(actor)
    pack = await _pack(session, pack_id)
    if pack.status == "retired":
        raise AppError(
            "These words are closed. Start a new set instead.",
            code="pack_retired",
            status_code=409,
        )
    row = await session.get(ContentItem, item_id)
    if row is None or row.pack_id != pack.id:
        raise NotFoundError("That word was not found.")

    if row.status == "live":
        return row

    youngest = pack.age_band == await _youngest_band(session)
    problems = _problems_for(row.payload, youngest=youngest, extra=await _extra_blocked(session))
    if problems:
        raise AppError(
            problems[0], code="item_invalid", status_code=422, details={"problems": problems}
        )

    answer = str(row.payload.get("answer", "")).strip().lower()
    if await repo.content_answer_is_live(
        session,
        game_id=pack.game_id,
        locale=pack.locale,
        age_band=pack.age_band,
        answer=answer,
        exclude_item=row.id,
    ):
        raise AppError("That word is already live.", code="item_already_live", status_code=409)

    now = repo.utcnow()
    row.status = "live"
    row.published_at = now
    row.published_by = actor.id
    if pack.status != "published":
        pack.status = "published"
        pack.published_at = pack.published_at or now
    await repo.audit(
        session,
        actor_id=actor.id,
        action="content.item_publish",
        target_type="content_item",
        target_id=str(row.id),
        details={"pack_id": str(pack.id), "answer": answer},
    )
    await session.commit()
    return row


async def unpublish_item(
    session: AsyncSession, *, actor: Actor, pack_id: uuid.UUID, item_id: uuid.UUID
) -> ContentItem:
    """Take a word out of the games. Never deleted, so the record survives."""
    _require_contributor(actor)
    pack = await _pack(session, pack_id)
    row = await session.get(ContentItem, item_id)
    if row is None or row.pack_id != pack.id:
        raise NotFoundError("That word was not found.")
    if row.status != "live":
        raise AppError("That word is not live.", code="item_not_live", status_code=409)

    row.status = "retired"
    await repo.audit(
        session,
        actor_id=actor.id,
        action="content.item_retire",
        target_type="content_item",
        target_id=str(row.id),
        details={"pack_id": str(pack.id)},
    )
    await session.commit()
    return row


async def publish_ready(session: AsyncSession, *, actor: Actor, pack_id: uuid.UUID) -> int:
    """Make every ready draft word live in one act. Returns how many moved.

    This is the same door as ``publish_item``, opened for 150 words at once
    after a CSV import. A word with a problem is skipped, never forced: the
    bulk button is speed, not a way around the validator.
    """
    _require_contributor(actor)
    pack = await _pack(session, pack_id)
    if pack.status == "retired":
        raise AppError(
            "These words are closed. Start a new set instead.",
            code="pack_retired",
            status_code=409,
        )

    rows = await _item_rows(session, pack.id)
    youngest = pack.age_band == await _youngest_band(session)
    extra = await _extra_blocked(session)
    live_answers = await repo.live_content_answers(
        session, game_id=pack.game_id, locale=pack.locale, age_band=pack.age_band
    )
    now = repo.utcnow()
    made = 0
    for row in rows:
        if row.status != "draft":
            continue
        if _problems_for(row.payload, youngest=youngest, extra=extra):
            continue
        answer = str(row.payload.get("answer", "")).strip().lower()
        if answer in live_answers:
            continue
        row.status = "live"
        row.published_at = now
        row.published_by = actor.id
        live_answers.add(answer)
        made += 1

    if made and pack.status != "published":
        pack.status = "published"
        pack.published_at = pack.published_at or now
    await repo.audit(
        session,
        actor_id=actor.id,
        action="content.publish_ready",
        target_type="content_pack",
        target_id=str(pack.id),
        details={"published": made, "items": len(rows)},
    )
    await session.commit()
    return made


async def retire(session: AsyncSession, *, actor: Actor, pack_id: uuid.UUID) -> ContentPack:
    """Close a set of words: it leaves the games, and its live words go with it."""
    _require_reviewer(actor)
    pack = await _pack(session, pack_id)
    if pack.status == "retired":
        return pack
    for row in await _item_rows(session, pack.id):
        if row.status == "live":
            row.status = "retired"
    pack.status = "retired"
    await repo.audit(
        session,
        actor_id=actor.id,
        action="content.retire",
        target_type="content_pack",
        target_id=str(pack.id),
        details={},
    )
    await session.commit()
    return pack


# ------------------------------------------------------- the blocked word list
@dataclass(frozen=True, slots=True)
class BlockedWordView:
    word: str
    built_in: bool
    added_by: str | None
    created_at: object | None


def _require_admin(actor: Actor) -> None:
    """Only a school admin may change the baseline's additions (D-37).

    A coach can write words; the list that decides what a school will never allow
    is a school-level decision, so it stays with the admin.
    """
    if actor.role is not Role.school_admin:
        raise ForbiddenError("Only a school admin can change this.")


async def blocked_word_list(session: AsyncSession, *, actor: Actor) -> list[BlockedWordView]:
    """The built-in words and the school's additions, in one readable list.

    The built-in entries are shown because a person asking "why was my word
    refused" deserves to find the word here, not to be told "it is in the code".
    """
    _require_reader(actor)
    rows = await repo.blocked_words(session)
    names: dict[uuid.UUID, str] = {}
    for row in rows:
        if row.added_by is not None and row.added_by not in names:
            name = await reviewer_name(session, row.added_by)
            if name:
                names[row.added_by] = name

    added = [
        BlockedWordView(
            word=row.word,
            built_in=False,
            added_by=names.get(row.added_by) if row.added_by else None,
            created_at=row.created_at,
        )
        for row in rows
    ]
    built_in = [
        BlockedWordView(word=word, built_in=True, added_by=None, created_at=None)
        for word in sorted(ws_safe.BLOCKED_WORDS - {row.word for row in rows})
    ]
    return added + built_in


async def add_blocked_word(session: AsyncSession, *, actor: Actor, word: str) -> BlockedWordView:
    """Add a word to the school's list. Effective on the next save of any word."""
    _require_admin(actor)
    normalised = ws_safe.normalise_for_list(word)
    # The table's check constraint also enforces this; refusing here keeps the
    # person reading a sentence instead of a database error.
    if len(normalised) < 2:
        raise AppError(
            "Type a word of two letters or more.",
            code="blocked_word_empty",
            status_code=422,
        )

    if normalised in ws_safe.BLOCKED_WORDS:
        raise AppError(
            "That word is already on the list.", code="blocked_word_exists", status_code=409
        )

    existing = await repo.get_blocked_word(session, normalised)
    if existing is not None:
        return BlockedWordView(
            word=existing.word, built_in=False, added_by=None, created_at=existing.created_at
        )

    await repo.add_blocked_word(session, word=normalised, actor_id=actor.id)
    await repo.audit(
        session,
        actor_id=actor.id,
        action="blocked_word.add",
        target_type="blocked_word",
        target_id=normalised,
        details={},
    )
    await session.commit()
    return BlockedWordView(
        word=normalised, built_in=False, added_by=actor.preferred_name, created_at=repo.utcnow()
    )


async def remove_blocked_word(session: AsyncSession, *, actor: Actor, word: str) -> None:
    """Remove a school's own addition. A built-in entry cannot be removed here."""
    _require_admin(actor)
    normalised = ws_safe.normalise_for_list(word)
    if normalised in ws_safe.BLOCKED_WORDS:
        raise AppError(
            "That word is built in and cannot be removed here.",
            code="blocked_word_builtin",
            status_code=409,
        )
    if await repo.get_blocked_word(session, normalised) is None:
        raise NotFoundError("That word is not on the list.")

    await repo.delete_blocked_word(session, normalised)
    await repo.audit(
        session,
        actor_id=actor.id,
        action="blocked_word.remove",
        target_type="blocked_word",
        target_id=normalised,
        details={},
    )
    await session.commit()


async def reviewer_name(session: AsyncSession, user_id: uuid.UUID | None) -> str | None:
    if user_id is None:
        return None
    user = await session.get(User, user_id)
    return user.preferred_name if user else None


async def age_bands(session: AsyncSession) -> list[AgeBand]:
    """Every band a pack can be written for, youngest first."""
    stmt = select(AgeBand).order_by(AgeBand.min_age.asc())
    return list((await session.execute(stmt)).scalars().all())


@dataclass(frozen=True, slots=True)
class BandSuggestion:
    """What the Words screen should pre-select, and why."""

    age_band: str | None
    label: str | None
    learners: int
    sentence: str | None


async def suggested_band(
    session: AsyncSession, *, actor: Actor, now: dt.datetime | None = None
) -> BandSuggestion:
    """The band most of this coach's learners fall into.

    Writing words used to start with a dropdown and no context. The bands still
    matter (a pack is keyed by one, and serving picks by the learner's band), so
    this keeps the band and removes the guesswork: the screen opens on the band
    the coach's own classes are mostly in, and one tap changes it.

    A coach with no classes, or a class with no birthdays, gets ``None`` and the
    screen simply keeps asking — never a made-up band.
    """
    now = now or dt.datetime.now(dt.UTC)
    classes = await visible_classes(session, actor=actor)
    if not classes:
        return BandSuggestion(age_band=None, label=None, learners=0, sentence=None)

    class_ids = [klass.id for klass in classes]
    birthdays = list(
        (
            await session.execute(
                select(User.date_of_birth)
                .join(ClassMember, ClassMember.user_id == User.id)
                .where(
                    ClassMember.class_id.in_(class_ids),
                    User.role == Role.learner,
                    User.date_of_birth.is_not(None),
                )
            )
        )
        .scalars()
        .all()
    )
    if not birthdays:
        return BandSuggestion(age_band=None, label=None, learners=0, sentence=None)

    bands = await age_bands(session)
    today = now.astimezone(ZoneInfo(actor.school_timezone)).date()
    counts: dict[str, int] = {}
    for birthday in birthdays:
        if birthday is None:  # pragma: no cover - filtered in SQL
            continue
        age = age_on(birthday, today)
        band = next(
            (
                item
                for item in bands
                if item.min_age <= age and (item.max_age is None or item.max_age >= age)
            ),
            None,
        )
        if band is not None:
            counts[band.id] = counts.get(band.id, 0) + 1

    if not counts:
        return BandSuggestion(
            age_band=None, label=None, learners=len(birthdays), sentence=None
        )

    by_id = {item.id: item for item in bands}
    # Most learners first; a tie goes to the younger band, which is the safer
    # default for a word list.
    chosen = min(
        counts.items(),
        key=lambda item: (-item[1], by_id[item[0]].min_age if item[0] in by_id else 99),
    )[0]
    label = by_id[chosen].label if chosen in by_id else chosen
    return BandSuggestion(
        age_band=chosen,
        label=label,
        learners=counts[chosen],
        sentence=f"Most of your learners are in {label.lower()}.",
    )


async def counts(session: AsyncSession) -> dict[str, int]:
    """The numbers the queue header shows, in one query each."""
    rows = (
        await session.execute(
            select(ContentPack.status, func.count())
            .where(ContentPack.game_id == GAME_ID)
            .group_by(ContentPack.status)
        )
    ).all()
    return {str(status): int(count) for status, count in rows}
