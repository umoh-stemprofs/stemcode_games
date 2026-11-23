"""Phase 8 chaos gate: kill the socket mid-move, fifty times (P8 DoD).

The promise being measured is narrow and concrete:

- a move is **never lost**: whatever the client believed it sent is either in
  the match or refused with a code, and a client that retries with the same
  ``client_move_id`` lands it exactly once;
- a move is **never duplicated**: one ``game_moves`` row per intent, no gaps in
  ``move_number``, and replaying the stored moves through the pure engine
  reproduces the board, the side to move and the counters the server holds.

It runs against the live dev API with seeded data, like ``phase7_e2e.py``. It
is not a test-suite replacement: it exercises the transport a browser cannot be
made to break on demand.

    npm run dev:api          # in another terminal, with the seeded database
    node scripts/py.mjs api/tools/phase8_chaos.py [--rounds 50]

Exit code 0 means every assertion held. Anything else prints the failure and
exits 1.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
import time
import uuid
from dataclasses import dataclass, field
from typing import Any

import asyncpg
import httpx
import websockets

API = "http://127.0.0.1:8000"
WS = "ws://127.0.0.1:8000/ws/games"
# The gateway refuses a handshake with no Origin (P8-T01), because a browser
# always sends one. This client says which page it is standing in for.
ORIGIN = "http://127.0.0.1:3000"
DB_DSN = "postgresql://postgres@127.0.0.1:5433/stem_games"

INVITER = "A-1001"
REDEEMER = "A-1002"
PIN = "2468"


# --------------------------------------------------------------------- helpers
@dataclass
class Player:
    code: str
    http: httpx.Client
    user_id: str = ""
    name: str = ""


@dataclass
class Report:
    rounds: int = 0
    kills_before_send: int = 0
    kills_after_send: int = 0
    landed_without_retry: int = 0
    landed_on_retry: int = 0
    duplicates_absorbed: int = 0
    slowest_retry_ms: int = 0
    rejections: dict[str, int] = field(default_factory=dict)

    def note_rejection(self, code: str) -> None:
        self.rejections[code] = self.rejections.get(code, 0) + 1


def login(code: str) -> Player:
    http = httpx.Client(base_url=API, timeout=20.0)
    response = http.post("/api/auth/login", json={"code": code, "pin": PIN})
    assert response.status_code == 200, (code, response.text)
    me = http.get("/api/auth/me").json()
    return Player(code=code, http=http, user_id=me["user"]["id"], name=me["user"]["preferred_name"])


async def ticket(player: Player, session_id: str) -> str:
    response = player.http.post("/api/ws/ticket", json={"session_id": session_id})
    assert response.status_code == 201, (player.code, response.text)
    return response.json()["ticket"]


def state(player: Player, session_id: str) -> dict[str, Any]:
    response = player.http.get(f"/api/games/live/{session_id}")
    assert response.status_code == 200, (player.code, response.text)
    return response.json()


async def open_socket(player: Player, session_id: str) -> Any:
    """A connected socket that has already been sent its first snapshot."""
    socket = await websockets.connect(
        f"{WS}?ticket={await ticket(player, session_id)}", origin=ORIGIN
    )
    await socket.send(json.dumps({"type": "match.join"}))
    # The first frame is the full snapshot; waiting for it means the join was
    # processed, so a move sent now is a move into a live match.
    while True:
        frame = json.loads(await asyncio.wait_for(socket.recv(), timeout=5))
        if frame.get("type") == "match.state":
            return socket


def kill(socket: Any) -> None:
    """Drop the TCP connection without a close handshake.

    A phone that loses signal, a laptop lid, a proxy restart: none of them say
    goodbye. ``transport.abort()`` is the closest thing to that on this side.
    """
    transport = getattr(socket, "transport", None)
    if transport is not None:
        transport.abort()
        return
    protocol = getattr(socket, "protocol", None)
    if protocol is not None and hasattr(protocol, "close_transport"):
        protocol.close_transport()
        return
    asyncio.get_event_loop().create_task(socket.close())


# ---------------------------------------------------------------- the database
class Store:
    """Rows as Postgres holds them — not as the API claims them."""

    def __init__(self, pool: asyncpg.Pool) -> None:
        self.pool = pool

    async def moves(self, session_id: str) -> list[dict[str, Any]]:
        rows = await self.pool.fetch(
            """
            select move_number, client_move_id, payload, user_id
            from game_moves
            where session_id = $1
            order by move_number
            """,
            uuid.UUID(session_id),
        )
        return [dict(row) for row in rows]

    async def session(self, session_id: str) -> dict[str, Any]:
        row = await self.pool.fetchrow(
            "select status, config from game_sessions where id = $1",
            uuid.UUID(session_id),
        )
        assert row is not None, "session row vanished"
        config = row["config"]
        return {
            "status": row["status"],
            "config": json.loads(config) if isinstance(config, str) else config,
        }

    async def seat_of(self, session_id: str, user_id: str) -> str:
        config = (await self.session(session_id))["config"]
        for seat, raw in config["seats"].items():
            if raw == user_id:
                return seat
        raise AssertionError("a participant has no seat")

    async def replays(self, session_id: str) -> int:
        """How many times each client_move_id is written. Must all be 1."""
        rows = await self.pool.fetch(
            """
            select client_move_id, count(*) as n
            from game_moves
            where session_id = $1
            group by client_move_id
            having count(*) > 1
            """,
            uuid.UUID(session_id),
        )
        return len(rows)


# ------------------------------------------------------------------ the replay
def replay(board: dict[str, Any], moves: list[dict[str, Any]]) -> None:
    """Apply the stored moves to a fresh board and compare with the live one.

    This is the whole gate in one function: if a move were lost, the numbers
    would be short; if one were written twice, the board would have diverged
    from ``config["state"]``. Imported here rather than at module scope so the
    script still starts if the API package is not importable.
    """
    from app.games.domain import checkers as rules

    current = rules.initial_state(side="white")
    for row in moves:
        payload = row["payload"]
        if isinstance(payload, str):
            # asyncpg hands JSONB back as text unless a codec was installed.
            payload = json.loads(payload)
        move = rules.find_move(current, payload["move"])
        assert move is not None, f"stored move {row['payload']['move']} is illegal at that point"
        current = rules.apply_move(current, move)

    live = board["state"]
    assert list(current.board) == list(live["board"]), "board diverged from the stored moves"
    assert current.side == live["side"], "side to move diverged"
    assert current.plies_since_progress == live["plies"], "progress counter diverged"
    assert len(moves) == int(board["move_number"]), (
        f"{len(moves)} stored moves but move_number is {board['move_number']}"
    )
    numbers = [row["move_number"] for row in moves]
    assert numbers == list(range(1, len(moves) + 1)), f"move numbers have a gap: {numbers}"


# --------------------------------------------------------------------- the run
async def submit_once(
    socket: Any,
    session_id: str,
    player: Player,
    client_move_id: str,
    expected: int,
    move_key: str,
) -> None:
    await socket.send(
        json.dumps(
            {
                "type": "move.submit",
                "client_move_id": client_move_id,
                "expected_move_number": expected,
                "move": move_key,
            }
        )
    )


async def read_reply(socket: Any, expected: int) -> dict[str, Any] | None:
    """The next frame that decides *this* move, or None when none arrives.

    A socket can be carrying older frames — the join's snapshot, a poke from the
    opponent leaving — and a state from before this move is not a verdict on it.
    Waiting only for a state at or after `expected` is what stops the harness
    from calling a good move lost because it looked at the wrong frame.
    """
    try:
        while True:
            frame = json.loads(await asyncio.wait_for(socket.recv(), timeout=3.0))
            kind = frame.get("type")
            if kind in ("move.rejected", "error"):
                return frame
            if kind == "match.state" and int(frame.get("move_number") or 0) >= expected:
                return frame
    except Exception:
        # A timeout or a dead socket both mean "no verdict arrived" here, and
        # the caller then asks the server what actually happened.
        return None


async def chaos_round(
    store: Store,
    seats: dict[str, Player],
    session_id: str,
    report: Report,
    index: int,
) -> bool:
    """One kill. Returns False when the match has ended and there is no turn left."""
    observer = next(iter(seats.values()))
    view = state(observer, session_id)
    if view["status"] not in ("active", "ready"):
        return False

    # `legal_moves` is only ever populated for the side to move (D-25), so the
    # mover has to be asked for their own snapshot, not read off the opponent's.
    mover_seat = view["side_to_move"]
    mover = seats[mover_seat]
    current = state(mover, session_id)
    if not current["legal_moves"]:
        return False

    move = current["legal_moves"][index % len(current["legal_moves"])]
    expected = current["move_number"] + 1
    client_move_id = uuid.uuid4().hex

    socket = await open_socket(mover, session_id)

    # Half the kills land before the frame leaves, half just after: a dropped
    # request and a dropped response are different failures to survive.
    before = index % 2 == 0
    if before:
        report.kills_before_send += 1
        kill(socket)
        await asyncio.sleep(0.05)
        # The client never got confirmation. It reconnects and asks the server
        # what actually happened, which is what the browser page does.
    else:
        report.kills_after_send += 1
        try:
            await submit_once(socket, session_id, mover, client_move_id, expected, move["key"])
        finally:
            kill(socket)
        await asyncio.sleep(0.15)

    after = state(mover, session_id)
    if after["move_number"] >= expected:
        report.landed_without_retry += 1
        return True

    # Not accepted: the honest retry, same client_move_id, on a fresh socket.
    retry = await open_socket(mover, session_id)
    started = time.monotonic()
    try:
        await submit_once(retry, session_id, mover, client_move_id, expected, move["key"])
        reply = await read_reply(retry, expected)
    finally:
        kill(retry)
        await asyncio.sleep(0.1)

    elapsed = int((time.monotonic() - started) * 1000)
    report.slowest_retry_ms = max(report.slowest_retry_ms, elapsed)
    final = await settle(mover, session_id, expected)
    if final["move_number"] >= expected:
        report.landed_on_retry += 1
        return True

    if reply is not None and reply.get("type") in ("move.rejected", "error"):
        # A refusal is a legal outcome: the server decided, and the log says why.
        report.note_rejection(str(reply.get("code")))
        return True

    raise AssertionError(
        f"round {index}: move {move['key']} at {expected} was neither accepted nor "
        f"refused (waited {elapsed} ms, reply {reply}, server holds {final['move_number']})"
    )


async def settle(player: Player, session_id: str, expected: int) -> dict[str, Any]:
    """The server's own record, given a moment to finish what it accepted.

    A submit that is still committing is not a lost move, and the read here is
    MVCC: it sees the row as of commit. Two seconds is longer than any local
    commit takes and short enough that a real stall still fails the gate.
    """
    deadline = time.monotonic() + 2.0
    view = state(player, session_id)
    while view["move_number"] < expected and time.monotonic() < deadline:
        await asyncio.sleep(0.05)
        view = state(player, session_id)
    return view


async def duplicate_check(
    store: Store, seats: dict[str, Player], session_id: str, report: Report
) -> None:
    """The same intent three times on one healthy socket: one row, one acceptance."""
    view = state(next(iter(seats.values())), session_id)
    if view["status"] != "active":
        return
    mover = seats[view["side_to_move"]]
    current = state(mover, session_id)
    if not current["legal_moves"]:
        return
    move = current["legal_moves"][0]
    expected = current["move_number"] + 1
    client_move_id = uuid.uuid4().hex

    socket = await open_socket(mover, session_id)
    try:
        for _ in range(3):
            await submit_once(socket, session_id, mover, client_move_id, expected, move["key"])
            await read_reply(socket, expected)
        await asyncio.sleep(0.2)
    finally:
        kill(socket)

    after = state(mover, session_id)
    assert after["move_number"] == expected, (
        f"three identical intents moved the match from {expected - 1} to {after['move_number']}"
    )
    rows = [row for row in await store.moves(session_id) if row["client_move_id"] == client_move_id]
    assert len(rows) == 1, f"identical intents wrote {len(rows)} rows"
    report.duplicates_absorbed += 1


async def open_match(inviter: Player, redeemer: Player) -> tuple[str, dict[str, Any]]:
    """A fresh live match with both seats taken, made through the public API."""
    created = inviter.http.post(
        "/api/games/live", json={"invitee_id": redeemer.user_id, "clock_ms": 1_800_000}
    )
    assert created.status_code == 201, created.text
    session_id = created.json()["session_id"]

    accepted = redeemer.http.post("/api/games/live/accept", json={"code": created.json()["code"]})
    assert accepted.status_code == 200, accepted.text
    return session_id, accepted.json()


async def main(rounds: int) -> int:
    players = {INVITER: login(INVITER), REDEEMER: login(REDEEMER)}
    session_id, first = await open_match(players[INVITER], players[REDEEMER])
    print(f"match {session_id} — {players[INVITER].name} vs {players[REDEEMER].name}")

    # Both players present, so the clocks start and moves are legal.
    for player in players.values():
        socket = await open_socket(player, session_id)
        kill(socket)
    await asyncio.sleep(0.2)
    assert state(players[INVITER], session_id)["status"] == "active", "match never became active"

    report = Report()
    pool = await asyncpg.create_pool(DB_DSN, min_size=1, max_size=3)
    store = Store(pool)
    seats = {await store.seat_of(session_id, player.user_id): player for player in players.values()}
    print(f"seats: {', '.join(f'{seat}={p.name}' for seat, p in seats.items())}")
    try:
        for index in range(rounds):
            report.rounds += 1
            alive = await chaos_round(store, seats, session_id, report, index)
            if not alive:
                print(f"match ended after {index} kills")
                break
            if index % 10 == 9:
                print(f"  {index + 1} kills done")

        await duplicate_check(store, seats, session_id, report)

        moves = await store.moves(session_id)
        session = await store.session(session_id)
        duplicated = await store.replays(session_id)

        print(f"\nsession {session['status']}: {len(moves)} moves recorded")
        print(f"kills: {report.kills_before_send} before send, {report.kills_after_send} after")
        print(
            f"outcomes: {report.landed_without_retry} landed anyway, "
            f"{report.landed_on_retry} landed on retry, {report.duplicates_absorbed} duplicates absorbed"
        )
        print(f"slowest retry: {report.slowest_retry_ms} ms from send to settled")
        if report.rejections:
            print(f"refusals: {report.rejections}")

        assert duplicated == 0, f"{duplicated} client_move_id values were written more than once"
        if session["status"] in ("finished", "abandoned", "no_contest"):
            # A finished match still has to replay to its final board.
            replay(session["config"], moves)
            print("replay: stored moves reproduce the final board exactly")
        else:
            replay(session["config"], moves)
            print("replay: stored moves reproduce the live board exactly")
    finally:
        await pool.close()
        for player in players.values():
            player.http.close()

    print("\nPASS — no lost moves, no duplicate rows, replay matches the server")
    return 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--rounds", type=int, default=50)
    args = parser.parse_args()
    sys.exit(asyncio.run(main(args.rounds)))
