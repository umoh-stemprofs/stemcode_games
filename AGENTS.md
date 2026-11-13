# AGENTS.md — conventions for AI agents and humans

Read [GAMES_BUILD_PLAN.md](GAMES_BUILD_PLAN.md) first. This file is the short version of the rules
that code review enforces.

## Non-negotiables

1. **Local development must keep working without Docker and without Redis** (plan rule 8, D-34).
   If a change needs Redis, it goes through `CacheClient`; if it needs a background job, it is
   registered in `app/jobs/registry.py` so `python -m app.cli job run <name>` still works.
2. **Never import a Redis client or ARQ directly** outside `app/core/cache.py`,
   `app/core/queue.py`, and `app/jobs/worker.py`. A test fails the build otherwise.
3. **Server decides.** Clients send intents (a guess, an answer, a move). The server decides
   results, scores, XP, clocks, time allowance, eligibility.
4. **Never serialise a `seed`, a secret number, an answer, or a token.** Especially not in logs
   or error details (D-25).
5. **Plain language (Appendix D).** Every learner-facing screen must pass Appendix D: <=25 words,
   <=8 per sentence, 56px targets, 20px text, read-aloud, one decision per screen. Every
   learner-facing server `reason` maps to one fixed sentence — never show a raw code.
6. **No `make`.** All commands are npm scripts; Python runs through `scripts/py.mjs`.

## Layout rules

- `app/core/` — infrastructure only: config, db, cache, queue, errors, logging, rate limits.
  No game rules, no HTTP routing.
- `app/api/` — routers. Thin: parse, authorise, call a service, return.
- `app/games/domain/` (Phase 2+) — **pure** functions. No I/O, no clock, no randomness except an
  injected `Random(seed)` and an injected `now`.
- `app/games/services/` — business logic and transactions.
- `app/jobs/` — task registration; the worker is a single dispatcher.

## Database

- Every table is created by an Alembic migration. **Never edit the database by hand.**
- Migrations are hand-written and reviewed; there is no autogenerate step.
- Add a migration: create `api/alembic/versions/NNNN_name.py` with `down_revision` pointing at the
  current head, then `npm run migrate`. Verify `npm run migrate:down` too.
- `game_moves`, `game_results`, `game_xp_ledger` are **append-only**. Fix mistakes with new rows
  (`supersedes_id` / `superseded_by`, compensating entries), never `UPDATE` or `DELETE`.

## Errors

All failures return `{error: {code, message, details, request_id}}` (`app/core/errors.py`).
Raise `AppError` (or a subclass) with a stable `code` and a short human message. Never put
internals, stack traces, seeds, or names in `details`.

## Configuration

Environment only (`app/core/config.py`). No secret has a default in code. New settings go in
`.env.example` with a comment; `staging`/`prod` must refuse to boot when something required is
missing.

## Tests

- Add tests with the feature, not after it.
- Three levels: pure unit, API integration, e2e (Playwright, Phase 4+).
- Mark Redis-dependent tests `@pytest.mark.redis`; CI runs them separately and fails on skips.
- Architecture tests (`test_layering.py`) exist to keep the abstractions real.

## Idempotency and scope

- Every mutating game action carries `client_move_id`.
- Every XP award is keyed `(session_id, user_id, reason)`.
- Every service function takes an `actor` and checks school/role scope. Never trust a `school_id`
  from the client.

## Front end

- Design tokens in `web/lib/tokens.ts`; do not hard-code colours or sizes in components.
- The browser only talks to same-origin `/api/*` (Next rewrite in dev, proxy in prod).
- Types come from `npm run gen:api`. Never hand-write API types; CI fails if the client is stale.

## Commits

Reference task IDs (`P4-T10`) in the subject. Keep changes scoped to the phase you are in; do not
start the next phase to make the current one tidier.
