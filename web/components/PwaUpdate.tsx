"use client";

/**
 * Installing the app, and telling a child when a new version is ready (P9-T01).
 *
 * The service worker is registered only in a production build: in `next dev`
 * the assets keep the same paths between edits, so a cache-first worker would
 * serve yesterday's chunk against today's page and break hot reload.
 *
 * When a new worker is installed the page does not reload underfoot — a check
 * mid-round would be a lost round. It offers one button instead, and the worker
 * is told to take over only when that button is pressed.
 */

import { useEffect, useState } from "react";

import { Button, Card } from "@/components/ui";

export function PwaUpdate() {
  const [waiting, setWaiting] = useState<ServiceWorker | null>(null);
  const [reloading, setReloading] = useState(false);

  useEffect(() => {
    if (process.env.NODE_ENV !== "production") return;
    if (typeof navigator === "undefined" || !("serviceWorker" in navigator)) return;

    let cancelled = false;
    let refreshed = false;

    const onControllerChange = () => {
      if (refreshed) return;
      refreshed = true;
      window.location.reload();
    };
    navigator.serviceWorker.addEventListener("controllerchange", onControllerChange);

    navigator.serviceWorker
      .register("/sw.js", { scope: "/" })
      .then((registration) => {
        if (cancelled) return;
        // A version installed by an earlier visit is already waiting.
        if (registration.waiting && navigator.serviceWorker.controller) {
          setWaiting(registration.waiting);
        }
        registration.addEventListener("updatefound", () => {
          const installing = registration.installing;
          if (!installing) return;
          installing.addEventListener("statechange", () => {
            if (installing.state === "installed" && navigator.serviceWorker.controller) {
              setWaiting(installing);
            }
          });
        });
      })
      .catch(() => {
        // No service worker is not a broken app; it just means no offline shell.
      });

    return () => {
      cancelled = true;
      navigator.serviceWorker.removeEventListener("controllerchange", onControllerChange);
    };
  }, []);

  if (!waiting) return null;

  return (
    <div className="pointer-events-none fixed inset-x-4 bottom-4 z-50 mx-auto max-w-md">
      <Card
        role="status"
        className="pointer-events-auto flex flex-col gap-3 border-2 border-brand p-4 sm:flex-row sm:items-center"
      >
        <p className="flex-1 text-body-min font-semibold text-ink">
          A new version is ready.
        </p>
        <div className="flex gap-2">
          <Button
            size="sm"
            disabled={reloading}
            onClick={() => {
              setReloading(true);
              waiting.postMessage({ type: "SKIP_WAITING" });
            }}
          >
            {reloading ? "Reloading" : "Reload"}
          </Button>
          <Button size="sm" variant="ghost" onClick={() => setWaiting(null)}>
            Later
          </Button>
        </div>
      </Card>
    </div>
  );
}
