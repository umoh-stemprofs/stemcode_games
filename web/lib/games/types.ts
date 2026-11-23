/**
 * Shapes from the games access endpoints (Phase 3).
 *
 * These mirror `api/app/games/schemas.py`. They are written by hand because the
 * pages touch a handful of fields; `lib/api/schema.ts` remains the generated
 * source of truth for anything new.
 */

export type AccessReason =
  | "ok"
  | "limit_reached"
  | "not_enough_time"
  | "locked_out"
  | "games_disabled"
  | "another_session_active"
  | "leaderboards_only";

export type AccessState = {
  allowed: boolean;
  reason: AccessReason;
  limit_minutes: number;
  limit_source: "platform" | "school" | "class" | "student";
  used_seconds: number;
  remaining_seconds: number;
  locked_until: string | null;
  local_date: string;
  resets_at: string;
  server_time: string;
};

export type MemberAccessRow = {
  user_id: string;
  preferred_name: string;
  avatar_key: string;
  limit_minutes: number;
  limit_source: string;
  used_seconds: number;
  remaining_seconds: number;
  locked_until: string | null;
  lockout_reason: string | null;
};

export type ClassAccessTable = {
  class_id: string;
  class_name: string;
  members: MemberAccessRow[];
};

export type AccessPolicy = {
  id: string;
  scope_type: "platform" | "school" | "class" | "student";
  scope_id: string | null;
  daily_limit_minutes: number;
  valid_from: string;
  valid_until: string | null;
  reason: string;
  set_by: string;
  created_at: string;
};

export type Lockout = {
  id: string;
  scope_type: "class" | "student";
  scope_id: string;
  reason: string;
  starts_at: string;
  expires_at: string;
  revoked_at: string | null;
  created_at: string;
};

export type GameSummary = {
  id: string;
  name: string;
  summary: string;
  is_live: boolean;
};

export type ActiveSession = {
  session_id: string | null;
  game_id: string | null;
};

export type RoundState = {
  number: number;
  time_left_ms: number;
  round_seconds: number;
  // Word Scramble (P4-T13).
  letters: string;
  clue: string | null;
  clue_image_key: string | null;
  clue_audio_key: string | null;
  revealed: string | null;
  tries_left: number;
  // Number Guess (P6-T03). `message` is the server's own sentence for
  // `feedback`, so this screen never turns a code into English.
  low?: number | null;
  high?: number | null;
  range_low?: number | null;
  range_high?: number | null;
  // The band this number came from (Number Guess). 1 and 2 are the bands whose
  // screen shows the 12-key pad.
  difficulty?: number | null;
  tries_total?: number | null;
  feedback?: "higher" | "lower" | "correct" | "repeat" | "out_of_range" | null;
  message?: string | null;
  guesses?: number[];
};

export type XpAward = {
  awarded: number;
  today: number;
  daily_cap: number;
};

export type PlayState = {
  session_id: string;
  game_id: string;
  status: string;
  round: RoundState | null;
  round_index: number;
  rounds_total: number;
  score: number;
  scores: number[];
  finished: boolean;
  // Present only on the response that finished the game (P5-T10).
  xp?: XpAward | null;
  // Best for this game, and whether this session beat it. Null for Checkers.
  best?: string | null;
  best_is_new?: boolean;
  // One sentence about what just happened: a finished number, a timeout.
  message?: string | null;
};

export type ActionType = "round_seen" | "answer" | "hint" | "skip" | "guess";
