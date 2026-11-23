"""Phase 9: downloading words for offline play (P9-T02).

The promises under test:

- a learner downloads their **own** band's live words, at one level;
- the bundle carries clues, including the picture/sound references the round
  needs when there is no network;
- it carries no seed, no session and no token, so nothing downloaded can be
  scored or ranked (D-12);
- a word retired in the Words screen is gone from the next download;
- a band with too few live words is refused with a sentence, not an empty pack;
- a game that needs the network is refused by name;
- the same content produces the same pack version, so the client can tell
  "already downloaded" from "update available".
"""

from __future__ import annotations

import datetime as dt

import pytest
from app.games.models import ContentItem
from app.identity.models import Role
from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession

from tests.factories import build_world, login, make_user

URL = "/api/games/offline/packs"


def _forbidden_keys(value: object) -> set[str]:
    found: set[str] = set()
    if isinstance(value, dict):
        found.update(value.keys())
        for item in value.values():
            found |= _forbidden_keys(item)
    elif isinstance(value, list):
        for item in value:
            found |= _forbidden_keys(item)
    return found


async def _retire_every_live_word(db: AsyncSession) -> None:
    """Take the whole bank out of play; the test transaction restores it."""
    await db.execute(
        update(ContentItem).where(ContentItem.status == "live").values(status="retired")
    )
    await db.flush()


async def test_a_learner_downloads_their_own_bands_words(
    client, db_session: AsyncSession
) -> None:
    world = await build_world(db_session)
    await login(client, world.learner_a)

    response = await client.get(URL, params={"game": "word-scramble", "difficulty": 1})
    assert response.status_code == 200, response.text
    body = response.json()

    assert body["game_id"] == "word_scramble"
    assert body["age_band"] == "11-13"
    assert body["difficulty"] == 1
    assert body["item_count"] == len(body["items"])
    assert body["item_count"] >= 15
    assert body["item_count"] <= 200
    # The version is level.pack.size.stamp, so it compares as a plain string.
    assert len(body["pack_version"].split(".")) == 4

    for item in body["items"]:
        assert item["answer"] == item["answer"].strip().lower()
        assert item["difficulty"] == 1
        # The clue keys must survive: an offline round still shows its picture.
        assert {"clue", "clue_image_key", "clue_audio_key"} <= set(item)


async def test_the_pack_never_carries_a_seed_or_a_session(
    client, db_session: AsyncSession
) -> None:
    world = await build_world(db_session)
    await login(client, world.learner_a)

    body = (
        await client.get(URL, params={"game": "word_scramble", "difficulty": 2})
    ).json()
    keys = _forbidden_keys(body)

    assert not {"seed", "session_id", "session_token", "token", "rounds"} & keys
    # Nothing about the learner's identity travels with the words either.
    assert not {"real_name", "student_code", "user_id"} & keys


async def test_signing_out_stops_the_download(client, db_session: AsyncSession) -> None:
    await build_world(db_session)
    response = await client.get(URL, params={"game": "word_scramble"})
    assert response.status_code == 401


async def test_a_game_that_needs_the_network_is_refused(
    client, db_session: AsyncSession
) -> None:
    world = await build_world(db_session)
    await login(client, world.learner_a)

    response = await client.get(URL, params={"game": "checkers"})
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "offline_not_available"


async def test_a_band_with_no_live_words_is_refused_with_a_sentence(
    client, db_session: AsyncSession
) -> None:
    world = await build_world(db_session)
    await login(client, world.learner_a)
    await _retire_every_live_word(db_session)

    response = await client.get(URL, params={"game": "word_scramble", "difficulty": 1})
    assert response.status_code == 409
    body = response.json()["error"]
    assert body["code"] == "not_enough_content"
    # Appendix D: a sentence a child can read, never the code.
    assert body["message"].endswith(".")


async def test_a_learner_outside_every_band_gets_no_pack(
    client, db_session: AsyncSession
) -> None:
    world = await build_world(db_session)
    grown_up = await make_user(
        db_session,
        school=world.school_a,
        role=Role.learner,
        preferred="Grown Up",
        date_of_birth=dt.date(1990, 1, 1),
    )
    await login(client, grown_up)

    response = await client.get(URL, params={"game": "word_scramble", "difficulty": 1})
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "not_enough_content"


async def test_the_pack_version_is_stable_until_the_words_change(
    client, db_session: AsyncSession
) -> None:
    world = await build_world(db_session)
    await login(client, world.learner_a)

    first = (await client.get(URL, params={"game": "word_scramble", "difficulty": 1})).json()
    second = (await client.get(URL, params={"game": "word_scramble", "difficulty": 1})).json()
    assert first["pack_version"] == second["pack_version"]

    third = (await client.get(URL, params={"game": "word_scramble", "difficulty": 2})).json()
    # A different level is a different set of words, so its own version.
    assert third["pack_version"] != first["pack_version"]


async def test_a_retired_word_leaves_the_next_download(
    client, db_session: AsyncSession
) -> None:
    world = await build_world(db_session)
    await login(client, world.learner_a)

    before = (await client.get(URL, params={"game": "word_scramble", "difficulty": 1})).json()
    victim = before["items"][0]["id"]

    await db_session.execute(
        update(ContentItem).where(ContentItem.id == victim).values(status="retired")
    )
    await db_session.flush()

    after = (await client.get(URL, params={"game": "word_scramble", "difficulty": 1})).json()
    assert victim not in {item["id"] for item in after["items"]}
    assert after["pack_version"] != before["pack_version"]


@pytest.mark.parametrize("difficulty", [0, 4])
async def test_an_impossible_level_is_refused(
    client, db_session: AsyncSession, difficulty: int
) -> None:
    world = await build_world(db_session)
    await login(client, world.learner_a)

    response = await client.get(
        URL, params={"game": "word_scramble", "difficulty": difficulty}
    )
    assert response.status_code == 422
