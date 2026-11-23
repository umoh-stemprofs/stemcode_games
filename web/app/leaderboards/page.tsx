"use client";

/**
 * The boards (P5-T10, P5-T11).
 *
 * One screen, one decision: which board to look at. Tabs the school cannot have
 * are **hidden, not disabled** — a school with no term dates has no "This term"
 * tab until an admin adds them, and a learner never sees "All time" at all
 * (D-35). Identity is masked everywhere: avatar and preferred name only.
 *
 * The top three get the podium because a rank you can see is the reason to play
 * one more game; everyone below gets a plain row so the list still reads quickly.
 */

import { useQuery } from "@tanstack/react-query";
import { useEffect, useMemo, useState } from "react";

import { AppShell } from "@/components/AppShell";
import { Icon } from "@/components/icons";
import {
  Alert,
  Button,
  Card,
  Chip,
  EmptyState,
  Loading,
  PageHeader,
  cx,
} from "@/components/ui";
import { ApiError, apiFetch } from "@/lib/api/client";
import { avatarEmoji } from "@/lib/avatars";
import { sentenceFor } from "@/lib/auth/messages";
import { useSession } from "@/lib/auth/session";
import type { ClassSummary } from "@/lib/auth/types";
import type { Board, BoardPeriod, SchoolTerm } from "@/lib/games/board-types";
import { PERIOD_WORDS } from "@/lib/games/board-types";

type GameSummary = {
  id: string;
  name: string;
  summary: string;
  is_live: boolean;
};

const LEARNER_PERIODS: BoardPeriod[] = ["daily", "weekly", "termly"];
const MEDALS = ["🥇", "🥈", "🥉"];

export default function LeaderboardsPage() {
  return (
    <AppShell>
      <BoardBody />
    </AppShell>
  );
}

function BoardBody() {
  const session = useSession();
  const role = session.status === "authenticated" ? session.me.user.role : null;
  const isAdmin = role === "school_admin";
  const isStaff = role === "coach" || isAdmin;
  // Keeps the "ends in" line current while the page stays open.
  useMinuteTick();

  const periods = useMemo<BoardPeriod[]>(
    () => (isAdmin ? [...LEARNER_PERIODS, "all_time"] : LEARNER_PERIODS),
    [isAdmin],
  );

  const [period, setPeriod] = useState<BoardPeriod>("daily");
  const [game, setGame] = useState("");
  const [classId, setClassId] = useState("");

  const games = useQuery({
    queryKey: ["catalog"],
    queryFn: () => apiFetch<GameSummary[]>("/api/games/catalog"),
    enabled: role !== null,
  });

  const classes = useQuery({
    queryKey: ["classes"],
    queryFn: () => apiFetch<ClassSummary[]>("/api/classes"),
    enabled: isStaff,
  });

  const query = new URLSearchParams();
  if (game) query.set("game", game);
  if (classId) query.set("class_id", classId);
  const suffix = query.toString() ? `?${query.toString()}` : "";

  const board = useQuery({
    queryKey: ["board", period, game, classId],
    queryFn: () => apiFetch<Board>(`/api/leaderboards/${period}${suffix}`),
    enabled: role !== null,
    // A hidden board answers 404; that is a state, not a failure to retry.
    retry: false,
  });

  const hidden = board.error instanceof ApiError && board.error.status === 404;
  const noCalendar = hidden && period === "termly";

  return (
    <div className="flex flex-col gap-8">
      <PageHeader
        icon="trophy"
        title="Classroom leaderboard"
        subtitle={
          board.data && !board.data.ends_at
            ? "This board never ends."
            : undefined
        }
        action={
          board.data ? (
            <p className="rounded-xl border border-line bg-surface px-3.5 py-2 text-label font-bold text-ink-muted">
              {resetSentence(board.data.ends_at)}
            </p>
          ) : isStaff ? null : (
            <Button
              variant="ghost"
              size="sm"
              onClick={() => void board.refetch()}
              icon="refresh"
            >
              Refresh
            </Button>
          )
        }
      />

      <div className="flex flex-wrap items-center gap-2">
        {periods
          // Do not offer a tab that answers 404 for this school.
          .filter((item) => !(item === "termly" && noCalendar))
          .map((item) => (
            <button
              key={item}
              type="button"
              aria-pressed={period === item}
              onClick={() => setPeriod(item)}
              className={cx(
                "min-h-[44px] rounded-xl border px-4 font-headline text-label font-bold transition-colors",
                period === item
                  ? "border-brand-soft bg-brand-soft text-brand-deep"
                  : "border-line bg-surface text-ink-muted hover:bg-surface-muted hover:text-ink",
              )}
            >
              {PERIOD_WORDS[item]}
            </button>
          ))}
      </div>

      {/* The near miss, said once and plainly: who is next, and by how much. */}
      {board.data?.chase ? (
        <p className="flex items-center gap-2 rounded-xl border border-sun bg-sun-soft px-4 py-3 text-body-min font-semibold text-sun-ink">
          <span aria-hidden="true">🔎</span>
          {board.data.chase.xp_gap} XP to pass {board.data.chase.preferred_name}
          .
        </p>
      ) : null}
      {board.data && board.data.entries.length > 0 && board.data.to_join ? (
        <p className="rounded-xl border border-line bg-surface px-4 py-3 text-body-min text-ink-muted">
          Play {board.data.to_join} more{" "}
          {board.data.to_join === 1 ? "game" : "games"} to join this board.
        </p>
      ) : null}

      {isStaff ? (
        <div className="flex flex-col gap-3 sm:flex-row">
          <label className="flex flex-1 flex-col gap-1 text-label font-bold text-ink-muted">
            Game
            <select
              value={game}
              onChange={(event) => setGame(event.target.value)}
              className="min-h-target rounded-xl border border-line bg-surface px-3 text-body text-ink"
            >
              <option value="">All games</option>
              {(games.data ?? []).map((item) => (
                <option key={item.id} value={item.id}>
                  {item.name}
                </option>
              ))}
            </select>
          </label>

          <label className="flex flex-1 flex-col gap-1 text-label font-bold text-ink-muted">
            Class
            <select
              value={classId}
              onChange={(event) => setClassId(event.target.value)}
              className="min-h-target rounded-xl border border-line bg-surface px-3 text-body text-ink"
            >
              <option value="">Whole school</option>
              {(classes.data ?? []).map((item) => (
                <option key={item.id} value={item.id}>
                  {item.name}
                </option>
              ))}
            </select>
          </label>
        </div>
      ) : null}

      {board.isPending ? <Loading /> : null}

      {board.isError ? (
        <Alert>
          {noCalendar
            ? "This school has no term dates yet."
            : sentenceFor(
                board.error instanceof ApiError ? board.error.code : undefined,
                board.error instanceof ApiError
                  ? board.error.status
                  : undefined,
              )}
        </Alert>
      ) : null}

      {noCalendar && isAdmin ? <TermForm /> : null}

      {board.data ? (
        <BoardTable board={board.data} isLearner={role === "learner"} />
      ) : null}
    </div>
  );
}

/**
 * How long this board has left (P5-T10).
 *
 * The boundary is the server's, in school-local time; the browser only renders
 * the difference between two absolute instants, so a laptop in another timezone
 * still sees the right answer.
 */
function resetSentence(endsAt: string | null): string {
  if (!endsAt) return "This board never ends.";
  const leftMs = new Date(endsAt).getTime() - Date.now();
  if (leftMs <= 0) return "This board has ended. The next one starts soon.";
  const minutes = Math.round(leftMs / 60000);
  if (minutes < 60) return `Ends in ${minutes} min.`;
  const hours = Math.floor(minutes / 60);
  // A term board is weeks away; "483 h 50 min" is arithmetic where a child
  // needs a date-like answer.
  if (hours >= 48) {
    const days = Math.round(hours / 24);
    return `Ends in ${days} days.`;
  }
  const rest = minutes % 60;
  return rest === 0 ? `Ends in ${hours} h.` : `Ends in ${hours} h ${rest} min.`;
}

/** Re-render once a minute so the countdown stays honest without a timer spam. */
function useMinuteTick(): number {
  const [tick, setTick] = useState(0);
  useEffect(() => {
    const id = window.setInterval(() => setTick((value) => value + 1), 60_000);
    return () => window.clearInterval(id);
  }, []);
  return tick;
}

function BoardTable({
  board,
  isLearner,
}: {
  board: Board;
  isLearner: boolean;
}) {
  if (board.entries.length === 0) {
    return (
      <EmptyState icon="trophy" title="No one is on this board yet">
        {isLearner
          ? `Play ${board.to_join ?? board.min_sessions} more ${
              (board.to_join ?? board.min_sessions) === 1 ? "game" : "games"
            } to start it.`
          : "Once learners play, their names appear here."}
      </EmptyState>
    );
  }

  const podium = board.entries.slice(0, 3);
  const rest = board.entries.slice(3);
  const myRowInList = board.entries.some((row) => row.is_me);

  return (
    <div className="flex flex-col gap-5">
      <section
        aria-label="Top 3 learners"
        className="grid grid-cols-1 gap-4 md:grid-cols-3"
      >
        {podium.map((row, index) => (
          <div
            key={`${row.rank}-${row.preferred_name}`}
            aria-current={row.is_me ? "true" : undefined}
            className={cx(
              "flex flex-col items-center gap-3 rounded-2xl bg-surface p-6 text-center shadow-card transition-transform hover:-translate-y-0.5",
              row.is_me ? "ring-2 ring-brand" : "ring-1 ring-line",
            )}
          >
            <span
              aria-hidden="true"
              className="grid size-16 place-items-center rounded-full bg-surface-muted text-3xl"
            >
              {MEDALS[index] ?? "⭐"}
            </span>
            <div className="flex flex-col gap-0.5">
              <span className="text-micro font-bold uppercase tracking-wider text-ink-muted">
                {row.rank === 1
                  ? "1st place"
                  : row.rank === 2
                    ? "2nd place"
                    : "3rd place"}
              </span>
              <h2 className="font-headline text-[21px] font-extrabold text-ink">
                {row.preferred_name}
                {row.is_me ? " (you)" : ""}
              </h2>
              <span aria-hidden="true" className="text-large">
                {avatarEmoji(row.avatar_key)}
              </span>
            </div>
            <span className="tabular rounded-pill bg-brand-soft px-4 py-2 font-headline text-label font-extrabold text-brand-deep">
              {row.xp_total} XP
            </span>
          </div>
        ))}
      </section>

      {/* Two learners on the board is a complete board: an empty card under
          them reads as a missing row, so the list only appears when it has
          something in it. */}
      {rest.length > 0 || (!myRowInList && board.me) ? (
        <Card className="flex flex-col gap-2.5 p-4 sm:p-6">
          <ol className="flex flex-col gap-2.5">
            {rest.map((row) => (
              <li
                key={`${row.rank}-${row.preferred_name}-${row.xp_total}`}
                aria-current={row.is_me ? "true" : undefined}
                className={cx(
                  "flex items-center justify-between gap-3 rounded-2xl px-4 py-3",
                  row.is_me ? "bg-brand-soft" : "bg-surface-muted",
                )}
              >
                <div className="flex min-w-0 items-center gap-3">
                  <span
                    className={cx(
                      "tabular grid size-10 shrink-0 place-items-center rounded-xl font-headline text-label font-extrabold",
                      row.is_me
                        ? "bg-brand text-white"
                        : "bg-surface text-ink-muted",
                    )}
                  >
                    #{row.rank}
                  </span>
                  <span aria-hidden="true" className="text-large">
                    {avatarEmoji(row.avatar_key)}
                  </span>
                  <span
                    className={cx(
                      "truncate",
                      row.is_me
                        ? "font-headline text-body-min font-extrabold text-brand-deep"
                        : "text-body text-ink",
                    )}
                  >
                    {row.preferred_name}
                    {row.is_me ? " (you)" : ""}
                  </span>
                </div>
                <span className="tabular shrink-0 rounded-pill bg-surface px-3.5 py-1.5 text-label font-bold text-brand-deep">
                  {row.xp_total} XP
                </span>
              </li>
            ))}
          </ol>

          {!myRowInList && board.me ? (
            <div className="mt-2 flex items-center justify-between gap-3 rounded-2xl bg-brand-soft px-4 py-3">
              <div className="flex min-w-0 items-center gap-3">
                <span className="tabular grid size-10 shrink-0 place-items-center rounded-xl bg-brand font-headline text-label font-extrabold text-white">
                  #{board.me.rank}
                </span>
                <span className="truncate font-headline text-body-min font-extrabold text-brand-deep">
                  {board.me.preferred_name} (you)
                </span>
              </div>
              <span className="tabular shrink-0 text-label font-bold text-brand-deep">
                {board.me.xp_total} XP
              </span>
            </div>
          ) : null}
        </Card>
      ) : null}
    </div>
  );
}

function TermForm() {
  const [name, setName] = useState("");
  const [starts, setStarts] = useState("");
  const [ends, setEnds] = useState("");
  const [saved, setSaved] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const terms = useQuery({
    queryKey: ["terms"],
    queryFn: () => apiFetch<SchoolTerm[]>("/api/school/terms"),
  });

  async function submit(event: React.FormEvent) {
    event.preventDefault();
    setError(null);
    try {
      await apiFetch<SchoolTerm>("/api/school/terms", {
        method: "POST",
        body: JSON.stringify({ name, starts_on: starts, ends_on: ends }),
      });
      setSaved(true);
      setName("");
      setStarts("");
      setEnds("");
      await terms.refetch();
    } catch (caught) {
      setError(
        caught instanceof ApiError ? caught.message : "That did not save.",
      );
    }
  }

  return (
    <Card className="flex flex-col gap-4 p-6">
      <div className="flex flex-col gap-1">
        <h2 className="flex items-center gap-2 font-headline text-large font-extrabold text-ink">
          <Icon name="calendar" size={22} className="text-brand" />
          Add your term dates
        </h2>
        <p className="text-body-min text-ink-muted">
          The term board needs a start and an end.
        </p>
      </div>

      <form
        onSubmit={(event) => void submit(event)}
        className="flex flex-col gap-4"
      >
        <label className="flex flex-col gap-1.5 text-label font-bold text-ink-muted">
          Name
          <input
            value={name}
            onChange={(event) => setName(event.target.value)}
            required
            className="min-h-target rounded-xl border border-line bg-surface px-3 text-body text-ink"
          />
        </label>

        <div className="flex flex-col gap-3 sm:flex-row">
          <label className="flex flex-1 flex-col gap-1.5 text-label font-bold text-ink-muted">
            First day
            <input
              type="date"
              value={starts}
              onChange={(event) => setStarts(event.target.value)}
              required
              className="min-h-target rounded-xl border border-line bg-surface px-3 text-body text-ink"
            />
          </label>
          <label className="flex flex-1 flex-col gap-1.5 text-label font-bold text-ink-muted">
            Last day
            <input
              type="date"
              value={ends}
              onChange={(event) => setEnds(event.target.value)}
              required
              className="min-h-target rounded-xl border border-line bg-surface px-3 text-body text-ink"
            />
          </label>
        </div>

        <Button type="submit" arrow className="w-full sm:w-fit">
          Save the term
        </Button>

        {saved ? (
          <p role="status" className="text-body-min font-semibold text-ok">
            Term saved.
          </p>
        ) : null}
        {error ? <Alert>{error}</Alert> : null}
      </form>

      {terms.data && terms.data.length > 0 ? (
        <ul className="flex flex-wrap gap-2">
          {terms.data.map((term) => (
            <li key={term.id}>
              <Chip>
                {term.name}: {term.starts_on} to {term.ends_on}
              </Chip>
            </li>
          ))}
        </ul>
      ) : null}
    </Card>
  );
}
