"use client";

/**
 * Dashboard (P1-T07, P3-T11).
 *
 * The screen a learner lands on, designed around one question: *what do I want
 * to play next?* Everything above the fold answers it — the greeting, the time
 * left, then three big game cards. Below that, the classroom board and the way
 * into a friend's match, which are the two reasons to come back tomorrow.
 *
 * The time card still explains a blocked state in one calm sentence, and the
 * "open game somewhere else" state still offers the way back to it. Time is
 * read only; the server owns the clock.
 */

import { useQuery } from "@tanstack/react-query";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useState, type FormEvent } from "react";

import { AppShell } from "@/components/AppShell";
import {
  BestLine,
  QuestCard,
  StreakCapsule,
  bestFor,
  streakNudge,
  useEngagement,
} from "@/components/Engagement";
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
import { avatarEmoji } from "@/lib/avatars";
import { useSession } from "@/lib/auth/session";
import type { Board } from "@/lib/games/board-types";
import { accessDetail, accessHeadline } from "@/lib/games/time";
import type { GameSummary } from "@/lib/games/types";

export default function HomePage() {
  return (
    <AppShell>
      <HomeBody />
    </AppShell>
  );
}

function HomeBody() {
  const session = useSession();
  if (session.status !== "authenticated") return null;

  const { me } = session;
  if (me.user.role !== "learner") return <StaffHome />;

  return (
    <div className="flex flex-col gap-8">
      <WelcomeHero name={me.user.preferred_name} />
      <AccessNotice />
      <GameShelf />
      <QuestRow />
      <ClassBoardCard />
      <JoinCard />
      <p className="text-label text-ink-muted">
        Your class, invites and every game are one tap away.{" "}
        <Link href="/classes" className="font-bold text-brand underline underline-offset-4">
          Open my class
        </Link>
      </p>
    </div>
  );
}

/**
 * Greeting, the streak, and today's place on the board.
 *
 * The streak capsule is the design's reserved slot, filled with the only real
 * number that belongs there: how many days in a row this learner has played.
 * The nudge under the greeting is the reason to play *now* rather than later.
 */
function WelcomeHero({ name }: { name: string }) {
  const board = useQuery({
    queryKey: ["board", "daily", "", ""],
    queryFn: () => apiFetch<Board>("/api/leaderboards/daily"),
    retry: false,
  });
  const engagement = useEngagement();
  const rank = board.data?.me ?? null;
  const streak = engagement.data?.streak ?? null;

  return (
    <section className="flex flex-col gap-5 rounded-3xl border border-line bg-surface p-6 shadow-card sm:p-8 md:flex-row md:items-center md:justify-between">
      <div className="flex flex-col gap-2">
        <h1 className="font-headline text-[clamp(28px,5vw,40px)] font-extrabold leading-tight tracking-tight text-ink">
          Welcome back, {name}!{" "}
          <span aria-hidden="true" className="inline-block">
            👋
          </span>
        </h1>
        {streak ? (
          <p className="text-body text-ink-muted">{streakNudge(streak)}</p>
        ) : null}
      </div>

      <div className="flex flex-wrap items-center gap-3">
        {streak ? <StreakCapsule streak={streak} /> : null}

        {rank ? (
          <div className="flex items-center gap-2.5 rounded-2xl border border-line bg-brand-soft px-4 py-2.5 text-brand-deep">
            <Icon name="trophy" size={22} />
            <span className="flex flex-col leading-tight">
              <span className="text-micro font-bold uppercase text-brand-deep">Today</span>
              <span className="font-headline text-body-min font-extrabold">You are #{rank.rank}</span>
            </span>
          </div>
        ) : null}
      </div>
    </section>
  );
}

/** The daily quest sits between the games and the board: goal, then reason. */
function QuestRow() {
  const engagement = useEngagement();
  if (!engagement.data) return null;
  return <QuestCard quest={engagement.data.quest} />;
}

/**
 * Only appears when play is blocked. The header already carries the time; this
 * is the reason, in one sentence, and the way forward when there is one.
 */
function AccessNotice() {
  const session = useSession();
  const access = useAccess();
  if (session.status !== "authenticated" || !access.data || access.data.allowed) return null;

  return (
    <Card className="flex flex-col gap-3 border-2 border-line bg-surface-muted p-5">
      <p className="font-headline text-large font-bold text-ink">{accessHeadline(access.data)}</p>
      {accessDetail(access.data, session.me.school.timezone) ? (
        <p className="text-body-min text-ink-muted">
          {accessDetail(access.data, session.me.school.timezone)}
        </p>
      ) : null}
      {access.data.reason === "another_session_active" ? <ResumeGameLink /> : null}
    </Card>
  );
}

function GameShelf() {
  const session = useSession();
  const access = useAccess();
  const engagement = useEngagement();
  const catalog = useQuery({
    queryKey: ["catalog"],
    queryFn: () => apiFetch<GameSummary[]>("/api/games/catalog"),
    enabled: session.status === "authenticated",
  });

  const canPlay = access.data ? access.data.allowed : true;
  const games = catalog.data ?? [];

  return (
    <section className="flex flex-col gap-4">
      <div className="flex items-end justify-between gap-3 px-1">
        <h2 className="font-headline text-large font-extrabold tracking-tight text-ink">
          Pick a game
        </h2>
        <Link
          href="/games"
          className="flex items-center gap-1 text-label font-bold text-brand hover:text-brand-deep"
        >
          All {games.length || ""} games
          <Icon name="arrow-right" size={16} />
        </Link>
      </div>

      {catalog.isPending ? <Loading /> : null}
      {catalog.isError ? <Alert>That list did not load. Try again.</Alert> : null}
      {catalog.data && games.length === 0 ? (
        <EmptyState title="No games yet">Your Coach will add some soon.</EmptyState>
      ) : null}

      <div className="grid grid-cols-1 gap-5 sm:grid-cols-2 lg:grid-cols-3">
        {games.slice(0, 6).map((game) => {
          const look = GAME_LOOK[game.id];
          return (
            <article
              key={game.id}
              className="group flex flex-col gap-4 rounded-3xl border-2 border-line bg-surface p-5 transition-transform hover:-translate-y-0.5 hover:shadow-card"
            >
              <GamePreview gameId={game.id} />
              <div className="flex flex-col gap-1.5">
                <div className="flex items-start justify-between gap-2">
                  <h3 className="font-headline text-xl font-extrabold tracking-tight text-ink">
                    {game.name}
                  </h3>
                  {look ? (
                    <Chip tone={look.tone}>{look.chip}</Chip>
                  ) : (
                    <Chip>Game</Chip>
                  )}
                </div>
                <p className="text-body-min text-ink-muted">{game.summary}</p>
                {bestFor(engagement.data?.bests, game.id) ? (
                  <BestLine value={bestFor(engagement.data?.bests, game.id) ?? ""} />
                ) : null}
              </div>

              {canPlay && look ? (
                <ButtonLink
                  href={look.href}
                  variant={look.variant}
                  arrow
                  className="mt-auto w-full"
                >
                  {look.label}
                </ButtonLink>
              ) : (
                <p className="mt-auto rounded-2xl bg-surface-muted px-4 py-3 text-center text-label font-bold text-ink-muted">
                  Not right now
                </p>
              )}
            </article>
          );
        })}
      </div>
    </section>
  );
}

/** The classroom board, trimmed to the three names and your own row. */
function ClassBoardCard() {
  const board = useQuery({
    queryKey: ["board", "daily", "", ""],
    queryFn: () => apiFetch<Board>("/api/leaderboards/daily"),
    retry: false,
  });

  const top = board.data?.entries.slice(0, 3) ?? [];
  const me = board.data?.me ?? null;
  const medals = ["🥇", "🥈", "🥉"];

  return (
    <Card className="flex flex-col gap-5 p-6 sm:p-8">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h2 className="flex items-center gap-2.5 font-headline text-large font-extrabold tracking-tight text-ink">
          <span aria-hidden="true">🏆</span>
          Classroom leaderboard
        </h2>
        <Link
          href="/leaderboards"
          className="flex items-center gap-1 text-label font-bold text-brand hover:text-brand-deep"
        >
          Full standings
          <Icon name="chevron-right" size={16} />
        </Link>
      </div>

      {board.isPending ? <Loading /> : null}

      {board.isError ? (
        <EmptyState icon="trophy" title="No board yet">
          Play a game and the board will start.
        </EmptyState>
      ) : null}

      {board.data && top.length === 0 ? (
        <EmptyState icon="trophy" title="Nobody is on the board yet">
          Play {board.data.to_join ?? board.data.min_sessions}{" "}
          {(board.data.to_join ?? board.data.min_sessions) === 1 ? "game" : "games"} to be the
          first.
        </EmptyState>
      ) : null}

      {top.length > 0 ? (
        <div className="grid grid-cols-1 gap-3 sm:grid-cols-3">
          {top.map((row, index) => (
            <div
              key={`${row.rank}-${row.preferred_name}`}
              className="flex items-center justify-between gap-3 rounded-2xl border border-line bg-surface-muted p-4 sm:flex-col sm:justify-center sm:text-center"
            >
              <div className="flex items-center gap-3 sm:flex-col sm:gap-1.5">
                <span aria-hidden="true" className="text-3xl leading-none">
                  {medals[index] ?? "⭐"}
                </span>
                <span className="font-headline text-body-min font-extrabold text-ink">
                  {row.preferred_name}
                </span>
              </div>
              <span className="tabular rounded-xl border border-line bg-surface px-3 py-1 text-label font-bold text-brand-deep">
                {row.xp_total} XP
              </span>
            </div>
          ))}
        </div>
      ) : null}

      {me ? (
        <div className="flex items-center justify-between gap-3 rounded-2xl bg-brand-soft px-4 py-3">
          <div className="flex min-w-0 items-center gap-3">
            <span className="grid size-9 shrink-0 place-items-center rounded-xl bg-brand text-label font-bold text-white">
              #{me.rank}
            </span>
            <span className="truncate font-headline text-body-min font-extrabold text-brand-deep">
              {me.preferred_name} (you)
            </span>
            <span aria-hidden="true" className="text-large">
              {avatarEmoji(me.avatar_key)}
            </span>
          </div>
          <span className="tabular shrink-0 text-label font-bold text-brand-deep">
            {me.xp_total} XP
          </span>
        </div>
      ) : null}

      {/* The near-miss nudge: the next place up, or the games still missing. */}
      {board.data?.chase ? (
        <p className="flex items-center gap-2 text-body-min font-semibold text-ink">
          <span aria-hidden="true">🔎</span>
          {board.data.chase.xp_gap} XP to pass {board.data.chase.preferred_name}.
        </p>
      ) : null}
      {top.length > 0 && board.data?.to_join ? (
        <p className="text-body-min text-ink-muted">
          Play {board.data.to_join} more {board.data.to_join === 1 ? "game" : "games"} to join
          this board.
        </p>
      ) : null}
    </Card>
  );
}

/** The dark multiplayer strip: paste a code, land in a friend's match. */
function JoinCard() {
  const router = useRouter();
  const [code, setCode] = useState("");

  function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const trimmed = code.trim().toUpperCase();
    router.push(trimmed ? `/games/join?code=${encodeURIComponent(trimmed)}` : "/games/join");
  }

  return (
    <section className="relative overflow-hidden rounded-3xl bg-ink p-6 text-white shadow-card sm:p-9">
      <div
        aria-hidden="true"
        className="pointer-events-none absolute -bottom-24 -right-16 size-72 rounded-full bg-brand opacity-30 blur-3xl"
      />
      <div className="relative flex flex-col gap-6 lg:flex-row lg:items-center lg:justify-between">
        <div className="flex flex-col gap-4 sm:flex-row sm:items-center">
          <span
            aria-hidden="true"
            className="grid size-16 shrink-0 place-items-center rounded-2xl border border-white/25 bg-white/10"
          >
            <Icon name="user-plus" size={30} />
          </span>
          <div className="flex flex-col gap-1.5">
            <span className="w-fit rounded-pill bg-white/15 px-2.5 py-0.5 text-micro font-bold uppercase tracking-wider text-white">
              Multiplayer match
            </span>
            <h2 className="font-headline text-[clamp(22px,3.4vw,30px)] font-extrabold tracking-tight">
              Have a game code from a friend?
            </h2>
            <p className="max-w-lg text-body-min text-white/80">
              Type the code below to jump into their match.
            </p>
          </div>
        </div>

        <form onSubmit={submit} className="flex w-full flex-col gap-3 sm:flex-row lg:w-auto">
          <label htmlFor="join-code" className="sr-only">
            Game code
          </label>
          <input
            id="join-code"
            value={code}
            onChange={(event) => setCode(event.target.value.toUpperCase())}
            maxLength={12}
            placeholder="• • • • • • • •"
            autoCapitalize="characters"
            spellCheck={false}
            className="tabular h-14 w-full rounded-2xl border-2 border-white/25 bg-white/10 px-5 text-center text-xl tracking-[0.2em] text-white outline-none transition-colors placeholder:tracking-[0.2em] placeholder:text-white/50 focus:border-white focus:bg-white focus:text-ink sm:w-64"
          />
          <Button type="submit" variant="primary" size="md" arrow className="h-14 shrink-0">
            Join match
          </Button>
        </form>
      </div>

      <p className="relative mt-4 text-label text-white/70">
        Or{" "}
        <Link href="/games/invites" className="font-bold text-white underline underline-offset-4">
          see your invites
        </Link>
        .
      </p>
    </section>
  );
}

/** Staff land here: their work is in Classes and Time limits. */
function StaffHome() {
  const session = useSession();
  if (session.status !== "authenticated") return null;
  const { me } = session;

  return (
    <div className="flex flex-col gap-8">
      <Card className="p-6 sm:p-8">
        <PageHeader
          title={`Hello, ${me.user.preferred_name}`}
          subtitle="Every class, one tap away."
          icon="users"
        />
        <div className="mt-5 flex flex-wrap gap-3">
          <Chip tone="blue">{me.user.role === "school_admin" ? "School admin" : "Coach"}</Chip>
        </div>
      </Card>

      <div className="grid gap-5 md:grid-cols-2">
        <Card className="flex flex-col gap-4 p-6">
          <span aria-hidden="true" className="grid size-12 place-items-center rounded-2xl bg-brand-soft text-brand-deep">
            <Icon name="users" size={24} />
          </span>
          <h2 className="font-headline text-large font-extrabold text-ink">Classes</h2>
          <p className="text-body-min text-ink-muted">
            Every learner, the time they have left, and one tap to change it.
          </p>
          <ButtonLink href="/classes" arrow className="mt-auto">
            Open Classes
          </ButtonLink>
        </Card>

        <Card className="flex flex-col gap-4 p-6">
          <span aria-hidden="true" className="grid size-12 place-items-center rounded-2xl bg-sun-soft text-sun-ink">
            <Icon name="clock" size={24} />
          </span>
          <h2 className="font-headline text-large font-extrabold text-ink">Time limits</h2>
          <p className="text-body-min text-ink-muted">
            Set the day&rsquo;s allowance for a class or one learner.
          </p>
          <ButtonLink href="/coach/limits" variant="secondary" arrow className="mt-auto">
            Open Time limits
          </ButtonLink>
        </Card>
      </div>

      <Card className="flex flex-col gap-3 p-6">
        <h2 className="font-headline text-large font-extrabold text-ink">Also yours</h2>
        <p className="text-body-min text-ink-muted">
          Boards, reports and word lists, without leaving the dashboard.
        </p>
        <div className="flex flex-wrap gap-3">
          <ButtonLink href="/leaderboards" variant="ghost" size="sm">
            Boards
          </ButtonLink>
          <ButtonLink href="/coach/reports" variant="ghost" size="sm">
            Reports
          </ButtonLink>
          <ButtonLink href="/coach/content" variant="ghost" size="sm">
            Words
          </ButtonLink>
        </div>
      </Card>
    </div>
  );
}

