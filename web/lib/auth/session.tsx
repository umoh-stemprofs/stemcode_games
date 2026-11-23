"use client";

/**
 * Session provider (P1-T07, D-19).
 *
 * The browser never sees a token: the API sets httpOnly cookies, and this
 * provider only asks "who am I?" through the same-origin `/api` path.
 *
 * On mount it tries `/api/auth/me`. If the 15-minute access cookie has expired
 * but the refresh cookie is still good, it performs exactly **one** silent
 * `POST /api/auth/refresh` and retries. If that fails the session is anonymous
 * and the caller decides where to send the person.
 */

import { useQueryClient } from "@tanstack/react-query";
import { useRouter } from "next/navigation";
import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
  type ReactNode,
} from "react";

import { ApiError, apiFetch } from "@/lib/api/client";

import type { Me, Role } from "./types";

type State =
  | { status: "loading" }
  | { status: "anonymous" }
  | { status: "authenticated"; me: Me };

type SessionValue = State & {
  /** Sign in with a student code and PIN. Throws `ApiError` for the form. */
  login: (code: string, pin: string) => Promise<void>;
  logout: () => Promise<void>;
  /** Re-read the session, e.g. after an admin changes something. */
  reload: () => Promise<void>;
  hasRole: (...roles: Role[]) => boolean;
};

const SessionContext = createContext<SessionValue | null>(null);

export function SessionProvider({ children }: { children: ReactNode }) {
  const [state, setState] = useState<State>({ status: "loading" });
  const router = useRouter();
  // Teachers share laptops. Whatever the last person loaded — a class, a limit,
  // a draft — must not still be on screen for the next one, so the cache is
  // dropped whenever the signed-in person changes.
  const queryClient = useQueryClient();

  const readSession = useCallback(async (): Promise<Me> => {
    try {
      return await apiFetch<Me>("/api/auth/me");
    } catch (error) {
      if (error instanceof ApiError && error.status === 401) {
        // Access cookie expired. One rotation attempt, never a loop.
        return await apiFetch<Me>("/api/auth/refresh", { method: "POST" });
      }
      throw error;
    }
  }, []);

  const reload = useCallback(async () => {
    try {
      const me = await readSession();
      setState({ status: "authenticated", me });
    } catch (error) {
      // A cookie can outlive the session it points at (a revoked login, or a
      // rebuilt database). The middleware only checks that a cookie exists, so
      // leaving it behind bounces /login straight back to a page with no
      // session — the person is stuck. Clear it when the server says the
      // session is not valid; a network failure is not proof of that.
      if (error instanceof ApiError && error.status === 401) {
        try {
          await apiFetch<null>("/api/auth/logout", { method: "POST" });
        } catch {
          // Already gone is the outcome we wanted.
        }
      }
      queryClient.clear();
      setState({ status: "anonymous" });
    }
  }, [readSession, queryClient]);

  useEffect(() => {
    void reload();
  }, [reload]);

  const login = useCallback(
    async (code: string, pin: string) => {
      const me = await apiFetch<Me>("/api/auth/login", {
        method: "POST",
        body: JSON.stringify({ code, pin }),
      });
      queryClient.clear();
      setState({ status: "authenticated", me });
      // Server-rendered parts of the tree may have been built while anonymous.
      router.refresh();
    },
    [router, queryClient],
  );

  const logout = useCallback(async () => {
    try {
      await apiFetch<null>("/api/auth/logout", { method: "POST" });
    } finally {
      queryClient.clear();
      setState({ status: "anonymous" });
      router.replace("/login");
      router.refresh();
    }
  }, [router, queryClient]);

  const value = useMemo<SessionValue>(() => {
    const hasRole = (...roles: Role[]) =>
      state.status === "authenticated" && roles.includes(state.me.user.role);

    return { ...state, login, logout, reload, hasRole };
  }, [state, login, logout, reload]);

  return <SessionContext.Provider value={value}>{children}</SessionContext.Provider>;
}

export function useSession(): SessionValue {
  const value = useContext(SessionContext);
  if (value === null) {
    throw new Error("useSession must be used inside <SessionProvider>");
  }
  return value;
}
