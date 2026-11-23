/**
 * Number Guess rules, offline (P9-T03).
 *
 * A direct port of `api/app/games/domain/guessing.py`, for the same reason as
 * Word Scramble: an offline batch is replayed on the server, so the local
 * secret at `(seed, index, difficulty)` must be the server's secret. The seed
 * is an integer, and the Python original seeds with the text `"{seed}:{index}"`
 * so each of the five numbers gets its own stream; that detail is preserved
 * exactly here.
 *
 * The secret is derived, never stored, on both sides. Nothing in this module
 * hands it to a screen; a view only ever learns `higher`, `lower` or `correct`.
 */

import { PythonRandom } from "./random";

export const GAME_ID = "number_guess";
export const ROUNDS = 5;
export const ROUND_SECONDS = 60;
// A slow connection must not lose a number (D-24).
export const DEADLINE_GRACE_SECONDS = 2;
// D-29's activity minimum: fewer solved numbers awards no XP.
export const MIN_SOLVED = 2;
export const MAX_POINTS_PER_NUMBER = 100;

export interface Level {
  low: number;
  high: number;
  tries: number;
}

export const LEVELS: Readonly<Record<number, Level>> = {
  1: { low: 1, high: 50, tries: 8 },
  2: { low: 1, high: 200, tries: 9 },
  3: { low: 1, high: 1000, tries: 10 },
};

export type Verdict = "correct" | "higher" | "lower";

export function levelFor(difficulty: number): Level {
  const level = LEVELS[difficulty];
  if (level === undefined) throw new RangeError(`no difficulty ${difficulty}`);
  return level;
}

/** The five numbers of a session, without their secrets. */
export function roundsFor(difficulty: number): Array<{
  number: number;
  low: number;
  high: number;
  tries: number;
}> {
  const level = levelFor(difficulty);
  return Array.from({ length: ROUNDS }, (_, index) => ({
    number: index + 1,
    low: level.low,
    high: level.high,
    tries: level.tries,
  }));
}

/**
 * The number to find, reproducible from the session seed alone.
 *
 * The text seed is `"{seed}:{index}"`, not the bare seed: two positions in one
 * session must not share a stream. `seed` is a bigint where the server's
 * 63-bit value would lose precision as a JS number.
 */
export function secretFor(seed: bigint | number, index: number, difficulty: number): number {
  const level = levelFor(difficulty);
  return new PythonRandom(`${seed.toString()}:${index}`).randint(level.low, level.high);
}

export function inRange(value: number, level: Level): boolean {
  return level.low <= value && value <= level.high;
}

/** `correct`, or which way the learner must move next. */
export function compare(secret: number, guess: number): Verdict {
  if (guess === secret) return "correct";
  return secret > guess ? "higher" : "lower";
}

/** The range after a wrong guess, so the bar visibly shrinks. */
export function narrow(low: number, high: number, guess: number, feedback: Verdict): [number, number] {
  if (feedback === "higher") return [Math.max(low, guess + 1), high];
  if (feedback === "lower") return [low, Math.min(high, guess - 1)];
  return [low, high];
}

/**
 * Points for a correct guess: 100 on the first try, less on later ones.
 *
 * `int(100 * remaining / tries + 0.5)` is half-up rounding, because Python's
 * `round` is banker's rounding and two learners on the same try would get
 * different points depending on the neighbour's parity.
 */
export function scoreFor({ attempt, tries }: { attempt: number; tries: number }): number {
  if (tries <= 0) return 0;
  const used = Math.min(Math.max(1, attempt), tries);
  const remaining = tries - used + 1;
  return Math.floor((MAX_POINTS_PER_NUMBER * remaining) / tries + 0.5);
}

export function deadline(startedAt: Date): Date {
  return new Date(startedAt.getTime() + (ROUND_SECONDS + DEADLINE_GRACE_SECONDS) * 1000);
}

export function isLate(startedAt: Date, now: Date): boolean {
  return now.getTime() > deadline(startedAt).getTime();
}

/**
 * The one sentence a learner sees for a server feedback code (Appendix D).
 *
 * An unknown code gets a safe sentence rather than reaching the screen raw.
 */
export function feedbackSentence(feedback: string): string {
  const sentences: Record<string, string> = {
    higher: "Too low. Go up.",
    lower: "Too high. Go down.",
    correct: "You found it!",
    repeat: "You tried that number.",
    out_of_range: "That number is outside the box.",
  };
  return sentences[feedback] ?? "Try another number.";
}
