"""Three roles, and a status on every word (D-37, D-38).

Two changes that belong together, because the second is the reason for the
first.

**Roles go from seven to three.** ``learner``, ``coach``, ``school_admin``.
The content roles fold into the people who already exist: a coach writes words,
a school admin publishes them. ``platform_admin`` and ``moderator`` disappear —
making a school is a command on the server, not a screen. Existing accounts are
mapped, never deleted, so nobody loses their login:
``content_contributor -> coach`` and
``content_reviewer | moderator | platform_admin -> school_admin``.

**A word goes live on its own.** Status used to live only on the pack, so
"I like these 12 words, not those 3" could not be expressed. ``status`` on
``game_content_items`` fixes that: ``draft`` while it is being typed, ``live``
once its author pressed *Make it live*, ``retired`` when taken down. A word is
retired, never deleted, so the record of what a child played survives.

Words that were already being played are backfilled to ``live``; everything
else starts as ``draft``. Packs stay as the bucket that groups words by band
and version.

Revision ID: 0009_three_roles
Revises: 0008_content_review_note
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0009_three_roles"
down_revision = "0008_content_review_note"
branch_labels = None
depends_on = None

NEW_ROLES = ("learner", "coach", "school_admin")
OLD_ROLES = (
    "learner",
    "coach",
    "school_admin",
    "platform_admin",
    "content_contributor",
    "content_reviewer",
    "moderator",
)


def upgrade() -> None:
    # --- roles: map the accounts first, so no row can fail the new type ----
    op.execute("UPDATE users SET role = 'coach' WHERE role = 'content_contributor'")
    op.execute(
        "UPDATE users SET role = 'school_admin' "
        "WHERE role IN ('content_reviewer', 'moderator', 'platform_admin')"
    )

    op.execute("ALTER TYPE identity_role RENAME TO identity_role_old")
    op.execute("CREATE TYPE identity_role AS ENUM ('learner', 'coach', 'school_admin')")
    op.execute(
        "ALTER TABLE users ALTER COLUMN role TYPE identity_role USING role::text::identity_role"
    )
    op.execute("DROP TYPE identity_role_old")

    # --- a status on every word ------------------------------------------
    op.add_column(
        "game_content_items",
        sa.Column("status", sa.Text(), nullable=False, server_default="draft"),
    )
    op.add_column(
        "game_content_items",
        sa.Column(
            "published_by",
            sa.UUID(as_uuid=True),
            sa.ForeignKey("users.id", name="fk_content_items_published_by"),
            nullable=True,
        ),
    )
    op.add_column("game_content_items", sa.Column("published_at", sa.DateTime(timezone=True)))
    op.create_check_constraint(
        "ck_content_items_status",
        "game_content_items",
        "status IN ('draft','live','retired')",
    )
    op.create_index("ix_content_items_live", "game_content_items", ["status", "pack_id"])

    # Anything a child could already play is live; the rest is drafting.
    op.execute(
        "UPDATE game_content_items AS item "
        "SET status = 'live', published_at = pack.published_at "
        "FROM game_content_packs AS pack "
        "WHERE pack.id = item.pack_id AND pack.status = 'published'"
    )


def downgrade() -> None:
    op.drop_index("ix_content_items_live", table_name="game_content_items")
    op.drop_constraint("ck_content_items_status", "game_content_items", type_="check")
    op.drop_column("game_content_items", "published_at")
    op.drop_column("game_content_items", "published_by")
    op.drop_column("game_content_items", "status")

    # Put the seven values back. Rows keep the role they were mapped to; the
    # old values become valid again but are not reassigned, because the mapping
    # was many-to-one and cannot honestly be reversed.
    op.execute("ALTER TYPE identity_role RENAME TO identity_role_new")
    op.execute(
        "CREATE TYPE identity_role AS ENUM (" + ", ".join(f"'{value}'" for value in OLD_ROLES) + ")"
    )
    op.execute(
        "ALTER TABLE users ALTER COLUMN role TYPE identity_role USING role::text::identity_role"
    )
    op.execute("DROP TYPE identity_role_new")
