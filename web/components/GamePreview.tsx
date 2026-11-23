/**
 * The little picture on a game card.
 *
 * A learner who cannot yet read a sentence picks their game by the picture
 * (Appendix D, step 1), so each game gets a different shape, not just a
 * different label: a chequered board, a shrinking number window, four loose
 * letter tiles.
 *
 * Purely decorative — the card's heading already names the game.
 */

import { cx } from "@/components/ui";

export type GameAccent = "blue" | "green" | "violet";

export const GAME_LOOK: Record<
  string,
  {
    chip: string;
    tone: GameAccent;
    variant: "primary" | "success" | "violet";
    href: string;
    label: string;
  }
> = {
  checkers: {
    chip: "1v1 match",
    tone: "blue",
    variant: "primary",
    href: "/games/checkers",
    label: "Play Checkers",
  },
  number_guess: {
    chip: "Math logic",
    tone: "green",
    variant: "success",
    href: "/games/number_guess",
    label: "Play Number Guess",
  },
  word_scramble: {
    chip: "Vocabulary",
    tone: "violet",
    variant: "violet",
    href: "/games/word_scramble",
    label: "Play Word Scramble",
  },
};

export function GamePreview({ gameId }: { gameId: string }) {
  if (gameId === "checkers") {
    return (
      <div
        aria-hidden="true"
        className="grid h-32 w-full grid-cols-4 grid-rows-3 gap-1.5 rounded-2xl border border-line bg-surface-muted p-3"
      >
        {Array.from({ length: 12 }, (_, index) => {
          const dark = (Math.floor(index / 4) + index) % 2 === 1;
          const piece = [1, 3, 6, 8, 11].includes(index);
          return (
            <div
              key={index}
              className={cx(
                "flex items-center justify-center rounded",
                dark ? "bg-brand" : "bg-brand-soft",
              )}
            >
              {piece ? (
                <span
                  className={cx(
                    "block size-3.5 rounded-full border-2",
                    index === 6
                      ? "border-white bg-focus"
                      : index === 3
                        ? "border-white bg-ink"
                        : "border-white bg-white",
                  )}
                />
              ) : null}
            </div>
          );
        })}
      </div>
    );
  }

  if (gameId === "number_guess") {
    return (
      <div
        aria-hidden="true"
        className="flex h-32 w-full flex-col items-center justify-between rounded-2xl border border-ok-soft bg-surface-muted p-3"
      >
        <div className="flex w-full items-center justify-between text-[11px] font-bold uppercase tracking-wide text-ink-muted">
          <span>Range: 1</span>
          <span>Target: 100</span>
        </div>
        <span className="tabular grid size-11 place-items-center rounded-xl bg-ok text-lg font-bold text-white">
          42
        </span>
        <span className="text-[11px] font-bold text-ok">Between 43 and 75</span>
      </div>
    );
  }

  return (
    <div
      aria-hidden="true"
      className="flex h-32 w-full items-center justify-center gap-2 rounded-2xl border border-violet-soft bg-surface-muted p-3"
    >
      {["W", "O", "R", "D"].map((letter, index) => (
        <span
          key={letter}
          className={cx(
            "grid size-9 place-items-center rounded-lg text-sm font-extrabold shadow-sm",
            index % 2 === 0
              ? "border border-violet bg-surface text-violet"
              : "bg-violet text-white",
            index === 0
              ? "-rotate-6"
              : index === 1
                ? "rotate-3"
                : index === 2
                  ? "-rotate-3"
                  : "rotate-6",
          )}
        >
          {letter}
        </span>
      ))}
    </div>
  );
}
