"use client";

/**
 * Me (engagement): streak, level, quest, badges and bests.
 *
 * This is the page the header avatar opens. It exists so the three-tab menu can
 * stay three tabs: everything personal lives here, one tap from every screen.
 *
 * Every number on this page is read from `/api/me/engagement`; the level is a
 * presentational restatement of Profile XP and nothing in the product reads it
 * to decide anything (P5-T05).
 */

import Link from "next/link";

import { AppShell } from "@/components/AppShell";
import {
  BadgeGrid,
  QuestCard,
  StreakCapsule,
  streakNudge,
  useEngagement,
} from "@/components/Engagement";
import { NoAccess } from "@/components/NoAccess";
import { Card, Chip, Loading, Progress } from "@/components/ui";
import { avatarEmoji } from "@/lib/avatars";
import { useSession } from "@/lib/auth/session";

export default function MePage() {
  return (
    <AppShell>
      <MeBody />
    </AppShell>
  );
}

function MeBody() {
  const session = useSession();
  const engagement = useEngagement(session.status === "authenticated");

  if (session.status !== "authenticated") return null;
  if (session.me.user.role !== "learner") return <NoAccess />;

  const { me } = session;
  const user = me.user;

  if (!engagement.data) {
    return (
      <div className="flex flex-col gap-4">
        <h1 className="font-headline text-heading font-extrabold tracking-tight text-ink">Me</h1>
        {engagement.isError ? (
          <p className="text-body text-ink-muted">That did not load. Try again.</p>
        ) : (
          <Loading />
        )}
      </div>
    );
  }

  const data = engagement.data;
  const { streak, level, quest, badges, bests } = data;
  const earned = badges.filter((badge) => badge.earned_on !== null);
  const nextBadge = badges.find((badge) => badge.earned_on === null) ?? null;

  return (
    <div className="flex flex-col gap-6">
      <section className="flex flex-col gap-5 rounded-3xl border border-line bg-surface p-6 shadow-card sm:p-8 md:flex-row md:items-center md:gap-8">
        <span
          aria-hidden="true"
          className="grid size-20 shrink-0 place-items-center rounded-3xl bg-surface-muted text-[42px] ring-2 ring-line"
        >
          {avatarEmoji(user.avatar_key)}
        </span>

        <div className="flex min-w-0 flex-1 flex-col gap-2">
          <h1 className="font-headline text-[clamp(26px,4.5vw,36px)] font-extrabold leading-tight tracking-tight text-ink">
            {user.preferred_name}
          </h1>
          <p className="text-body text-ink-muted">{streakNudge(streak)}</p>

          <div className="mt-1 flex flex-wrap items-center gap-2">
            <Chip tone="blue">Level {level.number}</Chip>
            <Chip tone="neutral">{level.profile_xp} XP in all</Chip>
            <Chip tone="neutral">
              {earned.length} {earned.length === 1 ? "badge" : "badges"}
            </Chip>
          </div>
        </div>

        <StreakCapsule streak={streak} />
      </section>

      <Card className="flex flex-col gap-3 p-5 sm:p-6">
        <div className="flex flex-wrap items-baseline justify-between gap-2">
          <h2 className="font-headline text-large font-extrabold tracking-tight text-ink">
            Level {level.number}
          </h2>
          <span className="tabular text-label font-bold text-ink-muted">
            {level.xp_into} of {level.xp_span} XP
          </span>
        </div>
        <Progress
          value={Math.round((level.xp_into / level.xp_span) * 100)}
          label={`Level ${level.number} progress`}
          className="h-3 bg-surface-sunk"
        />
        <p className="text-body-min text-ink-muted">
          {level.xp_to_next} XP to level {level.number + 1}.
          {streak.longest > 1 ? ` Longest streak: ${streak.longest} days.` : ""}
        </p>
      </Card>

      <QuestCard quest={quest} />

      <section className="flex flex-col gap-3">
        <div className="flex flex-wrap items-end justify-between gap-2 px-1">
          <h2 className="font-headline text-large font-extrabold tracking-tight text-ink">
            Badges
          </h2>
          {nextBadge ? (
            <Link
              href="/games"
              className="text-label font-bold text-brand hover:text-brand-deep"
            >
              Next: {nextBadge.title}
            </Link>
          ) : null}
        </div>
        <BadgeGrid badges={badges} />
      </section>

      <section className="flex flex-col gap-3">
        <h2 className="px-1 font-headline text-large font-extrabold tracking-tight text-ink">
          Your bests
        </h2>

        {bests.length === 0 ? (
          <Card className="p-5">
            <p className="text-body text-ink-muted">
              Play a game and your best score lands here.
            </p>
          </Card>
        ) : (
          <Card className="flex flex-col gap-2.5 p-4 sm:p-5">
            <ul className="flex flex-col gap-2.5">
              {bests.map((best) => (
                <li
                  key={best.game_id}
                  className="flex flex-wrap items-center justify-between gap-2 rounded-2xl bg-surface-muted px-4 py-3"
                >
                  <span className="font-headline text-body-min font-extrabold text-ink">
                    {best.name}
                  </span>
                  <span className="text-body-min text-ink">
                    <span aria-hidden="true">🏅</span> {best.value}
                  </span>
                  <span className="text-label text-ink-muted">
                    {best.played} {best.played === 1 ? "game" : "games"} played
                  </span>
                </li>
              ))}
            </ul>
          </Card>
        )}
      </section>
    </div>
  );
}
