"""The safe-language check (P4-T03).

The promises under test:

- a word or clue carrying profanity, a slur, sexual content, hard drugs,
  self-harm or graphic violence is refused;
- ordinary words that merely *contain* a blocked string are allowed, because the
  match is per word, not per substring;
- a disguise a child could type (`sh1t`, `fuuuck`, `sluts`) is still caught;
- the sentence never repeats the offending word back to anybody.
"""

from __future__ import annotations

import pytest
from app.games.domain import safe_language as safe
from app.games.domain import wordscramble as ws


@pytest.mark.parametrize(
    "answer",
    ["shit", "bitch", "rape", "suicide", "heroin", "murder", "nigger", "retard"],
)
def test_an_unsafe_answer_is_blocked(answer: str) -> None:
    assert safe.is_blocked_token(answer)


@pytest.mark.parametrize(
    "answer",
    ["shit!", "SHIT", "sh1t", "s h i t", "fuuuck"],
)
def test_a_disguised_answer_is_still_blocked(answer: str) -> None:
    assert safe.is_blocked_token(answer)


@pytest.mark.parametrize("answer", ["sluts", "murdered", "cigarettes"])
def test_a_plural_or_inflection_is_still_blocked(answer: str) -> None:
    assert safe.is_blocked_token(answer)


@pytest.mark.parametrize(
    "answer",
    ["grass", "class", "essex", "cocoa", "shell", "grape", "apple", "assassin", "scrap"],
)
def test_an_ordinary_word_containing_a_blocked_string_is_allowed(answer: str) -> None:
    """Substring matching would refuse every one of these, and it would be wrong."""
    assert not safe.is_blocked_token(answer)


def test_a_clue_with_an_unsafe_word_is_refused() -> None:
    problems = safe.problems(answer="chair", clue="You sit on the damn thing")
    assert problems == [safe.CLUE_PROBLEM]


def test_a_clue_with_a_two_word_phrase_is_refused() -> None:
    problems = safe.problems(answer="chair", clue="What you do with a blow job")
    assert safe.CLUE_PROBLEM in problems


def test_a_clean_item_has_no_safe_language_problem() -> None:
    assert safe.problems(answer="apple", clue="A red or green fruit") == []


def test_the_sentence_never_repeats_the_offending_word() -> None:
    """A coach's typo must not put the word itself on their screen."""
    for answer in ("shit", "retard", "heroin"):
        problems = safe.problems(answer=answer, clue="A word")
        assert problems
        for problem in problems:
            assert answer not in problem.lower()
            assert problem == safe.ANSWER_PROBLEM


def test_the_list_is_lowercase_and_normalised() -> None:
    """A stray capital or space in the data would silently disable an entry."""
    for word in safe.BLOCKED_WORDS:
        assert word == word.lower()
        assert word.isalpha()
        assert safe.normalise_token(word) == word


def test_validation_refuses_the_whole_item() -> None:
    """The check is part of ``validate_item``, so no route can skip it."""
    problems = ws.validate_item(
        {"answer": "shit", "alt_answers": [], "clue": "A rude word", "difficulty": 1}
    )
    assert safe.ANSWER_PROBLEM in problems

    problems = ws.validate_item(
        {"answer": "apple", "alt_answers": [], "clue": "A fucking fruit", "difficulty": 1}
    )
    assert safe.CLUE_PROBLEM in problems


def test_an_alternative_spelling_is_checked_too() -> None:
    """A blocked word must not sneak in as "another spelling"."""
    problems = ws.validate_item(
        {
            "answer": "apple",
            "alt_answers": ["shit"],
            "clue": "A red or green fruit",
            "difficulty": 1,
        }
    )
    assert safe.ANSWER_PROBLEM in problems
