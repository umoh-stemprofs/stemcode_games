"""English draughts, pure (P8-T06, P8-T07, D-05).

No I/O, no clock, no randomness: a state goes in, a state comes out. The server
is the only judge — clients are shown `legal_moves` and may only submit one of
them, so an illegal move is not rejected late, it is never offered (P8-T17).

The two rules implementations usually get wrong, spelled out:

- **Mandatory capture, but not maximum capture.** If any capture exists, only
  captures are legal. Among them, a player may pick *any* one: there is no
  "must take the most pieces" rule in English draughts.
- **Promotion ends the turn.** A man that lands on the far row stops there as a
  king, even when a further jump would be available.

The draw counter counts **plies**: one move by either side is 1. Forty plies
with no capture and no man move is a draw (P8-T07).

Board: 32 playable squares, indexed ``row * 4 + q`` for the dark squares of an
8x8 board. White sits at the low rows and moves towards row 0; black mirrors it.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, replace

EMPTY = 0
WHITE_MAN = 1
WHITE_KING = 2
BLACK_MAN = 3
BLACK_KING = 4

WHITE = "white"
BLACK = "black"

SQUARES = 32
DRAW_PLIES = 40

# Who owns a piece / is it a king.
_OWNER = {WHITE_MAN: WHITE, WHITE_KING: WHITE, BLACK_MAN: BLACK, BLACK_KING: BLACK}
_IS_KING = {WHITE_KING: True, BLACK_KING: True}

# Men move forward only; kings go both ways. Rows grow towards black's home.
_MAN_DIRECTIONS = {WHITE: ((-1, -1), (-1, 1)), BLACK: ((1, -1), (1, 1))}
_KING_DIRECTIONS = ((-1, -1), (-1, 1), (1, -1), (1, 1))

_PROMOTION_ROW = {WHITE: 0, BLACK: 7}


def owner_of(piece: int) -> str | None:
    return _OWNER.get(piece)


def opponent(side: str) -> str:
    return BLACK if side == WHITE else WHITE


def is_king(piece: int) -> bool:
    return _IS_KING.get(piece, False)


def _row_col(square: int) -> tuple[int, int]:
    row, q = divmod(square, 4)
    # Dark squares only: rows alternate which column they start on.
    col = 2 * q + (1 if row % 2 == 0 else 0)
    return row, col


def _square(row: int, col: int) -> int | None:
    if not (0 <= row < 8 and 0 <= col < 8):
        return None
    if (row + col) % 2 == 0:
        return None
    return row * 4 + col // 2


@dataclass(frozen=True, slots=True)
class Move:
    """One full turn: a single step, or a whole multi-jump."""

    from_square: int
    to_square: int
    path: tuple[int, ...]
    captures: tuple[int, ...]
    becomes_king: bool

    @property
    def key(self) -> str:
        """The stable wire form: board squares, then captures."""
        captures = ",".join(str(square) for square in self.captures)
        return f"{self.from_square}-{self.to_square}:{captures}"

    def as_dict(self) -> dict[str, object]:
        return {
            "from": self.from_square,
            "to": self.to_square,
            "path": list(self.path),
            "captures": list(self.captures),
            "king": self.becomes_king,
            "key": self.key,
        }


@dataclass(frozen=True, slots=True)
class State:
    """Position plus the facts the draw rules need."""

    board: tuple[int, ...]
    side: str
    plies_since_progress: int
    # (board, side) hashes, oldest first — threefold repetition (P8-T07).
    history: tuple[str, ...]

    def piece_count(self, side: str) -> int:
        return sum(1 for piece in self.board if _OWNER.get(piece) == side)

    def kings(self, side: str) -> int:
        return sum(1 for piece in self.board if _OWNER.get(piece) == side and is_king(piece))

    def position_key(self) -> str:
        return hashlib.sha256(
            (",".join(str(piece) for piece in self.board) + "|" + self.side).encode()
        ).hexdigest()


def initial_state(*, side: str = WHITE) -> State:
    """The standard start: three rows each, white to move by default."""
    board = [EMPTY] * SQUARES
    for square in range(SQUARES):
        row, _col = _row_col(square)
        if row <= 2:
            board[square] = BLACK_MAN
        elif row >= 5:
            board[square] = WHITE_MAN
    state = State(
        board=tuple(board),
        side=side,
        plies_since_progress=0,
        history=(),
    )
    return replace(state, history=(state.position_key(),))


def _directions(piece: int) -> tuple[tuple[int, int], ...]:
    if is_king(piece):
        return _KING_DIRECTIONS
    return _MAN_DIRECTIONS[_OWNER[piece]]


def _jump_sequences(
    board: list[int],
    square: int,
    piece: int,
    path: tuple[int, ...],
    captures: tuple[int, ...],
    promoted: bool,
    out: list[Move],
) -> None:
    """Every complete capture this piece can make, including branches."""
    row, col = _row_col(square)
    moved_on = False
    for d_row, d_col in _directions(piece):
        mid = _square(row + d_row, col + d_col)
        landing = _square(row + 2 * d_row, col + 2 * d_col)
        if mid is None or landing is None:
            continue
        victim = board[mid]
        if victim == EMPTY or _OWNER.get(victim) == _OWNER[piece]:
            continue
        if mid in captures:
            continue
        if board[landing] != EMPTY and landing not in captures:
            continue
        moved_on = True
        next_path = path + (landing,)
        next_captures = captures + (mid,)
        # A man that lands on the far row is crowned and the turn ends there.
        king_now = is_king(piece) or _row_col(landing)[0] == _PROMOTION_ROW[_OWNER[piece]]
        if king_now and not is_king(piece):
            out.append(
                Move(
                    from_square=path[0],
                    to_square=landing,
                    path=next_path,
                    captures=next_captures,
                    becomes_king=True,
                )
            )
            continue
        _jump_sequences(
            board,
            landing,
            piece,
            next_path,
            next_captures,
            promoted,
            out,
        )
    if not moved_on and len(captures) > 0:
        out.append(
            Move(
                from_square=path[0],
                to_square=square,
                path=path,
                captures=captures,
                becomes_king=promoted,
            )
        )


def legal_moves(state: State) -> list[Move]:
    """Capture moves if any exist, otherwise the quiet steps."""
    board = list(state.board)
    captures: list[Move] = []
    steps: list[Move] = []

    for square, piece in enumerate(board):
        if piece == EMPTY or _OWNER.get(piece) != state.side:
            continue
        _jump_sequences(board, square, piece, (square,), (), False, captures)

        row, col = _row_col(square)
        for d_row, d_col in _directions(piece):
            target = _square(row + d_row, col + d_col)
            if target is None or board[target] != EMPTY:
                continue
            king_now = is_king(piece) or _row_col(target)[0] == _PROMOTION_ROW[state.side]
            steps.append(
                Move(
                    from_square=square,
                    to_square=target,
                    path=(square, target),
                    captures=(),
                    becomes_king=king_now and not is_king(piece),
                )
            )

    return captures or steps


def find_move(state: State, key: str) -> Move | None:
    """The legal move with this key, or ``None`` — the only moves a client may send."""
    for move in legal_moves(state):
        if move.key == key:
            return move
    return None


def apply_move(state: State, move: Move) -> State:
    """Play a move that came from :func:`legal_moves`."""
    board = list(state.board)
    piece = board[move.from_square]
    if piece == EMPTY:
        raise ValueError("no piece on the from square")

    for captured in move.captures:
        board[captured] = EMPTY
    board[move.from_square] = EMPTY

    # A man that finishes on the far row is crowned; kings stay kings.
    if is_king(piece) or _row_col(move.to_square)[0] == _PROMOTION_ROW[_OWNER[piece]]:
        board[move.to_square] = WHITE_KING if _OWNER[piece] == WHITE else BLACK_KING
    else:
        board[move.to_square] = piece

    # D-05: the draw counter resets on a capture or on any move by a man.
    progress = bool(move.captures) or not is_king(piece)
    plies = 0 if progress else state.plies_since_progress + 1

    next_state = State(
        board=tuple(board),
        side=opponent(state.side),
        plies_since_progress=plies,
        history=state.history,
    )
    return replace(next_state, history=state.history + (next_state.position_key(),))


def repetition_count(state: State) -> int:
    """How many times this exact (board, side to move) has been seen."""
    key = state.position_key()
    return sum(1 for seen in state.history if seen == key)


def result(state: State) -> str | None:
    """``white`` / ``black`` / ``draw`` / ``None`` (the game goes on)."""
    if state.piece_count(opponent(state.side)) == 0:
        return state.side
    if not legal_moves(state):
        return opponent(state.side)
    if state.plies_since_progress >= DRAW_PLIES:
        return "draw"
    if repetition_count(state) >= 3:
        return "draw"
    return None


def material(state: State) -> dict[str, int]:
    """What the screen shows as a simple count of captured pieces."""
    return {
        "white": 12 - state.piece_count(WHITE),
        "black": 12 - state.piece_count(BLACK),
    }
