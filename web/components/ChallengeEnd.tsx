"use client";

/**
 * What the end screen says after playing a friend (P7-T05, P7-T09).
 *
 * One sentence from the server — "Amara won Number Guess this time." — and, if
 * the challenge is decided, one button that says `Report`.
 *
 * Nothing here is a number the learner has to work out, and nothing is shown
 * about the other attempt until both are in: while you wait it says
 * "Waiting for Amara to play." and no scores at all.
 *
 * The same component doubles as the report flow because a report can only be
 * about somebody you played: tap `Report`, tap a reason, done. Two taps, two
 * screens, one decision each (Appendix D).
 */

import { useState } from "react";

import { useQuery } from "@tanstack/react-query";

import { Icon } from "@/components/icons";
import { Alert, Button, Card } from "@/components/ui";
import { ApiError, apiFetch } from "@/lib/api/client";
import type { ChallengeResult } from "@/lib/games/social";

/** The four reasons the API accepts, each with the words a child reads. */
const REASONS = [
  { value: "bullying", label: "Unkind words" },
  { value: "cheating", label: "Cheating" },
  { value: "inappropriate_name", label: "An unkind name" },
  { value: "other", label: "Something else" },
] as const;

type Reason = (typeof REASONS)[number]["value"];

export function ChallengeEnd({ sessionId }: { sessionId: string }) {
  const result = useQuery({
    queryKey: ["challenge", sessionId],
    queryFn: () =>
      apiFetch<ChallengeResult | null>(`/api/games/sessions/${sessionId}/challenge`),
  });

  const [asking, setAsking] = useState(false);
  const [sent, setSent] = useState(false);
  const [error, setError] = useState<string | null>(null);

  if (!result.data) return null;
  const challenge = result.data;

  async function report(reason: Reason) {
    setError(null);
    try {
      await apiFetch("/api/games/reports", {
        method: "POST",
        body: JSON.stringify({
          reported_id: challenge.opponent_id,
          reason,
          session_id: sessionId,
        }),
      });
      setSent(true);
      setAsking(false);
    } catch (caught) {
      setError(caught instanceof ApiError ? caught.message : "That did not work. Try again.");
    }
  }

  if (asking) {
    return (
      <Card className="flex flex-col gap-4 p-6">
        <h2 className="font-headline text-large font-extrabold text-ink">What happened?</h2>

        {error ? <Alert>{error}</Alert> : null}

        <div className="flex flex-col gap-3">
          {REASONS.map((reason) => (
            <Button
              key={reason.value}
              variant="ghost"
              onClick={() => void report(reason.value)}
              className="w-full justify-start"
            >
              {reason.label}
            </Button>
          ))}
        </div>

        <Button variant="quiet" onClick={() => setAsking(false)} className="w-full">
          Never mind
        </Button>
      </Card>
    );
  }

  return (
    <Card className="flex flex-col gap-4 p-6">
      <p className="flex items-start gap-3 font-headline text-large font-bold text-ink">
        <Icon name="users" size={22} className="mt-0.5 shrink-0 text-brand" />
        {challenge.sentence}
      </p>

      {sent ? (
        <p
          role="status"
          className="flex items-center gap-2 rounded-2xl bg-ok-soft px-4 py-3 text-body-min font-semibold text-ok"
        >
          <Icon name="check" size={18} />
          Thank you. A grown-up will look at this.
        </p>
      ) : null}

      {!sent && challenge.settled && challenge.opponent_id ? (
        <Button
          variant="ghost"
          size="sm"
          icon="flag"
          onClick={() => setAsking(true)}
          className="w-full sm:w-fit"
        >
          Report
        </Button>
      ) : null}
    </Card>
  );
}
