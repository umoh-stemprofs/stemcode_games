"""Sign in with a student code and a PIN instead of email and password.

Product decision: a child types a short code and a 4-6 digit PIN, not an email
address. Staff use the same two fields, so there is exactly one sign-in form.

What changes:
- ``users.student_code`` — unique, uppercase, the only login handle.
- ``users.pin_hash`` — Argon2id hash of the PIN. Nullable: an account with no
  PIN set cannot sign in, which is honest for rows created before a PIN exists.
- ``email``, ``username`` and ``password_hash`` are dropped. Two ways to sign
  in would mean two sets of rules, two sets of tests, and a second path that
  quietly skips the PIN lockout.

The failed-attempt counter and lockout column stay: a 4-digit secret needs more
protection than a long password, not less.

Revision ID: 0003_login_codes
Revises: 0002_identity
Create Date: 2026-11-14
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0003_login_codes"
down_revision = "0002_identity"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("users", sa.Column("student_code", sa.Text(), nullable=True))
    op.add_column("users", sa.Column("pin_hash", sa.Text(), nullable=True))

    # Existing rows (dev data only) get a code derived from whatever they had,
    # so the column can become NOT NULL without inventing a second source of
    # truth. New rows are always written with an explicit code.
    op.execute(
        """
        UPDATE users
        SET student_code = upper(split_part(email, '@', 1))
        WHERE student_code IS NULL AND email IS NOT NULL
        """
    )
    op.execute(
        """
        UPDATE users
        SET student_code = upper(substr(replace(id::text, '-', ''), 1, 8))
        WHERE student_code IS NULL
        """
    )

    op.alter_column("users", "student_code", existing_type=sa.Text(), nullable=False)
    op.create_index("ux_users_student_code", "users", ["student_code"], unique=True)

    op.drop_constraint("ck_users_has_login_handle", "users", type_="check")
    op.drop_index("ux_users_email_lower", table_name="users")
    op.drop_index("ux_users_username_lower", table_name="users")
    op.drop_column("users", "email")
    op.drop_column("users", "username")
    op.drop_column("users", "password_hash")


def downgrade() -> None:
    op.add_column("users", sa.Column("email", sa.Text(), nullable=True))
    op.add_column("users", sa.Column("username", sa.Text(), nullable=True))
    op.add_column("users", sa.Column("password_hash", sa.Text(), nullable=True))
    op.create_index(
        "ux_users_email_lower",
        "users",
        [sa.text("lower(email)")],
        unique=True,
        postgresql_where=sa.text("email IS NOT NULL"),
    )
    op.create_index(
        "ux_users_username_lower",
        "users",
        [sa.text("lower(username)")],
        unique=True,
        postgresql_where=sa.text("username IS NOT NULL"),
    )

    op.drop_index("ux_users_student_code", table_name="users")
    op.drop_column("users", "pin_hash")
    op.drop_column("users", "student_code")
