"use client";

/**
 * The Checkers lobby (P8-T18).
 *
 * The only decision on this screen is *who*, and the roster answers it with one
 * tap: no typing, no code to read out unless nobody is free. A classmate who
 * cannot play still appears, with the reason in a sentence, because a name that
 * silently vanishes looks like a bug to a child (Appendix D.2.4).
 *
 * Creating a match sends the invite and takes the inviter straight to the board.
 * The board already knows how to wait ("Waiting for Bayo to join."), so there is
 * no second waiting screen to keep in step with it.
 */

import { useCallback, useState } from "react";
import { useRouter } from "next/navigation";
import { useQuery } from "@tanstack/react-query";

import { AppShell } from "@/components/AppShell";
import { GamePreview } from "@/components/GamePreview";
import { Icon } from "@/components/icons";
import {
  Alert,
  ButtonLink,
  Card,
  Chip,
  EmptyState,
  Loading,
  PageHeader,
} from "@/components/ui";
import { ApiError, apiFetch } from "@/lib/api/client";
import { sentenceFor } from "@/lib/auth/messages";
import { acceptInvite } from "@/lib/games/inviteAccept";
import type { LiveCreated, PresenceRow } from "@/lib/games/live";

export default function CheckersLobbyPage() {
  return (
    <AppShell>
      <LobbyBody />
    </AppShell>
  );
}

function LobbyBody() {
  const router = useRouter();
  const [pending, setPending] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const presence = useQuery({
    queryKey: ["presence"],
    queryFn: () => apiFetch<PresenceRow[]>("/api/games/presence"),
    // The dots go stale quickly; a learner waiting for a partner should see it
    // change while the screen is open.
    refetchInterval: 30_000,
    refetchOnWindowFocus: true,
  });

  const onlineCount = (presence.data ?? []).filter((friend) => friend.online).length;

  const invitable = useCallback(
    async (friend: PresenceRow) => {
      setPending(friend.user_id);
      setError(null);
      try {
        if (friend.invitation_id) {
          // They already made the match and the seat has my name on it. Taking
          // it is the same call the inbox makes, so the two paths cannot drift.
          router.push(await acceptInvite(friend.invitation_id));
          return;
        }
        const created = await apiFetch<LiveCreated>("/api/games/live", {
          method: "POST",
          body: JSON.stringify({ invitee_id: friend.user_id }),
        });
        router.push(`/games/checkers/${created.session_id}`);
      } catch (caught) {
        setError(
          caught instanceof ApiError
            ? sentenceFor(caught.code, caught.status)
            : sentenceFor(undefined),
        );
      } finally {
        setPending(null);
      }
    },
    [router],
  );

  return (
    <div className="flex flex-col gap-6">
      <PageHeader
        icon="play"
        title="Checkers"
        subtitle="Play draughts against a classmate."
        action={
          <ButtonLink href="/games" variant="ghost" size="sm" icon="arrow-left">
            All games
          </ButtonLink>
        }
      />

      {error ? <Alert>{error}</Alert> : null}

      <div className="grid items-start gap-4 sm:grid-cols-2">
        <Card className="flex flex-col gap-3 border-2 border-line p-5">
          <GamePreview gameId="checkers" />
          <div className="flex items-center justify-between gap-2">
            <p className="font-headline text-large font-extrabold text-ink">You play white.</p>
            <Chip tone="blue">1v1 match</Chip>
          </div>
          <p className="text-body-min text-ink-muted">
            Tap a piece, then a square. Only moves you can make are shown.
          </p>
        </Card>

        <Card className="flex flex-col gap-3 p-5">
          <div className="flex flex-wrap items-center gap-2">
            <h2 className="flex items-center gap-2 font-headline text-large font-extrabold text-ink">
              <Icon name="users" size={22} className="text-brand" />
              Who will you play?
            </h2>
            {/* The roster is only useful if it says who is actually there. */}
            {onlineCount > 0 ? (
              <Chip tone="green" className="ml-auto">
                {onlineCount === 1 ? "1 online" : `${onlineCount} online`}
              </Chip>
            ) : null}
          </div>

          {presence.isPending ? <Loading /> : null}

          {presence.isError ? (
            <p className="text-body-min text-ink-muted">Your classmates will show here.</p>
          ) : null}

          {presence.data && presence.data.length === 0 ? (
            <EmptyState icon="users" title="No classmates to play with yet">
              Ask your Coach to add people to your class.
            </EmptyState>
          ) : null}

          <ul className="grid grid-cols-2 gap-2.5">
            {presence.data?.map((friend) => {
              const free = friend.status === "available";
              const invited = Boolean(friend.invitation_id);
              return (
                <li key={friend.user_id} className="flex flex-col gap-1">
                  <button
                    type="button"
                    disabled={!free || pending !== null}
                    onClick={() => void invitable(friend)}
                    aria-label={
                      invited
                        ? `Play with ${friend.name}`
                        : free
                          ? `Invite ${friend.name}`
                          : friend.sentence
                    }
                    className="flex min-h-target flex-col items-center justify-center gap-1 rounded-2xl border-2 border-line bg-surface px-3 py-2.5 font-headline text-label font-bold text-ink transition-colors hover:border-brand hover:bg-brand-soft disabled:cursor-not-allowed disabled:border-line disabled:bg-surface-muted disabled:text-ink-muted sm:text-body-min"
                  >
                    <span className="relative">
                      <span
                        aria-hidden="true"
                        className="grid size-9 place-items-center rounded-full bg-canvas text-[19px] font-extrabold text-brand-deep ring-2 ring-line"
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
                    <span className="max-w-full truncate">{friend.name}</span>
                    {invited ? (
                      <span className="text-micro font-bold uppercase tracking-wide text-brand">
                        Invited you
                      </span>
                    ) : friend.online ? (
                      <span className="text-micro font-bold uppercase tracking-wide text-ok">
                        Online
                      </span>
                    ) : null}
                  </button>
                  {free ? null : (
                    <span className="text-label leading-tight text-ink-muted">{friend.sentence}</span>
                  )}
                </li>
              );
            })}
          </ul>
        </Card>
      </div>

      <Card className="flex flex-col gap-3 p-5 sm:flex-row sm:items-center sm:justify-between">
        <p className="text-body-min text-ink-muted">
          Nobody free? Play a friend in another class with a code.
        </p>
        <ButtonLink href="/games/join" variant="ghost" icon="key" className="w-full sm:w-auto">
          Type a code
        </ButtonLink>
      </Card>

    </div>
  );
}
