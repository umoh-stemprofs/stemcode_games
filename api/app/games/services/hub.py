"""The live-match fan-out (P8-T02, P8-T03, P8-T05, P8-T12).

Two jobs, deliberately separate:

- **Who is connected.** A small in-process registry, because a socket is by
  definition in one process. It enforces the two-connection cap and lets a new
  socket replace the old one (P8-T05) — a learner who reconnects after school
  wifi drops should not be told "too many connections".
- **How an event reaches both players.** One channel per match, published
  through ``CacheClient`` so a second API instance behaves the same way. In
  local development the in-memory implementation fans out in-process, which is
  all a single dev process needs (D-34, section 3A).

Only already-accepted events are published. The hub never decides a rule; it
carries the service's answer.
"""

from __future__ import annotations

import json
import uuid
from dataclasses import dataclass, field
from typing import Any

from app.core.cache import CacheClient
from app.core.logging import get_logger

log = get_logger(__name__)

MAX_CONNECTIONS_PER_USER = 2
MAX_MESSAGE_BYTES = 4 * 1024


def channel_for(session_id: uuid.UUID | str) -> str:
    return f"match:{session_id}"


@dataclass
class Connection:
    """One open socket, and the socket it replaced."""

    user_id: uuid.UUID
    session_id: uuid.UUID
    conn_id: str
    send: Any = None
    closed: bool = False
    replaced: bool = False
    meta: dict[str, Any] = field(default_factory=dict)


class Hub:
    """Connections of this process, plus the publish side of pub/sub."""

    def __init__(self) -> None:
        self._by_user: dict[uuid.UUID, list[str]] = {}
        self._by_id: dict[str, Connection] = {}

    def register(self, connection: Connection) -> Connection | None:
        """Add a socket. The oldest socket is closed when the cap is reached."""
        connections = self._by_user.setdefault(connection.user_id, [])
        replaced: Connection | None = None
        while len(connections) >= MAX_CONNECTIONS_PER_USER:
            oldest = connections.pop(0)
            stale = self._by_id.pop(oldest, None)
            if stale is not None:
                stale.replaced = True
                stale.closed = True
                replaced = stale
        connections.append(connection.conn_id)
        self._by_id[connection.conn_id] = connection
        return replaced

    def connections(self, session_id: uuid.UUID) -> list[Connection]:
        return [
            conn
            for conn in self._by_id.values()
            if conn.session_id == session_id and not conn.closed
        ]

    def forget(self, conn_id: str) -> None:
        conn = self._by_id.pop(conn_id, None)
        if conn is None:
            return
        conn.closed = True
        open_ids = self._by_user.get(conn.user_id, [])
        if conn_id in open_ids:
            open_ids.remove(conn_id)
        if not open_ids:
            self._by_user.pop(conn.user_id, None)

    def close_session(self, session_id: uuid.UUID, *, reason: str = "match ended") -> None:
        """Every socket in this process that belongs to a finished match."""
        for conn in list(self.connections(session_id)):
            conn.closed = True
            try:
                if conn.send is not None:
                    conn.send({"type": "match.ended", "reason": reason})
            except Exception:  # pragma: no cover - a dead socket is not an error
                log.debug("ws.close_send_failed", extra={"route": conn.conn_id})
            self.forget(conn.conn_id)

    def count(self) -> int:
        return len(self._by_id)


# One per process; the app attaches its cache on startup and this module stays
# free of settings and of FastAPI.
HUB = Hub()


async def publish(cache: CacheClient, session_id: uuid.UUID, event: dict[str, Any]) -> None:
    """Send one accepted event to everyone watching this match."""
    await cache.publish(channel_for(session_id), json.dumps(event, separators=(",", ":")))


def frame(event: dict[str, Any]) -> dict[str, Any]:
    """The envelope every server event carries (P8-T02)."""
    return {
        "type": event.get("type", "error"),
        "v": 1,
        "id": event.get("id") or uuid.uuid4().hex,
        **{key: value for key, value in event.items() if key not in ("type", "v", "id")},
    }
