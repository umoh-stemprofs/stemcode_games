/**
 * Live Checkers over the socket (Phase 8).
 *
 * The browser talks to the same origin for everything except the socket: Next
 * rewrites cannot upgrade a connection, so in development `/ws/games` goes to
 * the API port directly (see `next.config.mjs`) and in production the reverse
 * proxy owns the path. The ticket is fetched with an ordinary cookie-authenticated
 * REST call and is good for one handshake, thirty seconds (P8-T01).
 */

export type Seat = "white" | "black";

export type LegalMove = {
  from: number;
  to: number;
  path: number[];
  captures: number[];
  king: boolean;
  key: string;
};

/**
 * Every legal move is a capture, so another piece may not move at all (D.3).
 *
 * The server sends only this player's legal moves, so the question "must I
 * jump?" is answered by asking whether any of them avoids a capture.
 */
export function mustJump(moves: LegalMove[]): boolean {
  return moves.length > 0 && moves.every((move) => move.captures.length > 0);
}

export type LiveState = {
  session_id: string;
  game_id: string;
  status: "created" | "ready" | "active" | "paused" | "finished" | "abandoned" | "expired" | string;
  seat: Seat;
  side_to_move: Seat;
  your_turn: boolean;
  board: number[];
  legal_moves: LegalMove[];
  move_number: number;
  clock_ms: Record<string, number>;
  increment_ms: number;
  moves_by: Record<string, number>;
  captures: Record<string, number>;
  opponent: { name: string | null; connected: boolean };
  you_connected: boolean;
  draw_offer_from: Seat | null;
  draw_offered_at: string | null;
  outcome: { winner: Seat | null; reason: string } | null;
  moves_since_progress: number;
};

export type PresenceRow = {
  user_id: string;
  name: string;
  avatar_key: string;
  status: "available" | "in_match" | "busy";
  /** Their browser is open right now. Not a promise that they are free. */
  online: boolean;
  sentence: string;
};

export type LiveCreated = {
  session_id: string;
  game_name: string;
  invitation_id: string;
  code: string | null;
  formatted_code: string | null;
  join_path: string | null;
  expires_sentence: string;
};

export type Ticket = { ticket: string; expires_in: number };

/** A frame from the server. `match.state` carries a whole snapshot of *this* player. */
export type ServerEvent =
  | ({ type: "match.state"; seq?: number } & LiveState)
  | { type: "move.accepted"; move_number: number; by: Seat }
  | { type: "move.rejected"; code: string; message: string }
  | { type: "match.ended"; reason?: string }
  | { type: "clock.sync"; clock_ms: Record<string, number>; move_number: number; status: string }
  | { type: "error"; code: string }
  | { type: "ping" };

export class LiveSocket {
  private socket: WebSocket | null = null;
  private closed = false;
  private retry = 0;
  private timer: ReturnType<typeof setTimeout> | null = null;

  constructor(
    private readonly sessionId: string,
    private readonly handlers: {
      onEvent: (event: ServerEvent) => void;
      onOpen: () => void;
      onClose: () => void;
      ticket: () => Promise<string>;
    },
  ) {}

  connect() {
    this.closed = false;
    void this.open();
  }

  private async open() {
    if (this.closed) return;
    let ticket: string;
    try {
      ticket = await this.handlers.ticket();
    } catch {
      this.scheduleRetry();
      return;
    }
    const socket = new WebSocket(`${socketOrigin()}/ws/games?ticket=${encodeURIComponent(ticket)}`);
    this.socket = socket;

    socket.onopen = () => {
      this.retry = 0;
      this.handlers.onOpen();
      this.send({ type: "match.join" });
    };

    socket.onmessage = (message) => {
      try {
        const event = JSON.parse(String(message.data)) as ServerEvent;
        this.handlers.onEvent(event);
      } catch {
        // A frame we cannot read is not a reason to drop the match.
      }
    };

    socket.onclose = () => {
      this.socket = null;
      this.handlers.onClose();
      this.scheduleRetry();
    };
  }

  /** A lost connection retries, because school wifi drops (P8-T12). */
  private scheduleRetry() {
    if (this.closed) return;
    const wait = Math.min(1000 * 2 ** this.retry, 8000);
    this.retry += 1;
    this.timer = setTimeout(() => void this.open(), wait);
  }

  send(payload: Record<string, unknown>) {
    if (this.socket?.readyState !== WebSocket.OPEN) return false;
    this.socket.send(JSON.stringify(payload));
    return true;
  }

  close() {
    this.closed = true;
    if (this.timer) clearTimeout(this.timer);
    this.timer = null;
    this.socket?.close();
    this.socket = null;
  }

  get connected() {
    return this.socket?.readyState === WebSocket.OPEN;
  }
}

function socketOrigin(): string {
  const configured = process.env.NEXT_PUBLIC_WS_ORIGIN;
  if (configured) return configured.replace(/\/$/, "");
  if (typeof window !== "undefined") {
    const { hostname, protocol, host } = window.location;
    // In development the page is on :3000 while the API is on :8000.
    if (hostname === "localhost" || hostname === "127.0.0.1") return "ws://127.0.0.1:8000";
    return `${protocol === "https:" ? "wss" : "ws"}://${host}`;
  }
  return "ws://127.0.0.1:8000";
}

/** A clock a child can read at a glance: `4:59`, and `0:09` when it is urgent. */
export function formatClock(ms: number): string {
  const total = Math.max(0, Math.round(ms / 1000));
  return `${Math.floor(total / 60)}:${String(total % 60).padStart(2, "0")}`;
}

export const WHITE_MAN = 1;
export const WHITE_KING = 2;
export const BLACK_MAN = 3;
export const BLACK_KING = 4;

/** Square index for a visible (row, col) pair, or null on a light square. */
export function squareAt(row: number, col: number): number | null {
  if ((row + col) % 2 === 0) return null;
  return row * 4 + Math.floor(col / 2);
}
