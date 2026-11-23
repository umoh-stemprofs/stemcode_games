"""Starter Word Scramble content (P4-T06).

150 original words with clues, spread evenly across the three difficulties and
published for the two pilot age bands. Every item is checked by the same
validator a contributor would face (P4-T03), so a typo in this table fails the
seed instead of reaching a child.

Why two bands and not four: 150 words x four bands x three review passes is a
content project in itself. The pilot ships the two middle bands; the older and
younger ones wait for a real review cycle.

Clues: D.3 says a clue must never be text-only for a young reader, and the D.5
first-session test is run with a player who cannot read the clue. Every easy
word that honestly has a picture now carries one (``PICTURES``), and the screen
shows it large beside the words. The rest of the bank is still text-only: the
medium and hard words, three easy ones with no honest picture (table, brave,
window), and every word in the 8-10 band, which must not be published until it
has picture or sound clues.
"""

from __future__ import annotations

import datetime as dt
import uuid
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.games.domain import wordscramble as rules
from app.games.models import ContentItem, ContentPack
from app.identity.models import User

LOCALE = "en"
GAME_ID = "word_scramble"
VERSION = 1
PUBLISHED_BANDS = ("11-13", "14-16")
NAMESPACE = uuid.UUID("2f4c6d0e-8a1b-4c3d-9e5f-7a8b9c0d1e2f")

# (answer, clue, difficulty)
STARTER_WORDS: tuple[tuple[str, str, int], ...] = (
    # ---------------------------------------------------------------- easy
    ("apple", "A red or green fruit", 1),
    ("bread", "We make toast with it", 1),
    ("chair", "You sit on this", 1),
    ("table", "It has a flat top and legs", 1),
    ("water", "You drink it every day", 1),
    ("house", "People live inside it", 1),
    ("green", "The colour of grass", 1),
    ("happy", "How you feel when you smile", 1),
    ("river", "Water that flows to the sea", 1),
    ("cloud", "A white shape in the sky", 1),
    ("music", "You hear it in a song", 1),
    ("light", "It comes from the sun or a lamp", 1),
    ("stone", "A small piece of rock", 1),
    ("pencil", "You write with it", 1),
    ("school", "Lessons happen here", 1),
    ("friend", "Someone you like to play with", 1),
    ("garden", "Flowers grow here", 1),
    ("market", "People buy food here", 1),
    ("night", "It is dark and you sleep", 1),
    ("dance", "Moving your body to music", 1),
    ("tiger", "A big cat with stripes", 1),
    ("horse", "You can ride this animal", 1),
    ("clock", "It tells you the time", 1),
    ("shoes", "You wear them on your feet", 1),
    ("plate", "You put food on it", 1),
    ("grass", "Green plants on the ground", 1),
    ("smile", "You do this with your mouth", 1),
    ("train", "It runs on rails", 1),
    ("beach", "Sand next to the sea", 1),
    ("sheep", "A white farm animal with wool", 1),
    ("plant", "It grows in soil", 1),
    ("money", "You use it to buy things", 1),
    ("sugar", "Sweet white grains", 1),
    ("paper", "You write on it", 1),
    ("honey", "Bees make it", 1),
    ("month", "There are twelve in a year", 1),
    ("shape", "A circle is one", 1),
    ("story", "It has a beginning and an end", 1),
    ("laugh", "The sound of a good joke", 1),
    ("juice", "A drink made from fruit", 1),
    ("socks", "You wear them inside shoes", 1),
    ("phone", "You talk to people with it", 1),
    ("brush", "You use it on your hair", 1),
    ("clean", "Not dirty", 1),
    ("empty", "It has nothing inside", 1),
    ("heavy", "Hard to lift", 1),
    ("quiet", "Very little sound", 1),
    ("brave", "Not afraid", 1),
    ("tired", "You need sleep", 1),
    ("window", "You look through it", 1),
    # -------------------------------------------------------------- medium
    ("teacher", "A person who helps you learn", 2),
    ("morning", "The early part of the day", 2),
    ("kitchen", "The room where food is cooked", 2),
    ("brother", "A boy in your family", 2),
    ("journey", "A trip from one place to another", 2),
    ("mountain", "A very high hill", 2),
    ("language", "The words a group of people speak", 2),
    ("question", "Something you ask", 2),
    ("library", "A place full of books", 2),
    ("holiday", "A day with no work", 2),
    ("message", "Words you send to someone", 2),
    ("picture", "A drawing or a photo", 2),
    ("weather", "Rain, sun or wind", 2),
    ("animal", "A living thing that is not a plant", 2),
    ("bicycle", "It has two wheels and pedals", 2),
    ("chicken", "A farm bird that lays eggs", 2),
    ("evening", "The end of the afternoon", 2),
    ("promise", "You say you will surely do it", 2),
    ("village", "A small group of homes", 2),
    ("station", "Where a train stops", 2),
    ("balloon", "You blow it up for a party", 2),
    ("feather", "It covers a bird", 2),
    ("glasses", "You wear them to see better", 2),
    ("blanket", "It keeps you warm in bed", 2),
    ("luggage", "Bags you take on a trip", 2),
    ("whisper", "To speak very softly", 2),
    ("thunder", "The loud noise after lightning", 2),
    ("harvest", "Gathering crops from a field", 2),
    ("island", "Land with water all around it", 2),
    ("factory", "A building where things are made", 2),
    ("gallery", "A place to see art", 2),
    ("improve", "To make something better", 2),
    ("include", "To have as one of the parts", 2),
    ("arrange", "To put things in order", 2),
    ("compare", "To look for what is the same", 2),
    ("explain", "To make something clear", 2),
    ("explore", "To go and find out about a place", 2),
    ("balance", "Not falling to one side", 2),
    ("careful", "Doing something with attention", 2),
    ("curious", "Wanting to know more", 2),
    ("dessert", "Sweet food after a meal", 2),
    ("diamond", "A very hard, clear stone", 2),
    ("distance", "The space between two places", 2),
    ("freedom", "Being able to do what you choose", 2),
    ("grammar", "The rules for putting words together", 2),
    ("honesty", "Telling the truth", 2),
    ("invented", "Made for the first time", 2),
    ("machine", "Something with parts that does work", 2),
    ("midnight", "Twelve at night", 2),
    ("sunflower", "A tall yellow flower", 2),
    # ---------------------------------------------------------------- hard
    ("adventure", "An exciting trip", 3),
    ("afternoon", "The time after midday", 3),
    ("attention", "Looking and listening closely", 3),
    ("beautiful", "Very lovely to look at", 3),
    ("behaviour", "The way a person acts", 3),
    ("breakfast", "The first meal of the day", 3),
    ("celebrate", "To mark a special day", 3),
    ("chocolate", "A sweet brown treat", 3),
    ("classroom", "A room where lessons happen", 3),
    ("dangerous", "Not safe", 3),
    ("different", "Not the same", 3),
    ("difficult", "Hard to do", 3),
    ("education", "Learning at school", 3),
    ("excellent", "Of the very best quality", 3),
    ("furniture", "Tables, chairs and beds", 3),
    ("happiness", "The feeling of being glad", 3),
    ("important", "It matters a lot", 3),
    ("invisible", "You cannot see it", 3),
    ("knowledge", "What you have learned", 3),
    ("magazine", "You read it every month", 3),
    ("necessary", "You must have it", 3),
    ("opposite", "Facing the other way", 3),
    ("practise", "To do something to get better", 3),
    ("probably", "Most likely to happen", 3),
    ("remember", "To keep something in your mind", 3),
    ("surprise", "Something you did not expect", 3),
    ("telephone", "A device for talking far away", 3),
    ("therefore", "For that reason", 3),
    ("together", "With one another", 3),
    ("understand", "To know what something means", 3),
    ("university", "A place to study after school", 3),
    ("vegetable", "A carrot is one", 3),
    ("wonderful", "Very, very good", 3),
    ("yesterday", "The day before today", 3),
    ("basketball", "A game played with a hoop", 3),
    ("calculator", "It helps with numbers", 3),
    ("dictionary", "It lists words and meanings", 3),
    ("electricity", "It powers lights", 3),
    ("experiment", "A test to learn something", 3),
    ("generation", "People born about the same time", 3),
    ("imagination", "Pictures in your mind", 3),
    ("information", "Facts about something", 3),
    ("instruction", "It tells you how to do something", 3),
    ("mathematics", "The study of numbers", 3),
    ("neighborhood", "The area around your home", 3),
    ("opportunity", "A chance to do something", 3),
    ("population", "How many people live somewhere", 3),
    ("preparation", "Getting ready for something", 3),
    ("temperature", "How hot or cold it is", 3),
    ("competition", "People trying to win", 3),
)


# A picture for the first word a learner meets (D.3).
#
# These are pictograms, not files: a school with no asset pipeline still gets a
# picture, and a reviewed set of drawings can replace them key for key without
# touching the client. Only words whose meaning a single glyph actually shows
# are listed — a wrong picture misleads a non-reader more than no picture, so
# "table", "brave", "window" and "brush" deliberately have none — a paintbrush
# would answer "You use it on your hair" with the wrong object.
PICTURES: dict[str, str] = {
    "apple": "🍎",
    "bread": "🍞",
    "chair": "🪑",
    "water": "💧",
    "house": "🏠",
    "green": "🟩",
    "happy": "😊",
    "river": "🌊",
    "cloud": "☁️",
    "music": "🎵",
    "light": "💡",
    "stone": "🪨",
    "pencil": "✏️",
    "school": "🏫",
    "friend": "👫",
    "garden": "🌷",
    "market": "🛒",
    "night": "🌙",
    "dance": "💃",
    "tiger": "🐯",
    "horse": "🐴",
    "clock": "⏰",
    "shoes": "👟",
    "plate": "🍽️",
    "grass": "🌿",
    "smile": "😄",
    "train": "🚂",
    "beach": "🏖️",
    "sheep": "🐑",
    "plant": "🌱",
    "money": "💰",
    "sugar": "🍬",
    "paper": "📄",
    "honey": "🍯",
    "month": "📅",
    "shape": "🔷",
    "story": "📖",
    "laugh": "😂",
    "juice": "🧃",
    "socks": "🧦",
    "phone": "📱",
    "heavy": "🏋️",
    "tired": "😴",
    "quiet": "🤫",
    "clean": "🧼",
    "empty": "🕳️",
}


def item_payloads() -> list[dict[str, Any]]:
    """The words as content payloads, validated. Raises on any bad row."""
    payloads: list[dict[str, Any]] = []
    seen: set[str] = set()
    problems: list[str] = []

    for answer, clue, difficulty in STARTER_WORDS:
        if answer in seen:
            problems.append(f"duplicate answer: {answer}")
        seen.add(answer)
        payload: dict[str, object] = {
            "answer": answer,
            "alt_answers": [],
            "clue": clue,
            "difficulty": difficulty,
        }
        picture = PICTURES.get(answer)
        if picture:
            payload["clue_image_key"] = picture
        for problem in rules.validate_item(payload):
            problems.append(f"{answer}: {problem}")
        payloads.append(payload)

    if problems:
        raise ValueError("starter content failed validation:\n" + "\n".join(problems))
    return payloads


def _pack_id(band: str) -> uuid.UUID:
    return uuid.uuid5(NAMESPACE, f"{GAME_ID}:{VERSION}:{LOCALE}:{band}")


def _item_id(band: str, answer: str) -> uuid.UUID:
    return uuid.uuid5(NAMESPACE, f"{band}:{answer}")


async def seed_content(session: AsyncSession) -> dict[str, int]:
    """Publish the starter packs. Idempotent: re-running adds nothing."""
    payloads = item_payloads()

    # With three roles (D-37) the words belong to staff: the coach who writes
    # them, and the school admin whose school the bank came from. Both still
    # exist, so a fresh database seeds the same way every time.
    author = (
        (await session.execute(select(User).where(User.student_code == "A-9005"))).scalars().first()
    )
    reviewer = (
        (await session.execute(select(User).where(User.student_code == "A-9001"))).scalars().first()
    )
    if author is None or reviewer is None:
        raise ValueError("seed identity first: the staff accounts are missing")

    packs = 0
    items = 0
    now = dt.datetime.now(dt.UTC)

    for band in PUBLISHED_BANDS:
        pack_id = _pack_id(band)
        existing = await session.get(ContentPack, pack_id)
        if existing is not None:
            continue

        session.add(
            ContentPack(
                id=pack_id,
                game_id=GAME_ID,
                version=VERSION,
                locale=LOCALE,
                age_band=band,
                difficulty=1,
                status="published",
                author_id=author.id,
                reviewer_id=reviewer.id,
                published_at=now,
                source="original",
                safe_language_reviewed=True,
            )
        )
        # Flush the pack first: the models are not related by a relationship,
        # so without this the items can be inserted before their pack.
        await session.flush()
        for order, payload in enumerate(payloads):
            session.add(
                ContentItem(
                    id=_item_id(band, str(payload["answer"])),
                    pack_id=pack_id,
                    payload=payload,
                    difficulty=int(payload["difficulty"]),
                    sort_order=order,
                    # The starter bank ships in play: a database with no live
                    # words cannot be played at all (D-38).
                    status="live",
                    published_by=reviewer.id,
                    published_at=now,
                )
            )
            items += 1
        packs += 1

    # A database seeded before the pictures existed still hands a child a
    # text-only clue. Filling only a *missing* picture key never overwrites a
    # coach's edit, and a second run changes nothing.
    pictures = 0
    for band in PUBLISHED_BANDS:
        for payload in payloads:
            item = await session.get(ContentItem, _item_id(band, str(payload["answer"])))
            if item is None:
                continue
            stored = dict(item.payload or {})
            current = stored.get("clue_image_key")
            if isinstance(current, str) and (current.startswith("/") or current.startswith("http")):
                # A reviewed drawing. The seed does not own it.
                continue
            wanted = payload.get("clue_image_key")
            if wanted:
                stored["clue_image_key"] = wanted
            else:
                stored.pop("clue_image_key", None)
            if stored != (item.payload or {}):
                item.payload = stored
                pictures += 1

    await session.flush()
    return {"packs": packs, "items": items, "pictures": pictures}
