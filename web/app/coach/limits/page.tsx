"use client";

/**
 * Time limits: pick a class (P3-T10).
 *
 * One decision per screen, as Appendix D asks: this page asks *which class*,
 * and the next page asks *what to change*. A coach only ever sees the classes
 * the API lets them see, so a class from another school is not in the list.
 */

import { useQuery } from "@tanstack/react-query";
import Link from "next/link";

import { AppShell } from "@/components/AppShell";
import { Icon } from "@/components/icons";
import { NoAccess } from "@/components/NoAccess";
import { Alert, ButtonLink, Card, EmptyState, Loading, PageHeader } from "@/components/ui";
import { ApiError, apiFetch } from "@/lib/api/client";
import { sentenceFor } from "@/lib/auth/messages";
import { useSession } from "@/lib/auth/session";
import type { ClassSummary, Role } from "@/lib/auth/types";

const STAFF: Role[] = ["coach", "school_admin"];

export default function CoachLimitsPage() {
  return (
    <AppShell>
      <CoachLimitsBody />
    </AppShell>
  );
}

function CoachLimitsBody() {
  const session = useSession();
  const allowed = session.status === "authenticated" && STAFF.includes(session.me.user.role);

  const classes = useQuery({
    queryKey: ["classes"],
    queryFn: () => apiFetch<ClassSummary[]>("/api/classes"),
    enabled: allowed,
  });

  if (session.status === "authenticated" && !allowed) {
    return <NoAccess />;
  }

  return (
    <div className="flex flex-col gap-6">
      <PageHeader
        icon="clock"
        title="Time limits"
        subtitle="Pick a class to see its time."
        action={
          <ButtonLink href="/coach/xp" variant="ghost" size="sm" icon="chart">
            Class XP
          </ButtonLink>
        }
      />

      {classes.isPending ? <Loading /> : null}

      {classes.isError ? (
        <Alert>
          {sentenceFor(
            classes.error instanceof ApiError ? classes.error.code : undefined,
            classes.error instanceof ApiError ? classes.error.status : undefined,
          )}
        </Alert>
      ) : null}

      {classes.data && classes.data.length === 0 ? (
        <Card className="p-4">
          <EmptyState icon="users" title="You have no classes yet">
            An admin adds classes and assigns you to one.
          </EmptyState>
        </Card>
      ) : null}

      <ul className="grid gap-4 sm:grid-cols-2">
        {classes.data?.map((klass) => (
          <li key={klass.id}>
            <Link
              href={`/coach/limits/${klass.id}`}
              className="flex min-h-[88px] items-center justify-between gap-4 rounded-2xl border-2 border-line bg-surface p-5 transition-all hover:-translate-y-0.5 hover:border-brand hover:shadow-card"
            >
              <span className="flex min-w-0 items-center gap-3">
                <span
                  aria-hidden="true"
                  className="grid size-11 shrink-0 place-items-center rounded-2xl bg-brand-soft text-brand-deep"
                >
                  <Icon name="clock" size={22} />
                </span>
                <span className="flex min-w-0 flex-col">
                  <span className="truncate font-headline text-[19px] font-bold text-ink">
                    {klass.name}
                  </span>
                  <span className="text-label text-ink-muted">Time and pauses</span>
                </span>
              </span>
              <Icon name="arrow-right" size={20} className="shrink-0 text-ink-muted" />
            </Link>
          </li>
        ))}
      </ul>
    </div>
  );
}
