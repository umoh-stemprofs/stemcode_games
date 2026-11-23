"use client";

/**
 * A coach's class XP (P5-T11).
 *
 * The same numbers a learner sees on the board, plus the one thing a coach
 * needs: *where the XP came from*, game by game. Every figure is a row of the
 * board projection, so it can be checked against the ledger (D-33).
 *
 * One decision per screen: pick a class, then read.
 */

import { useQuery } from "@tanstack/react-query";
import { useMemo, useState } from "react";

import { AppShell } from "@/components/AppShell";
import { NoAccess } from "@/components/NoAccess";
import {
  Alert,
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
import type { ClassSummary, Role } from "@/lib/auth/types";
import type { BoardPeriod, CoachBoard } from "@/lib/games/board-types";
import { PERIOD_WORDS } from "@/lib/games/board-types";
import type { GameSummary } from "@/lib/games/types";

const STAFF: Role[] = ["coach", "school_admin"];
const PERIODS: BoardPeriod[] = ["daily", "weekly", "termly"];

export default function CoachXpPage() {
  return (
    <AppShell>
      <CoachXpBody />
    </AppShell>
  );
}

function CoachXpBody() {
  const session = useSession();
  const role = session.status === "authenticated" ? session.me.user.role : null;
  const allowed = role !== null && STAFF.includes(role);
  const isAdmin = role === "school_admin";

  const periods = useMemo<BoardPeriod[]>(
    () => (isAdmin ? [...PERIODS, "all_time"] : PERIODS),
    [isAdmin],
  );
  const [period, setPeriod] = useState<BoardPeriod>("weekly");
  const [classId, setClassId] = useState("");

  const classes = useQuery({
    queryKey: ["classes"],
    queryFn: () => apiFetch<ClassSummary[]>("/api/classes"),
    enabled: allowed,
  });

  const games = useQuery({
    queryKey: ["catalog"],
    queryFn: () => apiFetch<GameSummary[]>("/api/games/catalog"),
    enabled: allowed,
  });

  const chosen = classId || classes.data?.[0]?.id || "";
  const suffix = chosen ? `?class_id=${chosen}` : "";

  const board = useQuery({
    queryKey: ["coach-xp", period, chosen],
    queryFn: () => apiFetch<CoachBoard>(`/api/leaderboards/${period}/students${suffix}`),
    enabled: allowed && chosen !== "",
    // A hidden board answers 404; that is a state, not a failure to retry.
    retry: false,
  });

  const gameName = useMemo(() => {
    const map = new Map<string, string>();
    for (const game of games.data ?? []) map.set(game.id, game.name);
    return map;
  }, [games.data]);

  if (session.status === "authenticated" && !allowed) {
    return <NoAccess />;
  }

  const noCalendar =
    board.error instanceof ApiError && board.error.status === 404 && period === "termly";

  return (
    <div className="flex flex-col gap-6">
      <PageHeader icon="chart" title="XP" subtitle="Pick a class to see its XP." />

      {classes.data && classes.data.length === 0 ? (
        <Card className="p-4">
          <EmptyState icon="users" title="You have no classes yet">
            An admin assigns you to a class.
          </EmptyState>
        </Card>
      ) : null}

      {classes.data && classes.data.length > 0 ? (
        <div className="flex flex-col gap-4 lg:flex-row lg:items-end">
          <label className="flex flex-col gap-1.5 text-label font-bold text-ink-muted lg:w-72">
            Class
            <select
              value={chosen}
              onChange={(event) => setClassId(event.target.value)}
              className="min-h-target rounded-xl border border-line bg-surface px-3 text-body text-ink"
            >
              {classes.data.map((klass) => (
                <option key={klass.id} value={klass.id}>
                  {klass.name}
                </option>
              ))}
            </select>
          </label>

          <nav aria-label="Which board" className="flex flex-wrap gap-2">
            {periods
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
          </nav>
        </div>
      ) : null}

      {board.isPending && chosen ? <Loading /> : null}

      {board.isError ? (
        <Alert>
          {noCalendar
            ? "This school has no term dates yet."
            : sentenceFor(
                board.error instanceof ApiError ? board.error.code : undefined,
                board.error instanceof ApiError ? board.error.status : undefined,
              )}
        </Alert>
      ) : null}

      {board.data && board.data.students.length === 0 ? (
        <Card className="p-4">
          <EmptyState icon="trophy" title="No one in this class has played yet">
            Their names appear here after the first game.
          </EmptyState>
        </Card>
      ) : null}

      {board.data && board.data.students.length > 0 ? (
        <ul className="flex flex-col gap-3">
          {board.data.students.map((student) => (
            <li key={`${student.preferred_name}-${student.xp_total}`}>
              <Card className="flex flex-col gap-3 p-5">
                <div className="flex items-center gap-3">
                  <span
                    aria-hidden="true"
                    className="grid size-11 shrink-0 place-items-center rounded-full bg-canvas text-[22px] ring-2 ring-line"
                  >
                    {avatarEmoji(student.avatar_key)}
                  </span>
                  <span className="font-headline text-body-min font-bold text-ink">
                    {student.preferred_name}
                  </span>
                  <Chip tone="sun" className="ml-auto">
                    {student.xp_total} XP
                  </Chip>
                </div>

                {student.games.length > 0 ? (
                  <ul className="flex flex-wrap gap-2">
                    {student.games.map((game) => (
                      <li key={game.game_id}>
                        <Chip>
                          {gameName.get(game.game_id) ?? "A game"}: {game.xp_total} XP
                        </Chip>
                      </li>
                    ))}
                  </ul>
                ) : (
                  <p className="text-label text-ink-muted">No games counted yet.</p>
                )}
              </Card>
            </li>
          ))}
        </ul>
      ) : null}
    </div>
  );
}
