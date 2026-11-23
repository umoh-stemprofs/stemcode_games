/**
 * Word packs a learner keeps on the device (P9-T02).
 *
 * Nobody presses a button here. When a learner loads the app, their packs are
 * fetched once in the background through the normal API — so it is still the
 * server that decides which words and which band — stored in IndexedDB, and
 * refreshed when they go stale or when the connection comes back. A level of
 * one game is a few tens of kilobytes, which is why a school tablet can hold
 * every level and still have room for everything else.
 *
 * IndexedDB rather than localStorage because a pack is a structured list, and
 * because the quota for localStorage is measured in single megabytes.
 *
 * **Packs belong to a person, not a tablet.** School devices are shared, and a
 * pack carries answers, so every stored row records the learner it was fetched
 * for and every read filters by it. A second child signing in on the same
 * tablet never sees the first child's words, and their own sync overwrites the
 * rows for the levels they keep.
 *
 * Storage is best-effort: a browser in private mode can refuse to open a
 * database, in which case nothing is stored and the online game carries on
 * unchanged.
 */

import { ApiError, apiFetch } from "@/lib/api/client";
import type { components } from "@/lib/api/schema";

export type OfflineItem = components["schemas"]["OfflineItemOut"];
export type OfflinePack = components["schemas"]["OfflinePackOut"];

const DB_NAME = "stem-offline";
const DB_VERSION = 1;
const STORE = "packs";
const LEVELS = [1, 2, 3] as const;

/**
 * Games that keep their words on the device. Number Guess needs no content at
 * all — it derives every round from its seed — so it has nothing to save.
 */
export const OFFLINE_GAMES = ["word_scramble"] as const;

/**
 * How long a saved pack is trusted before it is fetched again. A word list
 * changes when a coach publishes or takes a word down, which is not urgent;
 * six hours means a tablet that is opened every morning catches up on its own.
 */
export const SYNC_AFTER_MS = 6 * 60 * 60 * 1000;

export type StoredPack = {
  /** `game_id:difficulty`, so a level is replaced rather than duplicated. */
  key: string;
  /** The learner this pack was fetched for (see the note above). */
  user_id: string;
  game_id: string;
  difficulty: number;
  age_band: string;
  pack_version: string;
  bytes: number;
  downloaded_at: string;
  items: OfflineItem[];
};

export type PackSummary = {
  levels: number[];
  bytes: number;
  downloaded_at: string;
};

export type DownloadResult = {
  summary: PackSummary | null;
  /** Levels the server has too few words for yet. */
  skipped: number[];
};

/** Fired after a sync so a screen showing "saved" can re-read the store. */
export const OFFLINE_SYNCED = "stem-offline-synced";

export function canStorePacks(): boolean {
  return typeof window !== "undefined" && typeof window.indexedDB !== "undefined";
}

function openDb(): Promise<IDBDatabase> {
  return new Promise((resolve, reject) => {
    const request = window.indexedDB.open(DB_NAME, DB_VERSION);
    request.onupgradeneeded = () => {
      const db = request.result;
      if (!db.objectStoreNames.contains(STORE)) {
        const store = db.createObjectStore(STORE, { keyPath: "key" });
        store.createIndex("by_game", "game_id", { unique: false });
      }
    };
    request.onsuccess = () => resolve(request.result);
    request.onerror = () => reject(request.error ?? new Error("storage_unavailable"));
  });
}

function ask<T>(request: IDBRequest<T>): Promise<T> {
  return new Promise((resolve, reject) => {
    request.onsuccess = () => resolve(request.result);
    request.onerror = () => reject(request.error ?? new Error("storage_unavailable"));
  });
}

/** Rows for one game, including other learners' — callers filter. */
async function readGame(gameId: string): Promise<StoredPack[]> {
  const db = await openDb();
  try {
    const store = db.transaction(STORE, "readonly").objectStore(STORE);
    return await ask<StoredPack[]>(store.index("by_game").getAll(gameId));
  } finally {
    db.close();
  }
}

async function readOwn(gameId: string, userId: string): Promise<StoredPack[]> {
  return (await readGame(gameId)).filter((row) => row.user_id === userId);
}

async function writePack(pack: StoredPack): Promise<void> {
  const db = await openDb();
  try {
    await ask(db.transaction(STORE, "readwrite").objectStore(STORE).put(pack));
  } finally {
    db.close();
  }
}

async function deleteKeys(keys: string[]): Promise<void> {
  if (keys.length === 0) return;
  const db = await openDb();
  try {
    const store = db.transaction(STORE, "readwrite").objectStore(STORE);
    for (const key of keys) store.delete(key);
    await new Promise<void>((resolve, reject) => {
      store.transaction.oncomplete = () => resolve();
      store.transaction.onerror = () => reject(store.transaction.error);
    });
  } finally {
    db.close();
  }
}

function toStored(pack: OfflinePack, userId: string): StoredPack {
  // The size the bundle actually costs on disk, not the compressed transfer.
  const bytes = new TextEncoder().encode(JSON.stringify(pack.items)).length;
  return {
    key: `${pack.game_id}:${pack.difficulty}`,
    user_id: userId,
    game_id: pack.game_id,
    difficulty: pack.difficulty,
    age_band: pack.age_band,
    pack_version: pack.pack_version,
    bytes,
    downloaded_at: new Date().toISOString(),
    items: pack.items,
  };
}

function summarise(rows: StoredPack[]): PackSummary | null {
  if (rows.length === 0) return null;
  return {
    levels: [...new Set(rows.map((row) => row.difficulty))].sort((a, b) => a - b),
    bytes: rows.reduce((total, row) => total + row.bytes, 0),
    downloaded_at: rows
      .map((row) => row.downloaded_at)
      .sort()
      .at(-1) as string,
  };
}

/** What is already on this device for this learner, or null when nothing is. */
export async function storedSummary(
  gameId: string,
  userId: string,
): Promise<PackSummary | null> {
  if (!canStorePacks()) return null;
  try {
    return summarise(await readOwn(gameId, userId));
  } catch {
    return null;
  }
}

/**
 * Fetch every level and keep it. A level the server has too few words for yet
 * is skipped rather than failing the whole download — easy is usually ready
 * long before hard is.
 *
 * A level whose stamp has not moved is left alone, so a background refresh
 * does not churn the store or rewrite the "saved" date for nothing.
 */
export async function downloadGame(
  gameId: string,
  userId: string,
  onProgress?: (done: number, total: number) => void,
): Promise<DownloadResult> {
  if (!canStorePacks()) throw new Error("storage_unavailable");

  const skipped: number[] = [];
  const existing = new Map((await readOwn(gameId, userId)).map((row) => [row.difficulty, row]));
  let saved = 0;

  for (const [index, level] of LEVELS.entries()) {
    onProgress?.(index, LEVELS.length);
    try {
      const pack = await apiFetch<OfflinePack>(
        `/api/games/offline/packs?game=${encodeURIComponent(gameId)}&difficulty=${level}`,
      );
      const previous = existing.get(level);
      if (
        previous &&
        previous.pack_version === pack.pack_version &&
        previous.age_band === pack.age_band
      ) {
        saved += 1;
        continue;
      }
      await writePack(toStored(pack, userId));
      saved += 1;
    } catch (error) {
      if (error instanceof ApiError && error.code === "not_enough_content") {
        skipped.push(level);
        continue;
      }
      throw error;
    }
  }
  onProgress?.(LEVELS.length, LEVELS.length);

  // Levels the server no longer has words for are removed, not left stale.
  const keep = new Set(await readOwn(gameId, userId).then((rows) => rows.map((row) => row.key)));
  const gone = [...existing.values()].map((row) => row.key).filter((key) => !keep.has(key));
  await deleteKeys(gone);

  return { summary: saved > 0 ? await storedSummary(gameId, userId) : null, skipped };
}

/** Forget every level of one game on this device, for everyone. */
export async function removeGame(gameId: string): Promise<void> {
  if (!canStorePacks()) return;
  try {
    await deleteKeys((await readGame(gameId)).map((row) => row.key));
  } catch {
    // Nothing stored is the outcome we wanted.
  }
}

/** Everything stored for a game and learner, for the offline runtime. */
export async function packsFor(gameId: string, userId: string): Promise<StoredPack[]> {
  if (!canStorePacks()) return [];
  try {
    return await readOwn(gameId, userId);
  } catch {
    return [];
  }
}

function lastSyncKey(userId: string): string {
  return `stem-offline-sync:${userId}`;
}

function lastSyncedAt(userId: string): number {
  try {
    const raw = window.localStorage.getItem(lastSyncKey(userId));
    return raw ? Number(raw) || 0 : 0;
  } catch {
    return 0;
  }
}

function markSynced(userId: string, at: number): void {
  try {
    window.localStorage.setItem(lastSyncKey(userId), String(at));
  } catch {
    // The stamp is an optimisation; without it we simply sync again.
  }
}

// One run at a time: the shell mounts once, but a reconnect can fire while a
// sync is still going, and two runs would fetch the same packs twice.
let running: Promise<void> | null = null;

/**
 * Keep every offline game's words on this device. Called by the shell, so it
 * is not something a learner has to think about.
 *
 * Silent by design: a failure here is never a message on screen. The online
 * game works exactly as before, and the next load tries again.
 */
export async function syncOfflinePacks(userId: string, force = false): Promise<void> {
  if (!canStorePacks()) return;
  if (typeof navigator !== "undefined" && navigator.onLine === false) return;
  if (running) return running;

  running = (async () => {
    try {
      let changed = false;
      for (const gameId of OFFLINE_GAMES) {
        const stamp = lastSyncedAt(userId);
        const stored = await storedSummary(gameId, userId);
        const fresh = Date.now() - stamp < SYNC_AFTER_MS;
        if (!force && fresh && stored) continue;
        try {
          const result = await downloadGame(gameId, userId);
          if (result.summary) {
            changed = true;
            markSynced(userId, Date.now());
          }
        } catch {
          // Offline, refused storage, or a session that just expired. Try next
          // time; nothing on screen changes.
        }
      }
      if (changed) window.dispatchEvent(new Event(OFFLINE_SYNCED));
    } finally {
      running = null;
    }
  })();

  return running;
}
