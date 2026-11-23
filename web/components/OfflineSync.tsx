"use client";

/**
 * Keeps the offline games ready without asking (P9-T02).
 *
 * Mounted once inside the signed-in shell, so every learner gets their packs
 * saved the first time they open the app — including a child who has never
 * pressed anything and never will. It renders nothing.
 *
 * Three triggers only: the first load after signing in, a reconnect, and the
 * six-hour staleness rule inside `syncOfflinePacks`. It waits a moment after
 * the page is up so it never competes with the screen the child is reading.
 */

import { useEffect } from "react";

import { useSession } from "@/lib/auth/session";
import { syncOfflinePacks } from "@/lib/offline/packs";

export function OfflineSync() {
  const session = useSession();
  const userId =
    session.status === "authenticated" && session.me.user.role === "learner"
      ? session.me.user.id
      : null;

  useEffect(() => {
    if (userId === null) return;

    let cancelled = false;
    const run = () => {
      if (!cancelled) void syncOfflinePacks(userId);
    };

    const timer = window.setTimeout(run, 1500);
    window.addEventListener("online", run);
    return () => {
      cancelled = true;
      window.clearTimeout(timer);
      window.removeEventListener("online", run);
    };
  }, [userId]);

  return null;
}
