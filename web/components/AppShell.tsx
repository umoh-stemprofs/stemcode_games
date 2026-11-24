"use client";

/**
 * The signed-in frame: role-aware navigation, who you are, and sign out.
 *
 * Three jobs beyond layout:
 *
 * 1. **Auth guard.** Anything rendered inside the shell requires a session. The
 *    middleware already redirected people with no cookie at all; this catches
 *    the case where a cookie exists but the server rejects it (expired,
 *    revoked, account disabled).
 * 2. **Role-aware navigation.** A learner sees the three places a learner has;
 *    staff see theirs. The API still decides what the pages may *contain* —
 *    hiding a link is a courtesy, never the authorization.
 * 3. **A header that fits a phone.** The old bar wrapped its own controls off
 *    the screen at 390px. The menu now drops to its own scrollable row below
 *    the brand row, so nothing ever clips.
 */

import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useEffect, type ReactNode } from "react";

import { Icon } from "@/components/icons";
import { InviteAlert } from "@/components/InviteAlert";
import { OfflineSync } from "@/components/OfflineSync";
import { PresenceHeartbeat } from "@/components/PresenceHeartbeat";
import { QuitGuardProvider, useQuitGuard } from "@/components/QuitGuard";
import { TimeMeter } from "@/components/TimeMeter";
import { XpChip } from "@/components/XpChip";
import { avatarEmoji, avatarLabel } from "@/lib/avatars";
import { useSession } from "@/lib/auth/session";
import type { Role } from "@/lib/auth/types";

type NavItem = { href: string; label: string };

const DASHBOARD: NavItem = { href: "/", label: "Dashboard" };
const GAMES_HUB: NavItem = { href: "/games", label: "Games Hub" };
const BOARD: NavItem = { href: "/leaderboards", label: "Leaderboard" };
const CLASSES: NavItem = { href: "/classes", label: "Classes" };
const TIME_LIMITS: NavItem = { href: "/coach/limits", label: "Time limits" };
const WORDS: NavItem = { href: "/coach/content", label: "Words" };
const BLOCKED: NavItem = { href: "/coach/blocked", label: "Blocked words" };
const REPORTS: NavItem = { href: "/coach/reports", label: "Reports" };
const CLASS_XP: NavItem = { href: "/coach/xp", label: "XP" };

// Three roles, so three menus (D-37). A coach runs a class and writes words; a
// school admin runs the school and is the one who can take a word down.
// A learner's menu is deliberately three items: more than that is a decision
// before the game, and the rest is one tap from the dashboard.
const NAV_BY_ROLE: Record<Role, NavItem[]> = {
  learner: [DASHBOARD, GAMES_HUB, BOARD],
  coach: [DASHBOARD, CLASSES, TIME_LIMITS, WORDS, BOARD, CLASS_XP],
  school_admin: [DASHBOARD, CLASSES, TIME_LIMITS, WORDS, BLOCKED, REPORTS, BOARD, CLASS_XP],
};

export function AppShell({ children }: { children: ReactNode }) {
  const session = useSession();
  const router = useRouter();
  const pathname = usePathname();

  useEffect(() => {
    if (session.status === "anonymous") {
      const next = pathname === "/" ? "" : `?next=${encodeURIComponent(pathname)}`;
      router.replace(`/login${next}`);
    }
  }, [session.status, router, pathname]);

  if (session.status !== "authenticated") {
    return (
      <main className="mx-auto flex min-h-screen max-w-2xl items-center justify-center p-6">
        <p className="text-body text-ink-muted" role="status">
          {session.status === "loading" ? "Just a moment." : "Please sign in again."}
        </p>
      </main>
    );
  }

  const { me } = session;
  const items = NAV_BY_ROLE[me.user.role] ?? [DASHBOARD];
  const isLearner = me.user.role === "learner";

  return (
    <QuitGuardProvider>
      {/* P9-T02: the offline games keep themselves ready. No button, no
          prompt — every learner gets their words saved on first load. */}
      <OfflineSync />
      {/* "I am here", so a classmate's roster can show a dot beside this
          learner's name. It expires by itself; no logout to remember. */}
      <PresenceHeartbeat />
      {/* A friend's invitation finds the learner wherever they are, then gets
          out of the way: ten seconds on screen, then a corner button. */}
      <InviteAlert />
      <div className="flex min-h-screen flex-col">
        <header className="sticky top-0 z-30 border-b border-line bg-surface">
          <div className="mx-auto flex w-full max-w-7xl items-center gap-2 px-4 py-3 md:px-6 lg:px-8">
            <Link href="/" className="flex shrink-0 items-center gap-3" aria-label="STEM Games home">
              <span
                aria-hidden="true"
                className="grid size-10 place-items-center rounded-2xl bg-brand text-white shadow-sm"
              >
                <Icon name="sparkles" size={21} />
              </span>
              <span className="flex flex-col leading-none">
                <span className="font-headline text-[19px] font-extrabold tracking-tight text-ink">
                  STEM Games
                </span>
                <span className="mt-1 text-[10px] font-bold uppercase tracking-[0.18em] text-ink-muted">
                  Games portal
                </span>
              </span>
            </Link>

            <nav aria-label="Main" className="ml-3 hidden items-center gap-1 border-l border-line pl-3 md:flex">
              {items.map((item) => (
                <NavTab key={item.href} item={item} pathname={pathname} />
              ))}
            </nav>

            <div className="ml-auto flex items-center gap-2">
              {/* Phones get the same meter in their own row under the menu: at
                  390px there is no room for a sentence beside the brand. */}
              <div className="hidden sm:block">{isLearner ? <TimeMeter /> : null}</div>
              {isLearner ? <XpChip /> : null}

              {/* The avatar is the fourth door without a fourth tab: a learner's
                  streak, level, badges and bests live one tap away, on /me. */}
              {isLearner ? (
                <Link
                  href="/me"
                  title={`${me.user.preferred_name} · Me`}
                  className="hidden items-center gap-2 rounded-full transition-colors hover:bg-surface-muted sm:flex"
                >
                  <span
                    aria-hidden="true"
                    className="grid size-9 place-items-center rounded-full bg-canvas text-[19px] ring-2 ring-line"
                  >
                    {avatarEmoji(me.user.avatar_key)}
                  </span>
                  <span className="sr-only">{avatarLabel(me.user.avatar_key)}, </span>
                  <span className="hidden max-w-[9rem] truncate font-headline text-label font-bold text-ink lg:inline">
                    {me.user.preferred_name}
                  </span>
                </Link>
              ) : (
                <span
                  className="hidden items-center gap-2 sm:flex"
                  title={`${me.user.preferred_name} · Teacher`}
                >
                  <span
                    aria-hidden="true"
                    className="grid size-9 place-items-center rounded-full bg-canvas text-[19px] ring-2 ring-line"
                  >
                    {avatarEmoji(me.user.avatar_key)}
                  </span>
                  <span className="sr-only">{avatarLabel(me.user.avatar_key)}, </span>
                  <span className="hidden max-w-[9rem] truncate font-headline text-label font-bold text-ink lg:inline">
                    {me.user.preferred_name}
                  </span>
                </span>
              )}

              <button
                type="button"
                onClick={() => void session.logout()}
                className="flex min-h-[44px] shrink-0 items-center gap-2 whitespace-nowrap rounded-2xl border border-line px-3 text-label font-bold text-ink-muted transition-colors hover:bg-surface-muted hover:text-ink"
              >
                <Icon name="logout" size={17} />
                <span className="sr-only sm:not-sr-only">Sign out</span>
              </button>
            </div>
          </div>

          {/* Phone: the menu gets its own row instead of fighting the brand for
              space. It scrolls sideways rather than wrapping the header taller. */}
          <div className="border-t border-line px-3 py-2 md:hidden">
            <nav aria-label="Main" className="-mx-1 flex items-center gap-1 overflow-x-auto px-1 pb-0.5">
              {items.map((item) => (
                <NavTab key={item.href} item={item} pathname={pathname} />
              ))}
            </nav>
          </div>
        </header>

        <main
          id="page-content"
          className="mx-auto w-full max-w-7xl flex-1 px-4 py-6 md:px-6 lg:px-8 lg:py-10"
        >
          {isLearner ? (
            <div className="mb-5 sm:hidden">
              <TimeMeter />
            </div>
          ) : null}
          {children}
        </main>
      </div>
    </QuitGuardProvider>
  );
}

/**
 * One menu tab. The only special case: a tab tapped mid-game asks first,
 * because leaving ends the attempt (see `QuitGuard`).
 */
function NavTab({ item, pathname }: { item: NavItem; pathname: string }) {
  const guard = useQuitGuard();
  const active = item.href === "/" ? pathname === "/" : pathname.startsWith(item.href);

  return (
    <Link
      href={item.href}
      aria-current={active ? "page" : undefined}
      onClick={(event) => {
        if (!guard.active) return;
        event.preventDefault();
        guard.leave(item.href);
      }}
      className={`flex min-h-[44px] shrink-0 items-center whitespace-nowrap rounded-xl px-3.5 font-headline text-[15px] font-semibold transition-colors ${
        active
          ? "bg-brand-soft text-brand-deep"
          : "text-ink-muted hover:bg-surface-muted hover:text-ink"
      }`}
    >
      {item.label}
    </Link>
  );
}
