"""reconcile legacy users columns

Revision ID: 0004
Revises: 0003
Create Date: 2026-04-06
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect, text


# revision identifiers, used by Alembic.
revision: str = "0004"
down_revision: Union[str, None] = "0003"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)

    columns = {col["name"]: col for col in inspector.get_columns("users")}

    # Legacy DBs had "hashed_password"; current ORM expects "password_hash".
    if "password_hash" not in columns:
        op.add_column("users", sa.Column("password_hash", sa.String(length=255), nullable=True))

    columns = {col["name"]: col for col in inspector.get_columns("users")}
    if "hashed_password" in columns:
        bind.execute(
            text(
                """
                UPDATE users
                SET password_hash = hashed_password
                WHERE password_hash IS NULL
                  AND hashed_password IS NOT NULL
                """
            )
        )

    null_count = bind.execute(
        text("SELECT COUNT(*) FROM users WHERE password_hash IS NULL")
    ).scalar_one()
    if null_count == 0:
        op.alter_column("users", "password_hash", existing_type=sa.String(length=255), nullable=False)

    # Legacy DBs may have date_of_birth as timestamp; normalize to DATE.
    columns = {col["name"]: col for col in inspector.get_columns("users")}
    dob_col = columns.get("date_of_birth")
    if dob_col and "timestamp" in str(dob_col.get("type", "")).lower():
        op.execute(
            """
            ALTER TABLE users
            ALTER COLUMN date_of_birth TYPE DATE
            USING date_of_birth::date
            """
        )


def downgrade() -> None:
    # Keep downgrade non-destructive: restore nullable only.
    op.alter_column("users", "password_hash", existing_type=sa.String(length=255), nullable=True)

