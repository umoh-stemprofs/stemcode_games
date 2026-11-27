# P11 audit — run on 2026-11-26

Scope: the checklist in `GAMES_BUILD_PLAN.md` Phase 11 (P11-T01 … P11-T10), run against the
tree on `master`. This is the record of what was actually executed, what passed, and what is
still open. Nothing here was inferred from the plan; every "pass" has the command that produced
it.

## What ran, and what it said

| Check | Command | Result |
| --- | --- | --- |
| API test suite | `npm run test:api` | **exit 0** — 369 tests, 0 failures, 5 skips (the `redis`-marked contract tests; local runs have no Redis, CI runs them against a real server) |
| API lint | `npm run lint:api` (ruff) | clean |
| API types | `npm run typecheck:api` (mypy, 70 files) | clean |
| Web types | `npm run typecheck:web` | clean |
| Rule parity | `npm run test:parity` | 18/18 |
| Web production build | `npm run build:web` | exit 0; 103 kB shared JS, 126–133 kB first load per page |
| Python dependencies | `pip-audit` | 6 advisories on **starlette 1.0.0** (fixed in 1.1.0 / 1.3.0 / 1.3.1); `pypdf` hits are a local venv extra, not a project dependency |
| JS dependencies | `npm audit --omit=dev` | 2 vulnerabilities (1 high): vulnerable `postcss` bundled inside **next 15.5.29**; the only fix is Next 16 (breaking) |
| Security headers, docs gating | `pytest api/tests/test_security.py` | 10/10 |

Environment note: Postgres had to be restarted with a clean environment. The earlier hang was not
the tests — a Windows `PATH` clash killed Postgres child processes (`0xC0000142`), every DB-backed
test errored at setup, and the run looked like a hang.

## P11-T01 Security

**Passing, checked in code and tests**

- CSRF: every unsafe method is checked against the app's own origin, plus loopback for dev
  (`app/core/origin.py`, wired as middleware in `app/main.py`). The WebSocket gateway has its own
  origin check.
- Session cookies: `HttpOnly`, `SameSite=Lax`, `Secure` whenever `APP_ENV` is staging/prod.
- CORS: no CORS middleware at all, so no cross-origin allowance exists to misconfigure.
- SQL injection: the only `text()` uses are literal fragments (`'counts_as_active AND ...'`,
  composite unique keys); no user input is interpolated into SQL.
- Authorization: the role × endpoint × school matrix is exercised by `test_scope.py`,
  `test_security.py`, `test_xp_isolation.py`, `test_profile_privacy.py`.
- Rate limits: sign-in, invite, report, session-create and action-submit are all limited;
  `test_rate_limit.py` and `test_security.py` cover the refusal path.
- No secret has a default in code; `staging`/`prod` refuse to boot without `SECRET_KEY` and
  `REDIS_URL`.

**Fixed on 2026-11-26 (findings 1–3)**

1. ~~**High — a live session token is committed.**~~ `.cookies.txt`, `.z.sid` and `.pg-start.out`
   are untracked (`git rm --cached`) and listed in `.gitignore`. The committed refresh token is
   therefore spent: sign in again wherever that jar was used. It is still in history, which is
   only a problem if the repository is ever made public.
2. ~~**Medium — no security headers.**~~ Every API answer now carries `X-Content-Type-Options`,
   `X-Frame-Options: DENY`, a framing-locked CSP, `Permissions-Policy` and `Referrer-Policy`
   (`security_headers()` in `app/main.py`, applied in the same middleware that stamps the request
   id, including on the early 403). HSTS is added when `is_production`. The Next app sends its own
   set (`web/next.config.mjs`, framing directive only, so a strict CSP cannot break a game
   screen), and `infra/nginx.conf` sets them server-wide.
3. ~~**Medium — API docs are on in every environment.**~~ `docs_url` and `openapi_url` are `None`
   when `settings.is_production`; dev and test keep them. Covered by
   `test_api_docs_are_closed_and_hsts_is_on_in_production`.

**Fixed on 2026-11-27 (finding 4)**

4. ~~**Medium — dependencies drift.**~~ Every Python dependency is pinned with `==` in
   `api/requirements.txt`, the resolved tree (all 72 packages, transitives included) lives in
   `api/requirements.lock.txt` and is what CI installs. Web dependencies are pinned exactly in
   `web/package.json`, locked by `web/package-lock.json`, and CI installs with `npm ci`. Both jobs
   now scan: `pip-audit -r api/requirements.lock.txt` and `npm audit --omit=dev --audit-level=high`.
   Pinning exposed three real problems, all fixed while pinning:
   - `starlette 1.0.0` (six advisories) → `1.10.0`. It is pinned directly, not left to FastAPI's
     range, because its version decides which request-parsing advisories apply.
   - `PyJWT 2.13.0` (ten advisories) → `2.15.1`.
   - `redis 8.1.0` alongside `arq 0.28.0`, which declares `redis>=4.2,<6`. pip itself calls that
     pair conflicting; the worker was running on an untested combination. Pinned to `5.3.1`.
   - Next 15.5.29 bundles `postcss 8.4.31`, which carries a high-severity advisory. An npm
     `overrides` entry forces `8.5.33` for that nested copy; the production build still passes.

**Fixed on 2026-11-27 (findings 5 and 6)**

5. ~~**Low — `APP_BASE_URL` defaults to `http://localhost:3000` in prod.**~~ It has no default now.
   `staging` and `prod` refuse to boot without it, and the value must be an absolute `http(s)` URL
   with any trailing slash normalised away. Two consequences were tightened at the same time,
   because they are the reason the setting matters:
   - Loopback origins are only trusted where the app itself runs on loopback. In `staging`/`prod`
     the deployed origin is the only accepted one, for both the REST write check and the WebSocket
     handshake — and the gateway now calls `allowed_origins()` instead of keeping a second copy of
     the list, so the two cannot drift apart.
   - Covered by `test_a_deployed_app_refuses_to_boot_without_a_public_base_url`,
     `test_a_relative_base_url_is_refused` and `test_loopback_origins_are_refused_once_deployed`.
6. ~~**Low — no server-side token revocation.**~~ Re-checked rather than assumed. Revocation was
   already implemented: `logout` marks the `auth_sessions` row revoked and
   `actor_from_access_token()` rejects any token whose session row is gone or revoked, so a copied
   access token dies at logout rather than at its `exp`. What was missing was proof — the existing
   test only showed the cookies were cleared. `test_a_copied_access_token_stops_working_at_logout`
   now sends the copied token by hand, shows it works before logout and is a 401 after. No code
   change was needed for this one; the audit finding was wrong.

## P11-T02 Privacy

**Passing:** no third-party hosts anywhere in `web/app`, `web/components` or `web/lib` — no
analytics, no fonts CDN, no error SaaS. Logs are JSON with request ids and no real names, emails
or answer text; the error envelope exposes `code`, one sentence and `request_id` only. Public
profiles are limited to `/api/profiles/{id}/public`.

**Open:** there is no retention schedule implemented (no purge job for `game_moves` /
`game_results` detail), and no export or delete flow. The plan asks for a documented schedule
(e.g. move detail 12 months) and flows aligned with the host platform's policy. Real names and
dates of birth live in `identity`, so this needs a written decision even if nothing is built yet.

## P11-T04 Accessibility and Appendix D

**Passing:** design tokens encode the Appendix D minimums (20px body, 56px targets) and components
use them; `prefers-reduced-motion` is honoured in `globals.css`; the Checkers board is a
`role="grid"` of real buttons with `aria-label` per square and `aria-pressed` for selection, so
keyboard play is possible; `test_safe_language.py` guards learner-facing sentences.

**Open:** not verified on a real device, at 200% zoom, or with a screen reader. Contrast of the
accent colours on white was not measured. The D.5 five-learner study (P11-T10) has not been run —
it needs children, not a script.

## P11-T03 Performance, P11-T05 Cross-device, P11-T06 Observability, P11-T07 Operations

Not done. In order of what blocks a pilot:

- **Observability:** structured logs and health probes exist; there are no metrics, no error
  tracking, no alerts and no dashboard. A pilot cannot be babysat by reading JSON logs.
- **Load:** no k6/Locust script exists, so the WS/live-match/leaderboard targets are unmeasured.
  Payload budgets were not checked either.
- **Cross-device:** only the automated Playwright half ran in CI (`web/e2e/smoke.spec.ts`: sign-in,
  a solo game to the end, two learners in Checkers with a resignation). The manual device matrix
  (iOS Safari, low-end Android, throttled 3G, offline) is untouched.
- **Operations:** no backup/restore script, no runbook, no per-school feature flags, no
  multiplayer kill switch. `infra/` holds a single `nginx.conf`.

## Verdict

The code is in good shape: the suite is green end to end, types and lint are clean, the production
build works, and the security basics (origin check, cookie flags, scoping, rate limits) are real
rather than aspirational. The audit's blockers before a pilot are not in the game logic — they are
the committed cookie jar, the missing response headers, unpinned dependencies, the missing
retention decision, and the total absence of monitoring.

Findings 1–3 were closed the same day. What is left, in order: dependency pinning plus a CI
scan, observability, the load test, the device matrix, then the D.5 study.
