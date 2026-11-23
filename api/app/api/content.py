"""Content endpoints (P4-T04, D-38).

Thin, like every router here: authorise by role, call the service, return what
it decided. The service owns the status machine and the validation, so no
endpoint can drift from it.

A word goes live **one at a time**. ``POST .../items/{id}/publish`` is the only
door to the games, and its author may walk through it: the draft step and the
validator are the safety, not a second person.

Content is platform-wide, not per school: a live word is what every school's
learners play. That is why members of staff, and never a learner, may write it.
"""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.games.schemas import (
    BlockedWordIn,
    BlockedWordOut,
    ContentItemIn,
    ContentItemOut,
    ImportIn,
    ImportReportOut,
    ImportRowOut,
    PackCreateIn,
    PackDetailOut,
    PackSummaryOut,
    PublishReadyOut,
)
from app.games.services import content
from app.identity.deps import SessionDep, require_roles
from app.identity.models import Role
from app.identity.service import Actor

router = APIRouter(prefix="/content", tags=["content"])

ContentStaff = Annotated[Actor, Depends(require_roles(Role.coach, Role.school_admin))]


def _summary_out(summary: content.PackSummary) -> PackSummaryOut:
    return PackSummaryOut.model_validate(summary)


def _detail_out(detail: content.PackDetail) -> PackDetailOut:
    return PackDetailOut(
        pack=_summary_out(detail.summary),
        items=[ContentItemOut.model_validate(item) for item in detail.items],
        can_edit=detail.can_edit,
        can_review=detail.can_review,
        can_publish=detail.can_publish,
    )


async def _detail(session: AsyncSession, actor: Actor, pack_id: uuid.UUID) -> PackDetailOut:
    return _detail_out(await content.pack_detail(session, actor=actor, pack_id=pack_id))


async def _item_out(
    session: AsyncSession, actor: Actor, pack_id: uuid.UUID, item_id: uuid.UUID
) -> ContentItemOut:
    detail = await content.pack_detail(session, actor=actor, pack_id=pack_id)
    item = next(i for i in detail.items if i.id == item_id)
    return ContentItemOut.model_validate(item)


@router.get("/age-bands")
async def age_bands(session: SessionDep, actor: ContentStaff) -> list[dict[str, str]]:
    """The groups a pack can be written for, youngest first."""
    rows = await content.age_bands(session)
    return [{"id": band.id, "label": band.label} for band in rows]


@router.get("/suggested-band")
async def suggested_band(session: SessionDep, actor: ContentStaff) -> dict[str, object]:
    """The band most of this coach's learners are in, so the screen can pre-pick it.

    Advisory only: the client still sends an explicit ``age_band`` when it makes
    a list, and any other band remains one tap away.
    """
    row = await content.suggested_band(session, actor=actor)
    return {
        "age_band": row.age_band,
        "label": row.label,
        "learners": row.learners,
        "sentence": row.sentence,
    }


@router.get("/packs")
async def list_packs(session: SessionDep, actor: ContentStaff) -> list[PackSummaryOut]:
    """Every version of every pack, newest first."""
    return [_summary_out(row) for row in await content.list_packs(session, actor=actor)]


@router.get("/packs/{pack_id}")
async def read_pack(pack_id: uuid.UUID, session: SessionDep, actor: ContentStaff) -> PackDetailOut:
    return await _detail(session, actor, pack_id)


@router.post("/packs", status_code=201)
async def create_pack(
    body: PackCreateIn, session: SessionDep, actor: ContentStaff
) -> PackDetailOut:
    """A new draft version, optionally seeded with an existing pack's words."""
    pack = await content.create_draft(
        session, actor=actor, age_band=body.age_band, copy_from=body.copy_from
    )
    return await _detail(session, actor, pack.id)


@router.post("/packs/{pack_id}/items", status_code=201)
async def add_item(
    pack_id: uuid.UUID, body: ContentItemIn, session: SessionDep, actor: ContentStaff
) -> ContentItemOut:
    row = await content.add_item(
        session,
        actor=actor,
        pack_id=pack_id,
        answer=body.answer,
        clue=body.clue,
        difficulty=body.difficulty,
        alt_answers=body.alt_answers,
        allow_problems=body.allow_problems,
    )
    detail = await content.pack_detail(session, actor=actor, pack_id=pack_id)
    item = next(i for i in detail.items if i.id == row.id)
    return ContentItemOut.model_validate(item)


@router.patch("/packs/{pack_id}/items/{item_id}")
async def update_item(
    pack_id: uuid.UUID,
    item_id: uuid.UUID,
    body: ContentItemIn,
    session: SessionDep,
    actor: ContentStaff,
) -> ContentItemOut:
    row = await content.update_item(
        session,
        actor=actor,
        pack_id=pack_id,
        item_id=item_id,
        answer=body.answer,
        clue=body.clue,
        difficulty=body.difficulty,
        alt_answers=body.alt_answers,
    )
    detail = await content.pack_detail(session, actor=actor, pack_id=pack_id)
    item = next(i for i in detail.items if i.id == row.id)
    return ContentItemOut.model_validate(item)


@router.delete("/packs/{pack_id}/items/{item_id}", status_code=204)
async def delete_item(
    pack_id: uuid.UUID, item_id: uuid.UUID, session: SessionDep, actor: ContentStaff
) -> None:
    await content.delete_item(session, actor=actor, pack_id=pack_id, item_id=item_id)


@router.post("/packs/{pack_id}/import")
async def import_words(
    pack_id: uuid.UUID, body: ImportIn, session: SessionDep, actor: ContentStaff
) -> ImportReportOut:
    """``answer, clue, level`` per line, with a line-by-line report."""
    report = await content.import_csv(session, actor=actor, pack_id=pack_id, text=body.text)
    return ImportReportOut(
        added=report.added,
        rows=[
            ImportRowOut(line=row.line, answer=row.answer, ok=row.ok, message=row.message)
            for row in report.rows
        ],
    )


@router.post("/packs/{pack_id}/items/{item_id}/publish")
async def publish_item(
    pack_id: uuid.UUID,
    item_id: uuid.UUID,
    session: SessionDep,
    actor: ContentStaff,
) -> ContentItemOut:
    """Make one word live. The only door to the games."""
    await content.publish_item(session, actor=actor, pack_id=pack_id, item_id=item_id)
    return await _item_out(session, actor, pack_id, item_id)


@router.post("/packs/{pack_id}/items/{item_id}/unpublish")
async def unpublish_item(
    pack_id: uuid.UUID,
    item_id: uuid.UUID,
    session: SessionDep,
    actor: ContentStaff,
) -> ContentItemOut:
    """Take one live word out of the games. Nothing is deleted."""
    await content.unpublish_item(session, actor=actor, pack_id=pack_id, item_id=item_id)
    return await _item_out(session, actor, pack_id, item_id)


@router.post("/packs/{pack_id}/publish-ready")
async def publish_ready(
    pack_id: uuid.UUID, session: SessionDep, actor: ContentStaff
) -> PublishReadyOut:
    """Make every ready draft word live at once, skipping any that still fail."""
    made = await content.publish_ready(session, actor=actor, pack_id=pack_id)
    return PublishReadyOut(published=made)


@router.post("/packs/{pack_id}/retire")
async def retire_pack(
    pack_id: uuid.UUID, session: SessionDep, actor: ContentStaff
) -> PackDetailOut:
    await content.retire(session, actor=actor, pack_id=pack_id)
    return await _detail(session, actor, pack_id)


@router.get("/summary")
async def summary(session: SessionDep, actor: ContentStaff) -> dict[str, int]:
    """How many packs sit in each status, for the queue header."""
    return await content.counts(session)


# ------------------------------------------------------- the blocked word list
# A school admin's screen (D-37). The list is not secret, but it is not for
# learners either, so the endpoints require staff: reading is open to both staff
# roles, changing it is the admin's call (enforced in the service).
BlockedWordAdmin = Annotated[Actor, Depends(require_roles(Role.school_admin))]
BlockedWordReader = ContentStaff


def _blocked_out(row: content.BlockedWordView) -> BlockedWordOut:
    return BlockedWordOut(
        word=row.word,
        built_in=row.built_in,
        added_by=row.added_by,
        created_at=row.created_at,  # type: ignore[arg-type]
    )


@router.get("/blocked-words")
async def blocked_words(session: SessionDep, actor: BlockedWordReader) -> list[BlockedWordOut]:
    """Every word that cannot be used, and where it came from."""
    return [_blocked_out(row) for row in await content.blocked_word_list(session, actor=actor)]


@router.post("/blocked-words", status_code=201)
async def add_blocked_word(
    body: BlockedWordIn, session: SessionDep, actor: BlockedWordAdmin
) -> BlockedWordOut:
    """Add a word. It is refused from the next save onwards, with no deploy."""
    return _blocked_out(await content.add_blocked_word(session, actor=actor, word=body.word))


@router.delete("/blocked-words/{word}", status_code=204)
async def remove_blocked_word(word: str, session: SessionDep, actor: BlockedWordAdmin) -> None:
    """Undo a school's own addition. Built-in entries are refused."""
    await content.remove_blocked_word(session, actor=actor, word=word)
