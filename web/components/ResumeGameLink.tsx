"use client";

/**
 * The way back into the game a learner already has open (D-26).
 *
 * "You have a game open somewhere else" is only useful if it says *where*, so
 * this asks the server which session is open and offers one button to it. The
 * server decides what is open; the browser only chooses the screen:
 *
 * - Checkers is live-only, so a Checkers session is a match and lives on its
 *   own board page.
 * - Every other game resumes inside its game screen, which reloads the same
 *   session and mid-round clock.
 *
 * If nothing is open (the sweeper just abandoned it, or another tab closed it),
 * the button is not shown at all: a dead button is worse than no button.
 */

import { useQuery } from "@tanstack/react-query";

import { ButtonLink } from "@/components/ui";
import { apiFetch } from "@/lib/api/client";
import type { ActiveSession } from "@/lib/games/types";

export function ResumeGameLink() {
  const active = useQuery({
    queryKey: ["active-session"],
    queryFn: () => apiFetch<ActiveSession>("/api/games/sessions/active"),
    // The card is only rendered when a game is open, so one read is enough.
    staleTime: 5_000,
  });

  const open = active.data;
  if (!open?.session_id) return null;

  const href =
    open.game_id === "checkers"
      ? `/games/checkers/${open.session_id}`
      : `/games/${open.game_id}`;

  return (
    <ButtonLink href={href} arrow className="w-full sm:w-fit">
      Go back to my game
    </ButtonLink>
  );
}
