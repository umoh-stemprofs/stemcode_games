"use client";

/**
 * "No access" page (P1-T07).
 *
 * A real destination, not an error screen: pages that reach a definite 403, or
 * that a role has no business opening at all, send people here. The content
 * itself lives in `components/NoAccess.tsx` so it can also render inline.
 */

import { AppShell } from "@/components/AppShell";
import { NoAccess } from "@/components/NoAccess";

export default function NoAccessPage() {
  return (
    <AppShell>
      <NoAccess />
    </AppShell>
  );
}
