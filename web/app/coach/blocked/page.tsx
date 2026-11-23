"use client";

/**
 * Blocked words: the safe-language list a school admin controls (P4-T03).
 *
 * Two halves, shown as one list, because the question a person actually asks is
 * "why was my word refused?" — and the answer must be findable here rather than
 * being "it is somewhere in the code".
 *
 * - **Built in**: ships with the app, the same on every machine, not removable
 *   from here. A list nobody can empty by accident is the point.
 * - **Added here**: a school's own word, effective immediately, removable.
 *
 * Plain language throughout: no status codes, one decision per screen, and the
 * add button says what it does.
 */

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";

import { AppShell } from "@/components/AppShell";
import { Icon } from "@/components/icons";
import { NoAccess } from "@/components/NoAccess";
import { Alert, Button, Card, Chip, EmptyState, Loading, PageHeader } from "@/components/ui";
import { ApiError, apiFetch } from "@/lib/api/client";
import type { components } from "@/lib/api/schema";
import { useSession } from "@/lib/auth/session";
import type { Role } from "@/lib/auth/types";

type BlockedWord = components["schemas"]["BlockedWordOut"];

const ADMIN_ONLY: Role[] = ["school_admin"];

export default function BlockedWordsPage() {
  return (
    <AppShell>
      <BlockedBody />
    </AppShell>
  );
}

function BlockedBody() {
  const session = useSession();
  const queryClient = useQueryClient();
  const allowed = session.status === "authenticated" && ADMIN_ONLY.includes(session.me.user.role);

  const [word, setWord] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);

  const list = useQuery({
    queryKey: ["blocked-words"],
    queryFn: () => apiFetch<BlockedWord[]>("/api/content/blocked-words"),
    enabled: allowed,
  });

  const refresh = async () => {
    await queryClient.invalidateQueries({ queryKey: ["blocked-words"] });
    await queryClient.invalidateQueries({ queryKey: ["content"] });
  };

  const add = useMutation({
    mutationFn: () =>
      apiFetch<BlockedWord>("/api/content/blocked-words", {
        method: "POST",
        body: JSON.stringify({ word }),
      }),
    onSuccess: async (row) => {
      setWord("");
      setError(null);
      setNotice(`"${row.word}" is blocked now.`);
      await refresh();
    },
    onError: (caught) => {
      setNotice(null);
      setError(caught instanceof ApiError ? caught.message : "That word could not be added.");
    },
  });

  const remove = useMutation({
    mutationFn: (target: string) =>
      apiFetch<null>(`/api/content/blocked-words/${encodeURIComponent(target)}`, {
        method: "DELETE",
      }),
    onSuccess: async () => {
      setError(null);
      setNotice("Word removed.");
      await refresh();
    },
    onError: (caught) => {
      setNotice(null);
      setError(caught instanceof ApiError ? caught.message : "That word could not be removed.");
    },
  });

  if (session.status === "authenticated" && !allowed) {
    return <NoAccess />;
  }

  const added = list.data?.filter((row) => !row.built_in) ?? [];
  const builtIn = list.data?.filter((row) => row.built_in) ?? [];
  const busy = add.isPending || remove.isPending;

  return (
    <div className="flex flex-col gap-6">
      <PageHeader
        icon="shield"
        title="Blocked words"
        subtitle="A word here can never be used, in a word or in a clue."
      />

      <Card className="flex flex-col gap-4 p-5 sm:p-6">
        <h2 className="font-headline text-large font-extrabold text-ink">Add a word</h2>
        <label className="flex flex-col gap-1.5 text-label font-bold text-ink-muted" htmlFor="blocked-word">
          The word
          <input
            id="blocked-word"
            value={word}
            onChange={(event) => setWord(event.target.value)}
            autoCapitalize="none"
            maxLength={40}
            className="min-h-target rounded-xl border border-line bg-surface px-3 text-body text-ink"
          />
        </label>
        <p className="text-label text-ink-muted">It starts working straight away. Nothing to install.</p>

        <Button
          disabled={busy || word.trim().length === 0}
          onClick={() => add.mutate()}
          icon="plus"
          className="w-full sm:w-fit"
        >
          Block this word
        </Button>

        {notice ? (
          <p
            role="status"
            className="flex items-center gap-2 rounded-2xl bg-ok-soft px-4 py-3 text-body-min font-semibold text-ok"
          >
            <Icon name="check" size={18} />
            {notice}
          </p>
        ) : null}
        {error ? <Alert>{error}</Alert> : null}
      </Card>

      {list.isPending ? <Loading /> : null}

      {list.isError ? <Alert>The list could not be read. Try again.</Alert> : null}

      <section className="flex flex-col gap-3">
        <h2 className="font-headline text-large font-extrabold text-ink">Words you added</h2>

        {added.length === 0 ? (
          <Card className="p-4">
            <EmptyState icon="shield" title="You have not added any words yet">
              Add one above and it is blocked immediately.
            </EmptyState>
          </Card>
        ) : (
          <ul className="flex flex-col gap-2">
            {added.map((row) => (
              <li
                key={row.word}
                className="flex flex-wrap items-center gap-3 rounded-2xl border border-line bg-surface px-4 py-3"
              >
                <span className="font-headline text-[19px] font-bold text-ink">{row.word}</span>
                <Button
                  variant="ghost"
                  size="sm"
                  disabled={busy}
                  onClick={() => remove.mutate(row.word)}
                  icon="trash"
                  className="ml-auto"
                >
                  Remove
                </Button>
              </li>
            ))}
          </ul>
        )}
      </section>

      {/* Collapsed on purpose: an admin comes here to look up one word, not to
          read a wall of slurs. The count says the list is real and big. */}
      <details className="rounded-2xl border border-line bg-surface p-5">
        <summary className="flex min-h-target cursor-pointer items-center font-headline text-body-min font-bold text-ink">
          Words that come with the app ({builtIn.length})
        </summary>
        <p className="pt-3 text-body-min text-ink-muted">
          These cannot be removed. They keep every school safe the same way.
        </p>
        <ul className="flex flex-wrap gap-2 pt-3">
          {builtIn.map((row) => (
            <li key={row.word}>
              <Chip>{row.word}</Chip>
            </li>
          ))}
        </ul>
      </details>
    </div>
  );
}
