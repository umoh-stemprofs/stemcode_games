"use client";

/**
 * Number Guess (P6-T03): one number at a time.
 *
 * Appendix D in this screen's own terms:
 *
 * - **The box is the instruction.** "12 to 40", plus a bar that only gets
 *   shorter, so nobody has to hold a range in their head.
 * - **An arrow and words.** "Too low. Go up." is the server's sentence, so the
 *   wording lives in one place and this screen never invents its own.
 * - **Tries are pips and a sentence.** Filled dots, and "3 tries left."
 * - **A big 12-key pad, and a stepper.** On the two bands a child starts on,
 *   every digit is a 56px key, so a guess needs no keyboard and no reading: the
 *   pad's own ✓ submits. The −/+ stepper stays underneath both bands for a
 *   learner who is close and only wants to nudge. The Hard band keeps the typed
 *   box and the big button instead of the pad, because four digits of tapping
 *   buys nothing over the device's keyboard.
 *
 * The pad appends digits to one draft. When the box was filled by the machine (a
 * fresh midpoint, or a nudge), the next digit starts a new number rather than
 * extending the old one — the same way typing into a selected field behaves, and
 * the reason a child who wants 12 does not get 2512.
 */

import { useEffect, useState } from "react";

import { Icon } from "@/components/icons";
import { RoundClock } from "@/components/RoundClock";
import { Alert, Button, Card, cx } from "@/components/ui";
import type { PlayState } from "@/lib/games/types";

/** The bands whose numbers are short enough for a tap-only entry. */
const PAD_BANDS = new Set([1, 2]);

export function GuessScreen({
  state,
  feedback,
  error,
  pending,
  onGuess,
  onSkip,
  onExpire,
  started,
}: {
  state: PlayState;
  feedback: string | null;
  error: string | null;
  pending: boolean;
  onGuess: (number: number) => void;
  onSkip: () => void;
  onExpire: () => void;
  started: boolean;
}) {
  const round = state.round;

  // The next guess starts in the middle of what is left: the best first guess,
  // and always a sensible one after a "go up" or "go down".
  const low = round?.low ?? 1;
  const high = round?.high ?? 100;
  const number = round?.number;
  const mid = Math.round((low + high) / 2);

  const [draft, setDraft] = useState(String(mid));
  // True when the box holds a number the screen chose, so the next digit starts
  // a new one instead of extending it.
  const [fresh, setFresh] = useState(true);

  useEffect(() => {
    setDraft(String(mid));
    setFresh(true);
  }, [number, mid]);

  if (!round) return null;

  const rangeLow = round.range_low ?? low;
  const rangeHigh = round.range_high ?? high;
  const span = Math.max(1, rangeHigh - rangeLow + 1);
  const leftPct = ((low - rangeLow) / span) * 100;
  const widthPct = Math.max(2, ((high - low + 1) / span) * 100);
  const triesTotal = round.tries_total ?? round.tries_left;
  const arrow = round.feedback === "higher" ? "↑" : round.feedback === "lower" ? "↓" : "";
  const history = (round.guesses ?? []).slice(-6);

  const showPad = round.difficulty != null && PAD_BANDS.has(round.difficulty);
  const typed = Number(draft);
  const ready = draft !== "" && Number.isFinite(typed);

  // An arrow per past guess, read off the window it produced: a guess below the
  // window was too low, one above it was too high.
  const arrowFor = (guess: number) => (guess < low ? "↑" : guess > high ? "↓" : "");

  /** A pad digit: replaces a machine-set number, extends one the learner is building. */
  function press(digit: number) {
    const base = fresh ? "" : draft;
    const next = `${base}${digit}`;
    // A slip should not build a number the box never contains: no leading zero
    // (no box starts at 0, so "05" is always a mistake) and nothing past the
    // top of this box. The server would wave both through as free, but a key
    // that leaves a number nobody can submit is worse than one that does nothing.
    if (next.startsWith("0")) return;
    if (next.length > String(rangeHigh).length || Number(next) > rangeHigh) return;
    setDraft(next);
    setFresh(false);
  }

  function backspace() {
    if (fresh) return;
    const next = draft.slice(0, -1);
    if (next === "") {
      setDraft(String(mid));
      setFresh(true);
      return;
    }
    setDraft(next);
  }

  /** The stepper nudges the number in the box, then hands the box back to the machine. */
  function nudge(delta: number) {
    const current = fresh || !ready ? mid : typed;
    const next = Math.min(rangeHigh, Math.max(rangeLow, current + delta));
    setDraft(String(next));
    setFresh(true);
  }

  function submit() {
    if (!ready) return;
    onGuess(typed);
  }

  return (
    <div className="flex flex-col gap-5">
      {/* "What do I do now?" first (D.2.1), and no running score: D.2.5 allows
          only the points just gained, and the old counter row spent six of the
          twenty-five words on numbers nobody had to read. */}
      <div className="flex flex-col gap-2">
        <h1 className="font-headline text-large font-extrabold text-ink">Tap a number.</h1>

        {/* Rounds are dots and time is a bar, so the two never look alike: a
            learner watching a bar drain should not wonder which one runs out. */}
        <div className="flex gap-1.5" aria-hidden="true">
          {Array.from({ length: state.rounds_total }).map((_, index) => (
            <span
              key={index}
              className={cx(
                "h-2.5 w-2.5 rounded-full",
                index < state.round_index ? "bg-brand" : "bg-line",
              )}
            />
          ))}
        </div>
      </div>

      <RoundClock
        round={round}
        started={started}
        onExpire={onExpire}
        label="Time left for this number"
      />

      {/* D.2.3: the consequence is said before it can happen, in a line a
          learner can point at when asked what an empty bar means. */}
      <p className="flex items-center gap-2 text-label font-semibold text-ink-muted">
        <Icon name="hourglass" size={16} />
        Empty bar, no points.
      </p>

      <Card className="flex flex-col gap-3 p-5">
        <p className="tabular text-center font-headline text-[clamp(30px,7vw,44px)] font-extrabold leading-none text-ink">
          {low} <span className="text-ink-muted">to</span> {high}
        </p>

        <div
          className="relative h-3 w-full overflow-hidden rounded-pill bg-surface-sunk"
          aria-hidden="true"
        >
          <div
            className="absolute inset-y-0 rounded-pill bg-ok"
            style={{ left: `${leftPct}%`, width: `${widthPct}%` }}
          />
        </div>
      </Card>

      {arrow ? (
        <p
          role="status"
          className="flex items-center gap-3 rounded-2xl bg-ok-soft px-4 py-3 font-headline text-large font-bold text-ok"
        >
          <span aria-hidden="true" className="text-[40px] leading-none">
            {arrow}
          </span>
          <span>{round.message}</span>
        </p>
      ) : feedback ? (
        <p
          role="status"
          className="rounded-2xl bg-brand-soft px-4 py-3 font-headline text-large font-bold text-brand-deep"
        >
          {feedback}
        </p>
      ) : null}

      {error ? <Alert>{error}</Alert> : null}

      {/* The box, with the stepper either side: the number it holds is the guess
          the pad and the big button both submit. */}
      <div className="flex items-center gap-3">
        <button
          type="button"
          disabled={pending}
          aria-label="One less"
          onClick={() => nudge(-1)}
          className="flex min-h-[64px] min-w-target items-center justify-center rounded-2xl border-2 border-line bg-surface font-headline text-large font-bold text-ink transition-colors hover:bg-surface-muted disabled:opacity-50"
        >
          −
        </button>
        <input
          type="number"
          inputMode="numeric"
          aria-label="Your number"
          value={draft}
          min={rangeLow}
          max={rangeHigh}
          onChange={(event) => {
            setDraft(event.target.value);
            setFresh(false);
          }}
          className="tabular min-h-[64px] w-full rounded-2xl border-2 border-line bg-surface text-center font-headline text-[34px] font-extrabold text-ink outline-none transition-colors focus:border-brand focus:ring-4 focus:ring-brand-soft"
        />
        <button
          type="button"
          disabled={pending}
          aria-label="One more"
          onClick={() => nudge(1)}
          className="flex min-h-[64px] min-w-target items-center justify-center rounded-2xl border-2 border-line bg-surface font-headline text-large font-bold text-ink transition-colors hover:bg-surface-muted disabled:opacity-50"
        >
          +
        </button>
      </div>

      {showPad ? (
        <div className="grid grid-cols-3 gap-2.5">
          {[1, 2, 3, 4, 5, 6, 7, 8, 9].map((digit) => (
            <button
              key={digit}
              type="button"
              disabled={pending}
              aria-label={`${digit}`}
              onClick={() => press(digit)}
              className="tabular flex min-h-[64px] items-center justify-center rounded-2xl border-2 border-line bg-surface font-headline text-large font-extrabold text-ink shadow-tile transition-colors hover:border-brand hover:bg-brand-soft disabled:opacity-50"
            >
              {digit}
            </button>
          ))}
          <button
            type="button"
            disabled={pending || fresh}
            aria-label="Delete the last digit"
            onClick={backspace}
            className="flex min-h-[64px] items-center justify-center rounded-2xl border-2 border-line bg-surface font-headline text-large font-extrabold text-ink transition-colors hover:bg-surface-muted disabled:opacity-40"
          >
            ⌫
          </button>
          <button
            type="button"
            disabled={pending}
            aria-label="0"
            onClick={() => press(0)}
            className="tabular flex min-h-[64px] items-center justify-center rounded-2xl border-2 border-line bg-surface font-headline text-large font-extrabold text-ink shadow-tile transition-colors hover:border-brand hover:bg-brand-soft disabled:opacity-50"
          >
            0
          </button>
          {/* The pad's own submit, so the two bands never show two buttons that
              do the same thing. */}
          <button
            type="button"
            disabled={pending || !ready}
            aria-label="That is my number"
            onClick={submit}
            className="flex min-h-[64px] items-center justify-center rounded-2xl bg-brand font-headline text-large font-extrabold text-white shadow-primary transition-colors hover:bg-brand-deep disabled:opacity-50"
          >
            ✓
          </button>
        </div>
      ) : null}

      <div className="flex gap-2" aria-hidden="true">
        {Array.from({ length: triesTotal }).map((_, index) => (
          <span
            key={index}
            className={cx(
              "h-2.5 flex-1 rounded-pill",
              index < round.tries_left ? "bg-ok" : "bg-surface-sunk",
            )}
          />
        ))}
      </div>

      <p className="text-label font-semibold text-ink-muted">
        {round.tries_left === 1 ? "1 try left." : `${round.tries_left} tries left.`}
      </p>

      {history.length > 0 ? (
        <ul className="flex flex-wrap gap-2">
          {history.map((guess) => (
            <li
              key={guess}
              className="tabular rounded-xl border border-line bg-surface px-3 py-1 text-label font-bold text-ink-muted"
            >
              {guess} <span aria-hidden="true">{arrowFor(guess)}</span>
            </li>
          ))}
        </ul>
      ) : null}

      <div className="flex flex-col gap-3">
        {/* The pad carries its own submit on the two bands that show one, so this
            button would be a second way to do the same thing there. */}
        {showPad ? null : (
          <Button size="lg" disabled={pending || !ready} onClick={submit} arrow className="w-full">
            That is my number
          </Button>
        )}
        <Button variant="ghost" disabled={pending} onClick={onSkip} className="w-full">
          Show me the number
        </Button>
      </div>
    </div>
  );
}
