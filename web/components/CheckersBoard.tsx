"use client";

/**
 * The Checkers board (P8-T17, Appendix D).
 *
 * Rules the screen obeys:
 *
 * - **Tap a piece, then a square.** The server sends this player's legal moves
 *   and nothing else, so only those squares are offered. An illegal move is not
 *   a red flash: it cannot be tapped.
 * - **The board shows where to start.** A learner who cannot read still has to
 *   find the first tap, so every piece that may move carries a ring, and when
 *   only one piece may move it is selected for them (D.3: "a forced piece is
 *   auto-selected"). With a capture owed, the ring sits under an arrow and the
 *   page says "You must jump!".
 * - **56px targets, 20px text.** Each square is a large button, not a canvas
 *   with a hit-test.
 * - **The board is the scoreboard.** No counters to read, just the pieces.
 *
 * White pieces sit at the bottom and move up, because that is how the board
 * looks on a draughts table when you are the white player.
 */

import { useEffect, useMemo, useState } from "react";

import type { LegalMove, Seat } from "@/lib/games/live";
import { BLACK_KING, BLACK_MAN, WHITE_KING, WHITE_MAN, squareAt } from "@/lib/games/live";

const FILES = ["a", "b", "c", "d", "e", "f", "g", "h"];

export function CheckersBoard({
  board,
  seat,
  legalMoves,
  onMove,
  disabled,
}: {
  board: number[];
  seat: Seat;
  legalMoves: LegalMove[];
  onMove: (moveKey: string) => void;
  disabled: boolean;
}) {
  const [selected, setSelected] = useState<number | null>(null);

  // Every piece the server says may move, and whether all of their moves are
  // captures (in draughts a capture must be taken, so tapping anything else is
  // not just a bad move — it is not a move at all).
  const movable = useMemo(
    () => new Set(legalMoves.map((move) => move.from)),
    [legalMoves],
  );
  const mustJump = legalMoves.length > 0 && legalMoves.every((move) => move.captures.length > 0);
  const movableKey = [...movable].sort((a, b) => a - b).join(",");

  // One piece to move? Select it, so the destinations are already showing and
  // the learner only has to make the second tap.
  useEffect(() => {
    if (movable.size === 1) {
      setSelected([...movable][0] ?? null);
      return;
    }
    setSelected(null);
  }, [movableKey, movable]);

  const fromMine = useMemo(
    () => legalMoves.filter((move) => move.from === selected),
    [legalMoves, selected],
  );
  const targets = useMemo(
    () => new Map(fromMine.map((move) => [move.to, move])),
    [fromMine],
  );

  function tap(square: number) {
    if (disabled) return;
    const move = targets.get(square);
    if (move) {
      setSelected(null);
      onMove(move.key);
      return;
    }
    // A new piece to look at, or a tap on empty board that means "never mind".
    setSelected(square);
  }

  // Row 0 in the engine is white's promotion row, so drawing it at the bottom
  // gives the player their own side of the table.
  const rows = seat === "white" ? [0, 1, 2, 3, 4, 5, 6, 7] : [7, 6, 5, 4, 3, 2, 1, 0];

  // Eight squares at the 56px minimum cannot fit a phone, so the board keeps
  // its targets and scrolls sideways inside this box instead of widening the
  // page. Without the box the whole screen was pushed past the viewport and the
  // right-hand file was clipped away.
  return (
    <div className="w-full overflow-x-auto">
      <div
        className="grid min-w-[448px] grid-cols-8 overflow-hidden rounded-2xl border-2 border-line-strong shadow-card"
        role="grid"
        aria-label="Checkers board"
      >
        {rows.map((engineRow) =>
          FILES.map((file, col) => {
            const square = squareAt(engineRow, col);
            if (square === null) {
              return (
                <div
                  key={`${engineRow}-${col}`}
                  className="aspect-square bg-surface-muted"
                />
              );
            }
            const piece = board[square] ?? 0;
            const mine = seat === "white" ? [WHITE_MAN, WHITE_KING] : [BLACK_MAN, BLACK_KING];
            const isMine = mine.includes(piece);
            const canMove = movable.has(square);
            const canTap = !disabled && (isMine || targets.has(square));
            const isTarget = targets.has(square);
            const label = describe(square, piece, isTarget, canMove);

            return (
              <button
                key={`${engineRow}-${col}`}
                type="button"
                role="gridcell"
                aria-label={label}
                aria-pressed={selected === square}
                tabIndex={canTap ? 0 : -1}
                onClick={() => tap(square)}
                className={`relative flex aspect-square min-h-target items-center justify-center text-large font-semibold transition-colors ${
                  selected === square
                    ? "bg-brand text-brand-contrast"
                    : isTarget
                      ? "bg-ok"
                      : "bg-ink"
                } ${canTap ? "cursor-pointer" : "cursor-default"}`}
              >
                {mustJump && canMove ? (
                  <span
                    aria-hidden="true"
                    className="pointer-events-none absolute inset-x-0 top-0 text-center text-[12px] leading-none text-[color:var(--color-surface)]"
                  >
                    ▼
                  </span>
                ) : null}
                <Piece piece={piece} ringed={canMove && !disabled} />
              </button>
              );
            }),
          )}
      </div>
    </div>
  );
}

function Piece({ piece, ringed }: { piece: number; ringed: boolean }) {
  if (piece === 0) return <span aria-hidden="true" />;
  const isWhite = piece === WHITE_MAN || piece === WHITE_KING;
  const isKing = piece === WHITE_KING || piece === BLACK_KING;
  return (
    <span
      aria-hidden="true"
      className={`flex h-[70%] w-[70%] items-center justify-center rounded-full border-2 text-body-min ${
        isWhite
          ? "border-[color:var(--color-ink)] bg-[color:var(--color-surface)] text-[color:var(--color-ink)]"
          : "border-[color:var(--color-surface)] bg-[color:var(--color-ink)] text-[color:var(--color-surface)]"
      } ${ringed ? "ring-[3px] ring-focus" : ""}`}
    >
      {isKing ? "★" : ""}
    </span>
  );
}

function describe(
  square: number,
  piece: number,
  isTarget: boolean,
  canMove: boolean,
): string {
  const row = Math.floor(square / 4);
  const col = 2 * (square % 4) + (row % 2 === 0 ? 1 : 0);
  const name = `${FILES[col] ?? "?"}${8 - row}`;
  if (piece === 0) return isTarget ? `${name}, you can move here` : `${name}, empty`;
  const colour = piece === WHITE_MAN || piece === WHITE_KING ? "White" : "Black";
  const king = piece === WHITE_KING || piece === BLACK_KING ? " king" : "";
  const start = canMove ? ", you can move this one" : "";
  return `${name}, ${colour}${king}${start}${isTarget ? ", you can move here" : ""}`;
}
