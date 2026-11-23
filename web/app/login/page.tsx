"use client";

/**
 * Sign-in screen (P1-T07, 0003_login_codes).
 *
 * A child types a short code and a PIN — no email address, no password. Staff
 * use the same two fields, so there is one form and one set of rules to learn.
 *
 * Appendix D applies here first, because this is the very first screen a child
 * meets: one decision (sign in), two steps, body text at 20px, targets at
 * 56px, and exactly one plain sentence when something goes wrong.
 *
 * The four PIN boxes are not decoration: four separate targets mean a child who
 * mistypes the third digit can fix the third digit, and the show/hide control
 * exists because a classmate leaning over a shoulder is the usual reason a PIN
 * is typed wrong.
 */

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useRef, useState, type ClipboardEvent, type FormEvent } from "react";

import { Icon } from "@/components/icons";
import { ApiError } from "@/lib/api/client";
import { sentenceFor } from "@/lib/auth/messages";
import { useSession } from "@/lib/auth/session";

const PIN_LENGTH = 4;

export default function LoginPage() {
  const session = useSession();
  const router = useRouter();

  const [code, setCode] = useState("");
  const [pin, setPin] = useState("");
  const [showPin, setShowPin] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [pending, setPending] = useState(false);
  const nextRef = useRef<string>("/");
  const pinRefs = useRef<Array<HTMLInputElement | null>>([]);

  // Read the return path from the address bar. Doing it here rather than with
  // `useSearchParams` keeps the page free of a Suspense boundary.
  useEffect(() => {
    const params = new URLSearchParams(window.location.search);
    const next = params.get("next");
    // Only same-origin paths: never follow an absolute URL from a query string.
    if (next && next.startsWith("/") && !next.startsWith("//")) {
      nextRef.current = next;
    }
  }, []);

  useEffect(() => {
    if (session.status === "authenticated") {
      router.replace(nextRef.current);
    }
  }, [session.status, router]);

  async function onSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setError(null);
    setPending(true);
    try {
      await session.login(code.trim(), pin);
      router.replace(nextRef.current);
    } catch (caught) {
      setError(
        caught instanceof ApiError
          ? sentenceFor(caught.code, caught.status)
          : sentenceFor(undefined),
      );
    } finally {
      setPending(false);
    }
  }

  /** One box changed: keep only digits, then hand the cursor to the next box. */
  function setDigit(index: number, raw: string) {
    const digit = raw.replace(/\D/g, "").slice(-1);
    const next = pin.split("");
    next[index] = digit;
    const joined = next.join("").slice(0, PIN_LENGTH);
    setPin(joined);
    if (digit && index < PIN_LENGTH - 1) {
      pinRefs.current[index + 1]?.focus();
    }
  }

  function onPinKeyDown(index: number, event: React.KeyboardEvent<HTMLInputElement>) {
    if (event.key === "Backspace" && !pin[index] && index > 0) {
      event.preventDefault();
      pinRefs.current[index - 1]?.focus();
      setPin(pin.slice(0, index - 1));
    }
  }

  /** A pasted PIN should fill the row, not one box. */
  function onPinPaste(event: ClipboardEvent<HTMLInputElement>) {
    const digits = event.clipboardData.getData("text").replace(/\D/g, "").slice(0, PIN_LENGTH);
    if (!digits) return;
    event.preventDefault();
    setPin(digits);
    pinRefs.current[Math.min(digits.length, PIN_LENGTH - 1)]?.focus();
  }

  const ready = code.trim().length > 0 && pin.length === PIN_LENGTH;

  return (
    <div className="flex min-h-screen flex-col bg-canvas">
      <header className="border-b border-line bg-surface">
        <div className="mx-auto flex w-full max-w-7xl items-center gap-3 px-4 py-4 md:px-8">
          <span
            aria-hidden="true"
            className="grid size-11 place-items-center rounded-2xl bg-brand text-white shadow-sm"
          >
            <Icon name="sparkles" size={22} />
          </span>
          <span className="flex flex-col leading-none">
            <span className="font-headline text-xl font-extrabold tracking-tight text-ink">
              STEM Games
            </span>
            <span className="mt-1 text-[10px] font-bold uppercase tracking-[0.18em] text-ink-muted">
              Games portal
            </span>
          </span>
        </div>
      </header>

      <main
        id="page-content"
        className="flex flex-1 flex-col items-center px-4 py-10 md:py-14"
      >
        <div className="flex w-full max-w-[580px] flex-col items-center">
          <div className="mb-8 flex flex-col gap-2 text-center">
            <h1 className="font-headline text-[clamp(30px,6vw,42px)] font-extrabold leading-tight tracking-tight text-ink">
              Sign in to play{" "}
              <span aria-hidden="true" className="inline-block">
                🚀
              </span>
            </h1>
            <p className="text-body text-ink-muted">Two steps and you are in.</p>
          </div>

          <div className="flex w-full flex-col gap-7 rounded-3xl border border-line bg-surface p-6 shadow-card sm:p-9">
            <form onSubmit={onSubmit} className="flex flex-col gap-6" noValidate>
              {/* Step 1 */}
              <div className="flex flex-col gap-4 rounded-2xl border border-line bg-surface-muted p-5">
                <label
                  htmlFor="code"
                  className="flex items-center gap-3 font-headline text-[21px] font-bold text-ink"
                >
                  <span className="grid size-8 place-items-center rounded-full bg-brand text-[15px] font-bold text-white">
                    1
                  </span>
                  Student code
                </label>

                <div className="relative flex items-center">
                  <Icon
                    name="badge"
                    size={22}
                    className="pointer-events-none absolute left-4 text-ink-muted"
                  />
                  <input
                    id="code"
                    name="code"
                    type="text"
                    autoComplete="username"
                    autoCapitalize="characters"
                    spellCheck={false}
                    required
                    placeholder="A-1001"
                    value={code}
                    onChange={(event) => setCode(event.target.value.toUpperCase())}
                    aria-describedby={error ? "login-error" : undefined}
                    className="tabular h-16 w-full rounded-xl border border-line bg-surface pl-14 pr-4 text-2xl font-bold uppercase tracking-[0.12em] text-ink outline-none transition-colors placeholder:font-normal placeholder:tracking-normal placeholder:text-ink-muted focus:border-brand focus:ring-4 focus:ring-brand-soft"
                  />
                </div>

                <p className="flex items-center gap-2.5 rounded-xl border border-line bg-surface px-3.5 py-2.5 text-label font-semibold text-ink-muted">
                  <Icon name="badge" size={19} className="shrink-0 text-brand" />
                  Check the badge taped to your desk.
                </p>
              </div>

              {/* Step 2 */}
              <div className="flex flex-col gap-4 rounded-2xl border border-line bg-surface-muted p-5">
                <span className="flex items-center gap-3 font-headline text-[21px] font-bold text-ink">
                  <span className="grid size-8 place-items-center rounded-full bg-brand text-[15px] font-bold text-white">
                    2
                  </span>
                  Secret 4-digit PIN
                </span>

                <div className="grid grid-cols-4 gap-3">
                  {Array.from({ length: PIN_LENGTH }).map((_, index) => (
                    <input
                      key={index}
                      ref={(node) => {
                        pinRefs.current[index] = node;
                      }}
                      aria-label={`PIN digit ${index + 1} of ${PIN_LENGTH}`}
                      inputMode="numeric"
                      autoComplete="current-password"
                      pattern="[0-9]*"
                      maxLength={1}
                      type={showPin ? "text" : "password"}
                      value={pin[index] ?? ""}
                      onChange={(event) => setDigit(index, event.target.value)}
                      onKeyDown={(event) => onPinKeyDown(index, event)}
                      onPaste={onPinPaste}
                      className="tabular h-16 w-full rounded-xl border border-line bg-surface text-center text-3xl font-extrabold text-ink outline-none transition-colors focus:border-brand focus:ring-4 focus:ring-brand-soft sm:h-20"
                    />
                  ))}
                </div>

                <div className="flex flex-wrap items-center justify-between gap-2">
                  <p className="flex items-center gap-2 text-label font-semibold text-ink-muted">
                    <Icon name="key" size={18} className="text-brand" />
                    Four numbers
                  </p>
                  <button
                    type="button"
                    onClick={() => setShowPin((value) => !value)}
                    aria-pressed={showPin}
                    className="flex min-h-[44px] items-center gap-2 rounded-pill border border-line bg-surface px-3.5 text-label font-bold text-ink transition-colors hover:bg-canvas"
                  >
                    <Icon name={showPin ? "eye-off" : "eye"} size={18} />
                    {showPin ? "Hide numbers" : "Show numbers"}
                  </button>
                </div>
              </div>

              {error ? (
                <p
                  id="login-error"
                  role="alert"
                  className="rounded-2xl border border-line bg-danger-soft px-4 py-3 text-body-min font-semibold text-ink"
                >
                  {error}
                </p>
              ) : null}

              <button
                type="submit"
                disabled={pending || !ready}
                className="flex min-h-[64px] w-full items-center justify-center gap-3 rounded-2xl bg-brand px-6 font-headline text-xl font-bold text-white shadow-primary transition-colors hover:bg-brand-deep disabled:cursor-not-allowed disabled:opacity-50"
              >
                {pending ? "Signing you in…" : "Let’s play!"}
                {pending ? null : <Icon name="arrow-right" size={24} />}
              </button>
            </form>

            {/* Help is a sentence, not a button that pretends to call a teacher. */}
            <div className="flex items-center gap-4 rounded-2xl border border-line bg-sun-soft p-4">
              <span
                aria-hidden="true"
                className="grid size-12 shrink-0 place-items-center rounded-xl bg-surface text-sun-ink"
              >
                <Icon name="message" size={24} />
              </span>
              <span className="flex flex-col gap-0.5">
                <span className="font-headline text-body-min font-bold text-ink">
                  Stuck? Ask your Coach.
                </span>
                <span className="text-body-min text-ink-muted">
                  A teacher will come to your desk.
                </span>
              </span>
            </div>
          </div>

          <p className="mt-6 text-body-min text-ink-muted">
            <Link href="/" className="underline underline-offset-4">
              Back to the start
            </Link>
          </p>
        </div>
      </main>
    </div>
  );
}
