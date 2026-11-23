"use client";

/**
 * Reports, for the school admin (P7-T09).
 *
 * A minimal list on purpose: the plan leaves the workflow to Phase 10, and what
 * a person needs today is "who was reported, by whom, and why" — in one line
 * per report, with the reason already a sentence. No raw codes, no counts to
 * act on, nothing to configure.
 *
 * The API decides who may read this; the role check here only hides the link.
 */

import { useQuery } from "@tanstack/react-query";

import { AppShell } from "@/components/AppShell";
import { Icon } from "@/components/icons";
import { NoAccess } from "@/components/NoAccess";
import { Alert, Card, EmptyState, Loading, PageHeader } from "@/components/ui";
import { apiFetch } from "@/lib/api/client";
import { useSession } from "@/lib/auth/session";
import type { Role } from "@/lib/auth/types";
import type { AdminReport } from "@/lib/games/social";

const ADMIN_ONLY: Role[] = ["school_admin"];

export default function ReportsPage() {
  return (
    <AppShell>
      <ReportsBody />
    </AppShell>
  );
}

function ReportsBody() {
  const session = useSession();
  const allowed = session.status === "authenticated" && ADMIN_ONLY.includes(session.me.user.role);

  const reports = useQuery({
    queryKey: ["reports"],
    queryFn: () => apiFetch<AdminReport[]>("/api/games/reports"),
    enabled: allowed,
  });

  if (session.status === "authenticated" && !allowed) {
    return <NoAccess />;
  }

  return (
    <div className="flex flex-col gap-6">
      <PageHeader
        icon="flag"
        title="Reports"
        subtitle="Learners can report a classmate after a game."
      />

      {reports.isPending ? <Loading /> : null}

      {reports.isError ? <Alert>The list could not be read. Try again.</Alert> : null}

      {reports.data && reports.data.length === 0 ? (
        <Card className="p-4">
          <EmptyState icon="shield" title="Nobody has reported anything">
            A quiet week is a good week.
          </EmptyState>
        </Card>
      ) : null}

      <ul className="flex flex-col gap-3">
        {reports.data?.map((row) => (
          <li key={row.id}>
            <Card className="flex flex-col gap-1.5 p-5">
              <p className="flex items-center gap-2 font-headline text-body-min font-extrabold text-ink">
                <Icon name="flag" size={18} className="text-danger" />
                {row.reported_name}
              </p>
              <p className="text-body">{row.reason_sentence}</p>
              <p className="text-label text-ink-muted">Reported by {row.reporter_name}.</p>
              {row.note ? <p className="text-label text-ink-muted">{row.note}</p> : null}
            </Card>
          </li>
        ))}
      </ul>
    </div>
  );
}
