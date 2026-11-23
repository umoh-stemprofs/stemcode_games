"""Avatar set (P1-T06).

A fixed set of non-photographic keys. Learners pick one; nobody uploads
images, so there is no moderation path and no way to smuggle a real face or a
file into a profile. The artwork itself ships with the web app.

Keys are stable: they are snapshotted into names shown next to game results,
so renaming one would orphan old rows. Add, never rename.
"""

from __future__ import annotations

AVATAR_KEYS: tuple[str, ...] = (
    "fox",
    "owl",
    "panda",
    "tiger",
    "penguin",
    "koala",
    "dolphin",
    "hedgehog",
    "otter",
    "turtle",
    "butterfly",
    "bee",
    "giraffe",
    "zebra",
    "lion",
    "frog",
    "parrot",
    "whale",
    "squirrel",
    "raccoon",
    "camel",
    "ladybird",
    "seal",
    "crab",
)

DEFAULT_AVATAR_KEY = AVATAR_KEYS[0]


def is_valid_avatar(key: str) -> bool:
    return key in AVATAR_KEYS
