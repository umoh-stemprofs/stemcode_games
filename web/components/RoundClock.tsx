"use client";

/**
 * The round clock: a filling bar, never a ticking number (Appendix D).
 *
 * Both games share the same deadline rule — the server decides when a round is
 * over, and this only asks it to move on — so the bar lives here once instead
 * of being copied into each game's screen.
 */

import { useEffect, useState } from "react";

import type { RoundState } from "@/lib/games/types";

export function RoundClock({
  round,
  started,
  onExpire,
  label,
}: {
  round: RoundState;
  started: boolean;
  onExpire: () => void;
  label: string;
}) {
  const [receivedAt, setReceivedAt] = useState(() => Date.now());
  const [now, setNow] = useState(() => Date.now());
  const [timedOutRound, setTimedOutRound] = useState<number | null>(null);

  // A new round starts a new bar.
  useEffect(() => {
    setReceivedAt(Date.now());
    setNow(Date.now());
  }, [round.number]);

  useEffect(() => {
    const timer = setInterval(() => setNow(Date.now()), 400);
    return () => clearInterval(timer);
  }, []);

  const full = round.round_seconds * 1000;
  const running = started || round.time_left_ms < full - 500;
  const leftMs = running ? Math.max(0, round.time_left_ms - (now - receivedAt)) : full;

  // When the bar empties, ask the server to move on. It owns the deadline, so
  // this asks for the state rather than sending a skip the learner did not
  // press.
  useEffect(() => {
    if (!running || leftMs > 0 || timedOutRound === round.number) return;
    setTimedOutRound(round.number);
    onExpire();
  }, [leftMs, running, round.number, timedOutRound, onExpire]);

  const fill = Math.max(0, Math.min(100, (leftMs / full) * 100));
  const urgent = leftMs < 10_000;

  return (
    <div
      role="progressbar"
      aria-label={label}
      aria-valuemin={0}
      aria-valuemax={100}
      aria-valuenow={Math.round(fill)}
      className="h-3 w-full overflow-hidden rounded-pill bg-surface-sunk"
    >
      <div
        className={`h-full rounded-pill ${urgent ? "bg-danger" : "bg-brand"}`}
        style={{ width: `${fill}%` }}
      />
    </div>
  );
}
