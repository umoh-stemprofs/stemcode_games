"use client";

/**
 * Words: the content workspace (P4-T04, P4-T05).
 *
 * Two jobs on one screen, because both start with "which word list":
 * a contributor starts a new draft, and a reviewer opens the one waiting for
 * them. The status is always written as a sentence a person would say — "Live",
 * "Waiting for a check" — never the machine word.
 */

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";

import { AppShell } from "@/components/AppShell";
import { Icon } from "@/components/icons";
import { NoAccess } from "@/components/NoAccess";
import {
  Alert,
  Button,
  Card,
  Chip,
  EmptyState,
  Loading,
  PageHeader,
} from "@/components/ui";
import { ApiError, apiFetch } from "@/lib/api/client";
import type { components } from "@/lib/api/schema";
import { sentenceFor } from "@/lib/auth/messages";
import { useSession } from "@/lib/auth/session";
import type { Role } from "@/lib/auth/types";
import { STATUS_WORDS } from "@/lib/content/words";

type PackSummary = components["schemas"]["PackSummaryOut"];
type AgeBand = { id: string; label: string };
type BandSuggestion = {
  age_band: string | null;
  label: string | null;
  learners: number;
  sentence: string | null;
};

const CONTENT_ROLES: Role[] = ["coach", "school_admin"];
const CAN_WRITE: Role[] = ["coach", "school_admin"];

export default function ContentPacksPage() {
  return (
    <AppShell>
      <ContentBody />
    </AppShell>
  );
}

function ContentBody() {
  const session = useSession();
  const router = useRouter();
  const queryClient = useQueryClient();
  const allowed =
    session.status === "authenticated" && CONTENT_ROLES.includes(session.me.user.role);
  const canWrite = session.status === "authenticated" && CAN_WRITE.includes(session.me.user.role);

  const [band, setBand] = useState("");
  const [copy, setCopy] = useState(true);

  const packs = useQuery({
    queryKey: ["content", "packs"],
    queryFn: () => apiFetch<PackSummary[]>("/api/content/packs"),
    enabled: allowed,
  });

  const bands = useQuery({
    queryKey: ["content", "bands"],
    queryFn: () => apiFetch<AgeBand[]>("/api/content/age-bands"),
    enabled: allowed,
  });

  // The band most of this coach's learners are in. The server decides it; the
  // screen only uses it as the starting value, so one tap still changes it.
  const suggestion = useQuery({
    queryKey: ["content", "suggested-band"],
    queryFn: () => apiFetch<BandSuggestion>("/api/content/suggested-band"),
    enabled: allowed && canWrite,
  });

  useEffect(() => {
    if (band === "" && suggestion.data?.age_band) setBand(suggestion.data.age_band);
  }, [band, suggestion.data]);

  const create = useMutation({
    mutationFn: async () => {
      const published = packs.data?.find(
        (pack) => pack.age_band === band && pack.status === "published",
      );
      const body = await apiFetch<{ pack: PackSummary }>("/api/content/packs", {
        method: "POST",
        body: JSON.stringify({
          age_band: band,
          copy_from: copy && published ? published.id : null,
        }),
      });
      return body.pack;
    },
    onSuccess: async (pack) => {
      await queryClient.invalidateQueries({ queryKey: ["content"] });
      router.push(`/coach/content/${pack.id}`);
    },
  });

  if (session.status === "authenticated" && !allowed) {
    return <NoAccess />;
  }

  const bandLabel = (id: string) => bands.data?.find((item) => item.id === id)?.label ?? id;

  return (
    <div className="flex flex-col gap-6">
      <PageHeader
        icon="book"
        title="Words"
        subtitle="These are the words children play with."
        action={
          <Button
            variant="ghost"
            size="sm"
            icon="refresh"
            onClick={() => void packs.refetch()}
          >
            Refresh
          </Button>
        }
      />

      {create.isError ? (
        <Alert>
          {create.error instanceof ApiError ? create.error.message : sentenceFor(undefined)}
        </Alert>
      ) : null}

      {canWrite ? (
        <Card className="flex flex-col gap-4 p-5 sm:p-6">
          <div className="flex flex-col gap-1">
            <h2 className="font-headline text-large font-extrabold text-ink">
              Start a new word list
            </h2>
            <p className="text-body-min text-ink-muted">
              Words you add are drafts. You choose, one by one, which ones children can see.
            </p>
          </div>

          <div className="grid gap-4 sm:grid-cols-2">
            <label className="flex flex-col gap-1.5 text-label font-bold text-ink-muted" htmlFor="band">
              Age group
              <select
                id="band"
                value={band}
                onChange={(event) => setBand(event.target.value)}
                className="min-h-target rounded-xl border border-line bg-surface px-3 text-body text-ink"
              >
                <option value="">Pick one</option>
                {(bands.data ?? []).map((item) => (
                  <option key={item.id} value={item.id}>
                    {item.label}
                  </option>
                ))}
              </select>
              {suggestion.data?.sentence ? (
                <span className="text-label font-normal text-ink-muted">
                  {suggestion.data.sentence} Change it any time.
                </span>
              ) : null}
            </label>

            <label className="flex min-h-target items-center gap-3 self-end rounded-xl bg-surface-muted px-4 text-body-min font-semibold text-ink">
              <input
                type="checkbox"
                checked={copy}
                onChange={(event) => setCopy(event.target.checked)}
                className="size-6 accent-[color:var(--color-brand)]"
              />
              Start with the words that are live now
            </label>
          </div>

          <Button
            disabled={!band || create.isPending}
            onClick={() => create.mutate()}
            arrow
            className="w-full sm:w-fit"
          >
            Make the list
          </Button>
        </Card>
      ) : null}

      {packs.isPending ? <Loading /> : null}

      {packs.isError ? (
        <Alert>
          {sentenceFor(
            packs.error instanceof ApiError ? packs.error.code : undefined,
            packs.error instanceof ApiError ? packs.error.status : undefined,
          )}
        </Alert>
      ) : null}

      {packs.data && packs.data.length === 0 ? (
        <Card className="p-4">
          <EmptyState icon="book" title="There are no words yet">
            Start a list above and add the first word.
          </EmptyState>
        </Card>
      ) : null}

      <ul className="flex flex-col gap-3">
        {packs.data?.map((pack) => (
          <li key={pack.id}>
            <Link
              href={`/coach/content/${pack.id}`}
              className="flex flex-col gap-2 rounded-2xl border-2 border-line bg-surface p-5 transition-all hover:-translate-y-0.5 hover:border-brand hover:shadow-card"
            >
              <span className="flex flex-wrap items-center gap-2">
                <span className="font-headline text-[19px] font-bold text-ink">
                  {bandLabel(pack.age_band)}
                </span>
                <span className="text-label font-semibold text-ink-muted">List {pack.version}</span>
                <Chip
                  tone={
                    pack.status === "published" ? "green" : pack.status === "draft" ? "neutral" : "sun"
                  }
                >
                  {STATUS_WORDS[pack.status] ?? pack.status}
                </Chip>
                <Icon name="arrow-right" size={18} className="ml-auto text-ink-muted" />
              </span>
              <span className="text-label text-ink-muted">
                {pack.live_count} live · {pack.draft_count} draft · {pack.item_count} in all
                {pack.problems > 0
                  ? ` · ${pack.problems} need${pack.problems === 1 ? "s" : ""} fixing`
                  : ""}
              </span>
            </Link>
          </li>
        ))}
      </ul>
    </div>
  );
}
