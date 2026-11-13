# STEM Code V2 — Games

Games for schools: Word Scramble, Number Guess and Checkers, with points, leaderboards and a
daily play-time limit. The plan lives in [GAMES_BUILD_PLAN.md](GAMES_BUILD_PLAN.md).

This repository is at **Phase 0**: the skeleton. There are no games yet.

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
.venv/Scripts/python -m pip install -r api/requirements-dev.txt   # Windows
# .venv/bin/python -m pip install -r api/requirements-dev.txt     # macOS / Linux
```

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
pg_ctl -D .pgdata -o "-p 5433 -c listen_addresses=127.0.0.1" -l .pgdata/pg.log start
createdb -h 127.0.0.1 -p 5433 -U postgres stem_games
```

Stop it later with `pg_ctl -D .pgdata stop`.

### 4. Configuration

```bash
cp .env.example .env
```

Then check `DATABASE_URL` matches your cluster, e.g.

```
DATABASE_URL=postgresql+asyncpg://postgres@127.0.0.1:5433/stem_games
```

`.env` is git-ignored. No secret or connection string has a default in code.

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

### 6. Prove the environment is healthy

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
| `npm run migrate` | Apply migrations (`head`) |
| `npm run migrate:down` | Roll migrations back to `base` |
| `npm run seed` | Baseline seed data |
| `npm run job:list` | List background tasks |
| `npm run job:run <name>` | Run one task synchronously |
| `npm run test:api` | Python tests |
| `npm run lint:api` | Ruff |
| `npm run typecheck:api` | Mypy (strict) |
| `npm run typecheck:web` | `tsc --noEmit` |
| `npm run gen:api` | Regenerate the TypeScript client from the running API |
| `npm run check` | Lint + types + tests |

There is no `make`: it is missing on Windows, so every command is an npm script (P0-T02).

---

## Layout

```
api/            FastAPI: app/core (config, db, cache, queue, errors), app/api (routers)
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
