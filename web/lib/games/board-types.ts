/**
 * XP and leaderboard shapes (Phase 5).
 *
 * Mirrors `api/app/games/schemas.py`. Identity is masked everywhere: a board
 * row carries a preferred name and an avatar, never a real name (D-15).
 */

export type MeXp = {
  learning_xp_total: number;
  game_xp_total: number;
  profile_xp_total: number;
  game_xp_today: number;
  daily_cap: number;
};

export type BoardEntry = {
  rank: number;
  preferred_name: string;
  avatar_key: string;
  xp_total: number;
  sessions_count: number;
  is_me: boolean;
};

export type BoardChase = {
  preferred_name: string;
  xp_gap: number;
};

export type Board = {
  period: string;
  starts_at: string;
  ends_at: string | null;
  entries: BoardEntry[];
  me: BoardEntry | null;
  me_eligible: boolean;
  min_sessions: number;
  // Near-miss nudges, learner only. Null for staff and for the top of a board.
  chase: BoardChase | null;
  to_join: number | null;
};

export type Engagement = {
  streak: {
    current: number;
    longest: number;
    played_today: boolean;
    last_played_on: string | null;
  };
  quest: {
    id: string;
    title: string;
    target: number;
    progress: number;
    completed: boolean;
    reward_xp: number;
  };
  badges: Badge[];
  bests: Best[];
  level: {
    number: number;
    xp_into: number;
    xp_span: number;
    xp_to_next: number;
    profile_xp: number;
  };
};

export type Badge = {
  id: string;
  title: string;
  sentence: string;
  hint: string;
  earned_on: string | null;
};

export type Best = {
  game_id: string;
  name: string;
  value: string;
  played: number;
};

export type BoardPeriod = "daily" | "weekly" | "termly" | "all_time" | "monthly";

export const PERIOD_WORDS: Record<string, string> = {
  daily: "Today",
  weekly: "This week",
  termly: "This term",
  monthly: "This month",
  all_time: "All time",
};

export type StudentGameXp = {
  game_id: string;
  xp_total: number;
  sessions_count: number;
};

export type StudentXp = {
  preferred_name: string;
  avatar_key: string;
  xp_total: number;
  sessions_count: number;
  games: StudentGameXp[];
};

export type CoachBoard = {
  period: string;
  starts_at: string;
  ends_at: string | null;
  students: StudentXp[];
};

export type SchoolTerm = {
  id: string;
  name: string;
  starts_on: string;
  ends_on: string;
};
