"""relax legacy hashed_password not-null constraint

Revision ID: 0005
Revises: 0004
Create Date: 2026-04-06
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect, text


# revision identifiers, used by Alembic.
revision: str = "0005"
down_revision: Union[str, None] = "0004"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)
    columns = {col["name"] for col in inspector.get_columns("users")}

    # Legacy column kept for backward compatibility in existing DBs.
    # Current ORM writes to password_hash, so this column must not block inserts.
    if "hashed_password" in columns:
        bind.execute(
            text(
                """
                UPDATE users
                SET hashed_password = password_hash
                WHERE hashed_password IS NULL
                  AND password_hash IS NOT NULL
                """
            )
        )
        op.alter_column(
            "users",
            "hashed_password",
            existing_type=sa.String(length=255),
            nullable=True,
        )


def downgrade() -> None:
    # Non-destructive downgrade: keep data as-is.
    bind = op.get_bind()
    null_count = bind.execute(
        text("SELECT COUNT(*) FROM users WHERE hashed_password IS NULL")
    ).scalar_one()
    if null_count == 0:
        op.alter_column(
            "users",
            "hashed_password",
            existing_type=sa.String(length=255),
            nullable=False,
        )

