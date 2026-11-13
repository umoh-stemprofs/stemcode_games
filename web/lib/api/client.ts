/**
 * Typed fetch wrapper for the API (P0-T07).
 *
 * Types for individual responses are generated from the FastAPI schema into
 * `schema.ts`; this module only owns transport and the error envelope.
 *
 * The browser always calls same-origin `/api/*`: in development a Next rewrite
 * forwards it to FastAPI, and in production the reverse proxy does (D-19).
 */

export type ErrorEnvelope = {
  error: {
    code: string;
    message: string;
    details: Record<string, unknown>;
    request_id: string;
  };
};

export class ApiError extends Error {
  readonly code: string;
  readonly status: number;
  readonly requestId: string;
  readonly details: Record<string, unknown>;

  constructor(status: number, body: ErrorEnvelope) {
    super(body.error.message);
    this.name = "ApiError";
    this.status = status;
    this.code = body.error.code;
    this.requestId = body.error.request_id;
    this.details = body.error.details;
  }
}

function isErrorEnvelope(value: unknown): value is ErrorEnvelope {
  if (typeof value !== "object" || value === null) return false;
  const maybe = (value as { error?: unknown }).error;
  return typeof maybe === "object" && maybe !== null && "code" in maybe;
}

export async function apiFetch<T>(path: string, init: RequestInit = {}): Promise<T> {
  const response = await fetch(path, {
    ...init,
    credentials: "same-origin",
    headers: {
      Accept: "application/json",
      ...(init.body ? { "Content-Type": "application/json" } : {}),
      ...init.headers,
    },
  });

  const text = await response.text();
  const payload: unknown = text ? JSON.parse(text) : null;

  if (!response.ok) {
    if (isErrorEnvelope(payload)) throw new ApiError(response.status, payload);
    throw new ApiError(response.status, {
      error: {
        code: "unknown_error",
        message: "Something went wrong. Please try again.",
        details: {},
        request_id: "-",
      },
    });
  }

  return payload as T;
}

export type HealthResponse = { status: "ok" };

export function getHealth(): Promise<HealthResponse> {
  return apiFetch<HealthResponse>("/api/health");
}
