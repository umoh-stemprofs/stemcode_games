# STEM Code V2 — Games

Games for schools: Word Scramble, Number Guess and Checkers, with points, leaderboards and a
daily play-time limit. The plan lives in [GAMES_BUILD_PLAN.md](GAMES_BUILD_PLAN.md).

This repository is at **Phase 1**: the skeleton plus identity (schools, users, classes, roles,
login). There are no games yet.

---

## Two environments

| Path | Used for | Needs Docker? |
|---|---|---|
| **A. Native** (default) | Day-to-day development on Windows, macOS or Linux | **No** |
| **B. Container** | CI and machines that already have Docker | Yes |

Both must keep working. A change that breaks path A is a bug (plan rule 8).

---

## Path A — native, no Docker, no Redis

### 1. Prerequisites

- Python **3.12+** (`python --version`)
- Node **20+** (`node --version`)
- PostgreSQL **13+**, with `initdb`, `pg_ctl`, `psql` on `PATH`

Redis is **not** required. Without it the API uses in-memory cache and queue
implementations (decision D-34). They are single-process and lose state on restart — that is
intended, and startup refuses to use them outside `dev`/`test`.

### 2. Python environment

```bash
python -m venv .venv
.venv/Scripts/python -m pip install -r api/requirements.lock.txt   # Windows
# .venv/bin/python -m pip install -r api/requirements.lock.txt     # macOS / Linux
```

`requirements.txt` holds the human-readable pins and `requirements-dev.txt` adds the test and
quality tools. `requirements.lock.txt` is the resolved tree — every transitive package, pinned —
and it is the file CI installs and audits. Change a pin in `requirements*.txt`, run
`npm run lock:api`, then run the suite. `npm run audit:api` checks the lock for advisories; the
web dependencies are pinned in `web/package.json` and locked by `web/package-lock.json`.

All Python commands go through `scripts/py.mjs`, so you never activate the venv by hand:

```bash
npm run migrate      # alembic upgrade head
npm run test:api     # pytest
```

### 3. A local database

Use the cluster you already have, or create a project-local one (recommended — it keeps
experiments out of your system Postgres):

```bash
initdb -D .pgdata -U postgres --auth=trust -E UTF8
createdb -h 127.0.0.1 -p 5433 -U postgres stem_games    # start it first, see below
```

Start and stop it with `npm run db:start` and `npm run db:stop` (equivalently
`pg_ctl -D .pgdata -o "-p 5433 -c listen_addresses=127.0.0.1" -l .pgdata/server.log start`).

Use the npm scripts rather than a `pg_ctl start` you might interrupt or time out: a start that is
killed during crash recovery leaves the cluster half-started, and every later connection then
dies with `0xC0000142` / "could not reserve shared memory region". The cluster is undamaged —
stop it cleanly with `npm run db:stop` and start it again. `npm run db:status` says whether it is
up, and if a start fails the script prints the end of the server log.

### 4. Configuration

```bash
cp .env.example .env
```

Then check `DATABASE_URL` matches your cluster, e.g.

```
DATABASE_URL=postgresql+asyncpg://postgres@127.0.0.1:5433/stem_games
```

`.env` is git-ignored. No secret or connection string has a default in code.

`APP_BASE_URL` can stay at `http://localhost:3000` in dev — loopback is trusted there anyway. In
`staging` and `prod` it is **required**: it is the only origin the CSRF check and the WebSocket
handshake accept, and the base of every invite link. The app refuses to boot in those environments
without it rather than run with a loopback default and refuse every real write.

### 5. Run it

```bash
npm run migrate
npm run dev:api      # FastAPI on http://127.0.0.1:8000
npm run dev:web      # Next.js on http://localhost:3000  (second terminal)
npm run install:web  # first time only
```

Open <http://localhost:3000>. The badge calls `/api/health` **through the Next rewrite**, so the
browser only ever sees one origin (D-19).

> **WebSockets in dev:** Next rewrites do not upgrade WebSockets, so `/ws/*` connects to
> `127.0.0.1:8000` directly. The WS ticket is a normal REST call, so cookies still work.

### 6. Seed and sign in

```bash
npm run seed
```

Creates two schools on purpose (the second one exists so isolation can be tested with real
rows): Alpha Academy in `Africa/Lagos` and Beta College in `Europe/London`.

| Who | Code |
|---|---|
| School admin | `A-9001` |
| Coach 1 (owns Year 5A and 6A) | `A-9002` |
| Coach 2 (owns Year 5B) | `A-9003` |
| Second school admin | `A-9004` |
| Word writer (a coach with no class) | `A-9005` |
| Learners (30) | `A-1001` … `A-1030` |
| Second-school admin | `B-9001` |
| Second-school learners | `B-1001` … `B-1005` |

Every seeded account signs in with the PIN **`2468`**. It is dev fixture data, not a secret: the
CLI refuses to seed when `APP_ENV` is `staging` or `prod`. Codes are case-insensitive.

```bash
curl -c cookies.txt \
  -H 'content-type: application/json' \
  -d '{"code":"A-9002","pin":"2468"}' \
  http://127.0.0.1:8000/api/auth/login
curl -b cookies.txt http://127.0.0.1:8000/api/classes
```

Sessions live in httpOnly cookies (D-19); no token is ever returned in a JSON body.

The web app has the sign-in screens too: open <http://localhost:3000>, which sends you to
`/login`, and sign in with any seeded account. A learner sees **Home**, **Play** and **My
class**; both staff roles see **Classes**, **Time limits** and **Words**, and a school admin also
sees **Blocked words** (the safe-language list, D-39). Routes you cannot see answer with one
plain sentence, never an error page.

There are three roles (D-37): `learner`, `coach`, `school_admin`. A coach writes words and may
make their own words live; a school admin may do the same and can close a whole set. Making a
school, or its first admin, is a command on the server rather than a screen. A word is a draft
until somebody presses **Make it live** on that word (D-38).

### 7. Prove the environment is healthy

```bash
curl http://localhost:3000/api/health     # {"status":"ok"}
curl http://localhost:3000/api/ready      # database up, cache "memory"
npm run job:list                          # registered background tasks
npm run job:run reconcile                 # runs a job with no worker and no Redis
```

---

## Path B — container

```bash
cp .env.example .env
docker compose up --build
```

Services: `db` (postgres:16), `redis` (redis:7), `api`, `worker`, `web`, `proxy`.
The proxy serves everything on <http://localhost> with `/api` and `/ws` forwarded to FastAPI.

CI uses this path with service containers, so the container configuration is exercised even if
you never run it locally.

---

## Commands

| Command | What it does |
|---|---|
| `npm run dev:api` | FastAPI with reload on `:8000` |
| `npm run dev:web` | Next.js dev server on `:3000` |
| `npm run db:start` / `db:stop` / `db:status` | The project-local Postgres cluster on `:5433` |
| `npm run migrate` | Apply migrations (`head`) |
| `npm run migrate:down` | Roll migrations back to `base` |
| `npm run seed` | Demo schools, staff, classes and 35 learners (dev only) |
| `npm run job:list` | List background tasks |
| `npm run job:run <name>` | Run one task synchronously |
| `npm run test:api` | Python tests |
| `npm run lint:api` | Ruff |
| `npm run typecheck:api` | Mypy (strict) |
| `npm run audit:api` | Dependency scan of the Python lock |
| `npm run lock:api` | Re-resolve `api/requirements.lock.txt` after changing a pin |
| `npm run typecheck:web` | `tsc --noEmit` |
| `npm run test:e2e` | Playwright smoke suite (needs a seeded database and both servers) |
| `npm run gen:api` | Regenerate the TypeScript client from the running API |
| `npm run check` | Lint + types + tests |

There is no `make`: it is missing on Windows, so every command is an npm script (P0-T02).

### The end-to-end suite

`npm run test:e2e` drives a real browser through four journeys: signing in, playing a solo
game to its end, opening a Checkers match from the roster, and a second learner joining it
from their inbox before one of them resigns. It uses the seeded demo school (`A-1001` Amara,
`A-1002` Bayo, PIN `2468`), so it needs three things in this order:

```bash
npm run migrate && npm run seed
npm run dev:api          # terminal 1
npm run dev:web          # terminal 2
npm run test:e2e         # terminal 3
```

The first run downloads Chromium once (`npx --prefix web playwright install chromium`). CI runs
the same suite against a throwaway database and uploads the Playwright report when a flow
breaks.

---

## Layout

```
api/            FastAPI: app/core (config, db, cache, queue, errors), app/api (routers),
                app/identity (models, auth service, scope guards, seed)
api/alembic/    migrations (hand-written, reviewed)
api/tests/      unit + contract + architecture tests
web/            Next.js App Router
  lib/tokens.ts design tokens — Appendix D minimums live here
scripts/        py.mjs (cross-platform python runner), gen-api.mjs
.github/        CI: lint, types, migrations, tests, web build, client freshness
```

## Rules that are enforced by tests, not by hope

- **No direct Redis/ARQ imports** outside `app/core/cache.py`, `app/core/queue.py` and the
  worker entry point (`api/tests/test_layering.py`).
- **Both cache implementations share one contract suite** (`test_cache_contract.py`).
- **Redis tests must not silently skip in CI** (the workflow runs `-m redis` separately).
- **The generated client must be current** (CI regenerates and diffs `web/lib/api`).
- **Real names never reach a learner-facing schema** (`test_profile_privacy.py` scans the
  schemas and the actual responses).
- **Another school is a 404, not a 403** (`test_scope.py`), so ids cannot be probed.
