"""Phase 7 end-to-end: two learners, one roster tap, one code (P7 DoD).

Run against the live dev API with seeded data. Nothing here is a test-suite
replacement: it drives the real HTTP surface the browser uses, in the order a
lesson would, and prints what happened.
"""

from __future__ import annotations

import asyncio
import json
import sys
import uuid

import asyncpg
import httpx

API = "http://127.0.0.1:8000"
DB_DSN = "postgresql://postgres@127.0.0.1:5433/stem_games"

WORDS: dict[str, str] = {}


def client() -> httpx.Client:
    return httpx.Client(base_url=API, timeout=20.0)


def login(http: httpx.Client, code: str, pin: str = "2468") -> dict:
    response = http.post("/api/auth/login", json={"code": code, "pin": pin})
    assert response.status_code == 200, (code, response.text)
    return response.json()


def me(http: httpx.Client) -> dict:
    response = http.get("/api/auth/me")
    assert response.status_code == 200, response.text
    return response.json()


async def load_words() -> dict[str, str]:
    """Every live answer, keyed by its sorted letters.

    The client is never given the answer; this script is standing in for a very
    good player, so it looks it up the way a marker would.
    """
    conn = await asyncpg.connect(DB_DSN)
    try:
        rows = await conn.fetch(
            "select i.payload->>'answer' as answer from game_content_items i "
            "join game_content_packs p on p.id = i.pack_id "
            "where i.status = 'live' and p.game_id = 'word_scramble'"
        )
    finally:
        await conn.close()
    return {"".join(sorted(row["answer"].lower())): row["answer"] for row in rows if row["answer"]}


def word_for(letters: str) -> str | None:
    return WORDS.get("".join(sorted(letters.lower())))


def play(http: httpx.Client, session_id: str, *, solve: bool) -> dict:
    """Play every round; when `solve` is false, say "I don't know" each time."""
    state: dict = {}
    for _ in range(20):
        current = http.get(f"/api/games/sessions/{session_id}")
        assert current.status_code == 200, current.text
        state = current.json()
        if state["finished"]:
            break
        round_ = state["round"]
        seen = http.post(
            f"/api/games/sessions/{session_id}/actions",
            json={"client_move_id": uuid.uuid4().hex, "type": "round_seen"},
        )
        assert seen.status_code == 200, seen.text
        if solve:
            answer = word_for(round_["letters"])
            assert answer, round_
            action = {"client_move_id": uuid.uuid4().hex, "type": "answer", "value": answer}
        else:
            action = {"client_move_id": uuid.uuid4().hex, "type": "skip"}
        response = http.post(f"/api/games/sessions/{session_id}/actions", json=action)
        assert response.status_code == 200, response.text
        state = response.json()
    assert state["finished"], state
    return state


def challenge_view(http: httpx.Client, session_id: str) -> dict | None:
    response = http.get(f"/api/games/sessions/{session_id}/challenge")
    assert response.status_code == 200, response.text
    return response.json()


def main() -> int:
    WORDS.update(asyncio.run(load_words()))
    print("live words loaded:", len(WORDS))

    amara = client()
    bayo = client()
    login(amara, "A-1001")
    login(bayo, "A-1002")
    print(
        "signed in:", me(amara)["user"]["preferred_name"], "and", me(bayo)["user"]["preferred_name"]
    )

    # --- 1. the roster tap: one tap, no typing -------------------------------
    roster = amara.get("/api/games/friends")
    assert roster.status_code == 200, roster.text
    friends = roster.json()
    print("roster:", [friend["name"] for friend in friends])
    target = next(friend for friend in friends if friend["id"] == me(bayo)["user"]["id"])

    created = amara.post(
        "/api/games/challenges",
        json={"game_id": "word_scramble", "difficulty": 1, "invitee_id": target["id"]},
    )
    assert created.status_code == 201, created.text
    invite = created.json()
    print("invite:", invite["invitee_name"], "|", invite["expires_sentence"])

    mine = amara.post(f"/api/games/challenges/{invite['parent_id']}/start")
    assert mine.status_code == 200, mine.text
    child_a = mine.json()["session_id"]

    inbox = bayo.get("/api/games/inbox")
    assert inbox.status_code == 200, inbox.text
    pending = inbox.json()["invites"]
    print("bayo's inbox:", [row["sentence"] for row in pending])
    accepted = bayo.post(
        "/api/games/invites/accept", json={"invitation_id": pending[0]["invitation_id"]}
    )
    assert accepted.status_code == 200, accepted.text
    started_b = bayo.post(f"/api/games/challenges/{invite['parent_id']}/start")
    assert started_b.status_code == 200, started_b.text
    child_b = started_b.json()["session_id"]
    assert child_a != child_b

    # --- 2. the same puzzles, in the same order ------------------------------
    first_a = amara.get(f"/api/games/sessions/{child_a}").json()["round"]
    first_b = bayo.get(f"/api/games/sessions/{child_b}").json()["round"]
    same = (first_a["letters"], first_a["clue"]) == (first_b["letters"], first_b["clue"])
    print("same first puzzle:", same, "|", first_a["letters"], "/", first_b["letters"])
    assert same

    # --- 3. both play to the end --------------------------------------------
    played_b = play(bayo, child_b, solve=False)
    played_a = play(amara, child_a, solve=True)
    print("scores:", played_a["score"], "vs", played_b["score"])

    # --- 4. the comparison, one sentence each --------------------------------
    view_a = challenge_view(amara, child_a)
    view_b = challenge_view(bayo, child_b)
    print("amara:", view_a["outcome"], "|", view_a["sentence"])
    print("bayo: ", view_b["outcome"], "|", view_b["sentence"])
    assert view_a["settled"] and view_b["settled"]
    assert view_a["outcome"] == "win" and view_b["outcome"] == "loss"
    assert view_a["opponent_id"] == me(bayo)["user"]["id"]

    # --- 5. a report reaches the admin --------------------------------------
    admin = client()
    login(admin, "A-9001")
    reported = bayo.post(
        "/api/games/reports",
        json={"reported_id": view_b["opponent_id"], "reason": "bullying", "session_id": child_b},
    )
    assert reported.status_code == 201, reported.text
    listed = admin.get("/api/games/reports")
    assert listed.status_code == 200, listed.text
    print("admin sees:", json.dumps(listed.json()[:2], indent=None)[:400])

    # --- 6. the code path, for a friend in another class ---------------------
    chidi = client()
    dumebi = client()
    login(chidi, "A-1011")  # a different class from A-1001
    login(dumebi, "A-1012")
    by_code = chidi.post(
        "/api/games/challenges",
        json={"game_id": "word_scramble", "difficulty": 1, "with_code": True},
    )
    assert by_code.status_code == 201, by_code.text
    code = by_code.json()["formatted_code"]
    print("code offered:", code, "|", by_code.json()["expires_sentence"])
    chidi.post(f"/api/games/challenges/{by_code.json()['parent_id']}/start")

    joined = dumebi.post("/api/games/invites/accept", json={"code": code})
    assert joined.status_code == 200, joined.text
    print("code join:", joined.json()["game_name"], joined.json()["session_id"][:8], "...")
    again = dumebi.post("/api/games/invites/accept", json={"code": code})
    assert again.status_code == 404
    print("same code twice:", again.status_code, again.json()["error"]["message"])

    # --- 7. a blocked learner cannot invite back ----------------------------
    blocker = client()
    blocked = client()
    login(blocker, "A-1021")
    login(blocked, "A-1022")
    block = blocked.post(
        "/api/games/blocks", json={"user_id": me(blocker)["user"]["id"], "type": "block"}
    )
    assert block.status_code == 204, block.text
    refused = blocker.post(
        "/api/games/challenges",
        json={"game_id": "word_scramble", "difficulty": 1, "invitee_id": me(blocked)["user"]["id"]},
    )
    print("invite after block:", refused.status_code, refused.json()["error"]["message"])
    assert refused.status_code == 404
    hidden = blocker.get("/api/games/friends").json()
    assert all(friend["id"] != me(blocked)["user"]["id"] for friend in hidden)
    print("blocked learner off the roster: yes")

    print("\nPHASE 7 DoD: all checks passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
