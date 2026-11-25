"use client";

/**
 * Leaving a game on purpose (P3-T04 lifecycle, P8 disconnect).
 *
 * A learner who taps a menu tab mid-round is leaving their game, and the game
 * does not survive that: the server marks the attempt abandoned, so it cannot
 * be picked up again and the seat is free. Because that is a real loss, the tab
 * asks first — one sentence, two buttons, nothing else.
 *
 * The guard lives above the navigation so the tab itself can ask, and it is
 * cleared by the game screen as soon as the game ends, so finishing a game and
 * then tapping `Play` is an ordinary tap.
 *
 * `play` carries the game's name only to keep the dialog honest; no seed, word
 * or score is involved (D-25).
 */

import { createContext, useCallback, useContext, useMemo, useState, type ReactNode } from "react";
import { useRouter } from "next/navigation";

import { apiFetch } from "@/lib/api/client";

export type ActiveGame = {
  sessionId: string;
  gameName: string;
  /**
   * What leaving means for this game. A live match resigns while it is being
   * played, because the other learner is sitting on the board and needs a
   * result; a game nobody has started is simply quit. Defaults to quitting.
   */
  onQuit?: () => Promise<void>;
};

type Guard = {
  active: ActiveGame | null;
  setActive: (game: ActiveGame | null) => void;
  /** Go to `href`, asking first when a game is in progress. */
  leave: (href: string) => void;
};

const QuitGuardContext = createContext<Guard | null>(null);

export function QuitGuardProvider({ children }: { children: ReactNode }) {
  const router = useRouter();
  const [game, setGame] = useState<ActiveGame | null>(null);
  const [pendingHref, setPendingHref] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const leave = useCallback(
    (href: string) => {
      if (!game) {
        router.push(href);
        return;
      }
      setPendingHref(href);
    },
    [game, router],
  );

  async function quit() {
    if (!game || !pendingHref) return;
    const href = pendingHref;
    const sessionId = game.sessionId;
    setBusy(true);
    setPendingHref(null);
    setGame(null);
    try {
      if (game.onQuit) {
        await game.onQuit();
      } else {
        await apiFetch(`/api/games/sessions/${sessionId}/quit`, { method: "POST" });
      }
    } catch {
      // The only refusal is "that game is already over", and leaving is still
      // what the learner asked for.
    } finally {
      setBusy(false);
      router.push(href);
    }
  }

  const value = useMemo<Guard>(() => ({ active: game, setActive: setGame, leave }), [game, leave]);

  return (
    <QuitGuardContext.Provider value={value}>
      {children}

      {pendingHref ? (
        <div
          role="dialog"
          aria-modal="true"
          aria-labelledby="quit-title"
          className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-6"
        >
          <div className="flex w-full max-w-md flex-col gap-4 rounded-lg border border-border bg-surface p-6">
            <h2 id="quit-title" className="text-large font-semibold">
              Leave this game?
            </h2>
            <p className="text-body">Your game will end.</p>

            <button
              type="button"
              disabled={busy}
              onClick={() => void quit()}
              className="min-h-target rounded-md bg-brand px-6 text-body font-semibold text-brand-contrast disabled:opacity-60"
            >
              Quit game
            </button>
            <button
              type="button"
              disabled={busy}
              onClick={() => setPendingHref(null)}
              className="min-h-target rounded-md border border-border bg-surface px-6 text-body font-medium disabled:opacity-60"
            >
              Keep playing
            </button>
          </div>
        </div>
      ) : null}
    </QuitGuardContext.Provider>
  );
}

/** Safe outside the provider: a page with no shell simply has no game open. */
export function useQuitGuard(): Guard {
  const context = useContext(QuitGuardContext);
  return (
    context ?? {
      active: null,
      setActive: () => undefined,
      leave: () => undefined,
    }
  );
}
