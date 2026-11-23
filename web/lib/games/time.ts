/**
 * Turning seconds into sentences (Appendix D).
 *
 * A child sees a sentence, never a number of seconds and never a code. Every
 * sentence here is under eight words and says exactly one thing, so it can be
 * read at 20px by someone who is still learning to read quickly.
 */

import type { AccessReason, AccessState } from "./types";

/** "48 minutes", "1 minute", "Less than a minute". */
export function minutesPhrase(seconds: number): string {
  const minutes = Math.floor(Math.max(0, seconds) / 60);
  if (minutes === 0) return "less than a minute";
  if (minutes === 1) return "1 minute";
  return `${minutes} minutes`;
}

/** The headline for a state: what is true right now. */
export function accessHeadline(access: AccessState): string {
  switch (access.reason) {
    case "limit_reached":
      return "You have used all your time today.";
    case "not_enough_time":
      return "You need more time left for a match.";
    case "locked_out":
      return "Games are paused for you.";
    case "games_disabled":
      return "Games are off right now.";
    case "leaderboards_only":
      return "Games are off. You can see the boards.";
    case "another_session_active":
      return "You have a game open somewhere else.";
    default:
      return `You have ${minutesPhrase(access.remaining_seconds)} left today.`;
  }
}

/**
 * The header meter's line.
 *
 * "You have a game open somewhere else" is the right headline on a *card* that
 * offers the way back into that game, but it is wrong in the meter above the
 * game the learner is already playing. There the meter answers one question —
 * how much time is left — so it keeps answering it.
 */
export function meterHeadline(access: AccessState): string {
  if (access.reason === "another_session_active") {
    return `You have ${minutesPhrase(access.remaining_seconds)} left today.`;
  }
  return accessHeadline(access);
}

/**
 * The second line, only when it adds something.
 *
 * The reset time comes from the server, so a device clock that is wrong cannot
 * tell a child they may play again before they can.
 */
export function accessDetail(access: AccessState, timezone: string): string | null {
  if (access.reason === "ok") {
    if (access.remaining_seconds <= 120) return "Two minutes left.";
    if (access.remaining_seconds <= 600) return "Ten minutes left.";
    return null;
  }
  if (access.reason === "limit_reached") return "You can play again tomorrow.";
  if (access.reason === "not_enough_time") return "A match needs 15 minutes left.";
  if (access.reason === "locked_out" && access.locked_until) {
    return `You can play again at ${formatTime(access.locked_until, timezone)}.`;
  }
  if (access.reason === "locked_out") return "Ask your Coach.";
  if (access.reason === "another_session_active") return "Finish that game first.";
  return null;
}

/** One label per reason, used on the coach's table too. */
export const REASON_LABEL: Record<AccessReason, string> = {
  ok: "Can play",
  limit_reached: "No time left",
  not_enough_time: "Too little time",
  locked_out: "Paused",
  games_disabled: "Games off",
  another_session_active: "Playing now",
  leaderboards_only: "Boards only",
};

/** "2:45 pm" in the school's own timezone. */
export function formatTime(iso: string, timezone: string): string {
  return new Intl.DateTimeFormat("en-GB", {
    hour: "numeric",
    minute: "2-digit",
    hour12: true,
    timeZone: timezone,
  }).format(new Date(iso));
}

/** "14 Nov" in the school's own timezone. */
export function formatDate(iso: string, timezone: string): string {
  return new Intl.DateTimeFormat("en-GB", {
    day: "numeric",
    month: "short",
    timeZone: timezone,
  }).format(new Date(iso));
}

/**
 * A `datetime-local` field value from a Date, in the *browser's* timezone.
 *
 * `toISOString()` cannot be used here: it always reports UTC, so a coach in
 * Lagos would see a time an hour earlier than the one they mean.
 */
export function toLocalInput(date: Date): string {
  const pad = (n: number) => String(n).padStart(2, "0");
  return (
    `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())}` +
    `T${pad(date.getHours())}:${pad(date.getMinutes())}`
  );
}

/** Where a limit came from, in plain words. */
export function limitSourceLabel(source: string): string {
  switch (source) {
    case "student":
      return "Set for this learner";
    case "class":
      return "Set for the class";
    case "school":
      return "Set for the school";
    default:
      return "The school default";
  }
}
