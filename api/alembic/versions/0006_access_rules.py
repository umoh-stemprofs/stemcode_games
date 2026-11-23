"""Access rules: the columns and checks Phase 3 needs (P3-T01 .. P3-T08).

Phase 2 created the six tables but left two things to application code:

1. **The D-10 grace window.** A solo session that is already running gets 10
   minutes past zero remaining, then stops. "Ten minutes from when?" needs a
   moment stored on the session -- recomputing it from daily totals is wrong
   because earlier sessions in the day also consumed allowance. Hence
   ``game_sessions.allowance_grace_until``: NULL until the session first runs
   past zero, then ``now + 10 minutes``.
2. **Two scope checks.** A policy with scope ``platform`` must have no
   ``scope_id``; every other scope must have one. And a lockout cannot expire
   before it starts. Both are cheap here and impossible to violate later.

It also seeds the two switches every access answer depends on:
``games_enabled`` (the platform-wide off switch) and ``leaderboards_only``
(boards visible, play refused).

Revision ID: 0006_access_rules
Revises: 0005_one_active_play
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0006_access_rules"
down_revision = "0005_one_active_play"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "game_sessions",
        sa.Column("allowance_grace_until", sa.DateTime(timezone=True)),
    )

    op.create_check_constraint(
        "ck_access_policies_scope_id",
        "game_access_policies",
        "(scope_type = 'platform' AND scope_id IS NULL)"
        " OR (scope_type <> 'platform' AND scope_id IS NOT NULL)",
    )
    op.create_check_constraint(
        "ck_lockouts_window",
        "game_lockouts",
        "expires_at > starts_at",
    )

    op.execute(
        """
        INSERT INTO platform_settings (key, value) VALUES
          ('games_enabled', 'true'::jsonb),
          ('leaderboards_only', 'false'::jsonb),
          ('soft_limit_grace_minutes', '10'::jsonb)
        ON CONFLICT (key) DO NOTHING
        """
    )


def downgrade() -> None:
    op.execute(
        """
        DELETE FROM platform_settings
        WHERE key IN ('games_enabled','leaderboards_only','soft_limit_grace_minutes')
        """
    )
    op.drop_constraint("ck_lockouts_window", "game_lockouts", type_="check")
    op.drop_constraint("ck_access_policies_scope_id", "game_access_policies", type_="check")
    op.drop_column("game_sessions", "allowance_grace_until")
