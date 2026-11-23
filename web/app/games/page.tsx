"use client";

/**
 * Games hub (P4-T07).
 *
 * The catalogue only ever contains games the server has enabled, so there is
 * no "coming soon" card to click and no dead end. Time is the same sentence as
 * everywhere else (P3), and one big button per game — in the game's own colour,
 * so a child who cannot read the label still knows which card is Checkers.
 */

import { useMutation, useQuery } from "@tanstack/react-query";
import Link from "next/link";
import { useRouter } from "next/navigation";

import { AppShell } from "@/components/AppShell";
import { GAME_LOOK, GamePreview } from "@/components/GamePreview";
import { Icon } from "@/components/icons";
import { ResumeGameLink } from "@/components/ResumeGameLink";
import { useAccess } from "@/components/TimeMeter";
import {
  Alert,
  Button,
  ButtonLink,
  Card,
  Chip,
  EmptyState,
  Loading,
  PageHeader,
} from "@/components/ui";
import { apiFetch } from "@/lib/api/client";
import { sentenceFor } from "@/lib/auth/messages";
import { useSession } from "@/lib/auth/session";
import type { Role } from "@/lib/auth/types";
import type { MyTurn } from "@/lib/games/social";
import { accessDetail, accessHeadline } from "@/lib/games/time";
import type { GameSummary } from "@/lib/games/types";

const LEARNER: Role[] = ["learner"];

export default function GamesPage() {
  return (
    <AppShell>
      <GamesBody />
    </AppShell>
  );
}

function GamesBody() {
  const session = useSession();
  const router = useRouter();
  const isLearner = session.status === "authenticated" && LEARNER.includes(session.me.user.role);

  const catalog = useQuery({
    queryKey: ["catalog"],
    queryFn: () => apiFetch<GameSummary[]>("/api/games/catalog"),
    enabled: isLearner,
  });
  // A challenge you still owe a turn in. Without it, a challenge sent five
  // minutes ago is only findable if the tab was never closed (P7-T06).
  const turns = useQuery({
    queryKey: ["my-challenges"],
    queryFn: () => apiFetch<MyTurn[]>("/api/games/challenges/mine"),
    enabled: isLearner,
  });
  const resume = useMutation({
    mutationFn: (turn: MyTurn) =>
      apiFetch(`/api/games/challenges/${turn.parent_id}/start`, { method: "POST" }),
    onSuccess: (_state, turn) => router.push(`/games/${turn.game_id}`),
  });
  const access = useAccess();

  if (session.status === "authenticated" && !isLearner) {
    return (
      <div className="flex flex-col gap-6">
        <PageHeader
          icon="play"
          title="Games"
          subtitle="Games are for learners. Your work is in Classes."
        />
        <ButtonLink href="/classes" arrow className="w-full sm:w-fit">
          Open Classes
        </ButtonLink>
      </div>
    );
  }

  const canPlay = access.data ? access.data.allowed : true;
  const games = catalog.data ?? [];

  return (
    <div className="flex flex-col gap-8">
      <PageHeader icon="play" title="Games" subtitle="Pick a game. One tap to start." />

      {/* The header already shows the time while play is allowed. This card is
          only for the states where the learner cannot play, where it explains
          why. */}
      {access.data && !access.data.allowed ? (
        <Card className="flex flex-col gap-3 border-2 border-line bg-surface-muted p-5">
          <p className="font-headline text-large font-bold text-ink">{accessHeadline(access.data)}</p>
          {accessDetail(
            access.data,
            session.status === "authenticated" ? session.me.school.timezone : "UTC",
          ) ? (
            <p className="text-body-min text-ink-muted">
              {accessDetail(
                access.data,
                session.status === "authenticated" ? session.me.school.timezone : "UTC",
              )}
            </p>
          ) : null}
          {access.data.reason === "another_session_active" ? <ResumeGameLink /> : null}
        </Card>
      ) : null}

      {turns.data && turns.data.length > 0 ? (
        <Card className="flex flex-col gap-4 border-2 border-brand bg-brand-soft p-5">
          <h2 className="flex items-center gap-2 font-headline text-large font-extrabold text-brand-deep">
            <Icon name="flag" size={22} />
            Your turn
          </h2>
          {turns.data.map((turn) => (
            <div key={turn.parent_id} className="flex flex-col gap-3">
              <p className="text-body text-ink">{turn.sentence}</p>
              <Button
                disabled={resume.isPending}
                onClick={() => resume.mutate(turn)}
                arrow
                className="w-full sm:w-fit"
              >
                Play my turn
              </Button>
            </div>
          ))}
        </Card>
      ) : null}

      {catalog.isPending ? <Loading /> : null}
      {catalog.isError ? <Alert>{sentenceFor(undefined)}</Alert> : null}
      {catalog.data && games.length === 0 ? (
        <EmptyState icon="play" title="There are no games yet">
          Your Coach will add some soon.
        </EmptyState>
      ) : null}

      <div className="grid grid-cols-1 gap-5 sm:grid-cols-2 lg:grid-cols-3">
        {games.map((game) => {
          const look = GAME_LOOK[game.id];
          return (
            <article
              key={game.id}
              className="flex flex-col gap-4 rounded-3xl border-2 border-line bg-surface p-5 transition-transform hover:-translate-y-0.5 hover:shadow-card"
            >
              {/* A learner who cannot read has to pick the right card by its
                  picture (D.5 step 1), so every game carries a mark. */}
              <GamePreview gameId={game.id} />

              <div className="flex flex-col gap-1.5">
                <div className="flex items-start justify-between gap-2">
                  <h2 className="font-headline text-xl font-extrabold tracking-tight text-ink">
                    {game.name}
                  </h2>
                  {look ? <Chip tone={look.tone}>{look.chip}</Chip> : <Chip>Game</Chip>}
                </div>
                <p className="text-body-min text-ink-muted">{game.summary}</p>
              </div>

              {canPlay && look ? (
                <ButtonLink href={look.href} variant={look.variant} arrow className="mt-auto w-full">
                  {look.label}
                </ButtonLink>
              ) : (
                <p className="mt-auto rounded-2xl bg-surface-muted px-4 py-3 text-center text-label font-bold text-ink-muted">
                  You cannot play right now.
                </p>
              )}
            </article>
          );
        })}
      </div>

      {/* P7-T06: the way in for an invite that arrived by code or link. */}
      <Card className="flex flex-col gap-4 p-6">
        <div className="flex items-start gap-4">
          <span
            aria-hidden="true"
            className="grid size-12 shrink-0 place-items-center rounded-2xl bg-sun-soft text-sun-ink"
          >
            <Icon name="user-plus" size={24} />
          </span>
          <div className="flex flex-col gap-1">
            <h2 className="font-headline text-large font-extrabold text-ink">Join a friend</h2>
            <p className="text-body-min text-ink-muted">
              Got a code or an invite? Start here.
            </p>
          </div>
        </div>

        <div className="flex flex-col gap-3 sm:flex-row">
          <ButtonLink href="/games/invites" variant="secondary" icon="message" className="w-full sm:w-auto">
            My invites
          </ButtonLink>
          <ButtonLink href="/games/join" variant="ghost" icon="key" className="w-full sm:w-auto">
            Type a code
          </ButtonLink>
        </div>

        <p className="text-label text-ink-muted">
          Lost?{" "}
          <Link href="/" className="font-bold text-brand underline underline-offset-4">
            Go back to your dashboard
          </Link>
          .
        </p>
      </Card>
    </div>
  );
}
