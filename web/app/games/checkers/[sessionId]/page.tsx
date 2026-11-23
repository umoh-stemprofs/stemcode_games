"use client";

/**
 * A live Checkers match (P8-T17, P8-T18).
 *
 * The screen is a mirror, not a referee: the server sends *this* player's board,
 * clocks and legal moves, and accepts only one of those moves. So the rules
 * screens avoid:
 *
 * - **one decision per screen** — it is your turn or it is not, and the board
 *   says which;
 * - **no countdown numbers** — each player's clock is a plain `4:59`, because a
 *   chess clock is the one place a number is the right shape;
 * - **nothing surprises you** — resigning asks first, and the connection state
 *   is said out loud instead of silently freezing the board.
 *
 * If the socket drops the match is paused by the server, not lost: the clock
 * stops for the player who is away and this page retries with a fresh ticket.
 */

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useParams, useRouter } from "next/navigation";
import { useQuery } from "@tanstack/react-query";

import { AppShell } from "@/components/AppShell";
import { CheckersBoard } from "@/components/CheckersBoard";
import { Icon } from "@/components/icons";
import {
  Alert,
  Button,
  ButtonLink,
  Card,
  PageHeader,
  Progress,
  cx,
} from "@/components/ui";
import { XP_CHANGED } from "@/components/XpChip";
import { ApiError, apiFetch } from "@/lib/api/client";
import { sentenceFor } from "@/lib/auth/messages";
import type { LiveCreated, LiveState, ServerEvent, Ticket } from "@/lib/games/live";
import { LiveSocket, formatClock, mustJump } from "@/lib/games/live";

const END_REASON: Record<string, string> = {
  timeout: "Time ran out.",
  resign: "One player resigned.",
  forfeit: "One player did not come back.",
  agreement: "You both agreed.",
  draw: "It was a draw.",
};

export default function LiveMatchPage() {
  return (
    <AppShell>
      <MatchBody />
    </AppShell>
  );
}

function MatchBody() {
  const params = useParams<{ sessionId: string }>();
  const sessionId = params.sessionId;
  const router = useRouter();

  const first = useQuery({
    queryKey: ["live-match", sessionId],
    queryFn: () => apiFetch<LiveState>(`/api/games/live/${sessionId}`),
    retry: 1,
  });

  const [state, setState] = useState<LiveState | null>(null);
  const [connected, setConnected] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [confirmResign, setConfirmResign] = useState(false);
  const [busy, setBusy] = useState(false);
  const [clockBase, setClockBase] = useState(() => Date.now());
  const [now, setNow] = useState(() => Date.now());
  const socketRef = useRef<LiveSocket | null>(null);
  // The clock the match started with, kept once so a bar means "left out of the
  // whole game" instead of shrinking as both players spend time.
  const openingClock = useRef(0);

  useEffect(() => {
    if (first.data) {
      setState(first.data);
      setClockBase(Date.now());
    }
  }, [first.data]);

  useEffect(() => {
    if (openingClock.current > 0 || !state) return;
    openingClock.current = Math.max(...Object.values(state.clock_ms), 1);
  }, [state]);

  const onEvent = useCallback((event: ServerEvent) => {
    if (event.type === "match.state") {
      // `seq` is the envelope's sequence number, not part of the snapshot.
      const { seq, ...snapshot } = event;
      void seq;
      setState(snapshot as LiveState);
      setClockBase(Date.now());
      // The result and its XP are written in the same request that ends the
      // match, so the chip re-reads now rather than on the next page load.
      if ((snapshot as LiveState).outcome !== null) {
        window.dispatchEvent(new Event(XP_CHANGED));
      }
      return;
    }
    if (event.type === "move.rejected") {
      setError(event.message);
      return;
    }
    if (event.type === "move.accepted") {
      setError(null);
    }
  }, []);

  useEffect(() => {
    if (!state) return;
    const socket = new LiveSocket(sessionId, {
      onEvent,
      onOpen: () => setConnected(true),
      onClose: () => setConnected(false),
      ticket: async () => {
        const issued = await apiFetch<Ticket>("/api/ws/ticket", {
          method: "POST",
          body: JSON.stringify({ session_id: sessionId }),
        });
        return issued.ticket;
      },
    });
    socketRef.current = socket;
    socket.connect();
    return () => {
      socket.close();
      socketRef.current = null;
    };
    // One socket per match: the ticket and callbacks do not change identity.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [sessionId, Boolean(state)]);

  // The clock ticks locally between server frames, so the number a child sees
  // does not jump once a second only when a socket frame arrives.
  useEffect(() => {
    const timer = setInterval(() => setNow(Date.now()), 500);
    return () => clearInterval(timer);
  }, []);

  const clocks = useMemo(() => {
    if (!state) return { mine: 0, theirs: 0 };
    // Only the side to move is charged, which is what the server does too.
    const elapsed = state.status === "active" ? now - clockBase : 0;
    const mine = state.clock_ms[state.seat] ?? 0;
    const theirs = state.clock_ms[otherSeat(state.seat)] ?? 0;
    const yourTurn = state.side_to_move === state.seat;
    return {
      mine: yourTurn ? Math.max(0, mine - elapsed) : mine,
      theirs: yourTurn ? theirs : Math.max(0, theirs - elapsed),
    };
  }, [state, now, clockBase]);

  const move = useCallback(
    (moveKey: string) => {
      if (!state || !socketRef.current) return;
      const clientMoveId = crypto.randomUUID().replaceAll("-", "");
      setError(null);
      setBusy(true);
      const sent = socketRef.current.send({
        type: "move.submit",
        client_move_id: clientMoveId,
        expected_move_number: state.move_number + 1,
        move: moveKey,
      });
      if (!sent) {
        // The socket is down: the same call exists over HTTP, so the move is
        // not lost, only slower.
        void apiFetch<LiveState>(`/api/games/live/${sessionId}/moves`, {
          method: "POST",
          body: JSON.stringify({
            client_move_id: clientMoveId,
            expected_move_number: state.move_number + 1,
            move: moveKey,
          }),
        })
          .then((next) => {
            setState(next);
            setClockBase(Date.now());
          })
          .catch((caught) => {
            setError(caught instanceof ApiError ? caught.message : sentenceFor(undefined));
          })
          .finally(() => setBusy(false));
        return;
      }
      setBusy(false);
    },
    [sessionId, state],
  );

  const intent = useCallback(
    async (type: string) => {
      setBusy(true);
      setError(null);
      const sent = socketRef.current?.send({ type });
      if (!sent) {
        const path =
          type === "match.resign"
            ? "resign"
            : type === "draw.offer"
              ? "draw/offer"
              : type === "draw.accept"
                ? "draw/accept"
                : "draw/decline";
        try {
          const next = await apiFetch<LiveState>(`/api/games/live/${sessionId}/${path}`, {
            method: "POST",
          });
          setState(next);
          setClockBase(Date.now());
        } catch (caught) {
          setError(caught instanceof ApiError ? caught.message : sentenceFor(undefined));
        }
      }
      setBusy(false);
    },
    [sessionId],
  );

  async function rematch() {
    setBusy(true);
    try {
      const created = await apiFetch<LiveCreated>(`/api/games/live/${sessionId}/rematch`, {
        method: "POST",
      });
      router.push(`/games/checkers/${created.session_id}`);
    } catch (caught) {
      setError(caught instanceof ApiError ? caught.message : sentenceFor(undefined));
    } finally {
      setBusy(false);
    }
  }

  if (first.isPending && !state) {
    return (
      <p role="status" className="text-body text-ink-muted">
        Just a moment.
      </p>
    );
  }

  if (first.isError || !state) {
    return (
      <div className="flex flex-col gap-4">
        <PageHeader icon="play" title="Checkers" />
        <Card className="p-6">
          <p className="text-body">We could not find that match.</p>
        </Card>
        <ButtonLink href="/games/checkers" arrow className="w-full sm:w-fit">
          Back to Checkers
        </ButtonLink>
      </div>
    );
  }

  // `created` is a real, live state: the invite is sitting in somebody's inbox
  // and this player is on the board waiting. Only a status that cannot start
  // again counts as over, so a waiting match is never told it is a draw.
  const ended =
    state.outcome !== null ||
    !["created", "ready", "active"].includes(state.status);
  const opponentName = state.opponent.name ?? "Your friend";
  const yourTurn = state.your_turn && connected;

  return (
    <div className="flex flex-col gap-4">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <PageHeader
          icon="play"
          title="Checkers"
          subtitle={state.seat === "white" ? "You play white." : "You play black."}
        />
        {/* D.1: every target is at least 56x56, text links included. */}
        <ButtonLink href="/games/checkers" variant="ghost" size="sm" icon="arrow-left">
          Leave
        </ButtonLink>
      </div>

      {error ? <Alert>{error}</Alert> : null}

      {ended ? <EndPanel state={state} busy={busy} onRematch={() => void rematch()} /> : null}

      {!ended ? (
        <>
          {/* "What do I do now?" is the first thing on the screen, above the
              board it is talking about (D.2.1). */}
          <p
            role="status"
            className={cx(
              "flex items-center gap-2.5 rounded-2xl px-4 py-3 font-headline text-large font-bold",
              yourTurn ? "bg-ok-soft text-ok" : "bg-brand-soft text-brand-deep",
            )}
          >
            <Icon name={yourTurn ? "check" : "clock"} size={22} />
            {turnSentence(state, connected, opponentName)}
          </p>

          <Card className="flex flex-col gap-3 p-3 sm:p-4">
            <PlayerRow
              name={opponentName}
              clock={clocks.theirs}
              total={openingClock.current}
              active={state.side_to_move !== state.seat}
              away={!state.opponent.connected}
            />
            <CheckersBoard
              board={state.board}
              seat={state.seat}
              legalMoves={state.legal_moves}
              onMove={move}
              disabled={!yourTurn || busy}
            />
            <PlayerRow
              name="You"
              clock={clocks.mine}
              total={openingClock.current}
              active={state.side_to_move === state.seat}
              you
            />
          </Card>

          {/* D.2.3: the consequence is stated before it can happen, and it is a
              line a learner can point at when asked what an empty bar means. */}
          <p className="flex items-center gap-2 text-label font-semibold text-ink-muted">
            <Icon name="hourglass" size={16} />
            If the bar empties, you lose.
          </p>

          {state.draw_offer_from && state.draw_offer_from !== state.seat ? (
            <Card className="flex flex-col gap-3 border-2 border-brand bg-brand-soft p-5">
              <p className="font-headline text-large font-bold text-brand-deep">
                {opponentName} offers a draw.
              </p>
              <div className="flex flex-col gap-3 sm:flex-row">
                <Button disabled={busy} onClick={() => void intent("draw.accept")} arrow className="w-full sm:w-auto">
                  Accept
                </Button>
                <Button
                  variant="ghost"
                  disabled={busy}
                  onClick={() => void intent("draw.decline")}
                  className="w-full sm:w-auto"
                >
                  No thanks
                </Button>
              </div>
            </Card>
          ) : null}

          {confirmResign ? (
            <Card className="flex flex-col gap-3 border-2 border-line bg-surface p-5">
              <p className="text-body font-semibold">Stop the match? You will lose it.</p>
              <div className="flex flex-col gap-3 sm:flex-row">
                <Button
                  variant="danger"
                  disabled={busy}
                  onClick={() => {
                    setConfirmResign(false);
                    void intent("match.resign");
                  }}
                  className="w-full sm:w-auto"
                >
                  Yes, resign
                </Button>
                <Button
                  variant="ghost"
                  onClick={() => setConfirmResign(false)}
                  className="w-full sm:w-auto"
                >
                  Keep playing
                </Button>
              </div>
            </Card>
          ) : (
            <div className="grid gap-3 sm:grid-cols-2">
              <Button
                variant="ghost"
                disabled={busy || state.status !== "active"}
                onClick={() => void intent("draw.offer")}
                className="w-full"
              >
                Draw
              </Button>
              <Button
                variant="ghost"
                disabled={busy || state.status !== "active"}
                onClick={() => setConfirmResign(true)}
                className="w-full"
              >
                Resign
              </Button>
            </div>
          )}
        </>
      ) : null}
    </div>
  );
}

function PlayerRow({
  name,
  clock,
  total,
  active,
  you,
  away,
}: {
  name: string;
  clock: number;
  total: number;
  active: boolean;
  you?: boolean;
  away?: boolean;
}) {
  const urgent = clock <= 30_000;
  const spoken = you ? `You have ${formatClock(clock)} left` : `${name} has ${formatClock(clock)} left`;
  // D.2.5: time is a bar, and the number is followed by the word it means.
  const fill = total > 0 ? Math.max(0, Math.min(100, (clock / total) * 100)) : 100;
  return (
    <div className={cx("flex items-center gap-3 rounded-2xl px-2 py-2", active && "bg-surface-muted")}>
      <span
        aria-hidden="true"
        className={cx(
          "grid size-11 shrink-0 place-items-center rounded-full font-headline text-body-min font-extrabold",
          you ? "bg-brand text-white" : "bg-surface-muted text-ink",
        )}
      >
        {you ? "You" : name.charAt(0).toUpperCase()}
      </span>
      <div className="flex min-w-0 flex-1 flex-col gap-1">
        <span className={cx("font-headline text-body-min text-ink", active ? "font-extrabold" : "font-semibold")}>
          {name}
          {away ? <span className="text-label text-ink-muted"> · away</span> : null}
        </span>
        <Progress
          value={fill}
          label={spoken}
          tone={urgent ? "danger" : "brand"}
          className="h-2 bg-surface-sunk"
        />
      </div>
      <span className={cx("tabular shrink-0 text-label font-bold", urgent ? "text-danger" : "text-ink-muted")}>
        {formatClock(clock)} left
      </span>
    </div>
  );
}

function EndPanel({
  state,
  busy,
  onRematch,
}: {
  state: LiveState;
  busy: boolean;
  onRematch: () => void;
}) {
  const winner = state.outcome?.winner ?? null;
  const reason = state.outcome?.reason ?? "";
  const head =
    state.outcome === null
      ? "The match is over."
      : winner === null
        ? "It was a draw."
        : winner === state.seat
          ? "You won."
          : `${state.opponent.name ?? "Your friend"} won.`;
  const detail =
    winner === null && reason === "agreement"
      ? END_REASON.agreement
      : winner === null
        ? (END_REASON[reason] ?? "Nobody won this time.")
        : reason === "timeout"
          ? "The clock ran out."
          : reason === "resign"
            ? "Someone resigned."
            : reason === "forfeit"
              ? "Someone did not come back."
              : "";

  return (
    <Card className="flex flex-col items-center gap-3 p-6 text-center sm:p-8">
      <span aria-hidden="true" className="text-[52px] leading-none">
        🏁
      </span>
      <p className="font-headline text-[clamp(26px,5vw,34px)] font-extrabold text-ink">{head}</p>
      {detail ? <p className="text-body text-ink-muted">{detail}</p> : null}
      <div className="mt-2 flex w-full flex-col gap-3 sm:w-fit sm:flex-row">
        <Button disabled={busy} onClick={onRematch} arrow>
          Play again
        </Button>
        <ButtonLink href="/games" variant="ghost">
          Back to games
        </ButtonLink>
      </div>
    </Card>
  );
}

function turnSentence(state: LiveState, connected: boolean, opponentName: string): string {
  if (!connected) return "You are offline. We are getting you back in.";
  if (state.status === "created" || state.status === "ready") {
    return `Waiting for ${opponentName} to join.`;
  }
  if (state.your_turn) {
    return mustJump(state.legal_moves) ? "Tap the piece. You must jump!" : "Your turn. Tap a piece.";
  }
  return `Waiting for ${opponentName}.`;
}

function otherSeat(seat: LiveState["seat"]): LiveState["seat"] {
  return seat === "white" ? "black" : "white";
}
