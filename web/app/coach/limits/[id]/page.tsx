"use client";

/**
 * One class: who has how much time, and what the coach can change (P3-T10).
 *
 * The table is the truth the learner sees, resolved by the same server call
 * that draws a child's own meter — so a coach cannot be told a different
 * number than the child.
 *
 * Two changes are possible, and only two: give a different daily limit, or
 * pause games for a while. Both need a reason, because a parent will ask why.
 * History sits under the table: never hidden, never editable.
 */

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useParams } from "next/navigation";
import { useState, type FormEvent } from "react";

import { AppShell } from "@/components/AppShell";
import { Icon } from "@/components/icons";
import { NoAccess } from "@/components/NoAccess";
import {
  Alert,
  Button,
  ButtonLink,
  Card,
  Chip,
  Loading,
  PageHeader,
} from "@/components/ui";
import { ApiError, apiFetch } from "@/lib/api/client";
import { sentenceFor } from "@/lib/auth/messages";
import { useSession } from "@/lib/auth/session";
import type { Role } from "@/lib/auth/types";
import {
  formatDate,
  formatTime,
  limitSourceLabel,
  minutesPhrase,
  REASON_LABEL,
  toLocalInput,
} from "@/lib/games/time";
import type {
  AccessPolicy,
  ClassAccessTable,
  Lockout,
  MemberAccessRow,
} from "@/lib/games/types";
import { avatarEmoji, avatarLabel } from "@/lib/avatars";

const STAFF: Role[] = ["coach", "school_admin"];

type Panel =
  | { mode: "limit"; userId: string; name: string }
  | { mode: "lockout"; userId: string; name: string }
  | { mode: "class-limit" }
  | null;

export default function ClassLimitsPage() {
  return (
    <AppShell>
      <ClassLimitsBody />
    </AppShell>
  );
}

function ClassLimitsBody() {
  const params = useParams<{ id: string }>();
  const classId = params.id;
  const session = useSession();
  const allowed = session.status === "authenticated" && STAFF.includes(session.me.user.role);
  const [panel, setPanel] = useState<Panel>(null);

  const table = useQuery({
    queryKey: ["class-access", classId],
    queryFn: () => apiFetch<ClassAccessTable>(`/api/games/classes/${classId}/access`),
    enabled: allowed,
  });
  const policies = useQuery({
    queryKey: ["limits"],
    queryFn: () => apiFetch<AccessPolicy[]>("/api/games/limits"),
    enabled: allowed,
  });
  const lockouts = useQuery({
    queryKey: ["lockouts"],
    queryFn: () => apiFetch<Lockout[]>("/api/games/lockouts"),
    enabled: allowed,
  });

  if (session.status === "authenticated" && !allowed) return <NoAccess />;

  if (table.isError) {
    const error = table.error;
    return (
      <div className="flex flex-col gap-4">
        <Alert>
          {sentenceFor(
            error instanceof ApiError ? error.code : undefined,
            error instanceof ApiError ? error.status : undefined,
          )}
        </Alert>
        <ButtonLink href="/coach/limits" variant="ghost" icon="arrow-left" className="w-full sm:w-fit">
          Go back
        </ButtonLink>
      </div>
    );
  }

  if (table.isPending || !table.data) {
    return <Loading />;
  }

  const timezone = session.status === "authenticated" ? session.me.school.timezone : "UTC";
  const data = table.data;
  const memberIds = new Set(data.members.map((m) => m.user_id));

  const classPolicies = (policies.data ?? []).filter(
    (p) =>
      (p.scope_type === "class" && p.scope_id === classId) ||
      (p.scope_type === "student" && p.scope_id !== null && memberIds.has(p.scope_id)),
  );
  const classLockouts = (lockouts.data ?? []).filter(
    (l) =>
      (l.scope_type === "class" && l.scope_id === classId) ||
      (l.scope_type === "student" && memberIds.has(l.scope_id)),
  );

  return (
    <div className="flex flex-col gap-8">
      <PageHeader
        icon="clock"
        title={data.class_name}
        subtitle={
          data.members.length === 1
            ? "There is 1 learner here."
            : `There are ${data.members.length} learners here.`
        }
        action={
          <ButtonLink href="/coach/limits" variant="ghost" size="sm" icon="arrow-left">
            All classes
          </ButtonLink>
        }
      />

      <Button
        onClick={() => setPanel({ mode: "class-limit" })}
        icon="users"
        arrow
        className="w-full sm:w-fit"
      >
        Set time for the whole class
      </Button>

      {panel?.mode === "class-limit" ? (
        <LimitForm
          classId={classId}
          classLabel={data.class_name}
          onClose={() => setPanel(null)}
        />
      ) : null}

      {panel?.mode === "limit" ? (
        <LimitForm
          classId={classId}
          studentId={panel.userId}
          studentName={panel.name}
          onClose={() => setPanel(null)}
        />
      ) : null}

      {panel?.mode === "lockout" ? (
        <LockoutForm
          classId={classId}
          studentId={panel.userId}
          studentName={panel.name}
          onClose={() => setPanel(null)}
        />
      ) : null}

      <ul className="flex flex-col gap-3">
        {data.members.map((member) => (
          <LearnerRow
            key={member.user_id}
            member={member}
            timezone={timezone}
            onChange={() =>
              setPanel({ mode: "limit", userId: member.user_id, name: member.preferred_name })
            }
            onLockout={() =>
              setPanel({ mode: "lockout", userId: member.user_id, name: member.preferred_name })
            }
          />
        ))}
      </ul>

      <section className="flex flex-col gap-3">
        <h2 className="font-headline text-large font-extrabold text-ink">Recent changes</h2>

        {classPolicies.length === 0 && classLockouts.length === 0 ? (
          <p className="rounded-2xl bg-surface-muted px-4 py-3 text-body-min text-ink-muted">
            Nothing has changed yet.
          </p>
        ) : (
          <ul className="flex flex-col gap-2">
            {classPolicies.map((policy) => (
              <li
                key={policy.id}
                className="flex flex-wrap items-center gap-x-2 gap-y-1 rounded-2xl border border-line bg-surface px-4 py-3 text-body-min"
              >
                <Chip tone="blue">{policy.daily_limit_minutes} minutes</Chip>
                <span className="text-ink">{policy.reason}</span>
                <span className="ml-auto text-label text-ink-muted">
                  {formatDate(policy.created_at, timezone)}
                </span>
              </li>
            ))}
            {classLockouts.map((lockout) => (
              <li
                key={lockout.id}
                className="flex flex-wrap items-center gap-x-2 gap-y-1 rounded-2xl border border-line bg-surface px-4 py-3 text-body-min"
              >
                <Chip tone="sun">Paused</Chip>
                <span className="text-ink">{lockout.reason}</span>
                <span className="ml-auto text-label text-ink-muted">
                  until {formatTime(lockout.expires_at, timezone)}
                  {lockout.revoked_at ? " — ended early" : ""}
                </span>
              </li>
            ))}
          </ul>
        )}
      </section>
    </div>
  );
}

function LearnerRow({
  member,
  timezone,
  onChange,
  onLockout,
}: {
  member: MemberAccessRow;
  timezone: string;
  onChange: () => void;
  onLockout: () => void;
}) {
  const paused = member.locked_until !== null && member.lockout_reason !== null;
  const label = paused
    ? `Paused until ${formatTime(member.locked_until as string, timezone)}`
    : `${minutesPhrase(member.remaining_seconds)} left`;

  return (
    <li>
      <Card className="flex flex-col gap-3 p-5">
        <div className="flex items-center gap-3">
          <span
            aria-hidden="true"
            className="grid size-11 shrink-0 place-items-center rounded-full bg-canvas text-[22px] ring-2 ring-line"
          >
            {avatarEmoji(member.avatar_key)}
          </span>
          <div className="flex min-w-0 flex-col">
            <span className="font-headline text-body-min font-bold text-ink">
              {member.preferred_name}
            </span>
            <span className="text-label text-ink-muted">
              {avatarLabel(member.avatar_key)} · {label}
            </span>
            <span className="text-label text-ink-muted">
              {member.limit_minutes} minutes a day · {limitSourceLabel(member.limit_source)}
            </span>
          </div>
          {paused ? (
            <Chip tone="sun" className="ml-auto">
              {REASON_LABEL.locked_out}
            </Chip>
          ) : null}
        </div>

        <div className="grid gap-2 sm:grid-cols-2">
          <Button variant="ghost" size="sm" onClick={onChange} className="w-full">
            Change time
          </Button>
          <Button variant="ghost" size="sm" onClick={onLockout} className="w-full">
            Pause games
          </Button>
        </div>
      </Card>
    </li>
  );
}

function LimitForm({
  classId,
  studentId,
  studentName,
  classLabel,
  onClose,
}: {
  classId: string;
  studentId?: string;
  studentName?: string;
  classLabel?: string;
  onClose: () => void;
}) {
  const queryClient = useQueryClient();
  const [minutes, setMinutes] = useState("60");
  const [reason, setReason] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [saved, setSaved] = useState(false);

  const save = useMutation({
    mutationFn: (payload: {
      scope_type: "class" | "student";
      scope_id: string;
      daily_limit_minutes: number;
      reason: string;
    }) =>
      apiFetch<AccessPolicy>("/api/games/limits", {
        method: "POST",
        body: JSON.stringify(payload),
      }),
    onSuccess: () => {
      setSaved(true);
      void queryClient.invalidateQueries({ queryKey: ["class-access", classId] });
      void queryClient.invalidateQueries({ queryKey: ["limits"] });
      void queryClient.invalidateQueries({ queryKey: ["access"] });
    },
    onError: (caught) => {
      setError(
        caught instanceof ApiError
          ? sentenceFor(caught.code, caught.status)
          : sentenceFor(undefined),
      );
    },
  });

  function onSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setError(null);
    save.mutate({
      scope_type: studentId ? "student" : "class",
      scope_id: studentId ?? classId,
      daily_limit_minutes: Number(minutes),
      reason,
    });
  }

  return (
    <Card aria-label="Change time limit" className="flex flex-col gap-4 p-6">
      <h2 className="flex items-center gap-2 font-headline text-large font-extrabold text-ink">
        <Icon name="clock" size={22} className="text-brand" />
        {studentId ? `Time for ${studentName}` : `Time for ${classLabel}`}
      </h2>

      <form onSubmit={onSubmit} className="flex flex-col gap-4">
        <div className="flex flex-col gap-1.5">
          <label htmlFor="minutes" className="text-label font-bold text-ink-muted">
            Minutes a day
          </label>
          <input
            id="minutes"
            type="number"
            min={0}
            max={240}
            step={5}
            required
            value={minutes}
            onChange={(event) => setMinutes(event.target.value)}
            className="tabular min-h-target rounded-xl border border-line bg-surface px-4 text-large text-ink"
          />
          <p className="text-label text-ink-muted">Between 0 and 240 minutes.</p>
        </div>

        <div className="flex flex-col gap-1.5">
          <label htmlFor="reason" className="text-label font-bold text-ink-muted">
            Why?
          </label>
          <input
            id="reason"
            type="text"
            required
            maxLength={200}
            value={reason}
            onChange={(event) => setReason(event.target.value)}
            className="min-h-target rounded-xl border border-line bg-surface px-4 text-body text-ink"
          />
        </div>

        {error ? <Alert>{error}</Alert> : null}
        {saved ? (
          <p role="status" className="flex items-center gap-2 rounded-2xl bg-ok-soft px-4 py-3 text-body-min font-semibold text-ok">
            <Icon name="check" size={18} />
            Saved.
          </p>
        ) : null}

        <div className="grid gap-2 sm:grid-cols-2">
          <Button type="submit" disabled={save.isPending} arrow className="w-full">
            {save.isPending ? "Saving…" : "Save"}
          </Button>
          <Button variant="ghost" onClick={onClose} className="w-full">
            Close
          </Button>
        </div>
      </form>
    </Card>
  );
}

function LockoutForm({
  classId,
  studentId,
  studentName,
  onClose,
}: {
  classId: string;
  studentId: string;
  studentName: string;
  onClose: () => void;
}) {
  const queryClient = useQueryClient();
  const [reason, setReason] = useState("");
  const [until, setUntil] = useState(() => toLocalInput(new Date(Date.now() + 60 * 60_000)));
  const [error, setError] = useState<string | null>(null);

  const save = useMutation({
    mutationFn: (payload: {
      scope_type: "student";
      scope_id: string;
      reason: string;
      expires_at: string;
    }) =>
      apiFetch<Lockout>("/api/games/lockouts", {
        method: "POST",
        body: JSON.stringify(payload),
      }),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ["class-access", classId] });
      void queryClient.invalidateQueries({ queryKey: ["lockouts"] });
      void queryClient.invalidateQueries({ queryKey: ["access"] });
      onClose();
    },
    onError: (caught) => {
      setError(
        caught instanceof ApiError
          ? sentenceFor(caught.code, caught.status)
          : sentenceFor(undefined),
      );
    },
  });

  function onSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setError(null);
    save.mutate({
      scope_type: "student",
      scope_id: studentId,
      reason,
      expires_at: new Date(until).toISOString(),
    });
  }

  return (
    <Card aria-label="Pause games" className="flex flex-col gap-4 border-2 border-line p-6">
      <h2 className="flex items-center gap-2 font-headline text-large font-extrabold text-ink">
        <Icon name="lock" size={22} className="text-sun-ink" />
        Pause games for {studentName}
      </h2>
      <p className="text-body-min text-ink-muted">They can play again when this ends.</p>

      <form onSubmit={onSubmit} className="flex flex-col gap-4">
        <div className="flex flex-col gap-1.5">
          <label htmlFor="lockout-reason" className="text-label font-bold text-ink-muted">
            Why?
          </label>
          <input
            id="lockout-reason"
            type="text"
            required
            maxLength={200}
            value={reason}
            onChange={(event) => setReason(event.target.value)}
            className="min-h-target rounded-xl border border-line bg-surface px-4 text-body text-ink"
          />
        </div>

        <div className="flex flex-col gap-1.5">
          <label htmlFor="until" className="text-label font-bold text-ink-muted">
            Until
          </label>
          <input
            id="until"
            type="datetime-local"
            required
            value={until}
            onChange={(event) => setUntil(event.target.value)}
            className="min-h-target rounded-xl border border-line bg-surface px-4 text-body text-ink"
          />
        </div>

        {error ? <Alert>{error}</Alert> : null}

        <div className="grid gap-2 sm:grid-cols-2">
          <Button type="submit" disabled={save.isPending} icon="lock" className="w-full">
            {save.isPending ? "Pausing…" : "Pause games"}
          </Button>
          <Button variant="ghost" onClick={onClose} className="w-full">
            Close
          </Button>
        </div>
      </form>
    </Card>
  );
}
