"""Same-origin guard for cookie-authenticated writes (P11-T01, D-19).

The session lives in an httpOnly cookie. A browser attaches that cookie to a
cross-site form post, so without this check another page could spend a learner's
time allowance, send an invitation in their name, or end their match — the
classic CSRF shape, and `SameSite=Lax` alone does not cover older browsers or a
mis-set cookie.

Two rules, and no third:

- **Only unsafe methods are checked.** A GET carries no intent to change
  anything, and the games read a lot of them.
- **A missing `Origin` is allowed.** A browser always sends it on a cross-origin
  POST, so an absent header is a test client, a script, or a same-origin form
  post from a browser that chose not to. Refusing those would break curl and the
  whole test suite without closing a real hole.

The header is compared against the app's own origin plus loopback for local
development, which is the same allow-list the WebSocket gateway keeps — one
place to change if the deployment origin ever moves.
"""

from __future__ import annotations

from app.core.config import Settings

UNSAFE_METHODS = frozenset({"POST", "PUT", "PATCH", "DELETE"})

# The two origins the dev server and its rewrite use. Only accepted where the
# app itself runs on loopback: in staging and prod the deployed origin is the
# only one that may write, and APP_BASE_URL is required there so this list is
# never empty.
LOOPBACK_ORIGINS = ("http://localhost:3000", "http://127.0.0.1:3000")


def allowed_origins(settings: Settings) -> set[str]:
    allowed: set[str] = set()
    if not settings.is_production:
        allowed.update(LOOPBACK_ORIGINS)
    base = (settings.app_base_url or "").rstrip("/")
    if base:
        allowed.add(base)
    return allowed


def origin_refused(method: str, origin: str | None, *, settings: Settings) -> bool:
    """True when this request came from a page this app did not serve."""
    if method.upper() not in UNSAFE_METHODS:
        return False
    if not origin:
        return False
    return origin.rstrip("/") not in allowed_origins(settings)
