/**
 * Rule parity: the offline TypeScript ports against the shared vectors (P9-T03).
 *
 * `api/tests/test_rules_parity.py` reads the same file. Together they are the
 * contract that lets the server replay an offline batch and get the learner's
 * own result back; a failure here means an offline score would be wrong.
 */

import { readFileSync } from "node:fs";

import { describe, expect, it } from "vitest";

import * as guessing from "./guessing";
import { PythonRandom } from "./random";
import * as wordscramble from "./wordscramble";

interface ScoringCase {
  elapsed_seconds: number;
  used_hint: boolean;
  attempt: number;
  time_bonus: number;
  score: number;
}

interface ItemJson {
  id: string;
  answer: string;
  alt_answers: string[];
  clue: string | null;
  clue_image_key: string | null;
  clue_audio_key: string | null;
  difficulty: number;
}

interface Vectors {
  random: {
    int_seed_stream: { seed: string; values: number[] };
    text_seed_stream: { seed: string; values: number[] };
    shuffle: Array<{ seed: number; values: string[]; expected: string[] }>;
    sample: Array<{ seed: number; n: number; k: number; expected: number[] }>;
  };
  word_scramble: {
    constants: Record<string, number | string>;
    time_bonus: Array<{ elapsed_seconds: number; bonus: number }>;
    round_score: ScoringCase[];
    correctness: Array<{ value: string; correct: boolean }>;
    revelation: Array<{ answer: string; first: string }>;
    scramble: Array<{ seed: number | string; answer: string; letters: string }>;
    build_rounds: Array<{
      name: string;
      seed: number;
      items: ItemJson[];
      expected: Array<{ item_id: string; letters: string; clue: string | null }>;
    }>;
    deadline: Array<{
      name?: string;
      started_at: string;
      deadline_ms?: number;
      now_ms?: number;
      is_late?: boolean;
    }>;
  };
  number_guess: {
    constants: Record<string, number | string>;
    levels: Array<{ difficulty: number; low: number; high: number; tries: number }>;
    rounds_for: Record<string, Array<{ number: number; low: number; high: number; tries: number }>>;
    secrets: Array<{ seed: string; index: number; difficulty: number; secret: number }>;
    scores: Array<{ attempt: number; tries: number; score: number }>;
    compare: Array<{ secret: number; guess: number; verdict: string }>;
    in_range: Array<{ difficulty: number; value: number; allowed: boolean }>;
    narrow: Array<{
      low: number;
      high: number;
      guess: number;
      feedback: ngVerdict;
      expected_low: number;
      expected_high: number;
    }>;
    feedback: Array<{ code: string; sentence: string }>;
    deadline: Array<{
      name?: string;
      started_at: string;
      deadline_ms?: number;
      now_ms?: number;
      is_late?: boolean;
    }>;
  };
}

type ngVerdict = "higher" | "lower" | "correct";

const vectors = JSON.parse(
  readFileSync(new URL("../../../../shared/parity/game-rules.json", import.meta.url), "utf8"),
) as Vectors;

function toItem(entry: ItemJson): wordscramble.Item {
  return {
    id: entry.id,
    answer: entry.answer,
    alt_answers: entry.alt_answers,
    clue: entry.clue,
    clue_image_key: entry.clue_image_key,
    clue_audio_key: entry.clue_audio_key,
    difficulty: entry.difficulty,
  };
}

describe("python-compatible random", () => {
  it("reproduces an integer seed", () => {
    const rng = new PythonRandom(BigInt(vectors.random.int_seed_stream.seed));
    const values = vectors.random.int_seed_stream.values.map(() => rng.getrandbits(32));
    expect(values).toEqual(vectors.random.int_seed_stream.values);
  });

  it("reproduces a text seed", () => {
    const rng = new PythonRandom(vectors.random.text_seed_stream.seed);
    const values = vectors.random.text_seed_stream.values.map(() => rng.getrandbits(32));
    expect(values).toEqual(vectors.random.text_seed_stream.values);
  });

  it("shuffles like CPython", () => {
    for (const testCase of vectors.random.shuffle) {
      const values = [...testCase.values];
      new PythonRandom(testCase.seed).shuffle(values);
      expect(values).toEqual(testCase.expected);
    }
  });

  it("samples like CPython in both branches", () => {
    for (const testCase of vectors.random.sample) {
      const population = Array.from({ length: testCase.n }, (_, index) => index);
      expect(new PythonRandom(testCase.seed).sample(population, testCase.k)).toEqual(
        testCase.expected,
      );
    }
  });
});

describe("word scramble", () => {
  const vectorsForGame = vectors.word_scramble;

  it("matches the constants", () => {
    expect(wordscramble.GAME_ID).toBe(vectorsForGame.constants.game_id);
    expect(wordscramble.ROUNDS).toBe(vectorsForGame.constants.rounds);
    expect(wordscramble.ROUND_SECONDS).toBe(vectorsForGame.constants.round_seconds);
    expect(wordscramble.DEADLINE_GRACE_SECONDS).toBe(
      vectorsForGame.constants.deadline_grace_seconds,
    );
    expect(wordscramble.MAX_ATTEMPTS).toBe(vectorsForGame.constants.max_attempts);
    expect(wordscramble.HINT_COST).toBe(vectorsForGame.constants.hint_cost);
    expect(wordscramble.BASE_POINTS).toBe(vectorsForGame.constants.base_points);
    expect(wordscramble.MAX_TIME_BONUS).toBe(vectorsForGame.constants.max_time_bonus);
    expect(wordscramble.MIN_ITEMS_PER_PACK).toBe(vectorsForGame.constants.min_items_per_pack);
  });

  it("scores time and hints like the server", () => {
    for (const testCase of vectorsForGame.time_bonus) {
      expect(wordscramble.timeBonus(testCase.elapsed_seconds)).toBe(testCase.bonus);
    }
    for (const testCase of vectorsForGame.round_score) {
      expect(
        wordscramble.roundScore({
          elapsedSeconds: testCase.elapsed_seconds,
          usedHint: testCase.used_hint,
          attempt: testCase.attempt,
        }),
      ).toBe(testCase.score);
    }
  });

  it("accepts the same answers", () => {
    const item = toItem({
      id: "item-stone",
      answer: "stone",
      alt_answers: ["stoun", "Stones"],
      clue: "Hard and grey.",
      clue_image_key: "img/stone",
      clue_audio_key: null,
      difficulty: 1,
    });
    for (const testCase of vectorsForGame.correctness) {
      expect(wordscramble.isCorrect(item, testCase.value)).toBe(testCase.correct);
    }
  });

  it("reveals the first letter", () => {
    for (const testCase of vectorsForGame.revelation) {
      expect(wordscramble.revelation(testCase.answer)).toBe(testCase.first);
    }
  });

  it("scrambles with the same draws", () => {
    for (const testCase of vectorsForGame.scramble) {
      const rng = new PythonRandom(BigInt(testCase.seed));
      expect(wordscramble.scramble(testCase.answer, rng)).toBe(testCase.letters);
    }
  });

  it("picks and scrambles the same ten rounds", () => {
    for (const testCase of vectorsForGame.build_rounds) {
      const rounds = wordscramble.buildRounds(
        testCase.items.map(toItem),
        new PythonRandom(testCase.seed),
      );
      expect(
        rounds.map((round) => ({
          item_id: round.item_id,
          letters: round.letters,
          clue: round.clue,
        })),
      ).toEqual(testCase.expected);
    }
  });

  it("agrees on the deadline", () => {
    const startCase = vectorsForGame.deadline[0]!;
    const started = new Date(startCase.started_at);
    expect(wordscramble.deadline(started).getTime()).toBe(startCase.deadline_ms);
    for (const testCase of vectorsForGame.deadline.slice(1)) {
      expect(
        wordscramble.isLate(new Date(testCase.started_at), new Date(testCase.now_ms!)),
      ).toBe(testCase.is_late);
    }
  });
});

describe("number guess", () => {
  const vectorsForGame = vectors.number_guess;

  it("matches the constants", () => {
    expect(guessing.GAME_ID).toBe(vectorsForGame.constants.game_id);
    expect(guessing.ROUNDS).toBe(vectorsForGame.constants.rounds);
    expect(guessing.ROUND_SECONDS).toBe(vectorsForGame.constants.round_seconds);
    expect(guessing.DEADLINE_GRACE_SECONDS).toBe(
      vectorsForGame.constants.deadline_grace_seconds,
    );
    expect(guessing.MIN_SOLVED).toBe(vectorsForGame.constants.min_solved);
    expect(guessing.MAX_POINTS_PER_NUMBER).toBe(
      vectorsForGame.constants.max_points_per_number,
    );
  });

  it("matches the levels and their rounds", () => {
    for (const testCase of vectorsForGame.levels) {
      expect(guessing.levelFor(testCase.difficulty)).toEqual({
        low: testCase.low,
        high: testCase.high,
        tries: testCase.tries,
      });
    }
    for (const [difficulty, expected] of Object.entries(vectorsForGame.rounds_for)) {
      expect(guessing.roundsFor(Number(difficulty))).toEqual(expected);
    }
  });

  it("derives the same secret for every seed", () => {
    for (const testCase of vectorsForGame.secrets) {
      expect(
        guessing.secretFor(BigInt(testCase.seed), testCase.index, testCase.difficulty),
      ).toBe(testCase.secret);
    }
  });

  it("scores every attempt like the server", () => {
    for (const testCase of vectorsForGame.scores) {
      expect(guessing.scoreFor({ attempt: testCase.attempt, tries: testCase.tries })).toBe(
        testCase.score,
      );
    }
  });

  it("compares and narrows the same way", () => {
    for (const testCase of vectorsForGame.compare) {
      expect(guessing.compare(testCase.secret, testCase.guess)).toBe(testCase.verdict);
    }
    for (const testCase of vectorsForGame.in_range) {
      expect(guessing.inRange(testCase.value, guessing.levelFor(testCase.difficulty))).toBe(
        testCase.allowed,
      );
    }
    for (const testCase of vectorsForGame.narrow) {
      expect(
        guessing.narrow(testCase.low, testCase.high, testCase.guess, testCase.feedback),
      ).toEqual([testCase.expected_low, testCase.expected_high]);
    }
  });

  it("speaks the same sentences", () => {
    for (const testCase of vectorsForGame.feedback) {
      expect(guessing.feedbackSentence(testCase.code)).toBe(testCase.sentence);
    }
  });

  it("agrees on the deadline", () => {
    const startCase = vectorsForGame.deadline[0]!;
    const started = new Date(startCase.started_at);
    expect(guessing.deadline(started).getTime()).toBe(startCase.deadline_ms);
    for (const testCase of vectorsForGame.deadline.slice(1)) {
      expect(guessing.isLate(new Date(testCase.started_at), new Date(testCase.now_ms!))).toBe(
        testCase.is_late,
      );
    }
  });
});
