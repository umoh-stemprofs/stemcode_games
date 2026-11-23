"""XP stays motivational (P5-T05, D-13).

Profile and Game XP exist to encourage play. The moment a grade, badge,
certificate, completion rule or eligibility check reads them, the number stops
being a game score and starts being a measure of a child.

The rule is enforced by import graph, because that is what a reviewer can see:
only the game-play path, the XP service itself, the boards, the maintenance jobs
and the HTTP layer may touch the XP modules. A new module that imports them
fails here until someone deliberately adds it to the list.
"""

from __future__ import annotations

import re
from pathlib import Path

APP_DIR = Path(__file__).resolve().parents[1] / "app"

XP_IMPORT = re.compile(
    r"^\s*(?:from\s+app\.games\.(?:services|domain)\s+import\s+[^\n]*\bxp\b"
    r"|from\s+app\.games\.services\.xp\s+import"
    r"|from\s+app\.games\.domain\s+import\s+[^\n]*xp_rules"
    r"|from\s+app\.games\.domain\.xp_rules\s+import"
    r"|import\s+app\.games\.services\.xp)",
    re.MULTILINE,
)

# The whole allowed surface. Each entry has to justify itself:
#   services/xp.py         — the only door to an award.
#   services/play.py       — awards when a result is written (P5-T03).
#   services/results.py    — ends a session and awards in the same transaction.
#   services/guessing.py   — Number Guess's play path; ends its sessions there.
#   services/challenge.py  — awards the +5 win bonus; it compares two results,
#                            never a grade (P7-T05).
#   services/leaderboards.py — reads the rules for the minimum (P5-T08).
#   services/engagement.py — pays the daily-quest bonus (an award path like the
#                            challenge bonus) and restates Profile XP as a
#                            presentational level. Its badge criteria receive
#                            ``BadgeFacts``, which has no XP field at all, and
#                            ``test_badge_facts_cannot_see_xp`` pins that.
#   api/leaderboards.py    — presents /me/xp.
ALLOWED = {
    Path("games/services/xp.py"),
    Path("games/services/play.py"),
    Path("games/services/results.py"),
    Path("games/services/guessing.py"),
    Path("games/services/challenge.py"),
    # Live match results award XP exactly as a solo result does (P8-T14).
    Path("games/services/live.py"),
    Path("games/services/leaderboards.py"),
    Path("games/services/maintenance.py"),
    Path("games/services/engagement.py"),
    Path("api/leaderboards.py"),
}


def test_only_the_allowed_modules_import_xp() -> None:
    offenders: list[str] = []
    for path in sorted(APP_DIR.rglob("*.py")):
        relative = path.relative_to(APP_DIR)
        if relative in ALLOWED:
            continue
        if XP_IMPORT.search(path.read_text(encoding="utf-8")):
            offenders.append(str(relative))
    assert offenders == [], (
        "XP is motivational only: do not read it from a grade, badge, certificate, "
        f"completion or eligibility path (P5-T05): {offenders}"
    )


def test_badge_facts_cannot_see_xp() -> None:
    """A badge may only look at play: counts, wins, days, quests.

    The import guard above is about modules; this is about the data a badge is
    handed. If someone adds ``profile_xp`` to ``BadgeFacts``, a badge can start
    measuring a child's total by the back door, and this test fails first.
    """
    from dataclasses import fields

    from app.games.domain.badges import BADGES, BadgeFacts

    names = {field.name for field in fields(BadgeFacts)}
    assert not any("xp" in name or "point" in name for name in names)
    assert BADGES, "the badge list cannot be empty"
    for badge in BADGES:
        assert "xp" not in badge.hint.lower(), badge.id


def test_the_guard_can_actually_see_an_import() -> None:
    """A guard that matches nothing is a comment, not a test."""
    sample = "from app.games.services import xp\n"
    assert XP_IMPORT.search(sample)
    sample = "from app.games.domain.xp_rules import capped_award\n"
    assert XP_IMPORT.search(sample)
