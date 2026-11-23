"use client";

/**
 * Class list (P1-T07).
 *
 * The API decides which classes a person may see (P1-T03): a learner gets the
 * classes they belong to, a coach gets the classes they are assigned, an admin
 * gets the school's classes. This page only renders what it is given.
 */

import { useQuery } from "@tanstack/react-query";
import Link from "next/link";

import { AppShell } from "@/components/AppShell";
import { Icon } from "@/components/icons";
import { NoAccess } from "@/components/NoAccess";
import { Alert, ButtonLink, Card, EmptyState, Loading, PageHeader } from "@/components/ui";
import { apiFetch } from "@/lib/api/client";
import { sentenceFor } from "@/lib/auth/messages";
import { useSession } from "@/lib/auth/session";
import type { ClassSummary, Role } from "@/lib/auth/types";

// Roles that attend a class. Content and moderation staff do not (P1-T01).
const CLASS_ROLES: Role[] = ["learner", "coach", "school_admin"];

export default function ClassesPage() {
  return (
    <AppShell>
      <ClassesBody />
    </AppShell>
  );
}

function ClassesBody() {
  const session = useSession();
  const isLearner = session.status === "authenticated" && session.me.user.role === "learner";

  const classes = useQuery({
    queryKey: ["classes"],
    queryFn: () => apiFetch<ClassSummary[]>("/api/classes"),
    // No point asking for a list this person can never use.
    enabled: session.status === "authenticated" && CLASS_ROLES.includes(session.me.user.role),
  });

  if (session.status === "authenticated" && !CLASS_ROLES.includes(session.me.user.role)) {
    return <NoAccess />;
  }

  return (
    <div className="flex flex-col gap-6">
      <PageHeader
        icon="users"
        title={isLearner ? "My class" : "Classes"}
        subtitle={
          isLearner ? "Everyone you play with." : "Open a class to see its learners and their time."
        }
        action={
          isLearner ? (
            <ButtonLink href="/leaderboards" variant="ghost" size="sm" icon="trophy">
              Leaderboard
            </ButtonLink>
          ) : null
        }
      />

      {classes.isPending ? <Loading /> : null}

      {classes.isError ? (
        <Alert>{sentenceFor(undefined, (classes.error as { status?: number })?.status)}</Alert>
      ) : null}

      {classes.data && classes.data.length === 0 ? (
        <Card className="p-4">
          <EmptyState icon="users" title="You are not in a class yet">
            Ask your Coach to add you.
          </EmptyState>
        </Card>
      ) : null}

      <ul className="grid gap-4 sm:grid-cols-2">
        {classes.data?.map((klass) => (
          <li key={klass.id}>
            <Link
              href={`/classes/${klass.id}`}
              className="flex min-h-[88px] items-center justify-between gap-4 rounded-2xl border-2 border-line bg-surface p-5 transition-all hover:-translate-y-0.5 hover:border-brand hover:shadow-card"
            >
              <span className="flex min-w-0 items-center gap-3">
                <span
                  aria-hidden="true"
                  className="grid size-11 shrink-0 place-items-center rounded-2xl bg-brand-soft text-brand-deep"
                >
                  <Icon name="users" size={22} />
                </span>
                <span className="truncate font-headline text-[19px] font-bold text-ink">
                  {klass.name}
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
