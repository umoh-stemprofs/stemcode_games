# STEM Code V2 Games: Build Plan (Scratch to Finish)

**Stack:** Next.js (App Router, TypeScript) + FastAPI (Python 3.12 — **pinned via `uv`; never the system Python**) + PostgreSQL 16 (CI/prod; local dev may run 18, see P0-T03b) + Redis 7 (required in production, optional in dev per D-34)
**Local development:** must work on a Windows PC **without Docker** (P0-T03b). The container path is a convenience for CI, not a prerequisite.
**Source of truth for product intent:** `GAMES_AND_GAMIFICATION.md` (maintained separately; not part of this repository)
**This document:** the execution plan. Where the two differ, the Decision Log (section 2) is the tie-breaker and must be updated, not silently ignored.

---

## 0. How to use this plan (read first, especially if you are an AI agent)

1. Work **phase by phase, in order**. Do not start a phase until the previous phase's "Definition of Done" is met.
2. Every task has an ID like `P4-T07`. Reference IDs in commit messages and PR titles.
3. Every delivery phase (0-11) has: Objective, Prerequisites, Tasks, and a Definition of Done (DoD). Phases that ship a discrete artefact also list Deliverables. Phase 12 is a backlog list, not a phase to execute.
4. When a task says "server decides", the client must never compute or send the outcome, score, XP, or time. Clients only send *intents* (a guess, an answer, a move).
5. If something is ambiguous, use the default in the Decision Log. If a default is wrong, change the Decision Log entry first, then the code.
6. Every table named here is created by Alembic migration only. Never edit the database by hand.
7. Every task ships with tests. A task is not done until its tests pass in CI.
8. **Local development must work on a Windows PC with no Docker and no Redis** (P0-T03b, D-34). A change that breaks that path is a bug.
9. **UI work is not done until it passes Appendix D.** This is not a polish step at the end; it is a gate inside every game phase.

### Release slices (what the phases add up to)

| Slice | Phases | What a pilot school can do |
|---|---|---|
| A. Single-player online | 0-5 | Play Word Scramble, earn XP, see the daily, weekly and termly boards, with the 2-hour limit enforced |
| B. Social | 6-7 | Add Guessing Game, challenge a friend by code or link (same puzzle, compare results) |
| C. Live multiplayer | 8 | Live Checkers via invite, with reconnect, clocks, resign/draw |
| D. Offline + safety depth | 9-10 | Offline single-player, anomaly detection, moderation tools |
| E. Launch | 11 | Hardened, load-tested, monitored, piloted |

---

## 1. Scope

### In scope (initial release)
1. **Leaderboards based on XP**: **daily, weekly and all-time** (Game XP, server-awarded, per school, optional class, age band). The learners' third tab is the all-time board, masked like the others (D-35, changed 2026-11-24: it replaced the termly tab).
2. **Multiplayer**: invites by shareable code or link; live Checkers; challenge mode for the other two games.
3. **Three games first**: Word Scramble, Guessing Game, Checkers.
4. **Invite friends or copy code.**
5. **Game functionality and visuals** (clean, neutral, accessible; no specific art direction required, but **Appendix D is binding** — the games must be understandable without reading).
6. **Daily play-time limit: default 2 hours/day**, adjustable by school admin or coach.
7. **Next.js + FastAPI.**
8. **Single-player offline mode** (Word Scramble, Guessing Game).

### Explicitly out of scope for first release (see Phase 12)
Chess, falling-block puzzle, daily/termly/all-time boards, sportsmanship XP, in-game text chat, voice, cross-school play, spectators, tournaments.

---

## 2. Decision Log (defaults the plan assumes)

Change a default here first if the product owner disagrees.

| ID | Decision | Default | Why |
|---|---|---|---|
| D-01 | Host platform (auth, schools, classes, roles, preferred name, avatar, Learning XP) | **Assume it does not exist yet.** Phase 1 builds a minimal version behind interfaces so it can be swapped for the real platform | "From scratch" was requested; the source doc depends on these concepts |
| D-02 | The three launch games | Word Scramble, Guessing Game, Checkers | Matches the source's proposed order; Checkers is the first *live* multiplayer game |
| D-03 | How multiplayer applies to games 1-2 | **Challenge mode (asynchronous)**: both players get the identical puzzle set from the same seed, play at their own time within 24h, results compared. Not live | Source says Word Scramble/Guessing Game validate sessions/XP before live board games; user wants invites for all games |
| D-04 | "Guessing Game" definition | **Number Guess**: server picks a secret integer in a range by difficulty, learner has limited attempts, gets higher/lower feedback; score by attempts used | Source never defines it; this is the simplest well-known interpretation |
| D-05 | Checkers rules | English draughts: 8x8, men move/capture forward only, kings move/capture both ways (not flying), **mandatory capture**, multi-jump required to completion | Source never names a variant; rules engine is isolated so the variant can be changed |
| D-06 | Leaderboard ranking metric | Sum of **leaderboard-eligible Game XP** in the period. Boards exist per game and as "All games", for every period in D-35 | User asked "based on XP"; source separates Learning and Game XP and says Profile XP is motivational only |
| D-07 | Week boundary | Monday 00:00 to Sunday 23:59:59 in the **school's timezone** | Needs one unambiguous rule for periods and "daily" limits |
| D-08 | Daily play limit resolution | Effective limit = first non-null of: student override, class override, school default, platform default; then **clamped to platform ceiling**. Platform default 120 min, platform ceiling 240 min | User says school admin or coach may raise or lower; source only mentions "stricter". A ceiling reconciles both |
| D-09 | Who can set limits | School admin: school default + any class/student in their school. Coach: only classes/students assigned to them. Platform admin: default + ceiling | Prevents scope escalation |
| D-10 | Time limit reached mid-match | **Soft limit**: an active solo or challenge attempt may finish (max 10 min overshoot). No new games start. **A live match is handled by D-27 instead**, not by this overshoot. A coach **lockout** is immediate: a live match becomes `no_contest` (no XP, no loss) | Hard-cutting a live match unfairly punishes the opponent |
| D-11 | What counts as active time | Server-side heartbeats from inside a playing session, while tab visible, and (on your own turn / in single-player) input within last 60 s. Menus, loading, offline-disconnected idle, and background tabs do not count. Waiting for an opponent's move counts if the tab is visible | Matches source section 4 |
| D-12 | Offline play and XP | Offline sessions sync into **personal history only**. They award **no Game XP** and never appear on leaderboards (MVP). Their active seconds **do** count toward the daily limit after sync | Source: unverified offline scores are excluded; simplest abuse-proof rule |
| D-13 | Game XP values | Participation 5; performance bonus up to 10 (game-specific); Checkers win +10, draw +5 (replaces performance bonus). **No daily Game XP cap by default** (changed 2026-11-24: the 60 XP cap is off; the setting survives, and 0 means no cap). Challenge win bonus +5. Max 3 rewarded two-player sessions (live matches or challenges, any game) per opponent pair per day. No XP unless the session meets the activity minimum for its game (D-29) | Anti-farming; numbers are tunable config, not code constants |
| D-14 | Leaderboard minimum activity | At least **1** verified completed session **that met the D-29 activity minimum and earned XP** in the period (changed 2026-11-24: a minimum of 3 hid a learner who had just played) | Source requires a "minimum eligible activity"; sessions worth zero XP must not count, or idling would qualify |
| D-15 | Who sees what | Learners see own school only, the **daily, weekly and all-time** boards, preferred name + avatar only. Coaches see their classes plus the school board, same masked identity. All-time is the same masked board for every role in the school (changed 2026-11-24: it replaced termly as the third tab). A school admin can additionally see real names in admin tools. Schools may disable leaderboards entirely | Source section 6; all-time boards deferred |
| D-16 | Invite model | Each invite has an **8-character code** (unambiguous alphabet, no 0/O/1/I/L) and a **link** with a separate opaque token. Both expire (code 30 min for live games, 24 h for challenges), are stored hashed, are rate-limited, and require an authenticated learner of the **same school** | Source: opaque expiring tokens; user: "send invite or copy code" |
| D-17 | "Friends" | No friend graph in MVP. "Friends" = same-school eligible players (presence list or class roster) plus anyone holding a code | Source has no friend model; avoids new privacy surface for minors |
| D-18 | Chat | **No free-text chat.** Optional later: fixed emoji/phrase reactions only | Child safety |
| D-19 | Auth between Next.js and FastAPI | FastAPI issues httpOnly, Secure, SameSite=Lax cookie sessions (short access + rotating refresh). Next.js and API are served under one domain (`/api` reverse-proxied in prod; a dev-only Next rewrite keeps one origin locally, P0-T06). WebSockets use a **single-use 30-second ticket** from an authenticated REST call | Avoids token-in-localStorage and WS auth ambiguity |
| D-20 | Client-server type sharing | FastAPI OpenAPI schema is the contract; TypeScript client is **generated** from it, never hand-written | Prevents drift |
| D-21 | Background jobs | ARQ (Redis-based, async-native) for rollups, expiry sweeps, anomaly scans. In local dev jobs run inline or on demand via the CLI (D-34, P0-T12) | Fits FastAPI/asyncio |
| D-22 | Age bands | Config table, default: `8-10`, `11-13`, `14-16`, `17+`. The learner's band is **snapshotted onto each result and XP row** when it is written | Prevents birthdays or reclassification rewriting history |
| D-23 | Class on leaderboard rows | `class_id` also snapshotted onto each XP row | Class transfers must not move past XP |
| D-24 | Connectivity assumption | Design for slow, intermittent connections and low-end phones: small payloads, reconnect everywhere, no blocking on large assets | Typical for school settings |
| D-25 | `seed` visibility | **Server-private.** The seed is never included in any learner-facing or opponent-facing payload, log line, telemetry event, or error detail. Only the server and the school admin's replay tool (P10-T03) may read it | For Number Guess the secret is a pure function of the seed, and in challenge mode both players share one seed, so a leaked seed leaks every answer |
| D-26 | Time accrual granularity | Active seconds accrue **per user per school-local date** on a single `last_counted_at` row (`game_play_clock`), never per session. At most **one active play session per learner** at a time; starting a second is refused with `another_session_active`, enforced by the partial unique index `ux_participants_one_active_play` | Two open tabs would otherwise burn the 2-hour allowance twice as fast |
| D-27 | Live match and the daily limit | A `live` match may only **start** when remaining time ≥ **15 minutes**. Once started it plays to completion, bounded by its clocks, and is **exempt** from the 10-minute overshoot in D-10. Clock default **5 minutes + 3 s increment per side** | A 10+5 clock allows a 25-minute match, which breaks both the 2-hour promise and D-10 |
| D-28 | Challenge session shape | A challenge is a **parent `challenge` session with two child `solo` sessions**, one per player, both sharing the parent's seed. Each child has its own move sequence, result, and attempt state. **The parent never counts as a player's active session;** the child does (D-26) | Two concurrent attempts cannot share one monotonic `move_number`, and "replay from seed + moves" needs exactly one player's move list |
| D-29 | Activity minimum for XP | Participation XP requires real play: Word Scramble ≥ **4 correct rounds** of 10; Number Guess ≥ **2 numbers solved** of 5; Checkers ≥ **4 moves per side** (changed 2026-11-24: eight moves paid nothing for a short but real game). Below the minimum the result is still stored in personal history with `leaderboard_eligible=false` and **zero XP** | Otherwise "start a session, let every round time out" farms 5 XP and counts toward the D-14 minimum |
| D-30 | Reconnect grace | The disconnected player's **clock is paused**; forfeit only after **3 minutes** in one disconnect or **10 minutes** cumulative in a match | A 60 s window loses games to school wifi, which a child reads as a broken game |
| D-31 | Invite join path | **Learners play on laptops, so there is no QR primary path.** Primary join is **one tap on a classmate's avatar in the roster**; the 8-character code (shown in two groups of four, large) is the path for someone outside your class; a QR code may be shown as an optional extra only when a camera exists. Explicitly **not** required: scanning, camera permission, or typing a URL. The link token is put into a short-lived `SameSite=Lax` cookie **on first load, before login**, returned via a POST body after login, never carried through a redirect, and every page sends `Referrer-Policy: no-referrer` | 8 characters is a hard task for the target user, and a token in a query string is lost by the login redirect and leaks via Referer, history, and logs |
| D-32 | Plain-language UI standard | **Appendix D is binding.** Word limits, icon-first layout, at most one decision per screen. **No read-aloud feature** (removed by product decision, D-36). Every game phase's DoD includes the Appendix D first-session test | The plan otherwise contains no comprehension standard; WCAG AA makes a game operable, not understandable |
| D-33 | Leaderboard read rules | Each board reads exactly **one** row set: per-game board = `game_id = <game>`; All-games board = `game_id IS NULL`. Never sum both. A learner with rows in two classes or snapshots is summed at read time, with tie-break key `MAX(last_award_at)`. Sessions flagged or excluded by P10 are filtered in the projection **and** in the nightly reconcile | Summing all rows double-counts XP; trusting only the ledger flag lets excluded XP return after reconcile |
| D-34 | Redis in local development | Redis is **required in production**. Local dev must run without it: every cache and queue call goes through the `CacheClient`/`QueueClient` interfaces (section 3A). The in-memory implementations are dev/test only and single-instance | The project must be developable on a Windows PC with no Docker (P0-T03b) |
| D-35 | Leaderboard periods and visibility | Periods: `daily`, `weekly`, `monthly`, `termly`, `all_time`. **The first release ships daily, weekly and all-time**; `monthly` is one config flag away because it uses the same generator and the same projection. All three are visible to eligible learners and coaches of the same school under masked identity — all-time is no longer admin-only (changed 2026-11-24). `all_time` never resets: one row per school with no `ends_at`. `termly` remains a valid period type and still needs a `school_terms` calendar, but it is no longer a shipped tab | The source doc requires all four periods and restricts all-time to admins. Deferring them costs more rework than building them on one shared projection, which is what P5-T07 already is |
| D-36 | Sign-in and read-aloud | **Sign-in is a student code + PIN.** No email address and no password anywhere: one form for learners and staff, codes stored uppercase and unique, PIN hashed with Argon2id, the lockout backoff kept because a 4-digit secret deserves more protection than a long password. **There is no read-aloud feature**, now or later; the Appendix D standard no longer mentions one. A child who cannot read is helped by icons, short sentences and a coach, never by a "Read this page" button | Product owner decision, 2026-11-14. An email address is a real-world identity a child may not have, and a PIN is what schools already hand out. Read-aloud was cut as clutter, so it must never be reintroduced by a later phase |
| D-37 | Three roles, and a word goes live one at a time | **The role enum is exactly three values: `learner`, `coach`, `school_admin`.** There is no `platform_admin`, `moderator`, `content_contributor` or `content_reviewer`. Content work belongs to members of staff: a coach writes words, and both staff roles may make a word live or take it down, because content is platform-wide and every school reads the same bank. Creating a school, and the first admin of a school, is a **command on the server** (`python -m app.cli`), not a screen and not a role. Moderation of reports sits with the school admin for their own school. Existing accounts are **mapped, never deleted**: `content_contributor -> coach`, and `content_reviewer | moderator | platform_admin -> school_admin` (migration `0009_three_roles`) | The product owner asked for one ladder a person can hold in their head: learner, coach, head teacher. Splitting "who writes" from "who checks" into separate logins made five accounts per school for work that is one job, and left nobody able to publish from a school with one member of staff |
| D-38 | A word carries its own status, and its author may publish it | **Status lives on `game_content_items`, not only on the pack:** `draft -> live -> retired`. Typing a word creates a `draft`; **Make it live** is the only door to the games, and it is one word wide. The pack is only the bucket that groups words by age band and version, so `published` on the pack now means "at least one of my words is live". **The author may publish their own word** — the draft step plus the validator is the safety, not a second reader. A word that still has a problem cannot go live by any route, including the bulk button, which skips it. The same answer may not be live twice in one band. Editing a live word **returns it to `draft`**, so nothing changes under a child mid-round. A live word is **taken down, never deleted**; only an unpublished draft may be deleted. `retired` words stay as the record of what children played. The `draft -> in_review -> approved -> published` pack chain and its review UI are **removed** | Product owner decision, 2026-11-14: "drafts matter, and from draft you approve one by one." The old chain forced a whole pack through review to fix one clue, and its "an author cannot approve their own pack" rule had nowhere to go once the content reviewer role was merged away (D-37). Removing it also removes a screen, two statuses and two audit actions |
| D-39 | The safe-language list has two halves | The **baseline** list ships in code (`app/games/domain/safe_language.py`): reviewed in a commit, identical everywhere, and impossible to empty by accident. The **school's own** words live in the `blocked_words` table and are managed from a screen by a **school admin** only (`/coach/blocked`), effective on the next save with no deploy. Both are checked on every route. Removing a row can never unblock a baseline word, and a learner can never read the list. Matching is per word (not substring) with disguises normalised, and the refusal sentence never repeats the offending word | A fixed list goes stale the moment a school meets a word nobody upstream imagined, and waiting for a release to block it is how a blocklist stops being trusted. Keeping the baseline in code stops a well-meaning admin disabling the whole thing, and keeps every school safe on the same floor |
| D-40 | Learner chat is a game of **Postcards**, never a text box | A message is built from **vetted phrase tiles** plus an optional game and score, so the client never sends free text and every message passes the same validator as a clue. Postcards are **same-school only** (D-15), reach another class only when that class' coach has opened it, are limited to **3 a day**, cost one **Stamp** each, and earn a daily quest and a collection card. There is still **no free-text chat** (D-18); a free-text phase needs a coach pilot, a review queue and a parent-visible transcript, and it is not scheduled | A text box between 8-year-olds in different classes is a moderation problem with a child at the end of it, and a school has no moderator on duty at 8pm. Phrase tiles give the same social reward — "I beat your score" still travels — while making the worst message impossible to type. Turning the exchange into postcards with stamps and a collection gives the loop a reason to repeat that a chat box does not have |

---

## 3. Target architecture

```text
Browser (Next.js PWA)
   |  HTTPS /api/*  (REST, cookie session)
   |  WSS  /ws/games?ticket=...  (live matches, presence)
   v
Reverse proxy (single domain)
   |-- Next.js (SSR/UI)
   |-- FastAPI (REST + WebSocket)
          |-- PostgreSQL  (durable truth: sessions, moves, results, XP ledger)
          |-- Redis       (WS pub/sub, presence, rate limits, ARQ queue, short-lived tickets)
          |-- ARQ worker  (leaderboard reconcile, expiry sweeps, anomaly scans)
```

### Repo layout

```text
/api
  app/
    core/        config, db, security, logging, errors, rate_limit, cache, queue, cli
    identity/    schools, users, classes, auth, rbac
    games/
      domain/    pure Python (no I/O): rules, scoring, state machines
        wordscramble.py  guessing.py  checkers.py  xp_rules.py
      services/  sessions, access, time, xp, leaderboard, invitations, matches
      api/       routers
      ws/        websocket gateway, hub
      jobs/      ARQ tasks
  alembic/
  tests/
/web
  app/           routes (App Router)
  features/games/ components per game, hooks, offline store
  lib/api/       generated client
/infra           docker-compose, nginx conf, CI, README no-docker setup
AGENTS.md        conventions for AI agents (created in P0-T08)
```

**Rule:** everything under `games/domain/` is pure functions on plain data. No database, no clock, no randomness except via an injected `Random(seed)` and an injected `now`. This makes rules testable and replayable.

### 3A. Cache and queue abstraction (D-34)

Every use of Redis goes through two small interfaces in `app/core/cache.py` and `app/core/queue.py`. Application code never imports a Redis client directly.

```python
class CacheClient(Protocol):
    async def get(self, key: str) -> str | None: ...
    async def set(self, key: str, value: str, ttl_s: int | None = None) -> None: ...
    async def set_nx(self, key: str, value: str, ttl_s: int) -> bool: ...   # atomic create-if-absent
    async def incr_window(self, key: str, window_s: int) -> int: ...       # new count; TTL set on first hit
    async def delete(self, *keys: str) -> None: ...
    async def publish(self, channel: str, message: str) -> None: ...
    async def subscribe(self, channel: str) -> AsyncIterator[str]: ...

class QueueClient(Protocol):
    async def enqueue(self, task: str, payload: dict, delay_s: int = 0) -> str: ...
    async def run_inline(self, task: str, payload: dict) -> None: ...       # dev only
```

| Feature | Redis (prod, CI) | In-memory (local dev, tests) |
|---|---|---|
| Implementation | `RedisCache` (redis-py asyncio), `ArqQueue` | `MemoryCache` (dict + TTL sweep), `InlineQueue` |
| Selected when | `REDIS_URL` is set | `REDIS_URL` unset **and** `APP_ENV=dev`/`test`; startup logs one loud warning |
| Rate limiter (P0-T05) | Shared across instances | Per-process; one uvicorn worker only |
| Presence (P8-T04) | Shared; instances agree | Single-process only; empty from other instances |
| WS tickets (P8-T01) | Shared, single-use across instances | Single-process only |
| Pub/sub (P8-T03) | Real fan-out to all API instances | In-process dispatcher to local sockets |
| ARQ jobs (P5-T06, P7-T10, P10-T02) | Worker process | `run_inline`, or `python -m app.cli job run <name>` |
| Durability | Redis persistence config | **None**, lost on restart, by design |
| `SET NX` locking | Atomic across instances | Atomic within one process only |

**Rules for the in-memory path (non-negotiable):**

1. **Behaviour may differ only in durability and cross-instance sharing.** TTL expiry, `incr_window` counting once per window, `set_nx` returning false on the second caller, and single-use tickets must be **identical**. Both implementations run against the same conformance suite (`tests/core/test_cache_contract.py`).
2. **The in-memory implementations may never boot outside `dev`/`test`.** Startup **refuses to start** if `REDIS_URL` is unset while `APP_ENV` is `staging` or `prod`. A missing production Redis is a crash, never a silent single-instance fallback.
3. **Anything that must be correct under concurrency is still proven on Redis in CI** (P5-T12's 20 concurrent awards, P7-T11's one-seat race, P8-T19's two-instance pub/sub). Those tests carry `@pytest.mark.redis`; CI **fails if they are skipped** when `REDIS_URL` is present, and they skip with a printed reminder locally.
4. **Postgres remains the record** for time usage, XP, and results. Nothing durable is ever stored in the cache layer, so swapping implementations can never lose a learner's data.

### Domain model (source tables plus required additions)

Source tables: `games, game_versions, game_content_packs, game_sessions, game_participants, game_moves, game_results, game_invitations, game_access_policies, game_lockouts, game_xp_ledger, leaderboard_periods, leaderboard_entries`.

**Additions this plan needs (not in the source list):**

| Table | Purpose |
|---|---|
| `game_time_usage` | Seconds of active play per user per local date, split by source (online/offline) |
| `game_play_clock` | **One row per user per local date** holding `last_counted_at`. Required by D-26 so overlapping sessions cannot double-charge the daily allowance |
| `game_session_heartbeats` (optional; cache-buffered with periodic flush) | Evidence for time accumulation |
| `game_xp_daily_totals` | Per user per local date running total used to enforce the daily cap atomically |
| `game_pair_daily_counts` | Rewarded matches per opponent pair per day (anti-collusion cap) |
| `game_content_items` | The items inside a content pack (referenced by P4-T01; must exist as its own table) |
| `game_offline_batches` | Idempotent record of synced offline sessions (by client UUID) |
| `game_reports`, `game_blocks` | Report, block, mute flows (source section 8) |
| `game_notifications` | In-app notification inbox and unread badge (P7-T07) |
| `fairplay_flags` | Output of the P10-T02 suspicion signals; read by the leaderboard projection (D-33) |
| `audit_log` | Append-only record of every admin and coach action (P3-T09, P10-T03) |
| `auth_sessions` | Refresh-token rotation and revocation (P1-T02) |
| `school_terms` | School term calendar (`starts_on`, `ends_on`) used to cut termly leaderboard periods (D-35) |
| `age_bands`, `platform_settings`, `school_game_settings` | Config: bands, default/ceiling limits, XP caps, leaderboards on/off, period flags |
| `learning_xp_ledger` (stub in D-01) | Needed only so Profile XP can be computed; owned by the host platform in reality |

---

## PHASE 0: Foundations, repo, environments

**Objective:** a running skeleton on a Windows PC **without Docker** (the default), plus a container path for CI, where web, API, Postgres and optionally Redis are up and CI is green.
**Prerequisites:** none.

### Tasks
- **P0-T01 Confirm Decision Log.** Product owner reviews section 2. Output: any changed defaults edited in place. Do not proceed with unresolved D-01 to D-06.
- **P0-T02 Create monorepo** with the layout above. Add `.editorconfig`, `.gitignore`, `pre-commit` (ruff, ruff-format, mypy, eslint, prettier), and a **cross-platform task runner**: scripts in the root `package.json` (`npm run dev:api`, `dev:web`, `migrate`, `gen:api`, `test`, `lint`, `seed`). **No `make`** — it is not present on Windows.
- **P0-T03a Container path (CI and machines that do have Docker):** `docker-compose.yml` with services `db` (postgres:16), `redis` (redis:7), `api`, `worker`, `web`, `proxy`. Named volume for Postgres. Healthchecks on all. This is the reference environment and the one CI uses.
- **P0-T03b Windows-native path (no Docker — the default for local dev):**
  - **Postgres:** use the installed PostgreSQL (18.x is supported; prod stays 16, and migrations are verified against 16 in CI). Create a `stem_games` role and database; `DATABASE_URL=postgresql+asyncpg://…@localhost:5432/stem_games`.
  - **Redis:** optional (D-34). Either install a Redis-compatible Windows service (Memurai Developer) and set `REDIS_URL`, or leave `REDIS_URL` unset and run the in-memory `CacheClient`/`QueueClient` (section 3A).
  - **No reverse proxy:** `uvicorn` on `:8000`, `next dev` on `:3000`. The browser must still see **one origin**, so `next.config` gets a **dev-only `rewrites()`** mapping `/api/*` to `http://127.0.0.1:8000/api/*`. Next rewrites do **not** upgrade WebSockets, so `/ws/games` connects to `:8000` directly in dev — acceptable, because the ticket is an ordinary REST call and cookies work.
  - **No background worker:** run jobs on demand with `python -m app.cli job run <name>` (P0-T12).
  - Documented in `README.md` with exact commands; `AGENTS.md` states that this path must keep working.
- **P0-T04 FastAPI skeleton:** pydantic-settings config (env only), SQLAlchemy 2 async + asyncpg, Alembic, structured JSON logging with request-id middleware, `/health` and `/ready` endpoints, a **standard error envelope** `{error:{code,message,details,request_id}}`, and a global exception handler.
- **P0-T05 Rate limiter** as a reusable dependency built on `CacheClient.incr_window` (section 3A): `rate_limit(key_fn, limit, window_seconds)`. Used from Phase 1 onward. Returns HTTP 429 with `Retry-After`. **A lint test fails the build if any module outside `app/core/cache.py` imports a Redis client directly.**
- **P0-T06 Next.js skeleton:** App Router, TypeScript strict, Tailwind, TanStack Query, a design-token file (colors, spacing, radius, font sizes) so visuals can be restyled later without touching components. Tokens carry the **Appendix D minimums** (56 px tap target, 20 px body text) as defaults, not overrides. Include the dev-only `/api` rewrite from P0-T03b.
- **P0-T07 OpenAPI client generation:** script `npm run gen:api` (pnpm if available) producing `web/lib/api/`. CI fails if generated output is stale.
- **P0-T08 Write `AGENTS.md`:** conventions (folder rules, the pure-domain rule, "server decides" rule, naming, how to run tests, how to add a migration, never commit secrets, error envelope, pagination style, the cache/queue interface rule, and the no-Docker local path).
- **P0-T09 Alembic baseline** migration behind `npm run migrate` (wrapping `python -m app.cli migrate`).
- **P0-T10 CI pipeline** (GitHub Actions or equivalent): lint, typecheck, API tests with Postgres+Redis service containers, web build, e2e smoke (Playwright) on PRs. CI **fails on a skipped `redis`-marked test**.
- **P0-T11 Config for secrets and environments:** `.env.example`, separate `dev`, `staging`, `prod` settings; no secret has a default in code.
- **P0-T12 Operational CLI (`python -m app.cli`):** `migrate`, `seed`, `job list`, `job run <name>` (runs any ARQ task synchronously — weekly period generation, invite expiry sweep, challenge close, reconcile, anomaly scan). Required so every background job is testable **without Redis or a worker process** (D-34).

### Deliverables
Running skeleton, CI green, `AGENTS.md`, generated client.

### DoD
- **Path A (no Docker, the default):** on a Windows PC with no Redis running, `npm run dev:api` + `npm run dev:web` → `GET http://127.0.0.1:3000/api/health` returns 200 **through the Next rewrite**, `/ready` reports the database up and cache `in-memory`, and the landing page renders.
- **Path B (container):** `docker compose up` → the same two checks pass on `http://localhost`.
- `npm run migrate` upgrades to head and downgrades to base on an empty database.
- `python -m app.cli job run reconcile` completes with no worker and no Redis running.
- A deliberately failing test in CI blocks merge.
- Rate-limit dependency has unit tests (allows N, blocks N+1, resets after window) passing against **both** cache implementations.
- The direct-Redis-import lint test fails when a client import is added outside `app/core/cache.py`.

---

## PHASE 1: Identity, school context, roles

**Objective:** the minimum host-platform features games depend on (D-01). If the real platform already provides them, implement the same interfaces as **adapters** and skip the tables.
**Prerequisites:** Phase 0.

### Tasks
- **P1-T01 Tables:** `schools(id, name, timezone, leaderboards_enabled, ...)`, `users(id, school_id, role, preferred_name, real_name, avatar_key, date_of_birth, status)`, `classes(id, school_id, name, grade)`, `class_members(class_id, user_id)`, `coach_assignments(coach_id, class_id)`, `auth_sessions(id, user_id, refresh_token_hash, expires_at, revoked_at, created_ip, created_at)`. Roles enum: **exactly `learner, coach, school_admin`** (D-37). There is no platform or content role.
- **P1-T02 Auth:** login with a **student code + PIN** (D-36) — no email, no password — Argon2id for the PIN, logout, refresh rotation, cookie sessions per D-19, brute-force rate limit, account lockout backoff. A staff account uses the same two fields, so there is one sign-in form. PIN reset can be a stub if the host platform handles it.
- **P1-T03 RBAC dependencies:** `current_user`, `require_role(...)`, and **scope guards**: `require_same_school`, `require_coach_of(class_id | user_id)`. All service calls take an `actor` and check scope; no endpoint trusts a school_id from the client.
- **P1-T04 Age band service:** `age_bands` table (D-22) and `get_age_band(user, on_date)`.
- **P1-T05 Public profile projection:** `GET /profiles/{id}/public` returns **only** `preferred_name` and `avatar_key`. A dedicated serializer is the only code allowed to render another learner; real names never appear in learner-facing schemas (enforce with a test that scans response schemas).
- **P1-T06 Avatar set:** fixed set of ~24 non-photographic avatar keys (SVG, original art). Learners cannot upload images.
- **P1-T07 Frontend auth shell:** login page, session provider, role-aware navigation, route guards, "no access" page.
- **P1-T08 Seed script:** 2 schools, 2 school_admins, 3 coaches (one of them the word writer, holding no class), 3 classes, 35 learners. The second school exists to test isolation. Every account signs in with a code and the same dev PIN.
- **P1-T09 Learning XP stub:** `learning_xp_ledger(user_id, amount, reason, created_at)` plus a seed endpoint for tests only (disabled in prod).

### Deliverables
Working login, roles, seeded data, masked public profile.

### DoD
- Learner in school A cannot read anything about school B (tested for every endpoint so far).
- Coach cannot access a class they are not assigned to.
- Test proves real names are absent from every learner-facing response.

---

## PHASE 2: Games domain data model

**Objective:** the schema and persistence rules everything else builds on.
**Prerequisites:** Phase 1.

### Tasks
- **P2-T01 Migrations (in this order):** `games`, `game_versions`, `game_content_packs`, `game_content_items`, `game_sessions`, `game_participants`, `game_moves`, `game_results`, `game_invitations`, `game_access_policies`, `game_lockouts`, `game_xp_ledger`, `game_xp_daily_totals`, `game_pair_daily_counts`, `game_time_usage`, `game_play_clock`, `game_offline_batches`, `game_reports`, `game_blocks`, `game_notifications`, `fairplay_flags`, `audit_log`, `school_terms`, `leaderboard_periods`, `leaderboard_entries`, `platform_settings`, `school_game_settings`.
- **P2-T02 Key column decisions:**
  - `game_sessions`: `id (uuid)`, `game_id`, `game_version_id`, `mode` (`solo | challenge | live | offline_solo`), `status` (see Appendix A), `seed (bigint)` — **server-private, never serialised (D-25)**, `school_id`, `created_by`, `parent_session_id` (set on the two child attempts of a challenge, D-28), `rematch_of`, `started_at`, `ended_at`, `content_pack_id`, `config jsonb`.
  - `game_participants`: `session_id`, `user_id`, `seat` (unique on `(session_id, user_id)` and on `(session_id, seat)`), `attempt_status` (`not_started|in_progress|finished|expired`; on a `challenge` parent row it summarises the matching child), `counts_as_active bool` (**false** on a `challenge` parent's rows, true everywhere else — D-26/D-28), `joined_at`, `age_band_snapshot`, `class_id_snapshot`. **One attempt per session** (D-28): a challenge parent has two participant rows but holds **no moves of its own**.
  - `game_moves`: `id`, `session_id`, `user_id`, `move_number` (monotonic per session, **unique with session_id**; unambiguous because exactly one user writes moves per session, D-28), `client_move_id` (unique with session_id, for idempotency), `payload jsonb`, `client_ts`, `server_ts`.
  - `game_results`: `id`, `session_id`, `user_id`, `outcome` (`win|loss|draw|completed|no_contest`), `score`, `details jsonb`, `leaderboard_eligible bool`, `supersedes_id` and `superseded_by` (the correction chain, queryable both ways), `created_at`. A challenge writes its results on the **child** sessions.
  - `game_xp_ledger`: `id`, `user_id`, `game_id`, `session_id`, `reason`, `requested_amount`, `awarded_amount`, `local_date`, `school_id`, `class_id_snapshot`, `age_band_snapshot`, `leaderboard_eligible`, `created_at`, **unique `(session_id, user_id, reason)`** for idempotency.
  - `game_play_clock`: `user_id`, `local_date`, `last_counted_at`, unique `(user_id, local_date)`; `game_time_usage`: `user_id`, `local_date`, `source`, `active_seconds`, unique `(user_id, local_date, source)` (D-26).
- **P2-T03 Append-only enforcement:** Postgres trigger on `game_moves`, `game_results`, `game_xp_ledger` rejecting UPDATE and DELETE. Corrections are **new rows** (`supersedes_id`, or compensating negative ledger entries with reason `correction`). **Invariant:** at most one *unsuperseded* result per `(session_id, user_id)` — enforce with a partial unique index on `(session_id, user_id) WHERE superseded_by IS NULL`, and add a `superseded_by` column so the chain is queryable in both directions.
- **P2-T04 Indexes:** partial unique `ux_participants_one_active_play` on `game_participants (user_id) WHERE counts_as_active AND attempt_status = 'in_progress'` (this **is** the D-26 rule: one open play per learner, decided by Postgres so two tabs cannot both win); `(user_id, local_date)` on usage, XP and `game_play_clock`; `(school_id, age_band_snapshot, created_at)` on XP ledger for leaderboards; `(session_id, move_number)`; `(parent_session_id)` partial where not null; `(period_id, game_id, xp_total DESC)` on `leaderboard_entries`; partial index on active invitations by status.
- **P2-T05 Config seeding:** `platform_settings` (default limit 120, ceiling 240, daily XP cap 60, live-match minimum remaining 15, game list flags, period flags for D-35), `age_bands`, two sample `school_terms` per seeded school, and `games` rows for the 3 launch games with `enabled=false` until their phase completes.
- **P2-T06 Repository layer** (thin SQLAlchemy functions; no business logic).
- **P2-T07 Tests:** UPDATE/DELETE on append-only tables fails; unique constraints reject duplicates; foreign keys behave; **`seed` is absent from every response schema** (schema-scan test, extends P1-T05); creating a challenge produces exactly one parent and two children, both children share the parent's seed and the parent holds no moves (D-28); a second concurrent active session for one user is refused by the database (D-26), a finished attempt frees the learner, and two classmates in one live match may both be playing.

### DoD
- `alembic upgrade head` and `alembic downgrade base` both work on an empty DB.
- Append-only trigger tests pass.

---

## PHASE 3: Access policy, play time, lockouts

**Objective:** nothing can be played until the server says it may. This is built **before any game** so every game inherits it.
**Prerequisites:** Phase 2.

### Tasks
- **P3-T01 Policy tables logic:** `game_access_policies(scope_type: platform|school|class|student, scope_id, daily_limit_minutes, valid_from, valid_until, set_by, reason)`. `game_lockouts(scope_type: class|student, scope_id, reason NOT NULL, starts_at, expires_at NOT NULL, created_by, revoked_at)`.
- **P3-T02 Resolver (pure function + service):** `effective_limit_minutes(user, local_date)` implementing D-08: choose the most specific active, non-expired policy; clamp to `[0, platform_ceiling]`. Returns the winning scope for display ("set by your coach").
- **P3-T03 School-local day:** helper `local_date(now_utc, school.timezone)`. All usage, XP caps, and limits use it. Handle DST and timezone changes (store `local_date` on rows, never recompute historically).
- **P3-T04 Play-session heartbeat protocol:**
  - `POST /games/sessions/{id}/start` marks active play begin and **must refuse a second concurrent session** for the same user (`another_session_active`, D-26).
  - `POST /games/sessions/{id}/heartbeat` every 15 s from the client when conditions in D-11 hold. Body: `{visible: bool, last_input_age_s: int}`.
  - Server adds `min(server_elapsed_since_last_heartbeat, 30)` seconds, **ignoring the client's own claimed duration**. Missed heartbeats do not accrue time.
  - `POST /games/sessions/{id}/pause` and automatic server-side pause when heartbeats stop for >45 s. **Pause and resume both reset `last_counted_at` to now**, so returning from a pause never charges a spurious 30 s.
- **P3-T05 Usage accumulation (single accrual function, D-26):** both heartbeats **and game actions** (answers, guesses, moves) call `record_activity(user_id, at)`, which works on the **user's** clock row:
  1. `INSERT INTO game_play_clock … ON CONFLICT DO NOTHING`, then `SELECT … FOR UPDATE` that `(user_id, local_date)` row. (Insert-then-lock, so two concurrent first-writes of the day cannot collide on the unique key.)
  2. Accrue `min(now - last_counted_at, 30 s)` into `game_time_usage(user_id, local_date, source)`.
  3. Set `last_counted_at = now`.
  Because the clock is **per user**, not per session, a second tab cannot age the allowance twice, and a heartbeat plus an action in one interval never double-counts. A client that suppresses heartbeats while still playing is still charged through its actions. Postgres is the record; Redis may buffer, and the buffer flushes on session end.
- **P3-T06 `GET /games/access`:** returns `{allowed, reason, limit_minutes, used_seconds, remaining_seconds, locked_until, limit_source, server_time}`. Reasons: `ok | limit_reached | not_enough_time | locked_out | games_disabled | another_session_active | leaderboards_only`. `not_enough_time` is the D-27 case where some time is left but not the 15 minutes a live match needs — it is deliberately not `limit_reached`, because "you have used all your time" would be false. `server_time` lets clients render the reset time without trusting the device clock.
- **P3-T07 Enforcement dependency `require_game_access(min_remaining_s=0)`:** used by every "create/join session" and "start" endpoint. Checks: user active, games enabled for school, not locked out, no other active session, `remaining_seconds > min_remaining_s`. Live match starts pass `min_remaining_s = 900` (D-27).
- **P3-T08 Soft-limit behavior (D-10, D-27):** a **solo or child challenge** session already `active` may continue until it ends or 10 minutes past zero remaining, whichever comes first; then the server ends it (`status=timed_out_allowance`), and for `solo` the final result is still recorded (subject to D-29). A **live** match that legally started under D-27 is **exempt** from that cutoff and plays to completion; no *new* session may start. A coach **lockout** is different and immediate: a live match becomes `no_contest` (no XP, no loss) and the opponent is notified.
- **P3-T09 Lockout/limit endpoints and RBAC (D-09):** CRUD for policies and lockouts with scope checks and mandatory `reason`. Every change writes an audit log row.
- **P3-T10 Admin/coach UI:** class and student tables with current effective limit, "adjust limit" dialog (minutes, optional expiry, reason), "lock out" dialog (reason and expiry required), visible history.
- **P3-T11 Learner UI:** time-remaining meter in the games hub header, stated as a sentence per Appendix D ("You have 12 minutes left today. Then you can play again tomorrow."); friendly card states for `limit_reached`, `locked_out` and `another_session_active` (one icon, one sentence, one button, never an error screen); the `another_session_active` card carries **one button back into that game** (`GET /games/sessions/active` decides which screen, so the card never guesses); 10-minute and 2-minute warnings.
- **P3-T12 Tests:** resolver precedence matrix; clamp to ceiling; coach cannot exceed scope; heartbeat spoofing (huge client duration ignored, rapid heartbeats do not double-count); **two tabs cannot consume the allowance twice (D-26)**; **pause and resume charge 0 s**; **a second concurrent session is refused**; **a live match is refused when remaining < 15 min (D-27)**; DST day boundary; limit raised mid-day takes effect immediately; lockout expiry.

### DoD
- A learner with 119 minutes used can start one more session; at 120 the next start returns `limit_reached`.
- Forged heartbeats cannot increase time faster than wall clock, and playing with heartbeats suppressed still accrues time through actions.
- Two open tabs do not consume the allowance twice, and returning from a pause adds no time.
- All RBAC edge tests pass.

---

## PHASE 4: Game shell, content operations, Word Scramble

**Objective:** first complete vertical slice: a learner plays Word Scramble online, result recorded, within time rules.
**Prerequisites:** Phase 3.

### 4A. Content operations (needed for Word Scramble)
- **P4-T01 Content pack schema:** `game_content_packs(id, game_id, version, locale, age_band, difficulty, status, source, author_id, reviewer_id, safe_language_reviewed, curriculum_ref, created_at, published_at)` with items in `game_content_items(id, pack_id, payload jsonb, difficulty, sort_order, **status, published_by, published_at**)`. **A word carries its own status** (D-38): `draft | live | retired`. The pack is the bucket; the word is what a child plays, so the word is what is served. Word Scramble item payload: `{answer, clue, clue_audio_key?, clue_image_key?, alt_answers[], difficulty}`. At least one of `clue`, `clue_audio_key`, `clue_image_key` is required, and **every item in the youngest band must carry an audio or image clue** (Appendix D: a text-only clue cannot be read by the target player).
- **P4-T02 Status workflow (D-38):** each word moves `draft -> live -> retired`, one at a time, and **its author may make it live**. The game serves items whose `status = 'live'` in a pack that is not retired; nothing is served by pack status alone. A word with any problem in P4-T03 cannot go live, by the single button or the bulk one. The same answer may not be live twice in one band. Editing a live word returns it to `draft`; taking a word down sets `retired`. Only a draft may be deleted. A bulk action makes every ready draft live and reports how many moved. There is **no pack-level review chain**: no `in_review`, no `approved`, no second reader, no rejection note.
- **P4-T03 Validation before a word may go live:** answer is letters only (allowing hyphen/apostrophe by locale rule), length 4-12, **at least 2 distinct permutations must exist** (reject items like `zzzz` where the only permutation equals the answer, or the scramble generator loops forever), no duplicates within pack, clue not empty and does not contain the answer, safe-language word-list check (blocklist) that stops the word going live — **offline and deterministic**, never an AI call: profanity, slurs, sexual content, hard drugs, self-harm and graphic violence, with disguised forms (`sh1t`, `fuuuck`, plurals) normalised first, and matched **per word** so `grass`, `class` and `essex` still pass (`app/games/domain/safe_language.py`). The refusal sentence never repeats the offending word. A school admin can add a word from the app (D-39), and it bites on the next save. The ≥ 15 usable items per (age band, difficulty) rule is **checked at `start`, not at publish** (D-38): words go live one at a time, so a half-filled level is a normal state and `start` fails cleanly with `not_enough_content` instead of retrying forever. The content screen shows the count as advice.
- **P4-T04a Blocked words screen (school admin only, D-39):** the school's own additions (add and remove) plus the baseline list, collapsed behind a count so the screen is not a wall of slurs. Reads are open to both staff roles, so a coach can find out why a word was refused; writes are the admin's alone. Every add and remove is audited.
- **P4-T04 Words UI (one screen, both staff roles):** pack list with live/draft counts, create/edit items (with bulk CSV import, row-level error report), **preview mode** (plays without recording results or XP), and a per-row **Make it live** / **Take it down** button plus a bulk **Make the ready words live**. The screen never shows a raw status code, and never offers the button on a word that still has a problem.
- **P4-T05 Removed (D-38):** there is no review queue, no reject-with-comment and no second reader. Its replacement is the per-word publish above. Any later phase that needs a second person's sign-off must add it back as a real workflow with a reason, not as a role.
- **P4-T06 Starter content:** ≥ **150 usable words per launch age band**, spread across easy/medium/hard (not 150 per difficulty), every one a draft until a coach makes it live (D-38), with audio or image clues for the youngest band. **Scope decision for the pilot: ship two age bands**, not four — 150 × 4 bands is a content project larger than Word Scramble itself. Content is a **blocking dependency** of this phase's DoD.

### 4B. Game shell and session lifecycle
- **P4-T07 Games hub page:** catalog cards (only enabled games), time-remaining meter (from P3), "Boards" link (placeholder until P5).
- **P4-T08 Generic session service:** `create_session`, `start`, `submit_action`, `complete`, `abandon` (exposed as `POST /games/sessions/{id}/quit`). **Leaving on purpose is a real end:** tapping a menu tab mid-round asks first ("Leave this game? / Your game will end."), and a confirmed quit sets the session `abandoned`, the attempt `expired`, writes no result and no XP, and frees the one-active-session seat at once. It is the same call every mode uses, so a live match (P8) closes its socket when its session is no longer open — the server is still the one that decides. A challenge turn that is quit closes that challenge's window immediately (P7-T05), so the friend who played is not left waiting a day, and is told "Bayo stopped playing." rather than being told they ran out of time. Each game registers a handler implementing an interface: `init(seed, config) -> state`, `apply(state, action, now) -> (state, events)`, `is_finished(state)`, `result(state) -> Result`. **One active session per user** (D-26): `create_session` refuses with `another_session_active`. A `challenge` parent is created with two child `solo` sessions (D-28). **Solo abandonment rule:** a `solo` session with no heartbeat and no action for 10 minutes is set to `abandoned` by the sweeper: no result row, no XP, time already accrued stays counted. This rule is the **only** way a silent session ends — rounds never auto-complete a session (see P4-T10). **In local development the API process runs `sweep_sessions`, `sweep_invites` and `sweep_live` itself, once at startup and then every minute, through the same registry the worker uses** (`app/jobs/scheduler.py`, dev only). Without that, rule 8 (no worker, no Redis locally) would make the abandonment rule true only in production, and a closed tab would hold a seat until the next manual `job run`.
- **P4-T09 Game registry** keyed by `game_id` + `game_version`. Result rows record the version for reproducibility.

### 4C. Word Scramble
- **P4-T10 Rules (pure, in `domain/wordscramble.py`):**
  - Session = **10 rounds**, items drawn by `Random(seed)` from the **live words** matching the learner's age band, locale, and chosen difficulty (D-38), with no repeats in one session. The session records the newest open pack it drew from, so a result can be traced back to the words it came from.
  - Server sends per round: scrambled letters (a permutation that differs from the answer by construction), clue, and the round length (45 s). **Never sends the answer and never sends the seed (D-25).**
  - **Round clock:** the timer starts when the client **acknowledges the round** (`type: round_seen`), not when the server sends it, so a slow connection cannot lose a round (D-24). The server stores `round_started_at` and judges deadlines on its own clock with a **2 s grace**.
  - **Attempts:** two per round. Attempt 1 correct = full score; attempt 2 correct = **half** the round score, rounded down; two wrong = 0 and the round ends.
  - **Hint:** at most one per round, reveals the first letter, costs **3 points** from that round, and the round score is **clamped at 0** (a hint can never make a round negative).
  - **Skip:** ends the round immediately for 0 points and counts as a played round. Skipping ends the round, so that round's timer stops.
  - **Timeout:** 0 points. The round advances only on answer, skip, or its deadline expiring **while the session is active**; a session with no input at all never auto-completes — the P4-T08 sweeper abandons it.
  - Score per round: `10 + time_bonus - hint_cost`, where `time_bonus` is `0..5` linear over the round timer. The time bonus is **not shown as a separate number** to the learner (Appendix D): the UI shows only "Correct! +10".
  - Session score = sum of the 10 round scores (maximum 150).
  - Valid if answer equals `answer` or any `alt_answers`, case-insensitive, trimmed.
- **P4-T11 Endpoints (every action calls `record_activity`, see P3-T05):** `POST /games/word-scramble/sessions` (difficulty; refuses with `another_session_active` if one is open), `POST /games/sessions/{id}/actions` (`{client_move_id, type: round_seen|answer|hint|skip, value}`), `GET /games/sessions/{id}` (state for reconnect, returning `round_time_left_ms` computed server-side and **never** the seed). Server validates round deadlines using its own clock with the 2 s grace.
- **P4-T12 Persistence:** each action stored in `game_moves` (so a session is replayable from `seed + moves`). On completion write one `game_results` row (`outcome=completed`, `score`, `details`, snapshots of class/age band, `leaderboard_eligible=true` for online solo; this flag only says the result is server-verified. Final board eligibility is decided on the ledger row in P5-T04 and by the activity minimum in D-29).
- **P4-T13 UI (Appendix D applies in full):** large letter tiles, tap-to-place with a visible undo, only the next empty slot active; clue with an image/audio clue in the youngest band; the round timer is a **filling bar**, not a countdown ring; progress dots; one big "I don't know" button (this is the skip action, not a hidden gesture); hint button shows exactly "Take a letter (−3)"; round feedback says only "Correct! +10" or "Not quite — try again, 1 try left"; end screen with score, a plain sentence ("You got 8 of 10 words. Good job.") and one "Play again" button (respecting access). Keyboard and touch accessible; high-contrast and reduced-motion respected.
- **P4-T14 Resume:** refresh mid-session restores state from `GET /games/sessions/{id}` including round time left.
- **P4-T15 Tests:** unit tests of rules (scramble never equals answer, the two-attempt scoring table, hint clamp at 0, skip = 0, alt answers); API tests (early answer before `round_seen` rejected, late answer rejected, duplicate `client_move_id` returns the same response, **neither `answer` nor `seed` present in any response payload**); e2e: play 10 rounds; session respects limit; session with 10 minutes of silence and no input becomes `abandoned` with no result or XP; a second session is refused while one is active (D-26).

**Note on the abandonment test:** with the round clock starting on `round_seen`, a silent client never acknowledges a round, so the session stays `active` and the sweeper is the only thing that ends it. That is the behaviour these tests assert.

### Deliverables
Content workflow, hub, Word Scramble playable online.

### DoD
- A complete session creates exactly 10 move groups and 1 result row.
- Inspecting network responses never reveals unrevealed answers **or the seed**.
- **Appendix D.5 first-session test passes (4 of 5 first-time players)**, including a player who cannot read the clue. **Partly verified** — two fresh learners now complete a round from the picture alone; the five-learner study is still owed.
- Word Scramble `games.enabled` can be set true for a pilot school flag.

**D.5 first-session gate, walked (Word Scramble):** two learners with no session open (Chika A-1003 fresh, Bayo A-1002) started from the hub and played without reading the clue. All three steps now pass: **hub → card → level is three taps**, with a picture on the card and stars on the level buttons; **the first round was completed from the picture alone**, twice — 🧦 spelled SOCKS and SHAPE from its clue — each answered "Correct! +12" by the server; and **the consequence question is answerable by pointing** at the card that says *Empty bar, no points.* Measured on the round screen: 21 words excluding the letter tiles, or 25 with the longest clue in the bank (limit 25), every target at least 56×56, type at 16/20/24px. Eight breaks, all fixed:

- **Every clue was text-only, so a learner who cannot read could not name the word at all.** This is the gate's real finding, and it was a content problem before it was a screen problem. The easy words now carry a pictogram in the seed (46 of 50 — `table`, `brave`, `window` and `brush` deliberately have none, because a wrong picture misleads more than no picture), the screen draws that picture large instead of printing the raw key the way it used to, and `clue_image_key` is documented as "a pictogram, or a path/URL once reviewed drawings exist". The seeder sets or clears pictograms on starter items but never overwrites a reviewed file.
- **Nothing said what an empty bar means** (D.2.3, step 3 of the gate). The round screen now carries the same ⏳ card as Checkers: *Empty bar, no points.*
- **The instruction was not at the top.** It only appeared inside the answer area and vanished after the first tile (D.2.1). *Tap the letters.* is now the first line.
- **A running "Score 12" and "Word 3 of 10"** contradicted D.2.5 (points are shown only as what was just gained) and spent six of the twenty-five words. Both are gone; the progress bar says where you are and *Correct! +12* says what you earned.
- **The level buttons were words only**, so a non-reader could not tell which one is the gentle start. They carry ★☆☆ / ★★☆ / ★★★ now, with the words kept for readers.
- **The choosing screen carried the whole class roster inline** — about 34 words, well past the limit, and one mis-tap sent an invite. *Play with a friend* opens the roster instead.
- **Undo was invisible.** Tapping a placed tile took it back, but nothing said so (D.3 asks for a visible undo). The placed tile now carries a ×.
- **Smaller:** the round screen had no picture branch at all and printed `Picture clue: honey-1` — a raw key — where a picture belonged.

**Pinned by a test:** `test_every_easy_word_has_a_picture_or_is_a_named_exception` asserts that every easy word carries a picture except the four named exceptions, so a fifth text-only easy word fails the suite instead of a child.

**Still open for P4:** the five-learner study, and the content tail — medium and hard words are still text-only, the 8-10 band remains blocked on picture or sound clues, and these pictograms are a stand-in until reviewed drawings replace them. The audio route is deliberately unused: there is no read-aloud feature (D-36).

---

## PHASE 5: XP ledger, Profile XP, leaderboards

**Objective:** results turn into Game XP (with caps), Profile XP is presented, and the daily, weekly and all-time boards work off one projection (D-35).
**Prerequisites:** Phase 4.

### Tasks
- **P5-T01 XP rules (pure, `domain/xp_rules.py`):** input = result + context -> `requested_amount` per D-13, every number from config. **Formulas (max performance bonus is 10 in every game):**
  - Word Scramble: `bonus = round(10 * score / 150)`, plus participation 5.
  - Number Guess: `bonus = round(10 * score / 500)` (5 numbers × 100 max), plus participation 5.
  - Checkers: win 10 / draw 5, which **replaces** the performance bonus; plus participation 5.
  - Challenge win: +5 on top, still subject to the daily cap and the pair cap.
  - **Activity gate (D-29):** if the session missed its minimum, `requested_amount = 0` and `leaderboard_eligible = false`, but the ledger row is still written with `reason='below_minimum'` so the decision is auditable.
- **P5-T02 XP award service (transactional):**
  1. Begin transaction; `INSERT … ON CONFLICT DO NOTHING` the `game_xp_daily_totals(user_id, local_date)` row, then `SELECT … FOR UPDATE` it (insert-then-lock: two concurrent first awards of the day must not collide on the unique key).
  2. `awarded = min(requested, daily_cap - total_so_far)`, never negative.
  3. Insert the ledger row (unique key makes retries idempotent), update the daily total, commit.
  4. Rows record both `requested_amount` and `awarded_amount` so capping is auditable.
  5. `game_pair_daily_counts` uses the same insert-then-lock pattern and is locked **before** the ledger row, so every award takes locks in one order and cannot deadlock.
- **P5-T03 Trigger point:** XP is awarded **only by the server when a result row is written** (same transaction or an outbox event processed by ARQ with at-least-once delivery and idempotent keys). No endpoint accepts an XP amount.
- **P5-T04 Eligibility flags:** the ledger row's `leaderboard_eligible` is the **final** flag and is true only if the result's own flag is true and: online, verified server-side, not `no_contest`, meets the activity minimum (D-29), the pair/day caps allowed it, and the session is not flagged by fair play (P10). **Exclusion is enforced twice:** the projection filters flagged/excluded sessions at write time **and** the nightly reconcile filters the same way (D-33). A school admin's exclusion therefore takes effect at the next reconcile **without** rewriting ledger rows; compensating entries are written only when the XP itself must be removed.
- **P5-T05 Profile XP (presentation only):** `GET /me/xp` returns `{learning_xp_total, game_xp_total, profile_xp_total, game_xp_today, daily_cap}`. `profile_xp_total = learning + game` where game is the capped sum from the ledger. Document and enforce: **no grade, badge, certificate, completion, or eligibility code may read Profile XP or Game XP** (add a lint test that greps the codebase for imports of the XP module outside allowed modules).
- **P5-T06 Leaderboard periods (D-35):** `leaderboard_periods(id, school_id, period_type, starts_at, ends_at, status)` with `period_type ∈ daily | weekly | monthly | termly | all_time`.
  - **Shipped:** `daily`, `weekly`, `termly`, `all_time`. `monthly` exists behind the `leaderboards.monthly_enabled` flag — same generator, same projection, no extra code path.
  - **Boundaries are school-local (D-07):** daily at 00:00, weekly on Monday 00:00, termly on the first day of the school's term, `all_time` = one row per school with `starts_at` = the school's first eligible award and `ends_at = NULL`.
  - **Term calendar:** `school_terms(id, school_id, name, starts_on, ends_on)`, maintained by the school admin with the same scope rules as limits (P3-T09). **A school with no terms configured has its termly board hidden**, not guessed: the API returns `period_unavailable` and the UI shows only the boards that exist.
  - **Generation:** a job closes the period that just ended and opens the next, run at each boundary, on first read, and by hand via `python -m app.cli job run roll_periods` (P0-T12). Periods are also created on demand at award time, because an award must never land in a missing period.
  - Never pre-generate more than one period ahead; a school's config may change.
- **P5-T07 Leaderboard projection (D-33):**
  - On each eligible XP award, upsert `leaderboard_entries(period_id, school_id, class_id NULL|id, age_band, game_id NULL|id, user_id, xp_total, sessions_count, last_award_at)` **into every open period for the school** (all-time, today, this week, this term, and this month if enabled). **Exactly two rows per period per award:** one for `game_id=<game>`, one for `game_id=NULL`. Unique key `(period_id, user_id, game_id, class_id, age_band)`.
  - **`all_time` is the one row set that is never reset.** It is maintained by the same upsert (no end date), so it must be correct from the first award onward — it cannot be rebuilt from "the last period" the way a weekly board can.
  - The age band is **locked at the learner's first eligible award of the period**, so nobody appears in two bands in one week. `class_id` follows the snapshot, so a mid-week class transfer leaves rows under two classes.
  - **`sessions_count` increments at most once per (session, user), not once per ledger row.** A challenge can write two ledger rows for one attempt (participation + `challenge_win`); counting awards instead of sessions would let a single game satisfy the D-14 minimum of 3.
  - **Read rules — never sum a `game_id=<game>` row together with a `game_id IS NULL` row:**
    - Per-game board: the `game_id = <game>` rows.
    - All-games board: the `game_id IS NULL` rows.
    - Class board: filter `class_id` **after** choosing the row set; a learner with two class rows appears once per class with that class's total.
    - School board: sum the chosen row set grouped by `user_id` across classes, sum `sessions_count`, tie-break on `MAX(last_award_at)`.
  - Nightly ARQ **reconcile job** recomputes totals from the ledger, **excluding** sessions flagged or excluded by P10, and fixes drift; log and alert on any mismatch. **Shipped as a rebuild:** it compares each open period's expected rows (per-game **and** all-games, grouped by user, class snapshot and age band) with the stored ones and rewrites only the rows that differ, so a clean run reports `drift_rows: 0` and writes nothing. The flag filter is `fairplay_flags.session_id → game_sessions` added in `0012_fairplay_session` (the column P10-T02's shape always called for); a flag with status other than `cleared` removes that session from every board and **never** touches a ledger row. Admin exclusions reuse the same filter when P10-T03 lands.
  - Clients can never write these tables.
- **P5-T08 Ranking rules:** order by `xp_total DESC`, tie-break by earlier `last_award_at` (for a summed row, `MAX(last_award_at)`), then `user_id`. Entries below the D-14 minimum — counted from the **chosen row set**, not from one class row — are hidden. Rank is computed at read time with a window function per `(school, age_band, optional class, game, period)`.
- **P5-T09 Endpoints:** `GET /leaderboards/{period}?game=&class=&age_band=` where `period ∈ daily | weekly | monthly | termly | all_time`, returning the top 10 plus the caller's own rank with masked identity (D-15); `GET /leaderboards/{period}/me`. **`all_time` is admin-only:** school admins for their own school only (D-37). A learner or coach requesting it gets a **generic 404** (not 403), so the board's existence is not advertised. Respect `school_game_settings.leaderboards_enabled` and the per-period flags; a period with no calendar returns `period_unavailable`.
- **P5-T10 Frontend:** XP header chip (profile XP with tooltip splitting learning vs game), post-game XP summary ("+12 XP, 48/60 today"), leaderboard page with **period tabs (Today / This week / This term)**, game and class filters, self-row highlight, empty and "not enough activity yet" states, and the period countdown in school timezone. **The All time tab appears only in admin views**, never in a learner or coach page. Tabs for a period the school cannot have (no terms, monthly off) are hidden, not disabled.
- **P5-T11 Coach view:** class leaderboard with the same masked identity, plus a per-student Game XP breakdown (auditable from the ledger). **Shipped as `GET /leaderboards/{period}/students?class_id=&age_band=`, staff only:** a coach is scoped to their assigned classes and gets a **404** for anyone else's class, an admin sees the whole school. The breakdown reads the **per-game rows only** (D-33) and the screen (`/coach/xp`) shows every learner who has played, including those below the learner-facing minimum, because a coach needs the small numbers too.
- **P5-T12 Tests:** cap enforced under 20 concurrent awards (concurrent on real Postgres; not `redis`-marked); retries do not double-award; leaderboard equals ledger sum after reconcile; **a board never double-counts the all-games row with a per-game row (D-33)**; **a session flagged by fair play disappears from the board at the next reconcile while its ledger rows stay**; **a below-minimum session awards zero XP yet still writes an auditable ledger row (D-29)**; a learner transferred mid-week appears correctly on both class boards and once on the school board; **boundaries on all four periods: midnight for daily, Monday 00:00 for weekly, term start for termly, never for all-time**; **all-time XP only ever grows and equals the sum over the whole history**; **a learner and a coach both get 404 on `all_time` while a school admin gets the board**; **a school with no `school_terms` hides termly instead of showing an empty board**; **monthly appears only with `leaderboards.monthly_enabled`**; age band snapshot stays after birthday; learner never sees real names; disabled-leaderboard school gets 404/empty; Game XP excluded from any academic-progress module (lint test).

### DoD
- Playing 5 Word Scramble sessions in a day caps at 60 Game XP.
- Daily, weekly and termly boards show correct ranks for a seeded class and each resets at its own boundary.
- The all-time board is reachable by an admin and **not** by a learner or coach, and equals the total of every eligible award.
- Reconcile job reports zero drift on the seeded dataset, and repeats with a flagged session excluded.
- Board totals match the ledger exactly under the D-33 read rules (no double counting).

---

## PHASE 6: Guessing Game (Number Guess)

**Objective:** second game, validating a different session shape (server-held secret, attempts).
**Prerequisites:** Phase 5.

### Tasks
- **P6-T01 Rules (pure, `domain/guessing.py`):**
  - Difficulty -> range and attempts: Easy 1-50 / 8 attempts; Medium 1-200 / 9; Hard 1-1000 / 10. (Config.)
  - Secret derived from `Random(seed)`; **held server-side only**, and the seed itself never leaves the server (D-25), so the secret cannot be recomputed by a client.
  - Each guess returns `higher | lower | correct`, plus attempts left. Invalid (out of range, non-integer, repeat) guesses do not consume an attempt.
  - Session = **5 numbers** per game for a meaningful score (one number is too short to be worth XP).
  - Score per number: correct on attempt k of N -> `round(100 * (N - k + 1) / N)`, miss = 0. Session score = sum.
  - Optional curriculum flavour later: "guess the value" with math hints (kept out of MVP).
  - **Shipped:** the secret is **derived, not stored**: `secret_for(seed, index, difficulty)` seeds `Random(f"{seed}:{index}")`, so nothing in the session row, the moves or a response ever contains a number to strip. Score uses half-up rounding (`int(x + 0.5)`), because Python's banker's rounding would pay two learners differently on the same try. Invalid guesses answer with a code **and** the fixed sentence, and cost nothing.
- **P6-T02 Endpoints** reuse the generic action endpoint with `type: guess`.
  - **Shipped:** `play.create_solo/get_state/submit_action` dispatch to `services/guessing.py` for `number_guess`, so the router stays generic and Word Scramble is untouched. Ending a session moved to `services/results.py`, shared by both games, so XP is still awarded in the same transaction as the result (P5-T03).
- **P6-T03 UI (Appendix D applies in full):** big number pad **and** a +/- stepper; history of guesses with arrows; a range bar that **visibly shrinks** after every guess; feedback as a big arrow **plus words** ("Too low — go up"); tries left as filled pips **and** words ("3 tries left").
  - **Shipped:** a **12-key pad** on Easy and Medium (1–9, ⌫, 0, ✓), every key 56px, whose own ✓ is the submit — so those two bands never show two buttons for one action. The pad appends digits to one draft and **replaces** a machine-set number on the first tap, so a child who wants 12 does not get 2512. The −/+ stepper stays under the box on every band, because a learner who is close wants to nudge a step rather than retype. Hard keeps the typed box and the big button: at 1–1,000 the device's keyboard beats four taps. The band arrives on the round payload as `difficulty`, so the screen renders what the server decided instead of inferring the control from the range width. The box starts at the middle of what is left, which is both the best next guess and the answer to "what do I type?". The round clock is shared with Word Scramble (`components/RoundClock.tsx`), so the bar behaves identically in both games.
- **P6-T04 XP and board wiring:** XP rule per P5-T01 (participation 5 + `round(10 * score / 500)`, gated by D-29); appears on per-game and all-games boards.
- **P6-T05 Content:** none required (no packs); `game_content_packs` not used. Confirm the shared pipeline handles games without packs.
  - **Shipped:** the registry splits `GameHandler` (metadata) from `ContentGameHandler` (round builders), so a game with no content says so by not being one, and `content_handler_for` fails loudly rather than treating it as an empty content game.
- **P6-T06 Tests:** **neither the secret nor the seed is serialised in any response, log line, or error detail (D-25)**; binary-search player always solves within the available attempts (sanity check that attempts are sufficient: Easy needs 6 of 8 given — 2^6 = 64 > 50; Medium needs 8 of 9 — 2^8 = 256 > 200; Hard needs 10 of 10 — 2^10 = 1024 > 1000, so the hard band has no margin and must be re-tuned if the range grows); replay reproduces results from seed + moves; a below-minimum session (fewer than 2 solved) awards zero XP and is not board-eligible (D-29).

### DoD
Playable, XP awarded, on board, passing tests; `games.enabled` flipped for pilot; **Appendix D.5 first-session test passes**. **Partly verified** — a fresh learner makes the first guess without reading and can point at the consequence card; the five-learner study is still owed.

**D.5 first-session gate, walked (Number Guess):** a fourth learner with no session open (Dayo A-1004) started from the hub and guessed without reading a word. All three steps now pass: **the card, the stars and Easy are three taps**; **the first guess is one tap** — a number is already in the box and a single button submits it (the pad's ✓ on Easy and Medium, the big button on Hard) — and the screen answers with a large ↑, *Too low. Go up.*, a window that moved from 1–50 to 27–50 and pips that fell from 8 to 7; and **the consequence question is answerable by pointing** at *Empty bar, no points.* Interface prose is now **21 words, or 25 with the server's feedback sentence** (limit 25), with every target at least 56×56. The guess chips are the game's own record like the pips, not sentences to read. Four breaks, fixed:

- **A running "Number 1 of 5 / Score 0" row** — six words of the twenty-five, and D.2.5 allows only the points just gained. Gone.
- **No instruction at the top.** The only line was *Type a number, then press the big button*, tucked under the range and hidden once a guess landed. *Tap a number.* is the first line now.
- **Nothing said what an empty bar means** (D.2.3, step 3 of the gate). Same ⏳ card as the other two games.
- **Two identical blue bars** — rounds and time — so a learner watching a bar drain could not tell which one runs out. Rounds are progress dots in both games now (which is what P4-T13 asked for), and the unfilled dots use the border colour instead of the surface colour, because they were invisible against the page.

D.3's 12-key pad now ships on the two bands a child starts on, with the stepper kept beside the box, so the source's "pad **and** stepper" is met where a child actually starts. The one remaining difference is Hard, where the typed box and the big button stay: at 1–1,000 the device's keyboard beats four taps, and choosing Hard already means the learner will type. On Easy and Medium the pad's ✓ is the single submit, so step 1 is still one tap.

**A guess looked as if it had been lost, and was not.** The walkthrough twice showed *Too high. Go down.*, a narrowed window and a fallen pip, and then, seconds later, an untouched round. Nothing was lost: the number's 60 seconds ran out while the screen sat idle, so the server had already recorded the guess, scored that number 0 and opened the next one, and the next poll drew the new round over the old sentence. The append-only move log and the round index say so — the guess sits at move 2, and the session stands at `round_index` 2 with two zero scores. Two simultaneous guesses also counted both tries, with and without the `FOR UPDATE` lock the live-match path uses, so no lock was added here. What the pause did expose was a real edge for a slow player: the board reset with no sentence saying the number was missed. **Fixed:** when the server advances an expired number it now answers with *Time is up. It was 37.* in the same response that opens the next one, so the poll (or a guess racing the deadline) shows the sentence above the new round for four seconds instead of swapping the board silently. The server still owns the deadline and the wording; `test_a_number_that_runs_out_says_which_number_it_was` pins it.

**Shipped and verified:** migration `0013_number_guess_live` enables the row; a scripted learner played three real sessions through the public API only (binary search on the server's answers), earning 11 + 9 + 11 Game XP and appearing on the daily board at rank 1 with `sessions_count: 3` once the D-14 minimum of three sessions was met. The browser run confirmed the level picker, the shrinking window, the arrow sentence, the pips, round expiry advancing the number and the "You got N of 5 numbers" summary.

---

## PHASE 7: Invitations, friends, challenge mode, safety minimum

**Objective:** "send invite to friends or copy code" works for all launch games, and basic safety exists **before** live multiplayer ships.
**Prerequisites:** Phase 6.

### Tasks
- **P7-T01 Invitation model:** `game_invitations(id, game_id, session_id, inviter_id, invitee_id NULL, code_hash, token_hash, status, expires_at, redeemed_by, redeemed_at, created_at)`, unique on `code_hash` and on `token_hash`. Status: `pending | accepted | declined | expired | cancelled | revoked`. For a challenge, `session_id` is the **parent** session (D-28).
- **P7-T02 Code and token generation (D-31):** code = 8 chars from `ABCDEFGHJKMNPQRSTUVWXYZ23456789` using `secrets`, displayed as **two groups of four in a large font**; token = 32 random bytes URL-safe. Only SHA-256 hashes are stored. **Link flow:** `/games/join?t=<token>` immediately stores the token reference in a 10-minute `SameSite=Lax` httpOnly cookie and **redirects to a clean URL without the token**; after login the client POSTs "redeem my pending invite" and the cookie is consumed. The token never travels through a redirect in a URL, and every page sends `Referrer-Policy: no-referrer`. **Primary join path is the roster avatar** (one click, no typing, no camera); the large typed code is the path for a learner outside your class. A QR code is optional and must never be the only way to join — the target devices are school laptops, which usually have no usable camera.
- **P7-T03 Redemption rules:** authenticated learner, **same school** as inviter, passes `require_game_access`, **has no other active session (D-26)**, not blocked either way, invite `pending` and unexpired, seat available, and — for a live match — remaining time ≥ 15 minutes (D-27). Redeeming is a single atomic UPDATE (`… WHERE status='pending' AND expires_at > now()`) so two people cannot take one seat.
- **P7-T04 Brute-force protection:** rate limit code redemption (5 failures per user per 10 minutes, 30 per IP per 10 minutes); generic error message that does not reveal whether a code exists, is expired, or belongs to another school.
- **P7-T05 Challenge mode (D-03, D-28) for Word Scramble and Guessing Game:**
  - The inviter creates a **`challenge` parent** session (seed fixed at creation) **plus two child `solo` sessions**, one per seat, both carrying the parent's seed and identical config. Invite sent via roster pick (primary on laptops), code, or link.
  - Both players get the **identical** puzzle set from the shared seed and play their own child session independently, under the normal one-active-session and time rules.
  - Window: 24 hours from acceptance. Each attempt is independent.
  - When both children finish, or the window closes: compare the two child scores -> `win/loss/draw`, written as a **new result row on each child** with `supersedes_id` pointing at that child's `completed` row. A player who never played has their child attempt `expired` and gets no result at all.
  - If one never plays, the other keeps their `completed` result and gets **no win bonus**.
  - XP: each player's own attempt awards participation plus performance XP (gated by D-29). The comparison adds `challenge_win` (+5), idempotent via the ledger key `(session_id, user_id, 'challenge_win')`, still under the daily cap and the pair cap.
- **P7-T06 Invite UI (Appendix D applies in full):** "Play with a friend" button on each game; the sheet leads with **avatars of classmates you can challenge** (one click — school laptops, no camera needed), then the **big code** for a friend in another class, then **Copy link** / **Share**. No QR requirement and no camera permission prompt. Expiry is written as a clock time ("This code stops working at 3:15"), never a countdown number. Cancel invite; "Join with a friend" entry on the hub (code box is the fallback screen, in two groups of four); inbox of pending invites with two buttons, `Play` and `No thanks`. **A challenge you still owe a turn in is listed on the hub as "Your turn"** (`GET /games/challenges/mine`): the sheet that created the invite is not the only way back to your own attempt, so closing the tab loses nothing.
- **P7-T07 Notifications (in-app):** table-backed `game_notifications` inbox and unread badge (invite received, challenge result) with one-sentence copy and a single action button. No email/SMS in MVP.
- **P7-T08 Block and mute (minimum):** `game_blocks(blocker_id, blocked_id, type: block|mute)`. A block prevents invites in both directions and removes the user from the other's roster; mute hides their presence. Never tells the blocked user.
- **P7-T09 Report (minimum):** `game_reports(id, reporter_id, reported_id, session_id NULL, reason enum, note, status)` plus a "Report" action on opponent results and live matches; reports appear in a minimal list on the school admin's screen (P10 deepens this). The end screen of a challenge reads the comparison from `GET /games/sessions/{id}/challenge` (one sentence, no scores before both are in) and shows `Report` only once the challenge is decided; the reason picker is the four fixed labels, one decision per screen.
- **P7-T10 Expiry sweeper:** every minute mark overdue invites `expired`, close challenges whose window ended, expire unfinished child attempts, and compute results. Implemented as an ARQ task in prod and runnable by hand with `python -m app.cli job run sweep_invites` (P0-T12).
- **P7-T11 Tests:** one-seat race (two concurrent redeems -> exactly one succeeds, `redis`-marked); cross-school redeem fails with generic error; expired code; blocked users; code entropy and hash-only storage; **the link token is consumed from the cookie and never appears in a redirect URL or a `Referer` header**; **a challenge creates one parent and two isolated children, and concurrent play on both children never collides on `move_number` (D-28)**; **an unfinished child expires with no result while the finisher keeps `completed`**; challenge compare logic; pair cap; a challenged player over their daily time limit cannot start but the invitation stays valid until expiry.

### DoD
- Two learners complete a challenge — one by roster tap, one by copy code — see identical puzzles, and get a correct result.
- The second player's end screen reads the comparison in one sentence and offers `Report`; the report reaches the school admin's list with names and a fixed reason sentence.
- A blocked learner cannot send or redeem an invite to the blocker.
- The link flow survives login: opening the link signed-out, logging in, and landing on the challenge with the token consumed.
- **Appendix D.5 first-session test passes for the invite flow.**

---

## PHASE 8: Real-time platform and live Checkers

**Objective:** live, server-authoritative multiplayer with reconnect and clean state transitions.
**Prerequisites:** Phase 7 (invites, blocks, reports exist).

### 8A. Real-time infrastructure
- **P8-T01 WebSocket gateway:** `GET /ws/games?ticket=...`. Ticket from `POST /ws/ticket` (single-use, 30 s, bound to **user and session**, stored through `CacheClient.set_nx`). Tickets are **not** bound to an IP address: school NAT and mobile handovers change it mid-lesson. Server verifies user active, same school, access policy.
- **P8-T02 Message protocol** (JSON, every message has `type`, `v`, `id`; server events carry `seq` for ordering):
  - Client -> server: `match.join {match_id}`, `move.submit {match_id, client_move_id, expected_move_number, move}`, `match.resign`, `draw.offer`, `draw.accept`, `draw.decline`, `ping`.
  - Server -> client: `match.state` (full snapshot including `legal_moves` for the side to move), `move.accepted`, `move.rejected {reason}`, `opponent.status {connected|disconnected}`, `clock.sync`, `draw.offered`, `match.ended {outcome, reason, xp}`, `error`.
- **P8-T03 Hub over pub/sub:** one channel per match so multiple API instances work, using `CacheClient.publish`/`subscribe` (section 3A). Gateway only forwards **already-accepted** events. In local dev the in-memory implementation fans out in-process only, which is fine because dev runs one API instance.
- **P8-T04 Presence:** keys with a 45 s TTL refreshed by `ping`, via `CacheClient` (dev: single-process only); shows **only same-school, eligible, unblocked** players; status `available | in_match`. `GET /games/presence` plus WS delta events. No presence for users in lockout or over limit — and the roster must then say **why** in plain words ("Max can't play right now") instead of showing an empty list (Appendix D.2.4). In live matches the WS `ping` (every 15 s) is the heartbeat and calls `record_activity` from P3-T05; do not run a second REST heartbeat.
- **P8-T05 Backpressure and limits:** max 1 active live match per user, and one active session of any kind (D-26); max 2 concurrent WS connections per user (a new one replaces the old); per-connection move rate limit (e.g. 5 messages/second, burst 10); max message size 4 KB.

### 8B. Checkers rules engine (pure)
- **P8-T06 `domain/checkers.py`:** state = board (32 playable squares), side to move, `moves_since_capture_or_man_move`, position history hash list. Functions: `initial_state()`, `legal_moves(state)`, `apply_move(state, move)`, `result(state)`. Implements D-05 including mandatory capture and complete multi-jump; promotion ends the turn. **Two rules stated explicitly because implementations diverge:** a player **must** capture when a capture exists but may choose **any** capture (there is no maximum-capture requirement), and `moves_since_capture_or_man_move` counts **plies** (each single move by either side counts as 1).
- **P8-T07 End conditions:** no pieces or no legal moves = loss for the side to move; **draw** by agreement, by **40 plies** without a capture or man move, or by threefold repetition of `(board, side to move)`; **timeout** = clock hits zero.
- **P8-T08 Test suite (large):** perft-style move-count tests from known positions, forced-capture cases, multi-jump with branching, king promotion mid-jump, repetition, the 40-ply rule, and a randomized fuzzer that plays 10,000 random games asserting the engine never throws and always terminates.

### 8C. Match lifecycle (state machine: Appendix A)
- **P8-T09 Live match creation:** inviter creates a `live` session with an invite (code valid 30 min) **only if their remaining time is ≥ 15 minutes (D-27)**; the redeemer must clear the same bar (P7-T03). On redemption both seats fill; colours come from the server RNG; status `ready` -> both clients connected -> `active`.
- **P8-T10 Move handling:** validate (a) sender is a participant of **this** session and it is their turn, (b) `expected_move_number` equals `last_move_number + 1` (**reject out-of-order or stale**), (c) the move is in `legal_moves`, (d) rate limit. Persist to `game_moves` and update the snapshot in one transaction, then publish. Duplicate `client_move_id` returns the original acceptance (idempotent). Only one user ever writes moves to a session, so the per-session `move_number` is unambiguous (D-28).
- **P8-T11 Clocks:** server-authoritative. Default **5 minutes per side** plus 3 s increment per move (config, D-27) — a 10+5 clock allows a 25-minute match, which cannot coexist with a 2-hour daily limit. Server stores `clock_ms` per seat and `turn_started_at`; clients only display. A server timer (cache-keyed expiry processed by ARQ, with an on-move lazy check as the backup that must work without a worker) fires `timeout`.
- **P8-T12 Disconnects and reconnect (D-30):** on disconnect mark `disconnected_at` and **pause that player's clock** (the opponent's clock is unaffected; a running turn timer resumes on reconnect). Forfeit only after **3 minutes in one disconnect** or **10 minutes cumulative** in a match (not for a lockout/limit event). Reconnect: client re-joins `match.join` and receives the full `match.state` from the durable record, including `clock_ms` and whose turn it is.
- **P8-T13 Resign, draw offers, rematch:** resign ends immediately (resigner loses). Draw offer valid until opponent's next move or 30 s; max 3 offers per player. Rematch = new session with `rematch_of`, colors swapped, a new invite is auto-created for the same pair (still subject to pair cap).
- **P8-T14 Abandoned and no_contest paths:** both players disconnected past the D-30 cumulative window = `abandoned` (no result, no XP); lockout or system fault = `no_contest` (no XP, no loss, not board-eligible).
- **P8-T15 Results and XP:** server writes both `game_results` rows (`win/loss/draw`) in the same transaction as the final move; then P5 awards under D-13 and D-29 (minimum **8 moves per side**, pair cap). The loser still gets participation XP when the match met the minimum.
- **P8-T16 Disputes:** "Report this match" creates a report linking `session_id`. Moderator may mark the match `disputed`; resolution writes **new** result rows with `supersedes_id` and compensating XP ledger entries. Nothing is edited in place.
- **P8-T17 Frontend board (Appendix D applies in full):** responsive 8x8 board, touch tap-to-select then tap-to-move (drag optional); **a learner can never make an illegal move** — only server-supplied `legal_moves` are highlighted, and when exactly one piece may move it is auto-selected with "You must jump!" and an arrow; last-move highlight; captured pieces shown as a simple count; clocks as filling bars; a connection indicator with one sentence ("Lost connection. Trying again…"); resign and offer-draw behind a confirm step ("Are you sure?"); end-of-match overlay with a plain sentence, the XP summary, and one `Play again` button; reconnect toast; optimistic UI **only** for animation, rolled back on `move.rejected`.
- **P8-T18 Lobby UI:** avatar grid of classmates you may challenge (one tap to invite), incoming invite sheet with `Play` / `No thanks`, and a fallback "Join with a friend" code screen. Empty and refused states explain themselves in one sentence (Appendix D.2.4); never a blank list.
- **P8-T19 Tests:** two-client e2e (Playwright, two browser contexts) full game to a win; reconnect mid-game **with the disconnected player's clock paused**; **forfeit only after the D-30 window, never after a 10 s drop**; stale move rejected; duplicate move id idempotent; illegal move rejected and not persisted; **a live match is refused when remaining time < 15 min (D-27)**; lockout converts to `no_contest`; two API instances with shared pub/sub deliver identically (CI only, `redis`-marked); WS ticket reuse fails; cross-school join fails.

### DoD
- Two learners can finish a Checkers match, results and XP are correct, the match survives one refresh each.
- Chaos test: kill a WebSocket mid-move 50 times; no lost or duplicated moves. **Passed** — `api/tools/phase8_chaos.py`, three times back to back.
- A 20-second network drop does not cost anyone the game; a 5-minute absence does.
- **Appendix D.5 first-session test passes**, including a player who has never seen a draughts board. **Partly verified** — the blind-navigation walkthrough and every mechanical D.1 check pass; the five-learner study is still owed.

**Shipped:** migration `0015_checkers_live` turns Checkers on and gives it a two-seat row; `app/games/domain/checkers.py` is the pure engine (mandatory capture, complete multi-jump, promotion ends the turn, plies counted for the 40-ply draw, threefold by `(board, side)`), checked against the published perft counts 7/49/302/1469. `app/games/services/live.py` owns the match lifecycle (create with the D-27 bar, accept, colours from the server RNG, `expected_move_number` rejection, clocks with increment, the D-30 pause-on-disconnect and forfeit windows, resign/draw/rematch, both result rows and P5 XP), `services/hub.py` fans out already-accepted events, and `api/realtime.py` exposes `/api/ws/ticket` (single-use via `CacheClient.set_nx`) plus the `/ws/games` gateway outside `/api` because a browser cannot upgrade through the dev rewrite. `sweep_live` is the P8-T11 sweeper.

Two deliberate deviations, both stated rather than hidden. The P8-T08 fuzzer runs **400** seeded random games, not 10,000: at 300–400 pure-Python move generations per game, ten thousand of them held the whole suite hostage for fifteen minutes, and four hundred still walk capture, multi-jump, promotion, repetition and the 40-ply rule in about ten seconds. And local development runs the sweeps through `app/jobs/scheduler.py` (a 60-second in-process loop started only when `app.env == "dev"`) instead of an ARQ worker, because D-34 keeps the laptop free of Redis — it calls the same registered tasks, so the rules cannot drift.

**Verified:** 324 backend tests pass (5 Redis-gated skips), mypy and ruff clean, web typecheck clean. In the browser a learner started Word Scramble, quit from the Play tab, and the seat freed; a second game was refused while another was open, the refusal screen offers **Go back to my game** (`components/ResumeGameLink.tsx`), and that button resumed the open session mid-round. A coach signed in with a code and PIN opened a class roster.

**P8-T19, two browser contexts, done:** Amara (A-1001) invited Bayo (A-1002) from the roster, Bayo accepted from his inbox, and the match was played to a finish twice — once on the clock (`timeout`, white's five minutes ran out, both result rows, no XP because four moves each is below the D-29 minimum) and once with sixteen moves and a resignation (`resign`, Amara `win` / Bayo `loss`, both `leaderboard_eligible = true`, ledger `played` 15 and 5). That run found seven things the integration tests could not, all fixed and now pinned by four tests in `test_live_match.py`:

- **There was no way in.** `/games/checkers` did not exist, so the hub's Play link was a 404 and no learner could create a live match. The lobby is `web/app/games/checkers/page.tsx` (roster pick first, code entry second).
- **The inviter could not open their own match.** Colours were chosen at redemption, so the creator was not a seat and their board said "we could not find that match". The inviter's colour and participant row are now written at creation, `accept` fills the seat that is free, and `preferred_seat` gives a rematch its owed swap.
- **Every socket died on its first frame.** `snapshot()` returned a `UUID` and the gateway called `json.dumps` on it, so both players sat on "You are offline". The snapshot's `session_id` is a string now.
- **`connected` was never written.** The services mutate nested config members in place, and `_cfg` shallow-copied, so old and new compared equal and SQLAlchemy wrote nothing: the match stayed `ready` with each player seeing the other as away. `_cfg` deep-copies.
- **The last socket out marked you away.** A reconnect (or React's double-mount) registers the new socket before the old one closes; `leave` now runs only when no socket for that player remains.
- **A waiting match was reported as a draw.** The board treated `created` as "over"; only a status that cannot restart ends it.
- **Smaller ones:** a live invitation accepted from the inbox called the challenge-start route with no parent id (both accept paths now branch on `live`), and the inbox said "this game" for Checkers because `GAME_NAMES` had no entry for it.

**Chaos gate, run:** `api/tools/phase8_chaos.py --rounds 50` drives a real live match through the dev API, kills the socket without a close handshake — half before the frame leaves, half just after, because a dropped request and a dropped response are different failures — and then proves the record from **Postgres**, not from the API's word: one `client_move_id` row per intent, `move_number` contiguous from 1, and replaying the stored moves through the pure engine reproduces the board, the side to move and the progress counter. It also sends the same intent three times on one healthy socket and demands one row. Three consecutive runs, each **25 kills before the send and 25 after, 51 moves, one duplicate absorbed, replay exact**: the first saw 23 moves land without a retry and 27 on the retry, the next two 25 and 25; the slowest retry took **211 ms**, **361 ms** and **493 ms** from send to settled. The gate found one real server bug and one real harness bug.

- **A concurrent retry could lose its own move.** A reconnect resent the pending move while the original request was still committing; the retry read the document before it changed, saw no duplicate, and hit the unique constraint on `client_move_id`. The player got **no frame at all** — neither accepted nor refused — and the board froze. Every mutating path now reads the match row `FOR UPDATE` (`repo.get_session(..., for_update=True)` inside `live._load`), so the retry waits and then sees the truth. Pinned by `test_every_move_is_made_under_the_row_lock`, which spies on the read for `join`, `submit`, `leave` and `resign`: a race cannot be reproduced on one connection, so the test pins the mechanism instead of pretending to test the timing.
- **The harness read a stale frame as the verdict.** The socket can still be carrying the join's snapshot or an opponent's poke, so a `match.state` from *before* the move was taken as the answer, the retry socket was killed, and the commit — which landed a moment later — was called a lost move. `read_reply` now accepts only a state at or after the move number it is asking about, and the final check gives the commit a two-second settle window while reporting the slowest retry, so a row that really does stall still fails.

**Verified after the gate:** 325 backend tests pass (5 Redis-gated skips), mypy clean on 65 files, ruff clean. Run the suite with `npm run test:api`, not a bare `pytest`: bare `pytest` from the repo root does not load `api/pyproject.toml`, so `asyncio_mode = auto` is lost and every `async def` test is reported as "not natively supported".

**D.5 first-session gate, walked:** a real match was driven end to end by a player working only from what is on screen — no reading of the instructions, no coaching. All three steps now pass: **the game is two taps from the hub** (card → board, the lobby is the roster pick from P8-T18), **the first move is two taps** (ringed piece, then the only green square, with a forced jump needing one tap because the piece is already selected), and **the consequence question is answerable by pointing** at a card that says "If the bar empties, you lose." Measured on the board: 21 words in the match area, or 24 with the "You must jump!" line showing (limit 25), longest sentence 6 words (limit 8), every target at least 56×56 including the Leave link, type at 16/20/24px. Eight real breaks, all fixed:

- **The board had no chequer pattern and no visible legal-move highlight.** `bg-[color:var(--color-ink)]/85` and `bg-[color:var(--color-success)]/25` ask Tailwind for an opacity modifier on a `var()` colour, which it cannot apply, so those classes emitted nothing: every square rendered the same pale grey and "you can move here" was invisible. Both are solid token colours now.
- **Three state colours were never defined.** `--color-success`, `--color-warning` and `--color-danger` are used in 26 places across the games (danger alone 23 times) but only existed in `lib/tokens.ts`, not in `globals.css` — so the resign confirm, the low-clock warning and the move highlight all resolved to nothing. Added to `:root`.
- **Nothing said what an empty bar means** (D.2.3, and step 3 of this gate). There is now a card: ⏳ *If the bar empties, you lose.*
- **Time was a number, not a bar** (D.2.5). Each player's clock is a filling bar with the number and the word it needs: *26:12 left*.
- **The instruction sat under the board** (D.2.1 puts it at the top). Moved above, with an avatar beside each name (D.3's "Your turn" / "Waiting for Bayo").
- **Nothing showed where to start.** A learner who cannot read had to guess that a piece must be tapped first. Pieces that may move now carry a ring, and when only one may move it is selected for you, so its destinations are already showing.
- **D.3's forced jump was missing.** A capture that must be taken now auto-selects its piece, marks it with a ▼, and changes the line to *Tap the piece. You must jump!*
- **The hub was three text-only cards**, so a non-reader could not pick the game (step 1). Each card now carries a picture: a chequered board, ↑↓, three loose tiles. Also: **Leave was 40×24px**, under the D.1 minimum, and at 390px eight 56px squares pushed the page wide and clipped the h-file — the board now scrolls inside its own box at a 56px minimum.

**Still open for P8:** the D.5 five-learner study itself has not been run (it needs five first-time children and a screen recording, not an agent), and two D.1 items belong to P11-T04's full audit rather than to this gate: the shared header clips on a phone-width viewport, and buttons still carry labels without icons. The XP chip also only refreshes on match end because of a page event — a school admin should probably see live matches somewhere in P10's console.

---

## PHASE 9: Offline single-player

**Objective:** Word Scramble and Number Guess work with no connection and sync later, without touching leaderboards (D-12).
**Prerequisites:** Phase 6 (which includes the shell from Phase 4 and access/time from Phase 3).

### Tasks
- **P9-T01 PWA:** web manifest, service worker (Workbox) caching the app shell, game bundles, fonts, avatars. Versioned caches with safe update flow ("new version available").
  - **Shipped:** `app/manifest.ts` (standalone, portrait, maskable icon), icons drawn by `web/public/icons/make_icons.py`, and a hand-written `web/public/sw.js` instead of a Workbox build step — same strategy, one fewer dependency. `/_next/static` and static files are cache-first under a versioned cache; **HTML and `/api/*` are never cached**, because a shared school tablet must not serve one child's dashboard to the next; a failed navigation shows `public/offline.html` (verified with the server killed). A new build waits for `PwaUpdate`'s "A new version is ready" button, so nobody is swapped mid-round. Registered in production builds only.
- **P9-T02 Offline content packs:** `GET /games/offline/packs?game=word-scramble` returns a size-limited bundle (about 200 words per chosen age band/locale/difficulty, and never fewer than the 15 usable items P4-T03 requires per pack) with `pack_version`, **including the audio/image clue references so the clue still works offline**. Stored in IndexedDB (via a small wrapper such as `idb`). Nobody has to choose: packs save themselves.
  - **Shipped:** `app/games/services/offline.py` serves one level at a time, scoped to the learner's own band (from their birthday, never a query string), capped at 200 items, refusing with a sentence when a level has fewer than 15 live words. `pack_version` is `level.pack.size.stamp`, where the stamp is the newest `published_at`, so a word going live or being retired changes it. `web/lib/offline/packs.ts` is the hand-rolled IndexedDB store (no `idb` dependency): `OfflineSync` in the shell saves every offline game's words in the background on first load, after a reconnect, or when the six-hour stamp is stale, and a level whose stamp has not moved is not rewritten. **Packs are per learner** — every row records the `user_id` it was fetched for and every read filters by it, so a second child on a shared tablet never sees the first child's words. `OfflineReady` on the Word Scramble start screen is a one-line receipt ("Saved on this device. Plays without internet."), not a button.
  - **Checks:** 10 API tests (band scope, no seed/session in the bundle, retired words leave, refusal paths), plus a live run in the browser: with storage cleared and nothing pressed, 3 levels (150 words, 26 KB) saved within a few seconds and the receipt appeared; signing in as a second learner replaced the stored rows with theirs.
- **P9-T03 Offline rules runtime:** reuse the same rules by compiling the pure domain logic to TypeScript **or** re-implement behind a shared test-vector file. **Decision:** write TS ports of `wordscramble` and `guessing` and verify both implementations against shared JSON test vectors (same seed, same moves -> same state) in CI. (Checkers stays online-only until Phase 12.) **The offline port must never accept or answer an online session id:** offline secrets are generated locally, which is safe only because offline play yields no XP or rank (D-12). A test asserts the offline runtime cannot be handed a server session token.
  - **Shipped (parity half):** `web/lib/games/rules/random.ts` is a CPython-compatible `random.Random` — MT19937, `init_by_array` seeding of 63-bit integers, the `int.from_bytes(s + sha512(s))` text seed, `shuffle`, `sample` (both the pool and set branches) and `_randbelow` — with a synchronous SHA-512, because Web Crypto is async and a round must be generated on a phone. `wordscramble.ts` and `guessing.ts` port the rules; `shared/parity/game-rules.json` is generated from the Python domain by `api/tools/parity_vectors.py` and read by both `api/tests/test_rules_parity.py` and `web/lib/games/rules/parity.test.ts` (Vitest, `npm run test:parity`, run in the web CI job). The vectors pin the two sample branches, which consume different draws (a 15-word pack and a 200-word pack), and the deadline's inclusive edge. Writing them found two port bugs before any game used them: `_randbelow` must use `n.bit_length()`, not `(n - 1).bit_length()` (the difference appears only at powers of two), and Python's chained comparison does not survive the translation. The offline runtime and its token-rejection assertion are still to come; this slice establishes that the two languages agree on seeds, letters, secrets, scores and deadlines.
- **P9-T04 Offline session record:** `{local_session_id (uuid), game, pack_version, seed, actions[], started_at, ended_at, active_seconds, app_version}` appended locally; never claims XP or rank. The `seed` here is **generated locally** and is never a server seed (D-25).
- **P9-T05 Offline time tracking:** local active timer under the same rules as D-11 and D-26 (one active session, clock accrues per user not per session) using monotonic time. The client caches `remaining_seconds` and `server_time` from the last online `GET /games/access` and stops offline play when it hits zero. **Documented accepted risk:** this can be bypassed locally and coach lockouts cannot apply until sync; mitigated because offline play yields no XP or board placement.
- **P9-T06 Sync endpoint:** `POST /games/offline/sync` with a batch. Idempotent by `local_session_id` (table `game_offline_batches`). Server: validates schema, bounds (`active_seconds` <= wall-clock between start and end, <= 2 h per session), replays actions against the pack version to recompute the score for **personal history**, stores a `game_sessions` row with `mode='offline_solo'` and a result with `leaderboard_eligible=false`, and credits the usage to `game_time_usage(source='offline')` **for the session's own local date**, updating that date's `game_play_clock` row (D-26).
- **P9-T07 Overage handling:** if synced offline time pushes today's total past the limit, `remaining_seconds` becomes zero (not negative display); competitive online play is blocked for the rest of the local day. Offline time from a previous local date is credited to **that** date, not today's.
- **P9-T08 UI:** offline banner, "Downloaded for offline" badges, queue indicator ("2 sessions waiting to sync"), sync-on-reconnect with retry/backoff, personal history page labelled "Offline (not on leaderboard)".
- **P9-T09 Tests:** airplane-mode e2e; sync idempotency (send same batch twice); tampered score is recomputed; absurd `active_seconds` clamped; pack version mismatch handled (still replayable with the old pack version retained server-side); **offline seconds from yesterday credit yesterday's `game_play_clock` row, not today's**; **a batch that pushes today over the limit leaves `remaining_seconds` at 0, never negative**; TS vs Python parity vectors.

### DoD
- Play three offline sessions with no network, reconnect, see them in history, and see **no** leaderboard or XP change.

---

## PHASE 10: Fair play and moderation depth

**Objective:** detection and tooling beyond the minimum in Phase 7.
**Prerequisites:** Phase 8.

### Tasks
- **P10-T01 Timestamps:** confirm client and server timestamps recorded on all actions; add derived metrics (median response time, variance) per session.
- **P10-T02 Suspicion signals (ARQ nightly + on-complete):**
  - Same pair playing > N matches/day or one side consistently resigning early (collusion).
  - Word Scramble sessions with inhuman answer times (< 1 s per word repeatedly).
  - Guessing Game perfect binary-search patterns with zero variance over many sessions is **not** suspicious by itself (it is a valid strategy): flag only on impossible speed.
  - XP hitting the daily cap on most days with near-identical session shapes.
  Output: `fairplay_flags(user_id, session_id, signal, score, status)`. Flags **do not auto-punish**; they set `leaderboard_eligible=false` for the flagged sessions pending review. **Enforcement is by filtering, not by editing history:** the projection and the nightly reconcile both skip flagged sessions (D-33), so a flag takes effect without touching append-only rows. Compensating ledger entries are written only when a school admin confirms the XP itself must go.
- **P10-T03 Admin console (school_admin, D-37):** report queue, flag queue, session replay viewer (from seed + moves, rendered **server-side or returned as a rendered move list — the seed itself is never sent to the admin's browser, D-25**), actions: dismiss, warn (in-app notice), exclude sessions from boards, temporary game lockout (reuses P3 lockouts with reason). Every action writes to `audit_log`.
- **P10-T04 Reporter and reported UX:** confirmation to the reporter that it was received (no outcome details); reported learners are not told who reported.
- **P10-T05 Appeals path:** learner can request review of an exclusion; the school admin resolves; result via superseding rows.
- **P10-T06 Rate-limit audit:** verify limits on session create, action submit, invite create (e.g. 10/hour), invite redeem (P7-T04), WS messages, report submission (10/day).
  - **Shipped so far (2026-11-25):** invite create is **10 an hour per learner** (challenge, live match and rematch share one key, so a rematch cannot be used to get around it) and a report is **10 a day per learner**. Both count on the account, never the browser: two tabs must not buy two allowances, and a shared tablet must not spend one child's on another. Session create is **30 an hour**, an action is **60 a minute**, and the REST move fallback gets the same ceiling as the socket (60 a minute). Sign-in (10/min by IP), code redemption and WS frames were already limited. All of P10-T06 is now covered.
- **P10-T07 Tests:** collusion signal fires on synthetic farming data; false-positive guard on normal play; flagged session excluded from the board **after the next reconcile** while its ledger rows remain intact; **zero-XP below-minimum sessions are not flagged as farming (D-29)**; admin audit log completeness; the replay viewer never returns the seed.

### DoD
Synthetic farming scenario is detected and neutralized without any deletion of historical rows, and the board converges to the correct total on the next reconcile run.

---

## PHASE 11: Hardening, QA, launch

**Objective:** safe to run for real schools.
**Prerequisites:** Phases 0-10.

> **Found on 2026-11-25, both fixed:** CI triggered on `push: branches: [main]` while the repo's
> branch is `master`, so **no push ever ran the suite** — every green build was local. And cookie
> writes had no `Origin` check at all (only the WebSocket gateway had one), leaving `SameSite=Lax`
> as the only thing between a learner's account and a cross-site form post. The guard now sits in
> front of every route (`app/core/origin.py`), allows a missing `Origin` so scripts and tests still
> work, and refuses anything else with one sentence.

### Tasks
- **P11-T01 Security review:** OWASP checklist; cookie flags; CSRF protection for cookie-authenticated mutating requests (double-submit token or SameSite+Origin check); CORS locked to the app origin; WS origin check; dependency scanning; secrets audit; SQL injection and mass-assignment review; authorization test matrix (role x endpoint x school).
- **P11-T02 Privacy review:** data minimization for minors, retention schedule for moves/replays (e.g. detail kept 12 months, XP/results kept per school policy), export and delete flows aligned with the host platform's policy and applicable law, no third-party trackers in the games area, logs contain no real names.
- **P11-T03 Performance and load:** k6 or Locust: 500 concurrent WS connections, 100 concurrent live matches, leaderboard queries under 100 ms p95 on a 10k-learner school dataset, heartbeat endpoint load (30 requests/s per 100 players). Add indexes or caching where needed. Payload budgets: Word Scramble session < 30 KB total; WS messages small.
- **P11-T04 Accessibility and comprehension:** WCAG 2.1 AA pass on all games (keyboard-only play, screen-reader labels for board squares and tiles, colour-blind-safe piece contrast, reduced motion, 200% text zoom without loss) **plus a full Appendix D audit**. Appendix D was already a DoD gate in P4, P6, P7 and P8; this task re-runs it on the integrated build and on the lowest-spec device in the matrix.
- **P11-T05 Cross-device QA:** low-end Android Chrome, iOS Safari, school laptops (Chrome/Edge), throttled 3G profile, offline mode on each.
  - **Shipped (2026-11-25), the automated half:** `web/e2e/smoke.spec.ts` is a Playwright suite that signs a learner in, plays Number Guess through all five numbers, opens a Checkers lobby from the roster, has a second learner join from their inbox, and resigns. It runs against the seeded demo school, is repeatable (it clears leftover invites and open sessions first), and CI runs it in a real browser with the report uploaded on failure. What remains for this task is the **manual** device matrix: iOS Safari, a low-end Android, throttled 3G and the offline profile.
- **P11-T06 Observability:** metrics (active matches, WS connections, move latency, XP awards, cap hits, reconciliation drift, queue depth), structured logs with request/session ids, error tracking, uptime checks, alerts (reconcile drift > 0, queue backlog, 5xx rate).
- **P11-T07 Operations:** automated Postgres backups with a tested restore, zero-downtime migration policy (expand then contract), feature flags per school (`games_enabled`, per-game enabled, `leaderboards_enabled`, `live_multiplayer_enabled`), kill-switch for multiplayer, runbooks (stuck match, wrong XP, lockout dispute, mass reconnect storm).
- **P11-T08 Pilot rollout:** 1 school, 2 classes, 2 weeks; collect: time-limit friction, invite success rate, match completion rate, support tickets; fix; then expand.
- **P11-T09 Launch checklist sign-off** (product owner, school admin representative, security).
- **P11-T10 Comprehension study with real learners:** run Appendix D.5 on the pilot build with **5 first-time learners from the target band** (at least two who cannot read the clue text), no coaching. Any intervention is a blocking bug. This is the last gate before pilot, and it is the one that decides whether the game is playable by the audience it was built for.

### DoD
All blocking issues closed; pilot success criteria met (suggested: invite success > 90%, match completion > 85%, zero ledger drift, zero P1 incidents in last 7 days, **Appendix D.5 pass rate ≥ 4 of 5 with zero adult interventions**).

---

## PHASE 12: Post-launch backlog (not in first release)

1. Chess (new `domain/chess.py`, same match framework; reuse clocks, reconnect, results).
2. Falling-block puzzle (original design, no trademarked names, assets, or exact mechanics; offline-capable; needs replay validation to qualify for boards).
3. Termly calendar sync with the host platform (P5-T06 uses a manually maintained `school_terms` until then).
4. Sportsmanship XP (based on reviewed reports, positive-behaviour signals).
5. Curriculum-linked content packs (tie words/clues to lessons).
6. Local play against the device for Checkers/Chess (offline).
7. Verified offline leaderboard eligibility via replay validation.
8. Reaction phrases (fixed set) in live matches — Phase 13 generalises this into Postcards, so build it there.
9. Tournaments and class ladders.

---

## PHASE 13: Postcards — learner chat as a game (after launch, D-40)

> **Open choice, not decided (2026-11-25):** the product owner may prefer a **class wall** — one
> board per class, every post visible to that class' coach, no private messages — because it gives
> real conversation at a fraction of the moderation risk. If that is chosen, this phase keeps the
> Stamps, the album and the daily quest, and swaps phrase tiles for moderated short posts. Ask
> before building either shape.

**Goal:** learners talk to each other, including to a class that is not their own, without a text
box. A message is a **postcard**: a picture, one sentence made of phrase tiles, and optionally the
score the sender just got. Nothing here is a new code path for strangers — it reuses the invitation
inbox, the block list, the report flow and the content validator.

**The game, in the order a learner meets it**

1. **A Stamp.** Every finished game may earn one Stamp (max 3 a day), and a Stamp is spent sending
   a postcard. Postcards are a reward you unlock by playing, not a tab you can sit in.
2. **A card.** Pick a picture from the game's own art, pick one phrase — `Good game!`,
   `You are fast!`, `Beat this!`, `Rematch?` — and attach the round you just played ("4 guesses").
   The server composes the sentence; the client sends three ids and a score.
3. **A reply.** The recipient opens the card from the same corner popup the invitations use, and has
   exactly two moves: `Nice!` or `Beat this!` (which opens the same game with the same friendly
   setup). Replying returns half a Stamp, so the pair can keep a rally going all week.
4. **A collection.** Every card received is kept in a **Postcard album** with the sender's name and
   avatar. Five cards from five classmates fills a page; a full page is a badge, which is the
   addictive part — the album is a thing to complete, and the only way to complete it is to play
   with more people.
5. **A daily quest.** `Send one card.` / `Reply to one card.` The quest pays a badge, not XP, so
   posting can never out-earn playing.

**Rules the server enforces**

- **Phrase tiles are content.** They live in the content tables (`kind = 'phrase'`), pass the same
  safe-language validator as a clue (D-39), are grouped by age band, and a coach can retire one
  without a deploy. The client may only send a tile id that exists, is live, and is in the sender's
  band.
- **Same school only** (D-15). Another class is reachable only when **that class' coach has opened
  postcards** for it; a closed class is not listed. Cross-school is a 404, never a 403.
- **Three a day**, one per recipient per hour, and never to somebody who blocked or muted you
  (silently dropped, like invites).
- **Structured, therefore auditable.** The stored row is `(sender, recipient, template, game, score,
  picture)`. A coach can read their class' outbox and inbox from `/coach/postcards`; there is no
  private channel, and nothing is ever deleted — a reported card is flagged, not removed.
- **The report flow is the same one.** Any card carries `Report`, which opens the existing reasons
  screen. Blocking a learner stops their cards instantly.

**Tasks**

- **P13-T01 Schema:** `game_postcards` (append-only), `game_postcard_replies` (or a self-reference),
  `game_phrase_items`, plus `stamps` in the engagement ledger. Hand-written migration, reversible.
- **P13-T02 Compose and send:** `POST /games/postcards` with `recipient_id`, `phrase_id`,
  `picture_key`, optional `session_id`. Server recomposes the sentence and validates scope, band,
  block, rate and Stamp balance. Idempotent by `client_move_id` like every other action.
- **P13-T03 Delivery:** reuse `game_notifications` (`kind = 'postcard'`) and the existing inbox
  payload, so the corner popup, the toast and the floating button need no new behaviour.
- **P13-T04 The album:** `/postcards` — received cards as a grid, one page per five, page art
  revealed as it fills. Reachable from the avatar sheet, **not** the top bar.
- **P13-T05 Cross-class picker:** the class directory of the school, with a class listed only when
  its coach has opened postcards. One tap on a class, one tap on a learner.
- **P13-T06 Coach view:** `/coach/postcards` — the last 50 cards in and out of each class, reported
  cards first. Read-only except `mute this learner's cards`.
- **P13-T07 Quests and badges:** `send_one_card`, `reply_to_one_card`, `five_senders`; Stamps in the
  engagement service beside streaks (same ledger shape).
- **P13-T08 Tests:** a card to another class arrives and a card to a closed class is refused; a
  retired phrase cannot be sent; a blocked sender's card is dropped without telling them; the
  fourth card in a day is refused with one sentence; a reply is idempotent; the album shows the
  sender's preferred name only; the coach list shows what a learner sent.

**Explicitly not in this phase:** free text, images from the device, voice notes, group chats, and
chat between schools. A later free-text phase would need a coach pilot, a review queue and a
parent-visible transcript — see D-40 — and is not on the roadmap.

**DoD:** a learner plays, earns a Stamp, sends a card to a friend in another class, that friend
replies from the corner popup, both see the card in the album, a coach reads the exchange, and the
whole loop passes Appendix D in under 25 words per screen.

---

## Appendix A. State machines (reference for P3, P4, P7, P8)

### Session status
```text
created -> waiting_invite        (live/challenge only, invite pending)
created -> active                (solo, and each child attempt of a challenge)
waiting_invite -> ready          (seats filled)
waiting_invite -> cancelled | expired
ready -> active                  (all participants connected/started)
ready -> cancelled               (a participant has not connected within 2 minutes; no result, no XP)
active -> completed              (normal finish, result written)
active -> timed_out_allowance    (soft limit exceeded; solo or child attempt ONLY — never a live match, D-27)
active -> abandoned              (no input past the sweeper window; no result)
active -> no_contest             (lockout/system fault; no XP)
active -> disputed               (admin flag; results may later be superseded)
completed -> disputed

challenge parent: active -> completed   (both child attempts terminal, or the 24 h window closed)
```
Terminal: `completed, cancelled, expired, abandoned, no_contest, timed_out_allowance`. `disputed` resolves by writing superseding results, never by reverting status silently.

**Challenge shape (D-28):** the parent `challenge` session holds two participant rows and **no moves**; each player's play happens in their own child `solo` session, which owns the moves, the result, and the attempt state. A parent is `completed` only when both children are terminal.

### Live Checkers match outcomes
`outcome_reason`: `no_pieces | no_moves | resign | timeout | disconnect_forfeit | draw_agreement | draw_40_ply | draw_repetition`.

### Invitation status
```text
pending -> accepted | declined | expired | cancelled | revoked
```
All transitions are single atomic conditional UPDATEs; terminal states never change.

---

## Appendix B. Cross-cutting rules (enforce in code review)

1. **Server decides:** results, scores, XP, clocks, time allowance, eligibility.
2. **Append-only:** `game_moves`, `game_results`, `game_xp_ledger`. Fix by superseding rows.
3. **Idempotency:** every mutating game action carries `client_move_id`; every XP award keyed by `(session, user, reason)`; every offline batch keyed by `local_session_id`.
4. **Scope checks:** every service function verifies school and role scope from the authenticated actor.
5. **Masked identity:** learner-facing schemas contain only preferred name and avatar.
6. **No cross-contamination:** Game XP and Profile XP never feed grades, badges, certificates, completion, or assessment eligibility.
7. **Config over constants:** limits, caps, XP values, timers, and thresholds live in `platform_settings`/game config.
8. **Pure domain:** rules code has no I/O, clock, or global randomness.
9. **Generic public errors** for anything involving invites or other schools (no existence leaks).
10. **Everything tested** at three levels: pure unit, API integration (real Postgres where it matters, real Redis in CI), e2e (Playwright).
11. **Seed is server-private:** never in a response, log, error, or browser-facing replay (D-25).
12. **One active session per learner:** time accrues per user per local date, never per session (D-26).
13. **Cache and queue only through `CacheClient`/`QueueClient`;** in-memory implementations may never boot outside `dev`/`test` (D-34).
14. **A live match that started legally always finishes** (D-27); only a lockout or a system fault may cut it short.
15. **Plain language is a requirement, not a polish step:** every screen passes Appendix D, and every learner-facing server `reason` maps to exactly one fixed plain sentence (D-32).

---

## Appendix C. Dependency graph (summary)

```text
P0 -> P1 -> P2 -> P3 -> P4 -> P5 -> P6 -> P7 -> P8 -> P10 -> P11
                          \-> (P9 needs P4 + P6; can run parallel to P7/P8 with a separate developer)
```
Critical path for the stated priorities: leaderboards (D-35) = P5; multiplayer + invites = P7 and P8.

**Environment note:** P0 has two paths and they serve different jobs, so both stay in the plan — **P0-T03b (Windows-native, no Docker)** is the gate for local development, and **P0-T03a (container)** is the gate for CI. A developer with Docker may use the container path locally, but the no-Docker path must keep passing its checks, because that is the only one that runs on the target machine.

**Content note:** P4-T06 is the longest-lead item in the whole plan. Start content authoring and review **during Phase 2**, not at Phase 4, or the games will be finished before the words are.

---

## Appendix D. Plain-language and low-literacy UX standard (binding, D-32)

**Who this is for.** A learner who reads at roughly a 6–8 year old level, and who may not read the interface language confidently. Many players will not read a sentence longer than a few words. **If a screen only works when you read it, that screen is broken.**

This applies to every screen in the games area: hub, all three games, invites, leaderboards, XP, limit and lockout states, and every error path.

### D.1 Hard rules (checkable in review)

| Rule | Limit |
|---|---|
| Words on screen at once, excluding the board and tiles | ≤ **25** |
| Words in one sentence | ≤ **8** |
| Decisions per screen | **1** primary button; secondary actions are icon + short label |
| Body text | ≥ **20 px**, never below 16 px |
| Touch target | ≥ **56 × 56 px**, ≥ 8 px apart |
| Contrast | WCAG AA (4.5:1 body, 3:1 large text and pieces) |
| Icons | Every button has an icon; no icon-only button without a label beneath it |
| Numbers | Always followed by words ("3 tries left", not "3/8") |
| Wording | No jargon. No word longer than three syllables where a shorter word exists. "XP" is always explained once on screen as "points" |

### D.2 Always, on every screen

1. **"What do I do now?"** is answered by one short line at the top: *"Tap the letters to make a word."*
2. **Read aloud.** A speaker button reads the instruction, the clue, and the button labels (browser speech synthesis — no audio assets needed). Auto-play the instruction on a first visit only.
3. **Say what happens next.** Every timed or irreversible action states its consequence *before* it happens: *"If the bar empties, this word is worth 0."*
4. **No dead ends, ever.** `limit_reached`, `locked_out`, `another_session_active`, `not_enough_content`, `below_minimum`, and every other server `reason` renders as a friendly card: one icon, one sentence, one button. **Server error codes are never shown to a learner.** All **learner-facing** reasons (access, session, invite, leaderboard) map through a single lookup table (`web/features/games/copy/reasons.ts`), and a test asserts that every learner-facing backend `reason` value has an entry.
5. **No surprise penalties.** Timers are **filling bars**, not countdown rings. Score is shown only as what was gained: "+10", never "+10 +5 −3".

### D.3 Per-game requirements

| Game | Requirements |
|---|---|
| Word Scramble | All interaction works with **mouse and keyboard** on a laptop — no touch-only or camera-only step anywhere. Clue must be **audio or picture** in the youngest band, never text-only. Large tiles, tap-to-place, visible undo, only the next empty slot active. A visible "I don't know" button instead of a hidden skip gesture. Hint button reads "Take a letter (−3)". |
| Number Guess | Big number pad **and** a +/- stepper. The range is one bar that **visibly shrinks** after each guess. Higher/lower is a big arrow **plus words** ("Too low — go up"). Tries left as filled pips plus words. |
| Checkers | **Illegal moves are impossible:** only legal destinations highlight, a forced piece is auto-selected with "You must jump!" and an arrow. Pieces differ by shape **and** colour. Turn indicator says "Your turn" / "Waiting for Max" with an avatar. |

### D.4 Invites, codes, limits, leaderboards

- Primary join is **click a classmate's avatar**. Keyboard-bound laptops are the target device, so the mouse path must be first and complete. Typing eight characters is the fallback for a friend outside your class, shown in two groups of four at ≥ 32 px. QR scanning is optional and never the only route.
- Expiry is a clock time ("This code stops working at 3:15"), never a countdown number.
- The daily limit is a sentence: *"You have 12 minutes left today. Then you can play again tomorrow."* Never a fraction or a percentage.
- Leaderboards show avatars and points, with a fixed "not on the board yet" card that says exactly how to get there ("Play 1 more game"). Never hide the board behind silence.

### D.5 The first-session test (a DoD gate for P4, P6, P7 and P8)

A player who has never seen the game, **cannot read the instructions (or the clue)**, and has had no adult help must:

1. Start the game from the hub within **30 seconds**.
2. Complete their **first round or first move** without asking for help.
3. Answer "what happens when the time bar is empty?" by pointing at the right card.

**Procedure:** 5 first-time players from the target band, no coaching, screen recorded, one observer counting interventions. **Pass = at least 4 of 5 complete all three steps.** Every intervention is logged with the screen it happened on and becomes a blocking fix for that phase.

### D.6 Motion, audio, and silence

- Every animation has a reduced-motion equivalent.
- No essential information is carried by sound alone. There is **no read-aloud feature** (D-36): every instruction is on screen as words plus one icon, and nothing depends on hearing it.
- No flashing, no auto-advancing screens, no time pressure on any menu, invite, or leaderboard screen. Pressure exists only inside a game round, and only where the rules require it.
