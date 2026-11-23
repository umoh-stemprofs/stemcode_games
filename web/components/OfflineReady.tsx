"use client";

/**
 * One quiet line saying the words are already on this device (P9-T02).
 *
 * There is no download button, because there is nothing to press: the shell
 * syncs packs in the background (see `OfflineSync`). This is the receipt, not
 * a task — and it is absent until the words are actually stored, so a child
 * never reads "saved" about a game that is not.
 */

import { useEffect, useState } from "react";

import { Icon } from "@/components/icons";
import { OFFLINE_SYNCED, canStorePacks, storedSummary, type PackSummary } from "@/lib/offline/packs";

function sizeLabel(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  return `${Math.max(1, Math.round(bytes / 1024))} KB`;
}

export function OfflineReady({ gameId, userId }: { gameId: string; userId: string }) {
  const [summary, setSummary] = useState<PackSummary | null>(null);

  useEffect(() => {
    if (!canStorePacks()) return;

    let alive = true;
    const read = () => {
      void storedSummary(gameId, userId).then((next) => {
        if (alive) setSummary(next);
      });
    };

    read();
    window.addEventListener(OFFLINE_SYNCED, read);
    return () => {
      alive = false;
      window.removeEventListener(OFFLINE_SYNCED, read);
    };
  }, [gameId, userId]);

  if (summary === null) return null;

  return (
    <p className="flex items-center gap-2 text-label font-semibold text-ink-muted">
      <Icon name="check" size={16} className="shrink-0 text-ok" />
      <span>Saved on this device. Plays without internet.</span>
      <span className="sr-only">{sizeLabel(summary.bytes)} stored.</span>
    </p>
  );
}
