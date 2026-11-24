"use client";

/**
 * "Play with a friend" (P7-T06), with Appendix D as the brief.
 *
 * The order of the screen is the order of the device they are on:
 *
 * 1. **Avatars of classmates.** One tap sends the invite. No typing, no camera,
 *    no code to copy — school laptops rarely have a usable one.
 * 2. **A big code**, in two groups of four, for a friend in another class. The
 *    characters are the ones a child can read aloud (no I, L, O, 0, 1).
 * 3. **Copy link / Share**, for the same thing without the reading.
 *
 * Expiry is a clock time ("This code stops working at 3:15."), never a
 * countdown, and there is never a QR requirement or a camera prompt.
 */

import { useState } from "react";

import { useQuery } from "@tanstack/react-query";

import { Icon } from "@/components/icons";
import { Alert, Button, Card, Loading } from "@/components/ui";
import { ApiError, apiFetch } from "@/lib/api/client";
import { sentenceFor } from "@/lib/auth/messages";
import type { PlayState } from "@/lib/games/types";
import type { ChallengeCreated, Friend } from "@/lib/games/social";

type Props = {
  gameId: string;
  gameName: string;
  onStarted: (state: PlayState) => void;
};

export function FriendSheet({ gameId, gameName, onStarted }: Props) {
  const friends = useQuery({
    queryKey: ["friends"],
    queryFn: () => apiFetch<Friend[]>("/api/games/friends"),
  });

  // The roster is a screen of its own: showing nine names next to the level
  // buttons put the choosing screen well past the 25 words Appendix D allows
  // at once, and invited a first-timer to tap a classmate by accident.
  const [open, setOpen] = useState(false);
  const [invite, setInvite] = useState<ChallengeCreated | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [copied, setCopied] = useState(false);

  async function send(inviteeId?: string) {
    setBusy(true);
    setError(null);
    try {
      const created = await apiFetch<ChallengeCreated>("/api/games/challenges", {
        method: "POST",
        body: JSON.stringify({
          game_id: gameId,
          difficulty: 1,
          invitee_id: inviteeId ?? null,
          with_code: true,
          with_link: true,
        }),
      });
      setInvite(created);
    } catch (caught) {
      setError(
        caught instanceof ApiError ? sentenceFor(caught.code, caught.status) : sentenceFor(undefined),
      );
    } finally {
      setBusy(false);
    }
  }

  async function playMyTurn() {
    if (!invite) return;
    setBusy(true);
    setError(null);
    try {
      const state = await apiFetch<PlayState & { parent_id: string }>(
        `/api/games/challenges/${invite.parent_id}/start`,
        { method: "POST" },
      );
      onStarted(state);
    } catch (caught) {
      setError(
        caught instanceof ApiError ? sentenceFor(caught.code, caught.status) : sentenceFor(undefined),
      );
    } finally {
      setBusy(false);
    }
  }

  async function copyLink() {
    if (!invite?.join_path) return;
    try {
      await navigator.clipboard.writeText(`${window.location.origin}${invite.join_path}`);
      setCopied(true);
    } catch {
      // A clipboard can be refused; the code below still works.
      setError("Copy the link from the box below.");
    }
  }

  if (invite) {
    return (
      <Card className="flex flex-col gap-4 p-6">
        <h2 className="font-headline text-large font-extrabold text-ink">
          {invite.invitee_name ? `Invite sent to ${invite.invitee_name}.` : `Your ${gameName} code`}
        </h2>

        {invite.formatted_code ? (
          <p className="tabular rounded-2xl border-2 border-dashed border-line bg-surface-muted px-4 py-5 text-center font-headline text-[clamp(28px,7vw,40px)] font-extrabold tracking-[0.18em] text-ink">
            {invite.formatted_code}
          </p>
        ) : null}
        <p className="text-body-min text-ink-muted">{invite.expires_sentence}</p>

        {error ? <Alert>{error}</Alert> : null}

        <Button size="lg" disabled={busy} onClick={() => void playMyTurn()} arrow className="w-full">
          Play my turn
        </Button>

        {invite.join_path ? (
          <Button
            variant="ghost"
            onClick={() => void copyLink()}
            icon={copied ? "check" : "link"}
            className="w-full"
          >
            {copied ? "Link copied" : "Copy link"}
          </Button>
        ) : null}
      </Card>
    );
  }

  if (!open) {
    return (
      <Button variant="secondary" onClick={() => setOpen(true)} icon="users" className="w-full sm:w-fit">
        Play with a friend
      </Button>
    );
  }

  return (
    <Card className="flex flex-col gap-4 p-6">
      <div className="flex items-start justify-between gap-3">
        <div className="flex flex-col gap-1">
          <h2 className="font-headline text-large font-extrabold text-ink">Play with a friend</h2>
          <p className="text-body-min text-ink-muted">Tap a friend to invite them.</p>
        </div>
        <Button variant="quiet" size="sm" onClick={() => setOpen(false)} icon="close">
          Close
        </Button>
      </div>

      {error ? <Alert>{error}</Alert> : null}

      {friends.isPending ? <Loading /> : null}

      {friends.data && friends.data.length === 0 ? (
        <p className="rounded-2xl bg-surface-muted px-4 py-3 text-body-min text-ink-muted">
          No classmates to invite yet.
        </p>
      ) : null}

      <ul className="flex flex-wrap gap-2.5">
        {friends.data?.map((friend) => (
          <li key={friend.id}>
            <button
              type="button"
              disabled={busy || !friend.can_invite}
              onClick={() => void send(friend.id)}
              aria-label={`Invite ${friend.name}`}
              className="flex min-h-target min-w-target flex-col items-center justify-center gap-1 rounded-2xl border-2 border-line bg-surface px-4 py-2 text-label font-bold text-ink transition-colors hover:border-brand hover:bg-brand-soft disabled:opacity-50"
            >
              <span className="relative">
                <span
                  aria-hidden="true"
                  className="grid size-9 place-items-center rounded-full bg-surface-muted text-[19px] font-extrabold text-brand-deep"
                >
                  {friend.name.charAt(0).toUpperCase()}
                </span>
                {friend.online ? (
                  <span
                    aria-hidden="true"
                    className="absolute -bottom-0.5 -right-0.5 size-3 rounded-full bg-ok ring-2 ring-surface"
                  />
                ) : null}
              </span>
              {friend.name}
              <span className={friend.online ? "text-micro font-bold text-ok" : "text-micro text-ink-muted"}>
                {friend.online ? "Online" : "Away"}
              </span>
            </button>
          </li>
        ))}
      </ul>

      <Button
        variant="ghost"
        disabled={busy}
        onClick={() => void send()}
        icon="key"
        className="w-full sm:w-fit"
      >
        Show a code instead
      </Button>

      <p className="flex items-center gap-2 text-label text-ink-muted">
        <Icon name="link" size={15} />
        Or share the link, below.
      </p>
    </Card>
  );
}
