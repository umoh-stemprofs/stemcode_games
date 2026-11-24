"use client";

/**
 * The inbox (P7-T07): one sentence per item and exactly one button.
 *
 * An invitation reads "Bayo wants to play Word Scramble with you." with two
 * buttons, `Play` and `No thanks`. A finished challenge reads one sentence and
 * has nothing to tap, because there is nothing left to do. There is no email
 * or SMS in the MVP, and no badge numbers — an unread count is a worry, not
 * information (Appendix D).
 */

import { useCallback, useEffect, useState } from "react";
import { useRouter } from "next/navigation";

import { useQuery } from "@tanstack/react-query";

import { AppShell } from "@/components/AppShell";
import { Icon } from "@/components/icons";
import { Alert, Button, ButtonLink, Card, EmptyState, Loading, PageHeader } from "@/components/ui";
import { ApiError, apiFetch } from "@/lib/api/client";
import { sentenceFor } from "@/lib/auth/messages";
import { acceptInvite } from "@/lib/games/inviteAccept";
import type { Inbox } from "@/lib/games/social";

export default function InvitesPage() {
  return (
    <AppShell>
      <InvitesBody />
    </AppShell>
  );
}

function InvitesBody() {
  const router = useRouter();
  const inbox = useQuery({
    queryKey: ["inbox"],
    queryFn: () => apiFetch<Inbox>("/api/games/inbox"),
  });
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!inbox.data?.unread) return;
    void apiFetch("/api/games/inbox/read", { method: "POST" }).catch(() => undefined);
  }, [inbox.data?.unread]);

  const play = useCallback(
    async (invitationId: string) => {
      setBusy(true);
      setError(null);
      try {
        // Shared with the popup, so both say yes in the same order: accept,
        // start the challenge when it is not a live match, then open it.
        router.push(await acceptInvite(invitationId));
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
    [router],
  );

  async function decline(invitationId: string) {
    setBusy(true);
    try {
      await apiFetch(`/api/games/invites/${invitationId}/decline`, { method: "POST" });
      await inbox.refetch();
    } catch {
      setError(sentenceFor(undefined));
    } finally {
      setBusy(false);
    }
  }

  if (inbox.isPending) {
    return (
      <div className="flex flex-col gap-6">
        <PageHeader icon="message" title="Invites" />
        <Loading />
      </div>
    );
  }

  if (inbox.isError) {
    return (
      <div className="flex flex-col gap-6">
        <PageHeader icon="message" title="Invites" />
        <Alert>{sentenceFor(undefined)}</Alert>
      </div>
    );
  }

  const data = inbox.data;
  const nothing = data.invites.length === 0 && data.notifications.length === 0;

  return (
    <div className="flex flex-col gap-6">
      <PageHeader
        icon="message"
        title="Invites"
        subtitle="A friend wants to play. One tap to start."
        action={
          <ButtonLink href="/games" variant="ghost" size="sm" icon="arrow-left">
            All games
          </ButtonLink>
        }
      />

      {error ? <Alert>{error}</Alert> : null}

      {nothing ? (
        <Card className="p-4">
          <EmptyState icon="message" title="There is nothing here yet">
            Ask a friend for a game code, or invite one from any game.
          </EmptyState>
        </Card>
      ) : null}

      {data.invites.map((invite) => (
        <Card key={invite.invitation_id} className="flex flex-col gap-4 p-6">
          <p className="flex items-start gap-3 font-headline text-large font-bold text-ink">
            <Icon name="user-plus" size={22} className="mt-0.5 shrink-0 text-brand" />
            {invite.sentence}
          </p>
          <div className="flex flex-col gap-3 sm:flex-row">
            <Button
              disabled={busy}
              onClick={() => void play(invite.invitation_id)}
              arrow
              className="w-full sm:w-auto"
            >
              Play
            </Button>
            <Button
              variant="ghost"
              disabled={busy}
              onClick={() => void decline(invite.invitation_id)}
              className="w-full sm:w-auto"
            >
              No thanks
            </Button>
          </div>
        </Card>
      ))}

      {data.notifications.length > 0 ? (
        <section className="flex flex-col gap-3">
          <h2 className="font-headline text-large font-extrabold text-ink">What happened</h2>
          <ul className="flex flex-col gap-3">
            {data.notifications.map((note) => (
              <li
                key={note.id}
                className="rounded-2xl border border-line bg-surface px-4 py-3 text-body"
              >
                {note.body}
              </li>
            ))}
          </ul>
        </section>
      ) : null}
    </div>
  );
}
