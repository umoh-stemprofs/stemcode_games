"""Invitation codes, links and the challenge comparison, pure (P7-T02, T05).

Three rules shape this module:

- **Only hashes are stored** (D-31). A code or a token exists in plaintext for
  exactly one response, and after that the database holds a SHA-256 digest. A
  dump of the table cannot be used to join anything.
- **The alphabet lies to nobody.** ``ABCDEFGHJKMNPQRSTUVWXYZ23456789`` drops the
  characters that are indistinguishable when read off a screen at 20px — I, L, O,
  0, 1 — because the code is typed by a child, not scanned.
- **A challenge is a comparison of two attempts, not a race.** The result is
  decided from the two scores after both children are done, so two learners on
  different biscuits of wifi still get a fair answer.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import re
import secrets

# No I, L, O, 0, 1: a learner reading the code off the screen cannot confuse
# what is not there.
CODE_ALPHABET = "ABCDEFGHJKMNPQRSTUVWXYZ23456789"
CODE_LENGTH = 8
TOKEN_BYTES = 32

# An invitation is good for a day: long enough for two classes to meet, short
# enough that an old code in a chat thread stops working.
INVITE_HOURS = 24
# Once accepted, the two attempts may be played any time in this window.
CHALLENGE_WINDOW_HOURS = 24

_CODE_CLEAN = re.compile(r"[^A-Z0-9]")


def generate_code() -> str:
    """Eight characters from the unambiguous alphabet (D-31)."""
    return "".join(secrets.choice(CODE_ALPHABET) for _ in range(CODE_LENGTH))


def format_code(code: str) -> str:
    """``ABCDEFGH`` -> ``ABCD EFGH``: two groups of four, for the large font."""
    clean = normalise_code(code) or ""
    return f"{clean[:4]} {clean[4:]}".strip()


def normalise_code(text: str) -> str | None:
    """What the learner typed, or ``None`` when it cannot be a code.

    Spaces and dashes are ignored (people paste with them), case does not
    matter, and anything outside the alphabet is a typo rather than a code.
    """
    cleaned = _CODE_CLEAN.sub("", text.upper())
    if len(cleaned) != CODE_LENGTH:
        return None
    if any(character not in CODE_ALPHABET for character in cleaned):
        return None
    return cleaned


def generate_token() -> str:
    """A URL-safe link token: 32 random bytes, never a guessable pattern."""
    return secrets.token_urlsafe(TOKEN_BYTES)


def hash_secret(value: str) -> str:
    """The only form of a code or token that is ever stored (D-31)."""
    return hashlib.sha256(value.strip().encode("utf-8")).hexdigest()


def invite_expiry(now: dt.datetime) -> dt.datetime:
    return now + dt.timedelta(hours=INVITE_HOURS)


def challenge_deadline(accepted_at: dt.datetime) -> dt.datetime:
    return accepted_at + dt.timedelta(hours=CHALLENGE_WINDOW_HOURS)


def compare_scores(mine: int, theirs: int) -> str:
    """``win | loss | draw`` from one player's side."""
    if mine > theirs:
        return "win"
    if mine < theirs:
        return "loss"
    return "draw"


def result_sentence(game_name: str, outcome: str, their_name: str) -> str:
    """One sentence for the inbox (Appendix D: under eight words per sentence)."""
    if outcome == "win":
        return f"You won {game_name} against {their_name}."
    if outcome == "loss":
        return f"{their_name} won {game_name} this time."
    return f"It was a draw with {their_name}."


def invite_sentence(game_name: str, inviter_name: str) -> str:
    return f"{inviter_name} wants to play {game_name} with you."


# Said when the match behind an invite is gone, so the tap is not a dead end.
# One idea, two short sentences: the invite is over, and what to do next.
INVITE_CLOSED = "That invite is closed. Ask your friend for a new one."
