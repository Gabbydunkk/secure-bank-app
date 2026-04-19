"""add role column to users

Revision ID: 0002
Revises: 0001
Create Date: 2024-03-16 00:00:00 UTC

Adds role-based access control to the users table.

The role column drives which JWT scopes are embedded in a user's access token
at login time (see app/services/auth_service._scopes_for_user).

  "user"    → read_only scope only              (all new registrations)
  "analyst" → read_only + transfer + analyst    (fraud team)
  "admin"   → all scopes including admin        (platform operators)

Migration is safe to run against a live database:
  1. ADD COLUMN with a NOT NULL default runs as a single metadata operation
     in Postgres 11+ — the column appears immediately without a table rewrite.
  2. The DEFAULT 'user' means every existing row is automatically assigned
     the least-privileged role — no data loss, no privilege escalation.
  3. The CHECK constraint is added after the column so existing rows are
     validated before the constraint is locked in.

Rollback (downgrade):
  Drops the column and its constraint. Existing role assignments are lost,
  but since every row had "user" (the default), this is safe.
"""

from alembic import op
import sqlalchemy as sa

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Step 1: Add the column with a server-side default.
    # NOT NULL + server_default means Postgres fills existing rows immediately
    # without a full table scan in modern versions (11+).
    op.add_column(
        "users",
        sa.Column(
            "role",
            sa.String(20),
            nullable=False,
            server_default="user",   # every existing row becomes "user"
        ),
    )

    # Step 2: Add the CHECK constraint now that all rows have a valid value.
    # Named constraint so it can be targeted precisely in future migrations.
    op.create_check_constraint(
        "user_role_check",
        "users",
        "role IN ('user', 'analyst', 'admin')",
    )


def downgrade() -> None:
    # Drop constraint first — Postgres requires this before the column can be removed.
    op.drop_constraint("user_role_check", "users", type_="check")
    op.drop_column("users", "role")