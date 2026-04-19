"""reconcile fraud_alerts columns and constraints

Revision ID: 0006
Revises: 0005
Create Date: 2026-04-06
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect, text


# revision identifiers, used by Alembic.
revision: str = "0006"
down_revision: Union[str, None] = "0005"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _has_check(bind, table: str, name: str) -> bool:
    row = bind.execute(
        text(
            """
            SELECT 1
            FROM pg_constraint c
            JOIN pg_class t ON c.conrelid = t.oid
            WHERE t.relname = :table
              AND c.conname = :name
              AND c.contype = 'c'
            """
        ),
        {"table": table, "name": name},
    ).first()
    return row is not None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)
    cols = {c["name"] for c in inspector.get_columns("fraud_alerts")}

    # Newer code writes resolution_notes on alert status updates.
    if "resolution_notes" not in cols:
        op.add_column("fraud_alerts", sa.Column("resolution_notes", sa.Text(), nullable=True))

    # Align status nullability/default with current model usage.
    op.execute("UPDATE fraud_alerts SET status = 'open' WHERE status IS NULL")
    op.alter_column(
        "fraud_alerts",
        "status",
        existing_type=sa.String(length=20),
        nullable=False,
        server_default="open",
    )

    # Add missing check constraints if legacy schema was created without them.
    if not _has_check(bind, "fraud_alerts", "alert_type_check"):
        op.create_check_constraint(
            "alert_type_check",
            "fraud_alerts",
            "alert_type IN ('suspicious_login', 'unusual_transaction', 'velocity_breach', "
            "'location_anomaly', 'device_change', 'pattern_anomaly')",
        )
    if not _has_check(bind, "fraud_alerts", "fraud_severity_check"):
        op.create_check_constraint(
            "fraud_severity_check",
            "fraud_alerts",
            "severity IN ('low', 'medium', 'high', 'critical')",
        )
    if not _has_check(bind, "fraud_alerts", "fraud_alert_status_check"):
        op.create_check_constraint(
            "fraud_alert_status_check",
            "fraud_alerts",
            "status IN ('open', 'investigating', 'resolved', 'false_positive')",
        )


def downgrade() -> None:
    bind = op.get_bind()
    if _has_check(bind, "fraud_alerts", "fraud_alert_status_check"):
        op.drop_constraint("fraud_alert_status_check", "fraud_alerts", type_="check")
    if _has_check(bind, "fraud_alerts", "fraud_severity_check"):
        op.drop_constraint("fraud_severity_check", "fraud_alerts", type_="check")
    if _has_check(bind, "fraud_alerts", "alert_type_check"):
        op.drop_constraint("alert_type_check", "fraud_alerts", type_="check")
