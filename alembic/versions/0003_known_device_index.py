"""add index on known_devices (user_id, device_fingerprint)

Revision ID: 0003
Revises: 0002
Create Date: 2024-03-17 00:00:00 UTC

DeviceAnomalyRule runs on every login and every transaction — it queries
known_devices by (user_id, device_fingerprint) each time.

Without an index, that query is a full table scan on known_devices.
For a user with many sessions across many devices, this is acceptable at
small scale but degrades linearly as the table grows.

This migration adds a composite index on (user_id, device_fingerprint)
that makes the lookup an index scan — effectively O(log n) regardless of
how many devices exist in the system.

The index also covers register_device()'s "does this fingerprint exist?"
check, since that query uses the same two columns.

Why a non-unique index?
  A user COULD theoretically have two rows with the same fingerprint if a
  race condition hit register_device() twice simultaneously. The upsert in
  device_service handles this gracefully by updating last_seen. A unique
  index would instead raise an IntegrityError in that race. Non-unique is
  the safer choice here; the application layer already prevents duplicates
  under normal conditions.
"""

from alembic import op

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_index(
        "ix_known_devices_user_fingerprint",
        "known_devices",
        ["user_id", "device_fingerprint"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_known_devices_user_fingerprint", table_name="known_devices")
    