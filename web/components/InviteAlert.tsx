"use client";

/**
 * The invitation that finds you (P7-T07).
 *
 * A learner should not have to sit on the inbox to hear that a friend wants to
 * play. This polls the one endpoint that already answers the question and shows
 * the newest invitation until the learner deals with it.
 *
 * Rules it keeps:
 *
 * - **One sentence, two choices.** The server's own sentence, then `Play` or
 *   close. Nothing else.
 * - **It never blocks.** It sits in the corner, outside the page flow, so a
 *   round in progress keeps its clock and its buttons.
 * - **Only the learner closes it.** There is no timer. A card that folds itself
 *   while a child is reading is the same as no card at all. Closing folds it
 *   into a round button that keeps bobbing.
 * - **A dead invite says so.** If the card on screen disappears from the inbox
 *   (the friend left, the seat went, the code expired) the learner gets one
 *   short toast instead of a card that silently vanishes.
 * - **Learners only.** Staff have their own pages and no seat to join.
 */

import { useCallback, useEffect, useRef, useState } from "react";
import { usePathname, useRouter } from "next/navigation";

import { useQuery, useQueryClient } from "@tanstack/react-query";

import { Icon } from "@/components/icons";
import { Button, cx } from "@/components/ui";
import { ApiError, apiFetch } from "@/lib/api/client";
import { sentenceFor } from "@/lib/auth/messages";
import { useSession } from "@/lib/auth/session";
import { acceptInvite } from "@/lib/games/inviteAccept";
import type { Inbox, PendingInvite } from "@/lib/games/social";

/** A friend's invite can wait; the inbox is the source of truth. */
const POLL_MS = 20_000;
/** How long the "that invite is closed" note stays up. */
const NOTICE_MS = 7_000;

export function InviteAlert() {
  const session = useSession();
  const role = session.status === "authenticated" ? session.me.user.role : null;
  const isLearner = role === "learner";
  const pathname = usePathname();
  const router = useRouter();
  const queryClient = useQueryClient();

  const inbox = useQuery({
    queryKey: ["inbox"],
    queryFn: () => apiFetch<Inbox>("/api/games/inbox"),
    enabled: isLearner,
    refetchInterval: POLL_MS,
    retry: false,
  });

  const invites = inbox.data?.invites ?? [];
  const first: PendingInvite | null = invites[0] ?? null;

  const [open, setOpen] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  // Invitations already announced, so a poll does not re-open a closed card.
  const announced = useRef(new Set<string>());
  // The card that was on screen last time, for the "it is gone" toast.
  const showing = useRef<string | null>(null);
  // Invites this tab accepted: those leaving the inbox is success, not news.
  const taken = useRef<string | null>(null);

  // A different invitation is news; the same one is not.
  useEffect(() => {
    if (!first) return;
    if (announced.current.has(first.invitation_id)) return;
    announced.current.add(first.invitation_id);
    setOpen(true);
    setError(null);
  }, [first]);

  // An invite that leaves the inbox while its card is up did not disappear on
  // its own: the match behind it is gone. Say so in one sentence.
  useEffect(() => {
    if (!inbox.isFetched) return;
    const previous = showing.current;
    showing.current = first?.invitation_id ?? null;
    if (!previous) return;
    if (invites.some((row) => row.invitation_id === previous)) return;
    if (taken.current === previous) return;
    setOpen(false);
    setNotice("That invite is closed. Ask your friend again.");
  }, [inbox.isFetched, invites, first]);

  // The note clears itself; nothing to tap, nothing to remember.
  useEffect(() => {
    if (!notice) return;
    const id = window.setTimeout(() => setNotice(null), NOTICE_MS);
    return () => window.clearTimeout(id);
  }, [notice]);

  const play = useCallback(
    async (invitationId: string) => {
      setBusy(true);
      setError(null);
      try {
        const path = await acceptInvite(invitationId);
        taken.current = invitationId;
        setOpen(false);
        await queryClient.invalidateQueries({ queryKey: ["inbox"] });
        router.push(path);
      } catch (caught) {
        setError(
          caught instanceof ApiError
            ? sentenceFor(caught.code, caught.status)
            : sentenceFor(undefined),
        );
      } finally {
        setBusy(false);
      }
    },
    [queryClient, router],
  );

  // The inbox page already shows every invitation; a second copy would be noise.
  if (!isLearner) return null;
  if (pathname.startsWith("/games/invites")) return null;
  if (!first && !notice) return null;

  return (
    <>
      {notice ? (
        <p
          role="status"
          aria-live="polite"
          className="fixed bottom-4 left-1/2 z-50 flex w-[min(22rem,calc(100vw-2rem))] -translate-x-1/2 items-center gap-2 rounded-2xl bg-ink px-4 py-3 text-body-min font-semibold text-white shadow-card"
        >
          <Icon name="close" size={18} className="shrink-0" />
          {notice}
        </p>
      ) : null}

      {first && open ? (
        <div className="fixed bottom-4 right-4 z-50 animate-bob">
          <aside
            role="status"
            aria-live="polite"
            className="flex w-[min(22rem,calc(100vw-2rem))] flex-col gap-3 rounded-2xl border border-line bg-surface p-4 shadow-card"
          >
            <div className="flex items-start gap-3">
              <span
                aria-hidden="true"
                className="grid size-10 shrink-0 place-items-center rounded-xl bg-brand-soft text-brand-deep"
              >
                <Icon name="user-plus" size={20} />
              </span>
              <p className="flex-1 font-headline text-body-min font-bold text-ink">
                {first.sentence}
              </p>
              <button
                type="button"
                aria-label="Hide this invitation"
                onClick={() => setOpen(false)}
                className="-m-1 grid size-9 shrink-0 place-items-center rounded-xl text-ink-muted transition-colors hover:bg-surface-muted hover:text-ink"
              >
                <Icon name="close" size={18} />
              </button>
            </div>

            {error ? <p className="text-label font-semibold text-danger">{error}</p> : null}

            <div className="flex gap-2">
              <Button
                size="sm"
                disabled={busy}
                onClick={() => void play(first.invitation_id)}
                arrow
                className="flex-1"
              >
                Play
              </Button>
              <Button
                size="sm"
                variant="ghost"
                disabled={busy}
                onClick={() => router.push("/games/invites")}
                className="flex-1"
              >
                See all
              </Button>
            </div>
          </aside>
        </div>
      ) : first ? (
        <div className="fixed bottom-4 right-4 z-50 animate-bob">
          <button
            type="button"
            onClick={() => setOpen(true)}
            aria-label={
              invites.length === 1
                ? "1 invitation is waiting"
                : `${invites.length} invitations are waiting`
            }
            className={cx(
              "relative grid size-14 place-items-center rounded-full bg-brand text-white",
              "shadow-primary transition-transform hover:scale-105",
            )}
          >
            <Icon name="user-plus" size={24} />
            <span
              aria-hidden="true"
              className={cx(
                "tabular absolute -right-1 -top-1 grid size-6 place-items-center rounded-full",
                "bg-sun text-[12px] font-extrabold text-sun-ink ring-2 ring-surface",
              )}
            >
              {invites.length}
            </span>
          </button>
        </div>
      ) : null}
    </>
  );
}
