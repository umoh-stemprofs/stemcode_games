"use client";

/**
 * The learner's time left, in the header (P3-T11).
 *
 * Three rules decide everything here:
 *
 * - **A sentence, not a number.** "You have 48 minutes left today." The bar is
 *   decoration for the sentence, so hiding it loses nothing.
 * - **The server owns the clock.** It is re-read every minute and the reset
 *   time comes from the server, never from this device.
 * - **No scary states.** When time runs out the meter becomes one calm
 *   sentence; it never turns into an error.
 */

import { useQuery } from "@tanstack/react-query";

import { Icon } from "@/components/icons";
import { Progress } from "@/components/ui";
import { apiFetch } from "@/lib/api/client";
import { useSession } from "@/lib/auth/session";
import { accessDetail, meterHeadline } from "@/lib/games/time";
import type { AccessState } from "@/lib/games/types";

export function useAccess() {
  const session = useSession();
  const enabled = session.status === "authenticated" && session.me.user.role === "learner";
  return useQuery({
    queryKey: ["access"],
    queryFn: () => apiFetch<AccessState>("/api/games/access"),
    enabled,
    // The allowance resets at midnight; a minute of staleness is harmless and
    // one request a minute is kind to school wifi (D-24).
    refetchInterval: 60_000,
    refetchOnWindowFocus: true,
  });
}

export function TimeMeter() {
  const session = useSession();
  const access = useAccess();

  if (session.status !== "authenticated" || !access.data) return null;

  const data = access.data;
  const timezone = session.me.school.timezone;
  // The open-game sentence belongs on the hub's resume card, not here (see
  // `meterHeadline`), so this meter never tells a learner to finish the game
  // they are looking at.
  const detail = data.reason === "another_session_active" ? null : accessDetail(data, timezone);
  const share =
    data.limit_minutes > 0
      ? Math.round((data.remaining_seconds / (data.limit_minutes * 60)) * 100)
      : 0;
  const running = data.reason === "ok" || data.reason === "another_session_active";
  // A header capsule holds a number, not a sentence. The sentence is still the
  // screen reader's version, and every blocked state keeps its own words.
  const minutes = Math.floor(Math.max(0, data.remaining_seconds) / 60);
  const compact = running;

  return (
    <div
      className="flex w-full flex-col gap-1.5 rounded-xl border border-line bg-canvas px-3 py-2 sm:w-auto sm:py-1.5"
      aria-live="polite"
    >
      <p
        className="flex items-center gap-1.5 whitespace-nowrap text-label font-bold leading-tight text-ink"
        aria-label={meterHeadline(data)}
      >
        <Icon name="clock" size={15} className={running ? "text-brand" : "text-ink-muted"} />
        <span className="min-w-0">
          {compact ? `${minutes} min left` : meterHeadline(data)}
        </span>
      </p>

      <div className="w-full sm:w-36">
        <Progress
          value={share}
          label="Time left today"
          tone={share <= 10 ? "danger" : "brand"}
          className="h-2 bg-surface-sunk"
        />
      </div>

      {detail ? (
        <p className="text-label font-semibold leading-tight text-ink-muted">{detail}</p>
      ) : null}
    </div>
  );
}
