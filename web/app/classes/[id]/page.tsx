"use client";

/**
 * Class roster (P1-T05, P1-T07).
 *
 * The roster is the same endpoint for everyone, but it only ever carries
 * `preferred_name` and `avatar_key` — a learner cannot receive a classmate's
 * real name even by asking this page for it.
 *
 * A class in another school, or one this person may not see, comes back as a
 * 404 from the API. That is rendered as the same friendly sentence as a 403:
 * the page must not tell a child which of the two happened.
 */

import { useQuery } from "@tanstack/react-query";
import { useParams, useRouter } from "next/navigation";
import { useEffect } from "react";

import { AppShell } from "@/components/AppShell";
import { Alert, ButtonLink, Card, Loading, PageHeader } from "@/components/ui";
import { ApiError, apiFetch } from "@/lib/api/client";
import { sentenceFor } from "@/lib/auth/messages";
import type { ClassMembers } from "@/lib/auth/types";
import { avatarEmoji, avatarLabel } from "@/lib/avatars";

export default function ClassPage() {
  return (
    <AppShell>
      <ClassBody />
    </AppShell>
  );
}

function ClassBody() {
  const params = useParams<{ id: string }>();
  const classId = params.id;
  const router = useRouter();

  const roster = useQuery({
    queryKey: ["class", classId, "members"],
    queryFn: () => apiFetch<ClassMembers>(`/api/classes/${classId}/members`),
  });

  // A 403 means "this exists, but not for you" — that has a page. A 404 could
  // be either missing or hidden, so it stays on this screen as one sentence.
  const forbidden = roster.error instanceof ApiError && roster.error.status === 403;
  useEffect(() => {
    if (forbidden) router.replace("/no-access");
  }, [forbidden, router]);

  if (roster.isPending || forbidden) {
    return <Loading />;
  }

  if (roster.isError) {
    const error = roster.error;
    const status = error instanceof ApiError ? error.status : undefined;
    const code = error instanceof ApiError ? error.code : undefined;

    return (
      <div className="flex flex-col gap-4">
        <Alert>{sentenceFor(code, status)}</Alert>
        <ButtonLink href="/classes" variant="ghost" icon="arrow-left" className="w-full sm:w-fit">
          Go back
        </ButtonLink>
      </div>
    );
  }

  const { class: klass, members } = roster.data;

  return (
    <div className="flex flex-col gap-6">
      <PageHeader
        icon="users"
        title={klass.name}
        subtitle={
          members.length === 1 ? "There is 1 person here." : `There are ${members.length} people here.`
        }
        action={
          <ButtonLink href="/classes" variant="ghost" size="sm" icon="arrow-left">
            All classes
          </ButtonLink>
        }
      />

      <ul className="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-4">
        {members.map((member) => (
          <li
            key={member.id}
            className="flex flex-col items-center gap-2 rounded-2xl border border-line bg-surface p-4 text-center shadow-card"
          >
            <span
              aria-hidden="true"
              className="grid size-16 place-items-center rounded-full bg-canvas text-[34px] ring-2 ring-line"
            >
              {avatarEmoji(member.avatar_key)}
            </span>
            <span className="text-body-min font-bold text-ink">{member.preferred_name}</span>
            <span className="sr-only">{avatarLabel(member.avatar_key)}</span>
          </li>
        ))}
      </ul>

      <Card className="flex flex-wrap items-center justify-between gap-3 p-5">
        <p className="text-body-min text-ink-muted">
          Want to beat your classmates? The board is one tap away.
        </p>
        <ButtonLink href="/leaderboards" variant="ghost" size="sm" icon="trophy">
          See the leaderboard
        </ButtonLink>
      </Card>
    </div>
  );
}
