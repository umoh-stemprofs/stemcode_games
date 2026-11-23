/**
 * Word Scramble rules, offline (P9-T03).
 *
 * A direct port of `api/app/games/domain/wordscramble.py`. The server replays
 * an offline batch to re-score it, so "close enough" is not close enough: the
 * same seed must pick the same ten items and arrange the same letters. Every
 * function here is pure, and `shared/parity/game-rules.json` is the contract
 * between the two languages.
 *
 * As on the server, nothing here knows the answer at round-build time: the
 * rounds carry letters and the clue, and the answer is checked separately.
 */

import { PythonRandom } from "./random";

export const GAME_ID = "word_scramble";
export const ROUNDS = 10;
export const ROUND_SECONDS = 45;
export const DEADLINE_GRACE_SECONDS = 2;
export const MAX_ATTEMPTS = 2;
export const HINT_COST = 3;
export const BASE_POINTS = 10;
export const MAX_TIME_BONUS = 5;
export const MIN_ITEMS_PER_PACK = 15;

/** One scramble item, with the field names the content payload already uses. */
export interface Item {
  id: string;
  answer: string;
  alt_answers: readonly string[];
  clue: string | null;
  clue_image_key: string | null;
  clue_audio_key: string | null;
  difficulty: number;
}

/** The part of an item a round may reveal (P4-T10): never the answer. */
export interface Round {
  item_id: string;
  letters: string;
  clue: string | null;
  clue_image_key: string | null;
  clue_audio_key: string | null;
}

export function normalise(value: string): string {
  return value.trim().toLowerCase();
}

/**
 * False for `zzzz`, which has exactly one arrangement.
 *
 * A word whose letters are all identical cannot be scrambled into something
 * different, so the generator would have to send the answer as the puzzle.
 */
export function hasAnotherArrangement(word: string): boolean {
  return new Set(word).size > 1;
}

/** 0..5, linear over the round timer. Faster answers score more. */
export function timeBonus(elapsedSeconds: number): number {
  const remaining = Math.max(0, ROUND_SECONDS - Math.max(0, elapsedSeconds));
  return Math.min(MAX_TIME_BONUS, Math.trunc((MAX_TIME_BONUS * remaining) / ROUND_SECONDS));
}

/** The points for a correct answer: base + bonus, hint cost, half on a retry. */
export function roundScore({
  elapsedSeconds,
  usedHint,
  attempt,
}: {
  elapsedSeconds: number;
  usedHint: boolean;
  attempt: number;
}): number {
  let score = BASE_POINTS + timeBonus(elapsedSeconds);
  if (usedHint) score -= HINT_COST;
  score = Math.max(0, score);
  if (attempt >= 2) score = Math.floor(score / 2);
  return Math.max(0, score);
}

export function deadline(startedAt: Date): Date {
  return new Date(startedAt.getTime() + (ROUND_SECONDS + DEADLINE_GRACE_SECONDS) * 1000);
}

export function isLate(startedAt: Date, now: Date): boolean {
  return now.getTime() > deadline(startedAt).getTime();
}

export function isCorrect(item: Item, value: string): boolean {
  const guess = normalise(value);
  if (guess === normalise(item.answer)) return true;
  return item.alt_answers.some((alt) => normalise(alt) === guess);
}

/** What a hint shows: the first letter only. */
export function revelation(answer: string): string {
  return answer.slice(0, 1).toUpperCase();
}

/**
 * A different arrangement of the answer's letters.
 *
 * The 20 attempts and the rotation fallback mirror the Python loop, including
 * its exact use of the shared RNG: a different number of draws here would move
 * every later round.
 */
export function scramble(answer: string, rng: PythonRandom): string {
  const letters = [...answer];
  for (let attempt = 0; attempt < 20; attempt += 1) {
    rng.shuffle(letters);
    const mixed = letters.join("");
    if (mixed !== answer) return mixed;
  }
  return answer.slice(1) + answer.slice(0, 1);
}

/** Pick ten items and scramble them; the rounds never include the answer. */
export function buildRounds(items: readonly Item[], rng: PythonRandom): Round[] {
  if (items.length < ROUNDS) {
    throw new Error("not enough items to build a session");
  }
  return rng.sample(items, ROUNDS).map((item) => ({
    item_id: item.id,
    letters: scramble(item.answer, rng),
    clue: item.clue,
    clue_image_key: item.clue_image_key,
    clue_audio_key: item.clue_audio_key,
  }));
}
