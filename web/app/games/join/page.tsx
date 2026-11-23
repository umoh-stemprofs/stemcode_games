"use client";

/**
 * "Join with a friend" (P7-T02, P7-T06).
 *
 * Two ways in, in the order the plan asks for:
 *
 * 1. **A link.** The middleware already moved any `?t=` token into an httpOnly
 *    cookie and cleaned the URL, so this page just asks the API to redeem
 *    whatever token it is holding. Nothing in the address bar can be shared by
 *    accident.
 * 2. **A code**, in two groups of four, for a learner in another class. A code
 *    typed into the dashboard arrives here as `?code=`, already filled in.
 *
 * Accepting a seat is not the same as starting the game: the learner is taken
 * to the game, which starts their own attempt through the normal play path —
 * including the time check. If they are out of time the invite is still theirs
 * tomorrow, and the screen says so in one sentence.
 */

import { useCallback, useEffect, useRef, useState } from "react";
import { useRouter } from "next/navigation";

import { AppShell } from "@/components/AppShell";
import { Icon } from "@/components/icons";
import { Alert, Button, ButtonLink, Card, PageHeader } from "@/components/ui";
import { ApiError, apiFetch } from "@/lib/api/client";
import { sentenceFor } from "@/lib/auth/messages";
import type { InviteAccepted } from "@/lib/games/social";
import { seatPath } from "@/lib/games/social";

export default function JoinPage() {
  return (
    <AppShell>
      <JoinBody />
    </AppShell>
  );
}

function JoinBody() {
  const router = useRouter();
  const [code, setCode] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [triedCookie, setTriedCookie] = useState(false);
  const attempted = useRef(false);

  const enter = useCallback(
    async (accepted: InviteAccepted) => {
      // A challenge needs its attempt started; a live match is the seat itself.
      if (!accepted.live) {
        await apiFetch(`/api/games/challenges/${accepted.parent_id}/start`, { method: "POST" });
      }
      router.replace(seatPath(accepted));
    },
    [router],
  );

  // A code typed on the dashboard comes in on the query string. Read it here
  // rather than with `useSearchParams`, which would force a Suspense boundary.
  useEffect(() => {
    const params = new URLSearchParams(window.location.search);
    const preset = params.get("code");
    if (preset) setCode(preset.replace(/[^A-Za-z0-9]/g, "").toUpperCase().slice(0, 8));
  }, []);

  // The link path: redeem the cookie the middleware left behind.
  useEffect(() => {
    if (attempted.current) return;
    attempted.current = true;
    (async () => {
      try {
        const accepted = await apiFetch<InviteAccepted>("/api/games/invites/pending", {
          method: "POST",
        });
        await enter(accepted);
      } catch {
        // No pending link: this is the code screen.
        setTriedCookie(true);
      }
    })();
  }, [enter]);

  async function submit(event: React.FormEvent) {
    event.preventDefault();
    setBusy(true);
    setError(null);
    try {
      const accepted = await apiFetch<InviteAccepted>("/api/games/invites/accept", {
        method: "POST",
        body: JSON.stringify({ code }),
      });
      await enter(accepted);
    } catch (caught) {
      setError(
        caught instanceof ApiError ? sentenceFor(caught.code, caught.status) : sentenceFor(undefined),
      );
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="mx-auto flex w-full max-w-xl flex-col gap-6">
      <PageHeader
        icon="key"
        title="Join a friend"
        subtitle="Type the code your friend gave you."
        action={
          <ButtonLink href="/games" variant="ghost" size="sm" icon="arrow-left">
            All games
          </ButtonLink>
        }
      />

      <Card className="flex flex-col gap-5 p-6 sm:p-8">
        <form onSubmit={(event) => void submit(event)} className="flex flex-col gap-4">
          <label htmlFor="code" className="font-headline text-[21px] font-bold text-ink">
            The code
          </label>
          <input
            id="code"
            name="code"
            value={code}
            onChange={(event) =>
              setCode(event.target.value.toUpperCase().replace(/[^A-Z0-9]/g, "").slice(0, 8))
            }
            autoComplete="off"
            autoCapitalize="characters"
            spellCheck={false}
            maxLength={8}
            placeholder="ABCD EFGH"
            aria-describedby="code-help"
            className="tabular h-20 w-full rounded-2xl border-2 border-line bg-surface px-4 text-center text-[30px] font-bold uppercase tracking-[0.18em] text-ink outline-none transition-colors placeholder:text-ink-muted focus:border-brand focus:ring-4 focus:ring-brand-soft"
          />
          <p id="code-help" className="flex items-center gap-2 text-label font-semibold text-ink-muted">
            <Icon name="badge" size={17} className="text-brand" />
            Eight letters and numbers.
          </p>

          {error ? <Alert>{error}</Alert> : null}

          <Button
            type="submit"
            size="lg"
            disabled={busy || code.length !== 8}
            arrow
            className="w-full"
          >
            {busy ? "Joining…" : "Join"}
          </Button>
        </form>

        {triedCookie ? (
          <p className="text-label text-ink-muted">Ask your Coach if the code does not work.</p>
        ) : null}
      </Card>
    </div>
  );
}
