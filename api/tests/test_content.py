"""Phase 4: writing words, and making them live one at a time (D-38).

The promises under test:

- a word you add is only a draft; a child cannot see it until somebody presses
  *Make it live* on that word;
- the author may make their own word live — the draft step and the validator are
  the safety, not a second person;
- a word that still has a problem cannot go live, at all, by any route;
- the same word cannot be live twice in one band;
- editing a live word sends it back to draft, so nothing changes under a child;
- a live word is taken down, never deleted;
- retiring a set takes its live words out of the games;
- only members of staff may read or write content.
"""

from __future__ import annotations

import uuid

import pytest
from app.core.errors import AppError, ForbiddenError
from app.games import repository as repo
from app.games.models import ContentItem, ContentPack
from app.games.services import content
from app.identity.models import Role, User
from app.identity.service import Actor
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from tests.factories import build_world, login, make_user

BAND = "11-13"


def _actor(user: User, role: Role | None = None) -> Actor:
    return Actor(
        id=user.id,
        role=role or user.role,
        school_id=user.school_id,
        session_id=uuid.uuid4(),
        preferred_name=user.preferred_name,
        avatar_key=user.avatar_key,
        school_timezone="Africa/Lagos",
    )


async def _reset_live_words(db: AsyncSession) -> None:
    """Start from "nothing is live".

    Which words are live is now a global set, and the database these tests run
    against is the development one, already holding the seeded word bank. The
    tests assert exact live sets, so they take the whole set out of play first.
    The outer test transaction is rolled back afterwards (conftest), so the
    development data is untouched once the run ends.
    """
    await db.execute(
        update(ContentItem).where(ContentItem.status == "live").values(status="retired")
    )
    await db.flush()


async def _staff(db: AsyncSession):
    """The two people who may touch words: a coach and a school admin."""
    await _reset_live_words(db)
    world = await build_world(db)
    writer = await make_user(
        db,
        school=world.school_a,
        role=Role.coach,
        code="WRITER-1",
        preferred="Writer",
    )
    admin = await make_user(
        db,
        school=world.school_a,
        role=Role.school_admin,
        code="ADMIN-1",
        preferred="Admin",
    )
    return world, writer, admin


WORDS = [
    ("apple", "A red or green fruit"),
    ("bread", "You eat it with butter"),
    ("chair", "You sit on it"),
    ("dance", "Moving your body to music"),
    ("eagle", "A big bird"),
    ("flame", "It is hot and bright"),
    ("grape", "A small purple fruit"),
    ("house", "People live in it"),
    ("igloo", "A house made of ice"),
    ("juice", "A drink made from fruit"),
    ("kite", "It flies on a string"),
    ("lemon", "A sour yellow fruit"),
    ("money", "You use it to buy things"),
    ("night", "The dark part of the day"),
    ("ocean", "A very big sea"),
    ("paper", "You write on it"),
    ("queen", "A woman who rules"),
    ("river", "Water that flows"),
    ("stone", "It is hard and heavy"),
    ("table", "You put food on it"),
]


async def _draft_with_words(db: AsyncSession, writer: User, count: int = 15) -> ContentPack:
    actor = _actor(writer)
    pack = await content.create_draft(db, actor=actor, age_band=BAND)
    for answer, clue in WORDS[:count]:
        await content.add_item(
            db,
            actor=actor,
            pack_id=pack.id,
            answer=answer,
            clue=clue,
            difficulty=1,
        )
    await db.refresh(pack)
    return pack


async def _item(db: AsyncSession, pack: ContentPack, answer: str) -> ContentItem:
    for row in await repo.pack_items(db, pack.id):
        if str(row.payload.get("answer")) == answer:
            return row
    raise AssertionError(f"{answer} is not in the pack")


# ---------------------------------------------------------- the word workflow
async def test_a_new_word_is_a_draft_and_only_goes_live_when_asked(
    db_session: AsyncSession,
) -> None:
    _world, writer, _admin = await _staff(db_session)
    pack = await _draft_with_words(db_session, writer, count=3)

    # Typed, saved, and invisible to a child.
    assert all(row.status == "draft" for row in await repo.pack_items(db_session, pack.id))
    live = await repo.live_items(db_session, game_id="word_scramble", locale="en", age_band=BAND)
    assert live == []

    apple = await _item(db_session, pack, "apple")
    await content.publish_item(db_session, actor=_actor(writer), pack_id=pack.id, item_id=apple.id)

    live = await repo.live_items(db_session, game_id="word_scramble", locale="en", age_band=BAND)
    assert [str(row.payload["answer"]) for row in live] == ["apple"]

    await db_session.refresh(pack)
    assert pack.status == "published" and pack.published_at is not None


async def test_the_author_may_publish_their_own_word(db_session: AsyncSession) -> None:
    """D-38: the draft step is the safety, not a second person."""
    _world, writer, _admin = await _staff(db_session)
    pack = await _draft_with_words(db_session, writer, count=1)
    apple = await _item(db_session, pack, "apple")

    await content.publish_item(db_session, actor=_actor(writer), pack_id=pack.id, item_id=apple.id)
    await db_session.refresh(apple)
    assert apple.status == "live"
    assert apple.published_by == writer.id and apple.published_at is not None


async def test_a_word_with_a_problem_cannot_go_live(db_session: AsyncSession) -> None:
    _world, writer, _admin = await _staff(db_session)
    pack = await content.create_draft(db_session, actor=_actor(writer), age_band=BAND)
    row = await content.add_item(
        db_session,
        actor=_actor(writer),
        pack_id=pack.id,
        answer="apple",
        clue="An apple is a fruit",
        difficulty=1,
        allow_problems=True,
    )

    with pytest.raises(AppError) as caught:
        await content.publish_item(
            db_session, actor=_actor(writer), pack_id=pack.id, item_id=row.id
        )
    assert caught.value.code == "item_invalid"

    # The bulk door is not a way around it either.
    assert await content.publish_ready(db_session, actor=_actor(writer), pack_id=pack.id) == 0
    await db_session.refresh(row)
    assert row.status == "draft"


async def test_bulk_publish_makes_the_ready_words_live_and_skips_the_rest(
    db_session: AsyncSession,
) -> None:
    _world, writer, _admin = await _staff(db_session)
    pack = await _draft_with_words(db_session, writer, count=4)
    await content.add_item(
        db_session,
        actor=_actor(writer),
        pack_id=pack.id,
        answer="zebra",
        clue="A zebra has stripes",
        difficulty=1,
        allow_problems=True,
    )

    made = await content.publish_ready(db_session, actor=_actor(writer), pack_id=pack.id)
    assert made == 4

    live = await repo.live_items(db_session, game_id="word_scramble", locale="en", age_band=BAND)
    assert len(live) == 4
    assert "zebra" not in {str(row.payload["answer"]) for row in live}


async def test_editing_a_live_word_sends_it_back_to_draft(db_session: AsyncSession) -> None:
    """A word children are playing must not change under them."""
    _world, writer, _admin = await _staff(db_session)
    pack = await _draft_with_words(db_session, writer, count=1)
    apple = await _item(db_session, pack, "apple")
    await content.publish_item(db_session, actor=_actor(writer), pack_id=pack.id, item_id=apple.id)

    await content.update_item(
        db_session,
        actor=_actor(writer),
        pack_id=pack.id,
        item_id=apple.id,
        answer="apple",
        clue="A crunchy fruit",
        difficulty=1,
    )
    await db_session.refresh(apple)
    assert apple.status == "draft" and apple.published_at is None
    live = await repo.live_items(db_session, game_id="word_scramble", locale="en", age_band=BAND)
    assert live == []


async def test_a_live_word_is_taken_down_not_deleted(db_session: AsyncSession) -> None:
    _world, writer, admin = await _staff(db_session)
    pack = await _draft_with_words(db_session, writer, count=1)
    apple = await _item(db_session, pack, "apple")
    await content.publish_item(db_session, actor=_actor(writer), pack_id=pack.id, item_id=apple.id)

    with pytest.raises(AppError) as caught:
        await content.delete_item(
            db_session, actor=_actor(writer), pack_id=pack.id, item_id=apple.id
        )
    assert caught.value.code == "item_not_draft"

    # Either member of staff may take it down, and the row survives.
    await content.unpublish_item(db_session, actor=_actor(admin), pack_id=pack.id, item_id=apple.id)
    await db_session.refresh(apple)
    assert apple.status == "retired"
    assert await repo.pack_items(db_session, pack.id) != []


async def test_a_word_cannot_be_live_twice_in_one_band(db_session: AsyncSession) -> None:
    _world, writer, _admin = await _staff(db_session)
    first = await _draft_with_words(db_session, writer, count=1)
    apple = await _item(db_session, first, "apple")
    await content.publish_item(db_session, actor=_actor(writer), pack_id=first.id, item_id=apple.id)

    second = await content.create_draft(db_session, actor=_actor(writer), age_band=BAND)
    copy = await content.add_item(
        db_session,
        actor=_actor(writer),
        pack_id=second.id,
        answer="apple",
        clue="A different clue for the same fruit",
        difficulty=1,
    )
    with pytest.raises(AppError) as caught:
        await content.publish_item(
            db_session, actor=_actor(writer), pack_id=second.id, item_id=copy.id
        )
    assert caught.value.code == "item_already_live"


async def test_retiring_a_set_takes_its_words_out_of_the_games(
    db_session: AsyncSession,
) -> None:
    _world, writer, admin = await _staff(db_session)
    pack = await _draft_with_words(db_session, writer, count=3)
    await content.publish_ready(db_session, actor=_actor(writer), pack_id=pack.id)

    await content.retire(db_session, actor=_actor(admin), pack_id=pack.id)

    live = await repo.live_items(db_session, game_id="word_scramble", locale="en", age_band=BAND)
    assert live == []
    await db_session.refresh(pack)
    assert pack.status == "retired"
    assert all(row.status == "retired" for row in await repo.pack_items(db_session, pack.id))


async def test_a_closed_set_accepts_no_new_words(db_session: AsyncSession) -> None:
    _world, writer, admin = await _staff(db_session)
    pack = await _draft_with_words(db_session, writer, count=1)
    await content.retire(db_session, actor=_actor(admin), pack_id=pack.id)

    with pytest.raises(AppError) as caught:
        await content.add_item(
            db_session,
            actor=_actor(writer),
            pack_id=pack.id,
            answer="zebra",
            clue="A striped animal",
            difficulty=1,
        )
    assert caught.value.code == "pack_retired"


# ---------------------------------------------------------------- validation
async def test_a_word_that_gives_itself_away_is_refused(db_session: AsyncSession) -> None:
    _world, writer, _admin = await _staff(db_session)
    pack = await content.create_draft(db_session, actor=_actor(writer), age_band=BAND)

    with pytest.raises(AppError) as caught:
        await content.add_item(
            db_session,
            actor=_actor(writer),
            pack_id=pack.id,
            answer="apple",
            clue="An apple is a fruit",
            difficulty=1,
        )
    assert caught.value.code == "item_invalid"
    assert "gives away the answer" in caught.value.message

    # A draft may be saved untidy, on purpose...
    row = await content.add_item(
        db_session,
        actor=_actor(writer),
        pack_id=pack.id,
        answer="apple",
        clue="An apple is a fruit",
        difficulty=1,
        allow_problems=True,
    )
    assert row.status == "draft"


async def test_a_duplicate_word_is_refused(db_session: AsyncSession) -> None:
    _world, writer, _admin = await _staff(db_session)
    pack = await _draft_with_words(db_session, writer, count=1)
    with pytest.raises(AppError) as caught:
        await content.add_item(
            db_session,
            actor=_actor(writer),
            pack_id=pack.id,
            answer="APPLE",
            clue="Another clue for the same fruit",
            difficulty=1,
        )
    assert "already in this pack" in caught.value.message


async def test_an_unsafe_word_is_refused_and_can_never_go_live(
    db_session: AsyncSession,
) -> None:
    """P4-T03: the blocklist is checked on the way in *and* at the live door."""
    _world, writer, _admin = await _staff(db_session)
    pack = await content.create_draft(db_session, actor=_actor(writer), age_band=BAND)

    with pytest.raises(AppError) as caught:
        await content.add_item(
            db_session,
            actor=_actor(writer),
            pack_id=pack.id,
            answer="shit",
            clue="A rude word",
            difficulty=1,
        )
    assert caught.value.code == "item_invalid"
    assert "not safe for children" in caught.value.message

    # Saved anyway (a draft may be untidy) it still has a problem, so both
    # doors to the games stay shut.
    row = await content.add_item(
        db_session,
        actor=_actor(writer),
        pack_id=pack.id,
        answer="shit",
        clue="A rude word",
        difficulty=1,
        allow_problems=True,
    )
    with pytest.raises(AppError) as caught:
        await content.publish_item(
            db_session, actor=_actor(writer), pack_id=pack.id, item_id=row.id
        )
    assert caught.value.code == "item_invalid"
    assert await content.publish_ready(db_session, actor=_actor(writer), pack_id=pack.id) == 0

    await db_session.refresh(row)
    assert row.status == "draft"


async def test_a_clean_word_in_an_unsafe_clue_is_refused(db_session: AsyncSession) -> None:
    _world, writer, _admin = await _staff(db_session)
    pack = await content.create_draft(db_session, actor=_actor(writer), age_band=BAND)

    with pytest.raises(AppError) as caught:
        await content.add_item(
            db_session,
            actor=_actor(writer),
            pack_id=pack.id,
            answer="apple",
            clue="A fucking fruit",
            difficulty=1,
        )
    assert "not safe for children" in caught.value.message


async def test_the_youngest_band_needs_a_picture_or_a_sound(db_session: AsyncSession) -> None:
    _world, writer, _admin = await _staff(db_session)
    pack = await content.create_draft(db_session, actor=_actor(writer), age_band="8-10")
    with pytest.raises(AppError) as caught:
        await content.add_item(
            db_session,
            actor=_actor(writer),
            pack_id=pack.id,
            answer="apple",
            clue="A fruit",
            difficulty=1,
        )
    assert "picture or a sound" in caught.value.message


# ----------------------------------------------------------------- CSV import
async def test_import_keeps_good_rows_and_explains_bad_ones(db_session: AsyncSession) -> None:
    _world, writer, _admin = await _staff(db_session)
    pack = await content.create_draft(db_session, actor=_actor(writer), age_band=BAND)

    report = await content.import_csv(
        db_session,
        actor=_actor(writer),
        pack_id=pack.id,
        text="\n".join(
            [
                "apple, A red or green fruit, 1",
                "zzzz, All the same letter, 1",
                "bread, , 1",
                "chair, You sit on it, 9",
                "apple, Repeated word, 1",
                "bread, You eat it with butter, 1",
            ]
        ),
    )
    assert report.added == 2
    assert [row.ok for row in report.rows] == [True, False, False, False, False, True]
    assert "mix" in (report.rows[1].message or "").lower()
    assert "clue" in (report.rows[2].message or "").lower()
    assert "difficulty" in (report.rows[3].message or "").lower()
    assert "already" in (report.rows[4].message or "").lower()

    rows = await repo.pack_items(db_session, pack.id)
    assert len(rows) == 2
    assert all(row.status == "draft" for row in rows)
    assert {str(item.payload["answer"]) for item in rows} == {"apple", "bread"}


# --------------------------------------------------------------- permissions
async def test_a_learner_cannot_touch_content(db_session: AsyncSession) -> None:
    world = await build_world(db_session)
    with pytest.raises(ForbiddenError):
        await content.list_packs(db_session, actor=_actor(world.learner_a))
    with pytest.raises(ForbiddenError):
        await content.create_draft(db_session, actor=_actor(world.learner_a), age_band=BAND)


async def test_a_coach_may_read_and_write_content(db_session: AsyncSession) -> None:
    world, writer, _admin = await _staff(db_session)
    assert await content.list_packs(db_session, actor=_actor(writer)) is not None
    assert world.coach_a.role is Role.coach


async def test_the_router_enforces_the_same_roles(client, db_session: AsyncSession) -> None:
    world, writer, _admin = await _staff(db_session)

    await login(client, world.learner_a)
    assert (await client.get("/api/content/packs")).status_code == 403

    await login(client, writer)
    created = await client.post("/api/content/packs", json={"age_band": BAND})
    assert created.status_code == 201
    body = created.json()
    assert body["pack"]["status"] == "draft" and body["pack"]["version"] >= 1
    assert body["can_edit"] is True

    pack_id = body["pack"]["id"]
    added = await client.post(
        f"/api/content/packs/{pack_id}/items",
        json={"answer": "apple", "clue": "A red or green fruit", "difficulty": 1},
    )
    assert added.status_code == 201
    item = added.json()
    assert item["status"] == "draft"
    assert sorted(item["scrambled"]) == sorted("apple") and item["scrambled"] != "apple"

    # The one word the screen can publish, and it is the author's own.
    published = await client.post(f"/api/content/packs/{pack_id}/items/{item['id']}/publish")
    assert published.status_code == 200
    assert published.json()["status"] == "live"

    taken_down = await client.post(f"/api/content/packs/{pack_id}/items/{item['id']}/unpublish")
    assert taken_down.status_code == 200
    assert taken_down.json()["status"] == "retired"

    detail = await client.get(f"/api/content/packs/{pack_id}")
    assert detail.json()["pack"]["live_count"] == 0


async def test_every_word_action_is_audited(db_session: AsyncSession) -> None:
    _world, writer, _admin = await _staff(db_session)
    pack = await _draft_with_words(db_session, writer, count=1)
    apple = await _item(db_session, pack, "apple")
    await content.publish_item(db_session, actor=_actor(writer), pack_id=pack.id, item_id=apple.id)
    await content.unpublish_item(
        db_session, actor=_actor(writer), pack_id=pack.id, item_id=apple.id
    )

    rows = (
        await db_session.execute(
            select(repo.AuditEntry.action, func.count())
            .where(repo.AuditEntry.target_id == str(pack.id))
            .group_by(repo.AuditEntry.action)
        )
    ).all()
    counts = {action: count for action, count in rows}
    assert counts["content.pack_create"] == 1

    item_rows = (
        await db_session.execute(
            select(repo.AuditEntry.action, func.count())
            .where(repo.AuditEntry.target_id == str(apple.id))
            .group_by(repo.AuditEntry.action)
        )
    ).all()
    item_counts = {action: count for action, count in item_rows}
    assert item_counts["content.item_add"] == 1
    assert item_counts["content.item_publish"] == 1
    assert item_counts["content.item_retire"] == 1


# ------------------------------------------------------- the blocked word list
async def test_a_school_admin_can_block_a_word_and_it_bites_at_once(
    db_session: AsyncSession,
) -> None:
    """No deploy, no restart: the next save is refused (P4-T03)."""
    _world, writer, admin = await _staff(db_session)
    view = await content.add_blocked_word(db_session, actor=_actor(admin), word="Balderdash")
    assert view.word == "balderdash"

    pack = await content.create_draft(db_session, actor=_actor(writer), age_band=BAND)
    with pytest.raises(AppError) as caught:
        await content.add_item(
            db_session,
            actor=_actor(writer),
            pack_id=pack.id,
            answer="balderdash",
            clue="Nonsense talk",
            difficulty=1,
        )
    assert caught.value.code == "item_invalid"
    assert "not safe for children" in caught.value.message

    # A saved draft cannot be pushed live either.
    row = await content.add_item(
        db_session,
        actor=_actor(writer),
        pack_id=pack.id,
        answer="waffle",
        clue="A soft breakfast food",
        difficulty=1,
    )
    await content.add_blocked_word(db_session, actor=_actor(admin), word="waffle")
    with pytest.raises(AppError) as caught:
        await content.publish_item(
            db_session, actor=_actor(writer), pack_id=pack.id, item_id=row.id
        )
    assert caught.value.code == "item_invalid"


async def test_removing_a_word_lets_it_be_used_again(db_session: AsyncSession) -> None:
    _world, writer, admin = await _staff(db_session)
    await content.add_blocked_word(db_session, actor=_actor(admin), word="wicked")
    await content.remove_blocked_word(db_session, actor=_actor(admin), word="wicked")

    pack = await content.create_draft(db_session, actor=_actor(writer), age_band=BAND)
    row = await content.add_item(
        db_session,
        actor=_actor(writer),
        pack_id=pack.id,
        answer="wicked",
        clue="Very bad, in a story",
        difficulty=1,
    )
    assert row.status == "draft"


async def test_a_built_in_word_cannot_be_removed_or_added_again(
    db_session: AsyncSession,
) -> None:
    _world, _writer, admin = await _staff(db_session)
    with pytest.raises(AppError) as caught:
        await content.add_blocked_word(db_session, actor=_actor(admin), word="shit")
    assert caught.value.code == "blocked_word_exists"

    with pytest.raises(AppError) as caught:
        await content.remove_blocked_word(db_session, actor=_actor(admin), word="shit")
    assert caught.value.code == "blocked_word_builtin"


async def test_only_a_school_admin_may_change_the_list(db_session: AsyncSession) -> None:
    _world, writer, admin = await _staff(db_session)
    with pytest.raises(ForbiddenError):
        await content.add_blocked_word(db_session, actor=_actor(writer), word="naughty")

    # Both staff roles may read it: a coach needs to know why a word was refused.
    rows = await content.blocked_word_list(db_session, actor=_actor(writer))
    assert any(row.word == "shit" and row.built_in for row in rows)


async def test_an_empty_word_is_nonsense(db_session: AsyncSession) -> None:
    _world, _writer, admin = await _staff(db_session)
    with pytest.raises(AppError) as caught:
        await content.add_blocked_word(db_session, actor=_actor(admin), word="!!!")
    assert caught.value.code == "blocked_word_empty"


async def test_the_router_keeps_learners_out(client, db_session: AsyncSession) -> None:
    world, _writer, admin = await _staff(db_session)

    await login(client, world.learner_a)
    assert (await client.get("/api/content/blocked-words")).status_code == 403

    await login(client, admin)
    added = await client.post("/api/content/blocked-words", json={"word": "flibbertigibbet"})
    assert added.status_code == 201
    assert added.json()["word"] == "flibbertigibbet"

    listed = await client.get("/api/content/blocked-words")
    assert listed.status_code == 200
    assert any(row["word"] == "flibbertigibbet" and not row["built_in"] for row in listed.json())
    assert any(row["built_in"] for row in listed.json())

    removed = await client.delete("/api/content/blocked-words/flibbertigibbet")
    assert removed.status_code == 204


async def test_the_words_screen_starts_on_the_band_most_learners_are_in(
    db_session: AsyncSession,
) -> None:
    """No dropdown guesswork: the coach's own classes decide the default.

    The band still exists and still keys the pack; this only removes the blank
    "Pick one" that made every coach answer a question they had no numbers for.
    """
    import datetime as dt

    world = await build_world(db_session)
    world.learner_a.date_of_birth = dt.date(2015, 3, 1)
    world.learner_a2.date_of_birth = dt.date(2014, 8, 20)
    await db_session.flush()

    row = await content.suggested_band(
        db_session,
        actor=_actor(world.coach_a),
        now=dt.datetime(2026, 11, 14, 9, 0, tzinfo=dt.UTC),
    )
    assert row.age_band == BAND
    assert row.learners == 2
    assert row.sentence == "Most of your learners are in ages 11 to 13."


async def test_a_coach_with_no_classes_is_never_given_a_made_up_band(
    db_session: AsyncSession,
) -> None:
    world = await build_world(db_session)
    lone = await make_user(
        db_session,
        school=world.school_a,
        role=Role.coach,
        code="COACH-LONE",
        preferred="New Coach",
        real="New Coach",
    )

    row = await content.suggested_band(db_session, actor=_actor(lone))
    assert row.age_band is None
    assert row.sentence is None
