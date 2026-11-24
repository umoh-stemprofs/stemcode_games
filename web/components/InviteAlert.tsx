"use client";

/**
 * The invitation that finds you (P7-T07).
 *
 * A learner should not have to sit on the inbox to hear that a friend wants to
 * play. This polls the one endpoint that already answers the question and shows
 * the newest invitation until the learner has dealt with it.
 *
 * Rules it keeps:
 *
 * - **One sentence, two choices.** The server's own sentence, then `Play` or
 *   close. Nothing else.
 * - **It never blocks.** It sits in the corner, outside the page flow, so a
 *   round in progress keeps its clock and its buttons.
 * - **It waits.** The card stays exactly where it is until the learner presses
 *   the close button (which folds it into the small round button), plays, or
 *   opens the inbox. It no longer disappears on a timer or on its own: a message
 *   that vanishes while a child is reading it reads as a lost turn.
 * - **It moves.** Card and button bob gently, because a still corner is easy to
 *   miss. `prefers-reduced-motion` stops it.
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

/** A friend's invite can wait 20 seconds; the inbox is the source of truth. */
const POLL_MS = 20_000;

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
  // Invitations already announced, so a poll does not re-open a closed card.
  const announced = useRef(new Set<string>());

  // A different invitation is news; the same one is not.
  useEffect(() => {
    if (!first) return;
    if (announced.current.has(first.invitation_id)) return;
    announced.current.add(first.invitation_id);
    setOpen(true);
    setError(null);
  }, [first]);

  // Nothing closes this on a timer. A new invitation opens the card again; an
  // existing one stays until the learner closes it.

  const play = useCallback(
    async (invitationId: string) => {
      setBusy(true);
      setError(null);
      try {
        const path = await acceptInvite(invitationId);
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
  if (!isLearner || !first) return null;
  if (pathname.startsWith("/games/invites")) return null;

  return (
    <>
      {open ? (
        <aside
          role="status"
          aria-live="polite"
          className="animate-bob fixed bottom-4 right-4 z-50 flex w-[min(22rem,calc(100vw-2rem))] flex-col gap-3 rounded-2xl border border-line bg-surface p-4 shadow-card"
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
      ) : (
        <div className="animate-bob fixed bottom-4 right-4 z-50">
          <button
            type="button"
            onClick={() => setOpen(true)}
            aria-label={
              invites.length === 1
                ? "1 invitation is waiting"
                : `${invites.length} invitations are waiting`
            }
            className="relative grid size-14 place-items-center rounded-full bg-brand text-white shadow-primary transition-transform hover:scale-105"
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
      )}
    </>
  );
}
