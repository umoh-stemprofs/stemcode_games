/**
 * The words the content screens show (P4-T05).
 *
 * Statuses are kept out of the UI as codes: a person reads "Waiting for a
 * check", never "in_review". One place, so the list and the editor cannot
 * describe the same status two different ways.
 */

export const STATUS_WORDS: Record<string, string> = {
  draft: "Draft",
  live: "Live",
  retired: "Taken down",
  published: "In play",
};

/** Mirrors `MIN_ITEMS_PER_LEVEL` on the server (P4-T03). */
export const MIN_WORDS_PER_LEVEL = 15;

export const LEVEL_WORDS: Record<number, string> = {
  1: "Easy",
  2: "Medium",
  3: "Hard",
};
