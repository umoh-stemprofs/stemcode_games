"""A blocklist a school admin can change without a deploy (P4-T03).

The built-in safe-language list is code on purpose: reviewed, identical
everywhere, and impossible to empty by accident. But a school will always meet a
word nobody upstream thought of, and making that wait for a release is how a
blocklist goes stale.

So the list has two halves:

* ``app/games/domain/safe_language.py`` — the baseline, shipped with the code;
* ``blocked_words`` — added from the app by a school admin, effective at once.

Both are checked on every route: adding a word, importing a sheet, publishing
one word, or the bulk publish. Removing a row here cannot unblock anything on
the baseline list, and nothing here can be reached by a learner.

Words are stored already normalised (lowercase, letters only), which the check
constraint enforces, so the primary key is the whole rule and adding the same
word twice is a no-op.

Revision ID: 0010_blocked_words
Revises: 0009_three_roles
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0010_blocked_words"
down_revision = "0009_three_roles"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "blocked_words",
        sa.Column("word", sa.Text(), primary_key=True),
        sa.Column(
            "added_by",
            sa.UUID(as_uuid=True),
            sa.ForeignKey("users.id", name="fk_blocked_words_added_by"),
            nullable=True,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.CheckConstraint(
            "word = lower(word) AND word ~ '^[a-z]{2,40}$'", name="ck_blocked_words_shape"
        ),
    )


def downgrade() -> None:
    op.drop_table("blocked_words")
