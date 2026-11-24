"use client";

/**
 * "I am here."
 *
 * The roster can only show who is online if the browser says so. This sends one
 * empty POST every 45 seconds while a tab is open; the server keeps a short
 * cache key that expires on its own, so closing the tab is all it takes to drop
 * off the list. Nothing is stored, and nothing is charged to the time allowance:
 * a heartbeat is not play.
 */

import { useEffect } from "react";

import { apiFetch } from "@/lib/api/client";
import { useSession } from "@/lib/auth/session";

const HEARTBEAT_MS = 45_000;

export function PresenceHeartbeat() {
  const session = useSession();
  const enabled = session.status === "authenticated" && session.me.user.role === "learner";

  useEffect(() => {
    if (!enabled) return undefined;
    let stopped = false;

    const ping = () => {
      // A hidden tab is not someone to invite; it also saves school wifi.
      if (stopped || document.visibilityState === "hidden") return;
      void apiFetch("/api/games/presence", { method: "POST" }).catch(() => undefined);
    };

    ping();
    const timer = window.setInterval(ping, HEARTBEAT_MS);
    const onVisible = () => ping();
    document.addEventListener("visibilitychange", onVisible);
    window.addEventListener("focus", onVisible);

    return () => {
      stopped = true;
      window.clearInterval(timer);
      document.removeEventListener("visibilitychange", onVisible);
      window.removeEventListener("focus", onVisible);
    };
  }, [enabled]);

  return null;
}
