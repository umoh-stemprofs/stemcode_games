/*
 * The app shell's network layer (P9-T01).
 *
 * Three rules, in order of importance:
 *
 * 1. **Person-specific answers are never cached.** `/api/*` is passed straight
 *    through. The dashboard, the clock, the board and the XP are one child's,
 *    and school devices are shared — a cached HTML page or API body could be
 *    served to the next person who signs in on that tablet.
 * 2. **Nothing that is build output is refetched needlessly.** `/_next/static`
 *    and image/font files are content-hashed or immutable, so they are
 *    cache-first: this is what lets the app open on a slow connection.
 * 3. **A page that cannot load says so.** A navigation that fails shows
 *    `/offline.html`, a plain file in `/public` that needs no session, no API
 *    and no font.
 *
 * Versioned cache names mean a new build starts from an empty shelf and the old
 * shelves are deleted on activate. `skipWaiting` is only automatic on the very
 * first install; every later version waits for the "Reload" button, so a child
 * is never swapped mid-round.
 */

const VERSION = "v1";
const SHELL_CACHE = `stem-shell-${VERSION}`;
const ASSET_CACHE = `stem-assets-${VERSION}`;

const PRECACHE = [
  "/offline.html",
  "/manifest.webmanifest",
  "/icons/icon-192.png",
  "/icons/icon-512.png",
  "/icons/maskable-512.png",
  "/icons/apple-touch-icon.png",
];

const STATIC_FILE = /\.(?:css|js|mjs|woff2?|ttf|png|svg|jpe?g|webp|avif|ico)$/;
const NAVIGATION_TIMEOUT_MS = 4000;

self.addEventListener("install", (event) => {
  event.waitUntil(
    (async () => {
      const cache = await caches.open(SHELL_CACHE);
      await Promise.all(
        PRECACHE.map(async (url) => {
          try {
            // `reload` bypasses the HTTP cache, so a new version never
            // precaches the previous version's copy of these files.
            await cache.add(new Request(url, { cache: "reload" }));
          } catch {
            // One missing file is not a reason to refuse to install.
          }
        }),
      );
      // On the first install nothing is running yet, so activating is safe.
      // On an update `registration.active` exists and we wait for the prompt.
      if (!self.registration.active) await self.skipWaiting();
    })(),
  );
});

self.addEventListener("activate", (event) => {
  event.waitUntil(
    (async () => {
      const keep = new Set([SHELL_CACHE, ASSET_CACHE]);
      for (const key of await caches.keys()) {
        if (!keep.has(key)) await caches.delete(key);
      }
      await self.clients.claim();
    })(),
  );
});

self.addEventListener("message", (event) => {
  if (event.data && event.data.type === "SKIP_WAITING") {
    void self.skipWaiting();
  }
});

self.addEventListener("fetch", (event) => {
  const request = event.request;
  if (request.method !== "GET") return;

  const url = new URL(request.url);
  if (url.origin !== self.location.origin) return;

  // Rule 1: the API is always live.
  if (url.pathname.startsWith("/api/")) return;

  if (request.mode === "navigate") {
    event.respondWith(navigation(request));
    return;
  }

  if (url.pathname.startsWith("/_next/static/") || STATIC_FILE.test(url.pathname)) {
    event.respondWith(cacheFirst(request));
  }
});

async function navigation(request) {
  try {
    const response = await fetchWithTimeout(request, NAVIGATION_TIMEOUT_MS);
    // Not cached, on purpose (rule 1).
    return response;
  } catch {
    const offline = await caches.match("/offline.html");
    return offline || Response.error();
  }
}

async function fetchWithTimeout(request, ms) {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), ms);
  try {
    return await fetch(request, { signal: controller.signal });
  } finally {
    clearTimeout(timer);
  }
}

async function cacheFirst(request) {
  const cache = await caches.open(ASSET_CACHE);
  const hit = await cache.match(request);
  if (hit) return hit;

  const response = await fetch(request);
  // A 206 (range request, e.g. a seeking audio file) cannot be cached.
  if (response.ok && response.status === 200 && response.type === "basic") {
    cache.put(request, response.clone()).catch(() => {});
  }
  return response;
}
