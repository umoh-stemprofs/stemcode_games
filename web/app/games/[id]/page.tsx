"use client";

/**
 * The game shell, with Word Scramble (P4-T13) and Number Guess (P6-T03) inside it.
 *
 * Appendix D is the design brief, in its own words:
 *
 * - **One decision per screen.** Choose a level, then play one round at a time.
 * - **Big targets.** Letter tiles are 56px; there is no small control anywhere.
 * - **No countdown numbers.** The round clock is a filling bar, so a slow
 *   reader is not also doing arithmetic against a ticking number.
 * - **Plain sentences.** "Correct! +10", "Not quite — try again, 1 try left.",
 *   "You got 8 of 10 words. Good job."
 * - **Nothing hidden.** "I don't know" is a big button, not a gesture.
 *
 * The client never sees an answer or a seed. It sends a guess; the server
 * decides. Refreshing mid-round restores the round and its remaining time from
 * `GET /games/sessions/{id}`.
 *
 * Number Guess keeps the same shell and swaps the round screen: a shrinking
 * window, a big number entry, and the server's own sentence for "too low".
 */

import { useCallback, useEffect, useRef, useState } from "react";
import Link from "next/link";
import { useParams } from "next/navigation";
import { useQueryClient } from "@tanstack/react-query";

import { AppShell } from "@/components/AppShell";
import { ChallengeEnd } from "@/components/ChallengeEnd";
import { useQuitGuard } from "@/components/QuitGuard";
import { FriendSheet } from "@/components/FriendSheet";
import { GuessScreen } from "@/components/GuessScreen";
import { Icon } from "@/components/icons";
import { OfflineReady } from "@/components/OfflineReady";
import { RoundClock } from "@/components/RoundClock";
import { ResumeGameLink } from "@/components/ResumeGameLink";
import { XP_CHANGED } from "@/components/XpChip";
import {
  Alert,
  Button,
  ButtonLink,
  Card,
  Chip,
  PageHeader,
  cx,
} from "@/components/ui";
import { ApiError, apiFetch } from "@/lib/api/client";
import { useSession } from "@/lib/auth/session";
import { sentenceFor } from "@/lib/auth/messages";
import type { ActiveSession, ActionType, PlayState } from "@/lib/games/types";

type Phase = "choosing" | "loading" | "playing" | "finished" | "blocked";

const DIFFICULTIES = [
  { value: 1, label: "Easy" },
  { value: 2, label: "Medium" },
  { value: 3, label: "Hard" },
];

const TITLES: Record<string, string> = {
  word_scramble: "Word Scramble",
  number_guess: "Number Guess",
};

// What each level means, in the words a learner needs before choosing.
const LEVEL_HINTS: Record<number, string> = {
  1: "1 to 50",
  2: "1 to 200",
  3: "1 to 1,000",
};

export default function GamePage() {
  return (
    <AppShell>
      <GameBody />
    </AppShell>
  );
}

function GameBody() {
  const params = useParams<{ id: string }>();
  const gameId = params.id;
  const isGuess = gameId === "number_guess";
  const title = TITLES[gameId] ?? "Game";

  const [phase, setPhase] = useState<Phase>("choosing");
  const [state, setState] = useState<PlayState | null>(null);
  const [difficulty, setDifficulty] = useState(1);
  const [pending, setPending] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [feedback, setFeedback] = useState<string | null>(null);
  const [blocked, setBlocked] = useState<string | null>(null);
  const session = useSession();
  const userId = session.status === "authenticated" ? session.me.user.id : null;

  // A finished game moves the chip, the streak, the quest and the board. Tell
  // the rest of the app once, rather than making every screen poll.
  const queryClient = useQueryClient();
  useEffect(() => {
    if (phase !== "finished") return;
    window.dispatchEvent(new Event(XP_CHANGED));
    void queryClient.invalidateQueries({ queryKey: ["engagement"] });
    void queryClient.invalidateQueries({ queryKey: ["board"] });
  }, [phase, queryClient]);

  // Which rounds this tab has already acknowledged (P4-T10).
  const seen = useRef<Set<number>>(new Set());

  // A game in progress is what makes the menu tabs ask before leaving. The
  // setter is the stable part, so this does not chase its own re-render.
  const { setActive } = useQuitGuard();
  const sessionId = state?.session_id;
  useEffect(() => {
    if (phase === "playing" && sessionId) {
      setActive({ sessionId, gameName: title });
    } else {
      setActive(null);
    }
    return () => setActive(null);
  }, [phase, sessionId, title, setActive]);

  // A round's result is a reward, not a label: show it, then let it go, so
  // "Correct! +10" never reads as if it belongs to the word below it.
  useEffect(() => {
    if (!feedback) return;
    // A reward can go as soon as it has been read. Being told the round was
    // missed carries something the next round does not repeat — which number it
    // was — so it stays up long enough to be read, not just glimpsed.
    const ms = feedback.startsWith("Time is up") ? 4000 : 1800;
    const timer = setTimeout(() => setFeedback(null), ms);
    return () => clearTimeout(timer);
  }, [feedback]);

  const begin = useCallback((next: PlayState) => {
    setState(next);
    setFeedback(null);
    setPhase(next.finished ? "finished" : "playing");
    if (
      next.round &&
      next.round.time_left_ms < next.round.round_seconds * 1000 - 500
    ) {
      // Resumed mid-round: the clock is already running, so do not re-acknowledge.
      seen.current.add(next.round.number);
    }
  }, []);

  // Resume: a refreshed tab returns to the open session, if there is one.
  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const active = await apiFetch<ActiveSession>("/api/games/sessions/active");
        if (cancelled || !active.session_id) return;
        if (active.game_id !== gameId) {
          setBlocked("You have another game open. Finish that one first.");
          setPhase("blocked");
          return;
        }
        const resumed = await apiFetch<PlayState>(`/api/games/sessions/${active.session_id}`);
        if (!cancelled) begin(resumed);
      } catch {
        // A missing session just means "start a new one"; the shell handles auth.
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [gameId, begin]);

  const start = useCallback(
    async (level: number) => {
      setPending(true);
      setError(null);
      setDifficulty(level);
      try {
        const created = await apiFetch<PlayState>(`/api/games/${gameId}/sessions`, {
          method: "POST",
          body: JSON.stringify({ difficulty: level }),
        });
        begin(created);
      } catch (caught) {
        if (caught instanceof ApiError) {
          if (caught.code === "another_session_active") {
            const active = await apiFetch<ActiveSession>("/api/games/sessions/active");
            if (active.session_id) {
              begin(
                await apiFetch<PlayState>(`/api/games/sessions/${active.session_id}`),
              );
              return;
            }
          }
          if (caught.status === 403 || caught.code === "not_enough_content") {
            setBlocked(caught.message);
            setPhase("blocked");
            return;
          }
          setError(sentenceFor(caught.code, caught.status));
        } else {
          setError(sentenceFor(undefined));
        }
      } finally {
        setPending(false);
      }
    },
    [gameId, begin],
  );

  // A guard, not a state flag: two taps in the same frame both see `pending`
  // as false, and Number Guess would send two guesses for one press.
  const busy = useRef(false);

  const act = useCallback(
    async (type: ActionType, value?: string) => {
      if (!state || busy.current) return;
      busy.current = true;
      const before = state;
      setPending(true);
      setError(null);
      try {
        const next = await apiFetch<PlayState>(
          `/api/games/sessions/${state.session_id}/actions`,
          {
            method: "POST",
            body: JSON.stringify({
              client_move_id: crypto.randomUUID(),
              type,
              value,
            }),
          },
        );
        setState(next);
        if (next.finished) setPhase("finished");

        // The server decides; this only says what happened, in one sentence.
        // Number Guess sends its own sentence (`message`), because "too low"
        // is not something a generic screen can infer from the numbers.
        if (next.message) {
          setFeedback(next.message);
        } else if (next.round_index > before.round_index) {
          const gained =
            next.scores.length > before.scores.length
              ? next.scores[next.scores.length - 1]
              : null;
          if (gained && gained > 0) setFeedback(`Correct! +${gained}`);
          else setFeedback(next.finished ? null : "Next word.");
        } else if (
          next.round &&
          before.round &&
          next.round.tries_left < before.round.tries_left
        ) {
          const left = next.round.tries_left;
          setFeedback(`Not quite — try again, ${left} ${left === 1 ? "try" : "tries"} left.`);
        }
      } catch (caught) {
        if (
          caught instanceof ApiError &&
          (caught.code === "round_expired" || caught.code === "session_ended")
        ) {
          const fresh = await apiFetch<PlayState>(`/api/games/sessions/${state.session_id}`);
          setState(fresh);
          if (fresh.finished) setPhase("finished");
          // The server already wrote the sentence; this screen used to
          // substitute "word", which is wrong in half the games. A late guess
          // also gets the state that advance wrote, so the learner still learns
          // which number was missed rather than only that one ran out.
          setFeedback(
            caught.code === "round_expired"
              ? fresh.message ?? caught.message
              : "That game has ended.",
          );
        } else if (caught instanceof ApiError) {
          setError(sentenceFor(caught.code, caught.status));
        } else {
          setError(sentenceFor(undefined));
        }
      } finally {
        busy.current = false;
        setPending(false);
      }
    },
    [state],
  );

  // A ref so a scheduled retry always sees the living session, not the one
  // captured when the callback was made.
  const stateRef = useRef<PlayState | null>(null);
  stateRef.current = state;
  const refreshRef = useRef<(() => void) | null>(null);

  const refresh = useCallback(async () => {
    const current = stateRef.current;
    if (!current) return;
    try {
      const next = await apiFetch<PlayState>(`/api/games/sessions/${current.session_id}`);
      // The sentence is the server's, so Number Guess can say which number was
      // missed ("Time is up. It was 37.") instead of a generic line. Games with
      // no sentence of their own still say what happened.
      if (next.message) setFeedback(next.message);
      else if (next.round_index > current.round_index) setFeedback("Time is up.");
      setState(next);
      if (next.finished) {
        setPhase("finished");
        return;
      }
      // The bar reaches zero a moment before the server's own deadline (it
      // allows a two-second grace, D-24), so the first ask may still return
      // the same round. Ask again when the server says the round is over —
      // otherwise the bar sits at zero and the game stops dead.
      if (next.round && next.round_index === current.round_index) {
        window.setTimeout(
          () => refreshRef.current?.(),
          Math.max(400, next.round.time_left_ms + 400),
        );
      }
    } catch {
      setError(sentenceFor(undefined));
    }
  }, []);
  refreshRef.current = () => void refresh();

  // Acknowledge each round once, so its clock starts on the server.
  const roundNumber = state?.round?.number ?? null;
  useEffect(() => {
    if (phase !== "playing" || !state?.round || roundNumber === null) return;
    if (seen.current.has(roundNumber)) return;
    seen.current.add(roundNumber);
    void act("round_seen");
  }, [phase, state, roundNumber, act]);

  if (phase === "blocked") {
    return (
      <div className="flex flex-col gap-6">
        <PageHeader icon="lock" title="Not right now" />
        <Card className="flex flex-col gap-4 border-2 border-line bg-surface-muted p-6">
          <p className="text-body">{blocked}</p>
          {/* Renders only when a session really is open elsewhere, so it is the
              way out of "finish that one first" without hunting for it. */}
          <ResumeGameLink />
        </Card>
        <ButtonLink href="/games" variant="ghost" icon="arrow-left" className="w-full sm:w-fit">
          Go back
        </ButtonLink>
      </div>
    );
  }

  if (phase === "choosing") {
    return (
      <div className="flex flex-col gap-6">
        <PageHeader
          icon="play"
          title={title}
          subtitle="Pick a level."
          action={
            <ButtonLink href="/games" variant="ghost" size="sm" icon="arrow-left">
              All games
            </ButtonLink>
          }
        />

        {error ? <Alert>{error}</Alert> : null}

        <div className="grid gap-3 sm:grid-cols-3">
          {DIFFICULTIES.map((level) => (
            <button
              key={level.value}
              type="button"
              disabled={pending}
              onClick={() => void start(level.value)}
              className="flex min-h-[96px] flex-col items-center justify-center gap-1 rounded-2xl border-2 border-line bg-surface px-4 py-4 font-headline transition-all hover:-translate-y-0.5 hover:border-brand hover:bg-brand-soft active:translate-y-0 disabled:cursor-not-allowed disabled:opacity-50"
            >
              {/* One star for easy, three for hard: a learner who cannot read
                  the words can still see which button is the gentle one. */}
              <span aria-hidden="true" className="text-large tracking-[0.2em] text-sun">
                {"★".repeat(level.value)}
                {"☆".repeat(3 - level.value)}
              </span>
              <span className="text-[19px] font-extrabold text-ink">{level.label}</span>
              {isGuess ? (
                <span className="tabular text-label font-semibold text-ink-muted">
                  {LEVEL_HINTS[level.value]}
                </span>
              ) : null}
            </button>
          ))}
        </div>

        {/* P9-T02: the words save themselves in the background, so this is
            only the receipt. Number Guess needs no content at all. */}
        {gameId === "word_scramble" && userId ? (
          <OfflineReady gameId={gameId} userId={userId} />
        ) : null}

        {/* P7-T06: a friend is invited from the game itself, so the sheet
            knows which seed to share. */}
        <FriendSheet gameId={gameId} gameName={title} onStarted={begin} />

        <Link href="/games" className="text-label font-bold text-ink-muted underline underline-offset-4">
          ← All games
        </Link>
      </div>
    );
  }

  if (!state) {
    return (
      <p className="text-body text-ink-muted" role="status">
        Just a moment.
      </p>
    );
  }

  if (phase === "finished") {
    const solved = state.scores.filter((score) => score > 0).length;
    const noun = isGuess ? "numbers" : "words";
    return (
      <div className="flex flex-col gap-6">
        <Card className="flex flex-col items-center gap-3 p-6 text-center sm:p-9">
          <span aria-hidden="true" className="text-[52px] leading-none">
            🎉
          </span>
          <h1 className="font-headline text-[clamp(26px,5vw,36px)] font-extrabold leading-tight text-ink">
            You got {solved} of {state.rounds_total} {noun}.
          </h1>
          <p className="text-body text-ink-muted">
            {solved === state.rounds_total
              ? `That is every ${noun === "words" ? "word" : "number"}. Great work.`
              : solved > 0
                ? "Good job."
                : "Try again when you are ready."}
          </p>

          <div className="flex flex-wrap items-center justify-center gap-2">
            <Chip tone="blue">Score {state.score}</Chip>
            {/* The personal best, and whether this game just moved it. */}
            {state.best ? (
              <Chip tone={state.best_is_new ? "green" : "neutral"}>
                {state.best_is_new ? `New best! ${state.best}` : `Best: ${state.best}`}
              </Chip>
            ) : null}
            {/* The XP summary: what this game paid and what is left today. */}
            {state.xp ? (
              <Chip tone={state.xp.awarded > 0 ? "sun" : "neutral"}>
                {state.xp.awarded > 0 ? `+${state.xp.awarded} XP` : "No XP this time"}
              </Chip>
            ) : null}
          </div>

          {state.xp ? (
            <p className="text-body-min text-ink-muted">
              {state.xp.daily_cap > 0
                ? `${state.xp.today} of ${state.xp.daily_cap} XP today.`
                : `${state.xp.today} XP today.`}
            </p>
          ) : null}
        </Card>

        {/* A game played against a friend ends with the comparison, and with
            the one button that matters if it was not friendly (P7-T05/T09). */}
        <ChallengeEnd sessionId={state.session_id} />

        <div className="flex flex-col gap-3 sm:flex-row">
          <Button
            disabled={pending}
            onClick={() => void start(difficulty)}
            arrow
            className="w-full sm:w-auto"
          >
            Play again
          </Button>
          <ButtonLink href="/games" variant="ghost" className="w-full sm:w-auto">
            All games
          </ButtonLink>
        </div>
      </div>
    );
  }

  if (!state.round) {
    return null;
  }

  if (isGuess) {
    return (
      <GuessScreen
        state={state}
        feedback={feedback}
        error={error}
        pending={pending}
        onGuess={(number) => void act("guess", String(number))}
        onSkip={() => void act("skip")}
        onExpire={() => void refresh()}
        started={seen.current.has(state.round.number)}
      />
    );
  }

  return (
    <RoundScreen
      state={state}
      feedback={feedback}
      error={error}
      pending={pending}
      onAnswer={(word) => void act("answer", word)}
      onHint={() => void act("hint")}
      onSkip={() => void act("skip")}
      onExpire={() => void refresh()}
      started={seen.current.has(state.round.number)}
    />
  );
}

function RoundScreen({
  state,
  feedback,
  error,
  pending,
  onAnswer,
  onHint,
  onSkip,
  onExpire,
  started,
}: {
  state: PlayState;
  feedback: string | null;
  error: string | null;
  pending: boolean;
  onAnswer: (word: string) => void;
  onHint: () => void;
  onSkip: () => void;
  onExpire: () => void;
  started: boolean;
}) {
  const round = state.round;
  const letters = round?.letters.split("") ?? [];
  const [placed, setPlaced] = useState<number[]>([]);

  // A new round clears the board.
  useEffect(() => {
    setPlaced([]);
  }, [round?.number]);

  if (!round) return null;

  const available = letters.map((_, index) => index).filter((i) => !placed.includes(i));
  const word = placed.map((i) => letters[i]).join("");

  return (
    <div className="flex flex-col gap-5">
      {/* "What do I do now?" is the first thing on the screen (D.2.1), and the
          progress bar below it already says which word this is, so the old
          "Word 3 of 10 / Score 12" counter row is gone: D.2.5 allows only the
          points that were just gained, never a running total. */}
      <div className="flex flex-col gap-2">
        <h1 className="font-headline text-large font-extrabold text-ink">Tap the letters.</h1>

        {/* Rounds are dots and time is a bar, so the two never look alike (the
            plan asks for progress dots; a bar next to a bar reads as one timer). */}
        <div className="flex gap-1.5" aria-hidden="true">
          {Array.from({ length: state.rounds_total }).map((_, index) => (
            <span
              key={index}
              className={cx(
                "h-2.5 w-2.5 rounded-full",
                index < state.round_index ? "bg-brand" : "bg-line",
              )}
            />
          ))}
        </div>
      </div>

      <RoundClock
        round={round}
        started={started}
        onExpire={onExpire}
        label="Time left in this word"
      />

      {/* D.2.3: the consequence is said before it can happen, in a line a
          learner can point at when asked what an empty bar means. */}
      <p className="flex items-center gap-2 text-label font-semibold text-ink-muted">
        <Icon name="hourglass" size={16} />
        Empty bar, no points.
      </p>

      {/* A picture clue is a picture, never the raw key: the seed stores a
          pictogram, and a reviewed set of drawings can arrive later as a path
          or a URL without changing this screen (D.3). */}
      {round?.clue_image_key ? (
        round.clue_image_key.startsWith("http") || round.clue_image_key.startsWith("/") ? (
          <img
            src={round.clue_image_key}
            alt="Picture clue"
            className="h-32 w-32 rounded-2xl border border-line bg-surface object-cover"
          />
        ) : (
          <p className="text-[64px] leading-none">{round.clue_image_key}</p>
        )
      ) : null}

      {round.clue ? <p className="text-body font-semibold text-ink">{round.clue}</p> : null}

      <Card className="flex flex-col gap-4 p-4 sm:p-5">
        <div
          className="flex min-h-[68px] flex-wrap items-center gap-2 rounded-2xl border-2 border-dashed border-line bg-surface-muted p-3"
          aria-label="Your word"
        >
          {round?.revealed ? (
            <span className="tabular flex h-14 w-12 items-center justify-center rounded-xl border border-line bg-surface text-large font-bold uppercase text-ink">
              {round.revealed}
            </span>
          ) : null}

          {placed.map((index) => (
            <button
              key={`placed-${index}`}
              type="button"
              onClick={() => setPlaced((current) => current.filter((i) => i !== index))}
              className="tabular relative flex h-14 w-12 items-center justify-center rounded-xl bg-brand font-headline text-large font-bold uppercase text-white shadow-primary"
              aria-label={`Take back ${letters[index]}`}
            >
              {letters[index]}
              {/* D.3's visible undo: the tile you can tap back carries the mark. */}
              <span aria-hidden="true" className="absolute right-1 top-0 text-label leading-none">
                ×
              </span>
            </button>
          ))}

          {placed.length === 0 && !round?.revealed ? (
            <span className="text-body-min text-ink-muted">Your word goes here.</span>
          ) : null}
        </div>

        <div className="flex flex-wrap gap-2">
          {available.map((index) => (
            <button
              key={`tile-${index}`}
              type="button"
              onClick={() => setPlaced((current) => [...current, index])}
              disabled={pending}
              className="tabular flex min-h-target min-w-target items-center justify-center rounded-xl border-2 border-line bg-surface px-3 font-headline text-large font-bold uppercase text-ink shadow-tile transition-colors hover:border-brand hover:bg-brand-soft disabled:opacity-50"
              aria-label={`Letter ${letters[index]}`}
            >
              {letters[index]}
            </button>
          ))}
        </div>
      </Card>

      {feedback ? (
        <p
          role="status"
          className={cx(
            "flex items-center gap-2.5 rounded-2xl px-4 py-3 font-headline text-large font-bold",
            feedback.startsWith("Correct") ? "bg-ok-soft text-ok" : "bg-brand-soft text-brand-deep",
          )}
        >
          <Icon name={feedback.startsWith("Correct") ? "check" : "arrow-right"} size={22} />
          {feedback}
        </p>
      ) : null}

      {error ? <Alert>{error}</Alert> : null}

      <p className="text-label font-semibold text-ink-muted">
        {round?.tries_left === 1 ? "1 try left." : `${round?.tries_left} tries left.`}
      </p>

      <div className="flex flex-col gap-3">
        <Button
          size="lg"
          disabled={pending || word.length === 0}
          onClick={() => {
            setPlaced([]);
            onAnswer(word);
          }}
          arrow
          className="w-full"
        >
          Done
        </Button>

        <div className="grid gap-3 sm:grid-cols-2">
          <Button
            variant="ghost"
            disabled={pending || Boolean(round?.revealed)}
            onClick={onHint}
            icon="sparkles"
            className="w-full"
          >
            Take a letter (−3)
          </Button>
          <Button
            variant="ghost"
            disabled={pending}
            onClick={() => {
              setPlaced([]);
              onSkip();
            }}
            className="w-full"
          >
            I don&apos;t know
          </Button>
        </div>
      </div>
    </div>
  );
}

