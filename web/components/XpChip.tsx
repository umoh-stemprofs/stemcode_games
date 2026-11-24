"use client";

/**
 * The Game XP chip (P5-T10).
 *
 * One number, no sentence: "48 XP" today, or "48 / 60" when a school has set a
 * daily cap. A learner never has to learn what XP is to read it, and it never
 * claims a rank or a grade — Profile XP is motivational only (P5-T05).
 */

import { useEffect, useState } from "react";

import { Icon } from "@/components/icons";
import { apiFetch } from "@/lib/api/client";
import type { MeXp } from "@/lib/games/board-types";

/** Fired when a game has ended, so the chip can stop claiming yesterday's number. */
export const XP_CHANGED = "games:xp";

export function XpChip() {
  const [xp, setXp] = useState<MeXp | null>(null);

  useEffect(() => {
    let cancelled = false;
    const load = async () => {
      try {
        const next = await apiFetch<MeXp>("/api/me/xp");
        if (!cancelled) setXp(next);
      } catch {
        // A missing chip is not an error a learner should ever see.
      }
    };
    void load();
    // A finished match awards XP in the same request that ends it, so the chip
    // would otherwise read "You won" next to "0 of 60 XP today" until reload.
    window.addEventListener(XP_CHANGED, load);
    return () => {
      cancelled = true;
      window.removeEventListener(XP_CHANGED, load);
    };
  }, []);

  if (!xp) return null;

  return (
    <span
      className="flex shrink-0 items-center gap-1.5 rounded-xl border border-line bg-sun-soft px-2.5 py-2 text-sun-ink"
      title={`Learning ${xp.learning_xp_total} + games ${xp.game_xp_total}`}
    >
      <Icon name="bolt" size={17} className="text-sun" />
      <span className="tabular text-[15px] font-bold leading-none">
        {xp.game_xp_today}
        {/* No cap means no denominator to read: "29 XP", not "29 / 0 XP". */}
        {xp.daily_cap > 0 ? (
          <span className="font-semibold text-ink-muted"> / {xp.daily_cap}</span>
        ) : null}
      </span>
      <span className="hidden text-label font-bold sm:inline">XP</span>
    </span>
  );
}
