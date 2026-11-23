"use client";

/**
 * One word list: write, then make live one word at a time (P4-T04, D-38).
 *
 * The screen has one idea, repeated on every row: a word is a draft until
 * somebody presses **Make it live** on that word. Typing a word is never the
 * same act as showing it to a child, and a word that still has a problem does
 * not get the button at all.
 *
 * Your own words are yours to publish. The draft step and the checker are what
 * keep a bad word out, not a second person, so nothing here is hidden from the
 * person who wrote it.
 */

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useParams } from "next/navigation";
import { useState } from "react";

import { AppShell } from "@/components/AppShell";
import { Icon } from "@/components/icons";
import { NoAccess } from "@/components/NoAccess";
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
import { ApiError, apiFetch } from "@/lib/api/client";
import type { components } from "@/lib/api/schema";
import { useSession } from "@/lib/auth/session";
import type { Role } from "@/lib/auth/types";
import { LEVEL_WORDS, MIN_WORDS_PER_LEVEL, STATUS_WORDS } from "@/lib/content/words";

type PackDetail = components["schemas"]["PackDetailOut"];
type ImportReport = components["schemas"]["ImportReportOut"];

const CONTENT_ROLES: Role[] = ["coach", "school_admin"];

export default function PackPage() {
  return (
    <AppShell>
      <PackBody />
    </AppShell>
  );
}

function PackBody() {
  const params = useParams<{ id: string }>();
  const session = useSession();
  const queryClient = useQueryClient();
  const allowed =
    session.status === "authenticated" && CONTENT_ROLES.includes(session.me.user.role);

  const queryKey = ["content", "pack", params.id];
  const detail = useQuery({
    queryKey,
    queryFn: () => apiFetch<PackDetail>(`/api/content/packs/${params.id}`),
    enabled: allowed,
  });

  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);

  const run = useMutation({
    mutationFn: (action: () => Promise<PackDetail>) => action(),
    onSuccess: async () => {
      setError(null);
      await queryClient.invalidateQueries({ queryKey: ["content"] });
    },
    onError: (caught) => {
      setError(
        caught instanceof ApiError ? caught.message : "Something went wrong. Try again.",
      );
    },
  });

  if (session.status === "authenticated" && !allowed) {
    return <NoAccess />;
  }

  if (detail.isPending) {
    return <Loading />;
  }

  if (detail.isError || !detail.data) {
    return (
      <div className="flex flex-col gap-5">
        <PageHeader icon="book" title="That word list was not found." />
        <ButtonLink href="/coach/content" variant="ghost" icon="arrow-left" className="w-full sm:w-fit">
          All words
        </ButtonLink>
      </div>
    );
  }

  const { pack, items, can_edit } = detail.data;
  const levels = [1, 2, 3].map((level) => ({
    level,
    count: pack.per_level[level] ?? 0,
  }));
  const thin = levels.filter((row) => row.count > 0 && row.count < MIN_WORDS_PER_LEVEL);

  return (
    <div className="flex flex-col gap-6">
      <PageHeader
        icon="book"
        title={`${pack.age_band} · Version ${pack.version}`}
        subtitle={`${pack.item_count} words. ${pack.live_count} are live.`}
        action={
          <ButtonLink href="/coach/content" variant="ghost" size="sm" icon="arrow-left">
            All words
          </ButtonLink>
        }
      />

      <ul className="flex flex-wrap gap-2">
        {levels.map((row) => (
          <li key={row.level}>
            <Chip tone={row.count >= MIN_WORDS_PER_LEVEL ? "green" : "neutral"}>
              {LEVEL_WORDS[row.level]}{" "}
              {row.count >= MIN_WORDS_PER_LEVEL ? row.count : `${row.count} of ${MIN_WORDS_PER_LEVEL}`}
            </Chip>
          </li>
        ))}
      </ul>

      {thin.length > 0 ? (
        <p className="text-label text-ink-muted">
          Each level with words needs {MIN_WORDS_PER_LEVEL} before this can go live.
        </p>
      ) : null}

      {/* --------------------------------------------------------- workflow */}
      <Card className="flex flex-col gap-4 p-5 sm:p-6">
        <div className="flex flex-col gap-1">
          <h2 className="font-headline text-large font-extrabold text-ink">What happens next</h2>
          <p className="text-body-min text-ink-muted">
            A word you add is only a draft. Children cannot see it until you press
            Make it live on that word.
          </p>
        </div>

        <p className="text-body">
          {pack.live_count === 0
            ? "No word is live yet."
            : pack.live_count === 1
              ? "One word is live."
              : `${pack.live_count} words are live.`}
        </p>

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

        {can_edit ? (
          <div className="flex flex-col gap-3 sm:flex-row sm:flex-wrap">
            {pack.draft_count > 0 ? (
              <Button
                disabled={run.isPending}
                onClick={() =>
                  run.mutate(async () => {
                    const result = await apiFetch<{ published: number }>(
                      `/api/content/packs/${pack.id}/publish-ready`,
                      { method: "POST" },
                    );
                    setNotice(
                      result.published === 0
                        ? "No draft was ready. Fix the red ones first."
                        : result.published === 1
                          ? "One word is live now."
                          : `${result.published} words are live now.`,
                    );
                    return apiFetch<PackDetail>(`/api/content/packs/${pack.id}`);
                  })
                }
                icon="check"
                arrow
                className="w-full sm:w-auto"
              >
                Make the ready words live
              </Button>
            ) : null}

            <Button
              variant="ghost"
              disabled={run.isPending}
              onClick={() =>
                run.mutate(async () => {
                  const next = await apiFetch<PackDetail>("/api/content/packs", {
                    method: "POST",
                    body: JSON.stringify({ age_band: pack.age_band, copy_from: pack.id }),
                  });
                  window.location.assign(`/coach/content/${next.pack.id}`);
                  return next;
                })
              }
              icon="plus"
              className="w-full sm:w-auto"
            >
              Start a new word list
            </Button>

            {pack.live_count > 0 ? (
              <Button
                variant="ghost"
                size="sm"
                disabled={run.isPending}
                onClick={() =>
                  run.mutate(() =>
                    apiFetch<PackDetail>(`/api/content/packs/${pack.id}/retire`, {
                      method: "POST",
                    }),
                  )
                }
                className="w-full sm:w-auto"
              >
                Close this list
              </Button>
            ) : null}
          </div>
        ) : null}

        {!can_edit ? (
          <p className="text-body-min text-ink-muted">
            This list is closed. Nothing in it is played any more.
          </p>
        ) : null}
      </Card>

      {/* ------------------------------------------------------------- words */}
      <section className="flex flex-col gap-3">
        <h2 className="font-headline text-large font-extrabold text-ink">The words</h2>

        {items.length === 0 ? (
          <Card className="p-4">
            <EmptyState icon="book" title="There are no words in this version yet">
              Add the first one below.
            </EmptyState>
          </Card>
        ) : null}

        <ul className="flex flex-col gap-2.5">
          {items.map((item) => (
            <li key={item.id}>
              <Card className="flex flex-col gap-2 p-4 sm:p-5">
                <span className="flex flex-wrap items-center gap-2">
                  <span className="tabular font-headline text-body-min font-extrabold uppercase tracking-wide text-ink">
                    {item.scrambled}
                  </span>
                  <Icon name="arrow-right" size={16} className="text-ink-muted" />
                  <span className="text-body font-semibold text-ink">{item.answer}</span>
                  <Chip className="ml-auto">{LEVEL_WORDS[item.difficulty] ?? item.difficulty}</Chip>
                </span>

                <span className="text-body-min text-ink-muted">{item.clue ?? "No clue"}</span>

                <span className="flex flex-wrap items-center gap-2">
                  <Chip tone={item.status === "live" ? "green" : item.status === "draft" ? "neutral" : "sun"}>
                    {STATUS_WORDS[item.status] ?? item.status}
                  </Chip>
                  {item.problems.length > 0 ? (
                    <span className="text-label font-semibold text-danger">{item.problems[0]}</span>
                  ) : null}
                </span>

                {can_edit ? (
                  <div className="mt-1 flex flex-wrap gap-2">
                    {item.status !== "live" && item.problems.length === 0 ? (
                      <Button
                        size="sm"
                        disabled={run.isPending}
                        onClick={() =>
                          run.mutate(async () => {
                            await apiFetch(
                              `/api/content/packs/${pack.id}/items/${item.id}/publish`,
                              { method: "POST" },
                            );
                            setNotice(`${item.answer} is live.`);
                            return apiFetch<PackDetail>(`/api/content/packs/${pack.id}`);
                          })
                        }
                        icon="check"
                      >
                        Make it live
                      </Button>
                    ) : null}

                    {item.status === "live" ? (
                      <Button
                        variant="ghost"
                        size="sm"
                        disabled={run.isPending}
                        onClick={() =>
                          run.mutate(async () => {
                            await apiFetch(
                              `/api/content/packs/${pack.id}/items/${item.id}/unpublish`,
                              { method: "POST" },
                            );
                            setNotice(`${item.answer} is out of the games.`);
                            return apiFetch<PackDetail>(`/api/content/packs/${pack.id}`);
                          })
                        }
                        icon="eye-off"
                      >
                        Take it down
                      </Button>
                    ) : null}

                    {item.status === "draft" ? (
                      <Button
                        variant="ghost"
                        size="sm"
                        disabled={run.isPending}
                        onClick={() =>
                          run.mutate(async () => {
                            await apiFetch(`/api/content/packs/${pack.id}/items/${item.id}`, {
                              method: "DELETE",
                            });
                            setNotice("Word removed.");
                            return apiFetch<PackDetail>(`/api/content/packs/${pack.id}`);
                          })
                        }
                        icon="trash"
                      >
                        Remove
                      </Button>
                    ) : null}
                  </div>
                ) : null}
              </Card>
            </li>
          ))}
        </ul>
      </section>

      {can_edit ? (
        <AddWord
          packId={pack.id}
          pending={run.isPending}
          onDone={(message) => {
            setNotice(message);
            // A new word that worked must not sit under an old complaint.
            setError(null);
            void queryClient.invalidateQueries({ queryKey: ["content"] });
          }}
          onError={setError}
        />
      ) : null}

      <ButtonLink href="/coach/content" variant="quiet" size="sm" icon="arrow-left" className="w-fit">
        All words
      </ButtonLink>
    </div>
  );
}

function AddWord({
  packId,
  pending,
  onDone,
  onError,
}: {
  packId: string;
  pending: boolean;
  onDone: (message: string) => void;
  onError: (message: string) => void;
}) {
  const queryClient = useQueryClient();
  const [answer, setAnswer] = useState("");
  const [clue, setClue] = useState("");
  const [level, setLevel] = useState(1);
  const [csv, setCsv] = useState("");
  const [report, setReport] = useState<ImportReport | null>(null);

  const add = useMutation({
    mutationFn: () =>
      apiFetch(`/api/content/packs/${packId}/items`, {
        method: "POST",
        body: JSON.stringify({ answer, clue, difficulty: level }),
      }),
    onSuccess: async () => {
      setAnswer("");
      setClue("");
      onDone("Word added.");
      await queryClient.invalidateQueries({ queryKey: ["content"] });
    },
    onError: (caught) => {
      const problems =
        caught instanceof ApiError
          ? ((caught.details as { problems?: string[] } | undefined)?.problems ?? [])
          : [];
      onError(problems.length > 0 ? problems.join(" ") : "That word could not be added.");
    },
  });

  const importCsv = useMutation({
    mutationFn: () =>
      apiFetch<ImportReport>(`/api/content/packs/${packId}/import`, {
        method: "POST",
        body: JSON.stringify({ text: csv }),
      }),
    onSuccess: async (result) => {
      setReport(result);
      setCsv("");
      await queryClient.invalidateQueries({ queryKey: ["content"] });
    },
    onError: () => onError("That list could not be read."),
  });

  const bad = report?.rows.filter((row) => !row.ok) ?? [];

  return (
    <Card className="flex flex-col gap-4 p-5 sm:p-6">
      <h2 className="flex items-center gap-2 font-headline text-large font-extrabold text-ink">
        <Icon name="plus" size={22} className="text-brand" />
        Add a word
      </h2>

      <div className="grid gap-4 sm:grid-cols-2">
        <label className="flex flex-col gap-1.5 text-label font-bold text-ink-muted" htmlFor="answer">
          The word
          <input
            id="answer"
            value={answer}
            onChange={(event) => setAnswer(event.target.value)}
            autoCapitalize="none"
            maxLength={12}
            className="min-h-target rounded-xl border border-line bg-surface px-3 text-body text-ink"
          />
        </label>

        <label className="flex flex-col gap-1.5 text-label font-bold text-ink-muted" htmlFor="clue">
          The clue
          <input
            id="clue"
            value={clue}
            onChange={(event) => setClue(event.target.value)}
            maxLength={200}
            className="min-h-target rounded-xl border border-line bg-surface px-3 text-body text-ink"
          />
        </label>

        <label className="flex flex-col gap-1.5 text-label font-bold text-ink-muted" htmlFor="level">
          Level
          <select
            id="level"
            value={level}
            onChange={(event) => setLevel(Number(event.target.value))}
            className="min-h-target rounded-xl border border-line bg-surface px-3 text-body text-ink"
          >
            {[1, 2, 3].map((value) => (
              <option key={value} value={value}>
                {LEVEL_WORDS[value]}
              </option>
            ))}
          </select>
        </label>
      </div>

      <Button
        disabled={pending || add.isPending || answer.trim().length === 0}
        onClick={() => add.mutate()}
        icon="plus"
        className="w-full sm:w-fit"
      >
        Add it
      </Button>

      <details className="rounded-2xl bg-surface-muted px-4 py-3">
        <summary className="flex min-h-target cursor-pointer items-center font-headline text-body-min font-bold text-ink">
          Add many words at once
        </summary>
        <div className="flex flex-col gap-3 pt-3">
          <p className="text-label text-ink-muted">
            One word on each line: the word, a comma, the clue, a comma, the level.
          </p>
          <textarea
            value={csv}
            onChange={(event) => setCsv(event.target.value)}
            rows={5}
            className="rounded-xl border border-line bg-surface p-3 font-mono text-body-min text-ink"
            placeholder={"apple, A red or green fruit, 1\nkite, It flies on a string, 2"}
          />
          <Button
            variant="ghost"
            disabled={pending || importCsv.isPending || csv.trim().length === 0}
            onClick={() => importCsv.mutate()}
            className="w-full sm:w-fit"
          >
            Add these words
          </Button>

          {report ? (
            <div className="flex flex-col gap-2">
              <p className="text-body-min font-bold text-ink">{report.added} added.</p>
              {bad.length > 0 ? (
                <ul className="flex flex-col gap-1 text-label font-semibold text-danger">
                  {bad.map((row) => (
                    <li key={row.line}>
                      Line {row.line}: {row.message}
                    </li>
                  ))}
                </ul>
              ) : null}
            </div>
          ) : null}
        </div>
      </details>
    </Card>
  );
}
