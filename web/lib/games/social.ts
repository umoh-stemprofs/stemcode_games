/**
 * Shapes from the Phase 7 endpoints (P7-T01 .. P7-T09).
 *
 * Mirrors `api/app/games/schemas.py`. Hand-written for the same reason the
 * other game types are: these pages read a handful of fields, and the generated
 * client stays the source of truth for everything else.
 */

export type Friend = {
  id: string;
  name: string;
  can_invite: boolean;
  sentence: string;
};

export type ChallengeCreated = {
  parent_id: string;
  invitation_id: string;
  game_id: string;
  game_name: string;
  code: string | null;
  formatted_code: string | null;
  join_path: string | null;
  expires_sentence: string;
  invitee_name: string | null;
};

export type InviteAccepted = {
  /** A challenge has a parent to start; a live match has none (P8-T09). */
  parent_id?: string | null;
  session_id: string;
  game_id: string;
  game_name: string;
  /** True for a live match: the seat is the match, so there is nothing to start. */
  live?: boolean;
};

/** Where an accepted seat should open, whatever kind of invitation it was. */
export function seatPath(accepted: InviteAccepted): string {
  if (accepted.live) return `/games/checkers/${accepted.session_id}`;
  return `/games/${accepted.game_id}`;
}

export type PendingInvite = {
  invitation_id: string;
  game_id: string;
  game_name: string;
  inviter_name: string;
  sentence: string;
};

export type Note = {
  id: string;
  kind: "invite" | "challenge_result" | string;
  body: string;
  invitation_id: string | null;
  session_id: string | null;
  unread: boolean;
};

export type Inbox = {
  invites: PendingInvite[];
  notifications: Note[];
  unread: number;
};

/**
 * One player's own challenge, for their end screen (P7-T05).
 *
 * There is no score field at all, on purpose: the sentence from the server is
 * the whole answer, and no number about the other attempt reaches the browser
 * before both are in (D-25).
 */
export type ChallengeResult = {
  parent_id: string;
  opponent_id: string | null;
  opponent_name: string | null;
  outcome: "win" | "loss" | "draw" | null;
  settled: boolean;
  sentence: string;
};

/** A challenge this learner still owes a turn in (P7-T06). */
export type MyTurn = {
  parent_id: string;
  game_id: string;
  game_name: string;
  opponent_name: string | null;
  sentence: string;
};

/** The school admin's minimum report list (P7-T09). */
export type AdminReport = {
  id: string;
  reported_id: string;
  reported_name: string;
  reporter_name: string;
  reason: string;
  reason_sentence: string;
  note: string | null;
  status: string;
  created_at: string;
};
