"""Safe-language check for words and clues (P4-T03). Pure, offline, free.

The audience is children, so a word or clue that carries profanity, a slur,
sexual content, hard drugs, self-harm or graphic violence must never reach a
game. This is the check the plan calls the **blocklist**, and it is deliberately
dumb: no model, no network, no guessing. A fixed list, matched carefully.

Why not an AI judge: it costs money per check, it answers differently on two
runs of the same word, it happily approves a misspelling, and when a parent asks
"who let this word through", "a language model did" is not an answer a school
can give. A list can be read, reviewed, argued with and fixed in one commit.

Where it runs
-------------
``wordscramble.validate_item`` calls this, and the content service calls that
before a word may be created *and* before it may go live. So the check cannot be
skipped by any route: single add, CSV import, one-word publish or the bulk
button. A word that fails simply has a problem, and a word with a problem has no
door to the games.

What is matched, and how carefully
----------------------------------
* **The answer and its other spellings** are compared to the whole list as
  single tokens. Not substrings — ``grass``, ``class``, ``essex`` and ``cocoa``
  must all pass, and substring matching would fail them.
* **The clue** is split into words, and each word is compared as a token. A
  small list of two-word phrases is also checked.
* **Disguises** a child could type are normalised first: ``0 -> o``, ``1 -> i``,
  ``3 -> e``, ``4 -> a``, ``5 -> s``, ``7 -> t``, ``@ -> a``, ``$ -> s``, runs of
  three or more of the same letter squeezed (``fuuuck``), and a trailing plural
  ``s`` dropped.

What it does **not** do
-----------------------
It does not judge meaning. "The clue describes the wrong thing" and "this clue
is ambiguous" are not on this list; rule P4-T03 only asks that an unsafe word be
refused, and a human still reads the words they publish.

Adding an entry is one line. Keep the list sorted, keep it lowercase, and never
log or echo the matched word back to a screen (someone's mistake should not put
a slur on their screen): the sentences below are deliberately generic.
"""

from __future__ import annotations

import re

# --------------------------------------------------------------------- the list
# Curated for a school word bank. Grouped for review, not for display: never
# show a group name or an entry to a learner.
_PROFANITY = {
    "arse",
    "arsehole",
    "bastard",
    "bitch",
    "bollocks",
    "bugger",
    "crap",
    "cunt",
    "damn",
    "dick",
    "dickhead",
    "douche",
    "fag",
    "faggot",
    "fuck",
    "fucked",
    "fucker",
    "fucking",
    "goddamn",
    "hell",
    "jackass",
    "motherfucker",
    "nigga",
    "nigger",
    "piss",
    "prick",
    "pussy",
    "shit",
    "shitty",
    "slut",
    "twat",
    "wank",
    "wanker",
    "whore",
}

_SLURS = {
    "chink",
    "coon",
    "dyke",
    "gook",
    "gyp",
    "kike",
    "paki",
    "raghead",
    "retard",
    "retarded",
    "spastic",
    "tranny",
    "wetback",
}

_SEXUAL = {
    "anus",
    "blowjob",
    "boob",
    "boobs",
    "condom",
    "cum",
    "dildo",
    "erotic",
    "genital",
    "genitals",
    "handjob",
    "hentai",
    "horny",
    "incest",
    "masturbate",
    "masturbation",
    "naked",
    "nipple",
    "nude",
    "orgasm",
    "penis",
    "porn",
    "porno",
    "pornography",
    "rape",
    "raped",
    "raping",
    "sex",
    "sexy",
    "sperm",
    "vagina",
    "vibrator",
    "virgin",
}

# Drugs, alcohol and self-harm: legal for adults, not for a 9-year-old's clue.
_HARMFUL = {
    "beer",
    "cigarette",
    "cigar",
    "cocaine",
    "drunk",
    "heroin",
    "marijuana",
    "meth",
    "opium",
    "suicide",
    "tobacco",
    "vodka",
    "weed",
    "whiskey",
    "whisky",
    "wine",
}

# Graphic violence and terminal illness, in the terms a child would meet.
_VIOLENCE = {
    "behead",
    "beheaded",
    "bloodbath",
    "corpse",
    "decapitate",
    "gore",
    "hangman",
    "massacre",
    "murder",
    "murdered",
    "murderer",
    "slaughter",
    "torture",
    "tortured",
}

BLOCKED_WORDS: frozenset[str] = frozenset(_PROFANITY | _SLURS | _SEXUAL | _HARMFUL | _VIOLENCE)

# Two-word forms that a single-token check would miss.
BLOCKED_PHRASES: tuple[str, ...] = (
    "blow job",
    "hand job",
    "hard core",
    "child porn",
    "kill yourself",
    "mother fucker",
    "son of a bitch",
)

# Statements a person can act on. Never name the matched word: the sentence is
# the whole message, and the word itself must not be repeated on screen.
ANSWER_PROBLEM = "That word is not safe for children."
CLUE_PROBLEM = "The clue has a word that is not safe for children."

_LEET = str.maketrans(
    {
        "0": "o",
        "1": "i",
        "3": "e",
        "4": "a",
        "5": "s",
        "7": "t",
        "@": "a",
        "$": "s",
        "!": "i",
    }
)
_NON_LETTERS = re.compile(r"[^a-z]+")
_RUNS = re.compile(r"([a-z])\1{2,}")


def normalise_token(value: str) -> str:
    """Lowercase, letters only, leetspeak undone, long runs squeezed."""
    lowered = value.strip().lower().translate(_LEET)
    letters = _NON_LETTERS.sub("", lowered)
    return _RUNS.sub(r"\1", letters)


def _readings(value: str) -> set[str]:
    """Two honest readings of one token, plus their variants.

    ``sh!t`` is a disguise, so ``!`` is read as ``i``. ``shit!`` is just a word
    with a bang after it, so the punctuation is also simply dropped. Trying both
    costs nothing and avoids a rule that fails on the ordinary case to catch the
    clever one.

    A plural is the same word (``sluts``), and a squeezed form catches padding
    (``fuuuck``). Nothing cleverer: guessing more spellings buys false alarms.
    """
    raw = value.strip().lower()
    leet = _NON_LETTERS.sub("", raw.translate(_LEET))
    plain = _NON_LETTERS.sub("", raw)

    forms: set[str] = set()
    for base in (leet, plain):
        if not base:
            continue
        forms.add(base)
        if len(base) > 3 and base.endswith("s"):
            forms.add(base[:-1])
        forms.add(_RUNS.sub(r"\1", base))
    return forms


def normalise_for_list(value: str) -> str:
    """The stored form of a word a school admin types in.

    **Punctuation is dropped, leetspeak is not interpreted.** Someone typing a
    word into a form is spelling a word, not dodging a filter; reading ``!`` as
    ``i`` there turns a stray exclamation into a nonsense entry. The built-in
    list still catches disguised forms in the words and clues that are checked.

    Returns an empty string when nothing usable is left, which the caller
    refuses.
    """
    return _NON_LETTERS.sub("", value.strip().lower())


def is_blocked_token(value: str, extra: frozenset[str] = frozenset()) -> bool:
    """True if this word, however disguised, is on either list.

    ``extra`` is the school's own list, read from the database. It is passed in
    rather than fetched here, because this module is pure by rule (AGENTS.md).
    """
    return any(form in BLOCKED_WORDS or form in extra for form in _readings(value))


def _clue_tokens(clue: str) -> list[str]:
    return [token for token in _NON_LETTERS.split(clue.strip().lower()) if token]


def problems(
    *,
    answer: str,
    clue: str | None,
    alt_answers: list[str] | None = None,
    extra: frozenset[str] = frozenset(),
) -> list[str]:
    """Every safe-language reason this item may not go live (P4-T03).

    Empty means fine. One sentence per problem, and the sentence never repeats
    the offending word. ``extra`` carries the school's own additions.
    """
    found: list[str] = []

    for candidate in [answer, *(alt_answers or [])]:
        if is_blocked_token(str(candidate), extra):
            found.append(ANSWER_PROBLEM)
            break

    if clue:
        tokens = _clue_tokens(clue)
        if any(is_blocked_token(token, extra) for token in tokens):
            found.append(CLUE_PROBLEM)
        else:
            flat = " ".join(tokens)
            if any(phrase in flat for phrase in BLOCKED_PHRASES):
                found.append(CLUE_PROBLEM)

    return found
