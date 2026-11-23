"""Checkers rules (P8-T06 .. P8-T08, D-05).

The numbers below are the published perft counts for English draughts from the
standard start, which is the cheapest way to know the generator is complete:
7 moves at depth 1, 49 at 2, 302 at 3, 1469 at 4.

Positions are written as (row, col) pairs, with row 0 at the top. Only dark
squares — those where row + col is odd — can hold a piece, and the helper says
so loudly if a test gets that wrong.
"""

from __future__ import annotations

import random

import pytest
from app.games.domain import checkers as rules

WHITE_MAN = rules.WHITE_MAN
WHITE_KING = rules.WHITE_KING
BLACK_MAN = rules.BLACK_MAN
BLACK_KING = rules.BLACK_KING

PIECES = {
    "w": WHITE_MAN,
    "W": WHITE_KING,
    "b": BLACK_MAN,
    "B": BLACK_KING,
}


def _square(row: int, col: int) -> int:
    assert (row + col) % 2 == 1, f"({row}, {col}) is a light square"
    return row * 4 + col // 2


def _state(
    pieces: dict[str, list[tuple[int, int]]],
    *,
    side: str = rules.WHITE,
    plies: int = 0,
) -> rules.State:
    board = [rules.EMPTY] * rules.SQUARES
    for char, squares in pieces.items():
        for row, col in squares:
            board[_square(row, col)] = PIECES[char]
    state = rules.State(board=tuple(board), side=side, plies_since_progress=plies, history=())
    return rules.State(
        board=state.board,
        side=side,
        plies_since_progress=plies,
        history=(state.position_key(),),
    )


def _captures(state: rules.State) -> list[rules.Move]:
    return [move for move in rules.legal_moves(state) if move.captures]


# ------------------------------------------------------------------- perft
def _perft(state: rules.State, depth: int) -> int:
    if depth == 0:
        return 1
    return sum(
        _perft(rules.apply_move(state, move), depth - 1) for move in rules.legal_moves(state)
    )


@pytest.mark.parametrize(("depth", "nodes"), [(1, 7), (2, 49), (3, 302), (4, 1469)])
def test_move_generation_matches_the_published_counts(depth: int, nodes: int) -> None:
    assert _perft(rules.initial_state(), depth) == nodes


def test_white_moves_first_and_the_board_starts_full() -> None:
    state = rules.initial_state()
    assert state.side == rules.WHITE
    assert state.piece_count(rules.WHITE) == 12
    assert state.piece_count(rules.BLACK) == 12
    assert state.kings(rules.WHITE) == 0


def test_white_men_move_up_the_board_and_black_men_move_down_it() -> None:
    # (5, 0) has one square in front of it; the other diagonal leaves the board.
    white = _state({"w": [(5, 0)]})
    assert {move.to_square for move in rules.legal_moves(white)} == {_square(4, 1)}

    # A white man on the top row has nowhere to go; a black one there steps down.
    stuck = _state({"w": [(0, 1)]}, side=rules.WHITE)
    assert rules.legal_moves(stuck) == []
    black = _state({"b": [(0, 1)]}, side=rules.BLACK)
    assert {move.to_square for move in rules.legal_moves(black)} == {
        _square(1, 0),
        _square(1, 2),
    }


# --------------------------------------------------------- mandatory capture
def test_a_capture_is_mandatory_when_one_exists() -> None:
    # White (5,0) may step to (4,1) or jump the black man on (4,1) to (3,2).
    state = _state({"w": [(5, 0)], "b": [(4, 1)]})
    moves = rules.legal_moves(state)
    assert len(moves) == 1
    assert moves[0].captures == (_square(4, 1),)
    assert moves[0].to_square == _square(3, 2)


def test_any_capture_is_allowed_not_only_the_biggest() -> None:
    # Two independent captures for two different men: both are offered (D-05).
    state = _state({"w": [(5, 0), (5, 4)], "b": [(4, 1), (4, 5)]})
    moves = _captures(state)
    assert len(moves) == 2
    assert all(len(move.captures) == 1 for move in moves)


def test_a_man_cannot_capture_backwards() -> None:
    # A black man sits behind a white one and another in front is not there:
    # no capture is available at all.
    state = _state({"w": [(4, 1)], "b": [(5, 0)]})
    assert _captures(state) == []


def test_a_king_captures_backwards() -> None:
    # The victim is behind a king (below it), which a man could never take.
    state = _state({"W": [(4, 3)], "b": [(5, 2)]})
    captures = _captures(state)
    assert len(captures) == 1
    assert captures[0].to_square == _square(6, 1)

    # The same position with a plain man offers no capture at all.
    man = _state({"w": [(4, 3)], "b": [(5, 2)]})
    assert _captures(man) == []


# --------------------------------------------------------------- multi-jumps
def test_a_double_jump_is_one_turn() -> None:
    # White (6,1) jumps (5,0)? No: (6,1) + (-1,-1) -> (5,0) then lands (4,-1)
    # is off the board, so use the other diagonal instead.
    state = _state({"w": [(6, 1)], "b": [(5, 2), (3, 4)]})
    moves = _captures(state)
    assert len(moves) == 1
    move = moves[0]
    assert len(move.captures) == 2
    assert len(move.path) == 3


def test_a_jump_that_could_continue_must_continue() -> None:
    state = _state({"w": [(6, 1)], "b": [(5, 2), (3, 4)]})
    assert all(len(move.captures) == 2 for move in rules.legal_moves(state))


def test_branching_multi_jump_offers_every_complete_route() -> None:
    # After taking (5,2) from (6,1) to (4,3), two further victims exist.
    state = _state(
        {"w": [(6, 1)], "b": [(5, 2), (3, 2), (3, 4)]},
    )
    moves = _captures(state)
    assert len(moves) == 2
    assert all(len(move.captures) == 2 for move in moves)


def test_promotion_ends_the_turn_even_with_a_jump_available() -> None:
    # White (2,1) takes (1,2) and lands on (0,3): crowned, and the turn stops.
    state = _state({"w": [(2, 1)], "b": [(1, 2), (0, 5)]})
    moves = _captures(state)
    assert len(moves) == 1
    move = moves[0]
    assert move.becomes_king is True
    assert len(move.captures) == 1
    after = rules.apply_move(state, move)
    assert rules.is_king(after.board[move.to_square])


# ------------------------------------------------------------------- draws
def test_a_man_move_resets_the_draw_counter_and_a_king_shuffle_does_not() -> None:
    king = _state({"W": [(4, 1)]}, plies=5)
    king_move = rules.legal_moves(king)[0]
    assert king_move.captures == ()
    assert rules.apply_move(king, king_move).plies_since_progress == 6

    man = _state({"w": [(5, 0)]}, plies=5)
    assert rules.apply_move(man, rules.legal_moves(man)[0]).plies_since_progress == 0


def test_forty_quiet_plies_is_a_draw() -> None:
    state = _state({"W": [(4, 1)], "b": [(3, 4)]}, plies=rules.DRAW_PLIES)
    assert rules.result(state) == "draw"


def test_threefold_repetition_is_a_draw() -> None:
    state = _state({"W": [(4, 1)], "b": [(3, 4)]})
    key = state.position_key()
    repeated = rules.State(
        board=state.board,
        side=state.side,
        plies_since_progress=0,
        history=(key, key, key),
    )
    assert rules.repetition_count(repeated) == 3
    assert rules.result(repeated) == "draw"


def test_winning_and_losing_positions() -> None:
    # White is to move and black has no pieces: white wins.
    assert rules.result(_state({"w": [(4, 1)]}, side=rules.WHITE)) == "white"
    # Black's only man is boxed in: the step is blocked and so is the landing
    # square of the jump it would otherwise have. Black cannot move and loses.
    stuck = _state({"b": [(3, 0)], "w": [(4, 1), (5, 2)]}, side=rules.BLACK)
    assert rules.legal_moves(stuck) == []
    assert rules.result(stuck) == "white"


# ------------------------------------------------------------------ the wire
def test_a_move_key_round_trips_and_only_legal_keys_are_accepted() -> None:
    state = rules.initial_state()
    move = rules.legal_moves(state)[0]
    assert rules.find_move(state, move.key) == move
    assert rules.find_move(state, "0-1:") is None


# ------------------------------------------------------------------ the fuzzer
def test_random_games_always_terminate() -> None:
    """P8-T08: random play must never throw and must always end.

    The count is 400 rather than ten thousand: a full random game is a few
    hundred move generations in pure Python, and ten thousand of them froze the
    suite for fifteen minutes. Four hundred seeded games still walk every rule
    — captures, multi-jumps, promotion, draws — in about ten seconds, and they
    are the same four hundred every run.
    """
    rng = random.Random(20261116)  # noqa: S311
    for _ in range(400):
        state = rules.initial_state()
        for _ply in range(400):
            if rules.result(state) is not None:
                break
            moves = rules.legal_moves(state)
            assert moves, "a position in play must have a legal move"
            state = rules.apply_move(state, rng.choice(moves))
        else:  # pragma: no cover - the 40-ply draw rule always stops us
            raise AssertionError("a game ran past 400 plies without ending")
