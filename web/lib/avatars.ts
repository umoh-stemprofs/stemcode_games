/**
 * Avatar rendering (P1-T06).
 *
 * The keys are the API's fixed set of 24 (`api/app/identity/avatars.py`):
 * non-photographic, identical for every school, and impossible to replace with
 * an uploaded image. Until the original SVG art lands, each key is drawn as an
 * emoji — still non-photographic, still the same 24 choices a learner can pick
 * from, and nothing has to change in the data when the art arrives.
 */

const EMOJI: Record<string, string> = {
  fox: "🦊",
  owl: "🦉",
  panda: "🐼",
  tiger: "🐯",
  penguin: "🐧",
  koala: "🐨",
  dolphin: "🐬",
  hedgehog: "🦔",
  otter: "🦦",
  turtle: "🐢",
  butterfly: "🦋",
  bee: "🐝",
  giraffe: "🦒",
  zebra: "🦓",
  lion: "🦁",
  frog: "🐸",
  parrot: "🦜",
  whale: "🐳",
  squirrel: "🐿️",
  raccoon: "🦝",
  camel: "🐪",
  ladybird: "🐞",
  seal: "🦭",
  crab: "🦀",
};

export const AVATAR_KEYS = Object.keys(EMOJI);

export function avatarEmoji(key: string): string {
  return EMOJI[key] ?? "🙂";
}

/** Read-aloud name, so a screen reader says "owl" rather than "picture". */
export function avatarLabel(key: string): string {
  return key.charAt(0).toUpperCase() + key.slice(1);
}
