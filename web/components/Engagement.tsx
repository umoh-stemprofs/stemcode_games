"use client";

/**
 * The engagement pieces: streak capsule, today's quest, badges and bests.
 *
 * All of it is read-only presentation of numbers the server wrote (see
 * `services/engagement.py`). Nothing here can add a day to a streak or finish a
 * quest; the only way to move any of it is to finish a game.
 */

import { useQuery } from "@tanstack/react-query";

import { Card, Chip, Progress } from "@/components/ui";
import { apiFetch } from "@/lib/api/client";
import type { Badge, Best, Engagement } from "@/lib/games/board-types";

export function useEngagement(enabled = true) {
  return useQuery({
    queryKey: ["engagement"],
    queryFn: () => apiFetch<Engagement>("/api/me/engagement"),
    enabled,
    // Finished games invalidate this key; a minute of staleness is harmless.
    staleTime: 30_000,
  });
}

/** The one sentence that tells a learner why the number matters. */
export function streakNudge(streak: Engagement["streak"]): string {
  if (streak.current <= 0) return "Play today to start a streak.";
  if (streak.played_today) return "Streak kept for today.";
  return "Play one game to keep your streak.";
}

export function StreakCapsule({ streak }: { streak: Engagement["streak"] }) {
  const alive = streak.current > 0;
  return (
    <div
      className={`flex items-center gap-2.5 rounded-2xl border px-4 py-2.5 ${
        alive
          ? "border-sun bg-sun-soft text-sun-ink"
          : "border-line bg-surface-muted text-ink-muted"
      }`}
    >
      <span aria-hidden="true" className="text-xl leading-none">
        🔥
      </span>
      <span className="flex flex-col leading-tight">
        <span className="text-micro font-bold uppercase">Streak</span>
        <span className="font-headline text-body-min font-extrabold">
          {alive ? `${streak.current} ${streak.current === 1 ? "day" : "days"}` : "Start today"}
        </span>
      </span>
    </div>
  );
}

/** Today's quest, with the one number that answers "am I nearly done?". */
export function QuestCard({ quest }: { quest: Engagement["quest"] }) {
  const left = Math.max(0, quest.target - quest.progress);
  return (
    <Card className="flex flex-col gap-4 p-5 sm:p-6">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h2 className="flex items-center gap-2 font-headline text-large font-extrabold tracking-tight text-ink">
          <span aria-hidden="true">🎯</span>
          Today&rsquo;s quest
        </h2>
        <Chip tone={quest.completed ? "green" : "sun"}>
          {quest.completed ? `Done! +${quest.reward_xp} XP` : `+${quest.reward_xp} XP`}
        </Chip>
      </div>

      <p className="text-body text-ink">{quest.title}</p>

      <div className="flex items-center gap-3">
        <Progress
          value={Math.round((quest.progress / quest.target) * 100)}
          label="Quest progress"
          tone={quest.completed ? "sun" : "brand"}
          className="h-3 bg-surface-sunk"
        />
        <span className="tabular shrink-0 text-label font-bold text-ink-muted">
          {quest.progress} of {quest.target}
        </span>
      </div>

      <p className="text-body-min text-ink-muted">
        {quest.completed
          ? "Quest finished. Come back tomorrow."
          : left === 1
            ? "One more game finishes it."
            : `${left} more games finish it.`}
      </p>
    </Card>
  );
}

/** Emoji per badge: presentation only, so a new badge needs no migration. */
const BADGE_LOOK: Record<string, string> = {
  first_game: "🎮",
  five_games: "✋",
  twenty_games: "🏅",
  first_win: "🥇",
  checkers_champ: "♟️",
  number_hunter: "🔢",
  all_games: "🎯",
  streak_3: "🔥",
  streak_7: "⚡",
  quest_keeper: "✅",
};

export function BadgeTile({ badge }: { badge: Badge }) {
  const earned = badge.earned_on !== null;
  return (
    <li
      className={`flex flex-col items-center gap-2 rounded-2xl border p-4 text-center ${
        earned ? "border-line bg-surface shadow-card" : "border-dashed border-line bg-surface-muted"
      }`}
    >
      <span
        aria-hidden="true"
        className={`text-3xl leading-none ${earned ? "" : "opacity-30 grayscale"}`}
      >
        {BADGE_LOOK[badge.id] ?? "⭐"}
      </span>
      <span
        className={`font-headline text-label font-extrabold ${
          earned ? "text-ink" : "text-ink-muted"
        }`}
      >
        {badge.title}
      </span>
      <span className="text-label leading-tight text-ink-muted">
        {earned ? badge.sentence : badge.hint}
      </span>
    </li>
  );
}

export function BadgeGrid({ badges }: { badges: Badge[] }) {
  return (
    <ul className="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-5">
      {badges.map((badge) => (
        <BadgeTile key={badge.id} badge={badge} />
      ))}
    </ul>
  );
}

/** A best is shown next to the game it belongs to, never as a bare number. */
export function BestLine({ value }: { value: string }) {
  return (
    <p className="text-label font-semibold text-ink-muted">
      <span aria-hidden="true">🏅</span> Best: {value}
    </p>
  );
}

export function bestFor(bests: Best[] | undefined, gameId: string): string | null {
  return bests?.find((best) => best.game_id === gameId)?.value ?? null;
}
