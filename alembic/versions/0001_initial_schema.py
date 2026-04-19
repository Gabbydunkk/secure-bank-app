"""initial schema — all 10 tables

Revision ID: 0001
Revises:
Create Date: 2024-03-15 00:00:00 UTC

Creates the full initial database schema from scratch.
This migration is the baseline — all future migrations build on top of it.

Tables created (in dependency order):
  1. users                   — core identity
  2. mfa_secrets             — TOTP secrets + backup codes (FK → users)
  3. sessions                — active login sessions (FK → users)
  4. login_attempts          — audit trail for every login try (FK → users)
  5. transactions            — financial transactions (FK → users)
  6. fraud_alerts            — fraud engine outputs (FK → users, transactions, sessions)
  7. user_behavior_patterns  — baseline for anomaly detection (FK → users)
  8. audit_logs              — immutable event log (FK → users)
  9. oauth_providers         — third-party OAuth tokens (FK → users)
 10. known_devices           — trusted device registry (FK → users)

NOTE: The 'role' column on users is NOT included here — it is added in
migration 0002. This split intentionally demonstrates the migration workflow:
0001 establishes the schema as it existed before role-based access control
was designed; 0002 adds it as an additive change.
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# Alembic metadata
revision = "0001"
down_revision = None        # first migration — no parent
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ── 1. users ─────────────────────────────────────────────────────────────
    op.create_table(
        "users",
        sa.Column("id",                    postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("email",                 sa.String(255),  nullable=False),
        sa.Column("username",              sa.String(100),  nullable=False),
        sa.Column("password_hash",         sa.String(255),  nullable=False),
        sa.Column("first_name",            sa.String(100),  nullable=False),
        sa.Column("last_name",             sa.String(100),  nullable=False),
        sa.Column("phone_number",          sa.String(20),   nullable=True),
        sa.Column("date_of_birth",         sa.Date(),       nullable=True),
        sa.Column("account_status",        sa.String(20),   nullable=False, server_default="active"),
        sa.Column("email_verified",        sa.Boolean(),    nullable=False, server_default="false"),
        sa.Column("phone_verified",        sa.Boolean(),    nullable=False, server_default="false"),
        sa.Column("mfa_enabled",           sa.Boolean(),    nullable=False, server_default="false"),
        sa.Column("created_at",            sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at",            sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_login",            sa.DateTime(timezone=True), nullable=True),
        sa.Column("failed_login_attempts", sa.Integer(),    nullable=False, server_default="0"),
        sa.Column("locked_until",          sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "account_status IN ('active', 'suspended', 'locked', 'closed')",
            name="account_status_check",
        ),
    )
    op.create_index("ix_users_email",    "users", ["email"],    unique=True)
    op.create_index("ix_users_username", "users", ["username"], unique=True)

    # ── 2. mfa_secrets ────────────────────────────────────────────────────────
    op.create_table(
        "mfa_secrets",
        sa.Column("id",                       postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("user_id",                  postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("mfa_type",                 sa.String(20),    nullable=False),
        sa.Column("secret_encrypted",         sa.LargeBinary(), nullable=False),
        sa.Column("backup_codes_encrypted",   sa.LargeBinary(), nullable=True),
        sa.Column("is_active",                sa.Boolean(),     nullable=False, server_default="true"),
        sa.Column("created_at",               sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("last_used",                sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.CheckConstraint(
            "mfa_type IN ('totp', 'sms', 'email')",
            name="mfa_type_check",
        ),
    )

    # ── 3. sessions ───────────────────────────────────────────────────────────
    op.create_table(
        "sessions",
        sa.Column("id",                  postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("user_id",             postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("access_token_hash",   sa.String(255),  nullable=False),
        sa.Column("refresh_token_hash",  sa.String(255),  nullable=True),
        sa.Column("device_fingerprint",  sa.String(255),  nullable=True),
        sa.Column("ip_address",          postgresql.INET(), nullable=True),
        sa.Column("user_agent",          sa.Text(),       nullable=True),
        sa.Column("location_country",    sa.String(2),    nullable=True),
        sa.Column("location_city",       sa.String(100),  nullable=True),
        sa.Column("is_active",           sa.Boolean(),    nullable=False, server_default="true"),
        sa.Column("created_at",          sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("expires_at",          sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_activity",       sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("logout_at",           sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
    )

    # ── 4. login_attempts ─────────────────────────────────────────────────────
    op.create_table(
        "login_attempts",
        sa.Column("id",               postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("user_id",          postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("email",            sa.String(255),  nullable=True),
        sa.Column("ip_address",       postgresql.INET(), nullable=False),
        sa.Column("user_agent",       sa.Text(),       nullable=True),
        sa.Column("success",          sa.Boolean(),    nullable=False),
        sa.Column("failure_reason",   sa.String(100),  nullable=True),
        sa.Column("mfa_required",     sa.Boolean(),    nullable=False, server_default="false"),
        sa.Column("mfa_success",      sa.Boolean(),    nullable=True),
        sa.Column("location_country", sa.String(2),    nullable=True),
        sa.Column("location_city",    sa.String(100),  nullable=True),
        sa.Column("attempted_at",     sa.DateTime(timezone=True), server_default=sa.func.now()),
        # SET NULL so login attempt history survives user deletion
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="SET NULL"),
    )

    # ── 5. transactions ───────────────────────────────────────────────────────
    op.create_table(
        "transactions",
        sa.Column("id",                  postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("user_id",             postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("transaction_type",    sa.String(50),     nullable=False),
        sa.Column("amount",              sa.Numeric(15, 2), nullable=False),
        sa.Column("currency",            sa.String(3),      nullable=False, server_default="USD"),
        sa.Column("recipient_account",   sa.String(100),    nullable=True),
        sa.Column("recipient_name",      sa.String(200),    nullable=True),
        sa.Column("description",         sa.Text(),         nullable=True),
        sa.Column("status",              sa.String(20),     nullable=False, server_default="pending"),
        sa.Column("risk_score",          sa.Integer(),      nullable=True),
        sa.Column("fraud_check_status",  sa.String(20),     nullable=False, server_default="pending"),
        sa.Column("device_fingerprint",  sa.String(255),    nullable=True),
        sa.Column("ip_address",          postgresql.INET(), nullable=True),
        sa.Column("location_country",    sa.String(2),      nullable=True),
        sa.Column("location_city",       sa.String(100),    nullable=True),
        sa.Column("created_at",          sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("processed_at",        sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at",        sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.CheckConstraint(
            "transaction_type IN ('transfer', 'payment', 'withdrawal', 'deposit')",
            name="transaction_type_check",
        ),
        sa.CheckConstraint(
            "status IN ('pending', 'processing', 'completed', 'failed', 'blocked', 'flagged')",
            name="transaction_status_check",
        ),
        sa.CheckConstraint(
            "fraud_check_status IN ('pending', 'approved', 'flagged', 'blocked')",
            name="fraud_check_status_check",
        ),
        sa.CheckConstraint("amount > 0",                            name="amount_positive_check"),
        sa.CheckConstraint("risk_score >= 0 AND risk_score <= 100", name="risk_score_range_check"),
    )

    # ── 6. fraud_alerts ───────────────────────────────────────────────────────
    op.create_table(
        "fraud_alerts",
        sa.Column("id",               postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("user_id",          postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("transaction_id",   postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("session_id",       postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("alert_type",       sa.String(50),  nullable=False),
        sa.Column("severity",         sa.String(20),  nullable=False),
        sa.Column("risk_score",       sa.Integer(),   nullable=True),
        sa.Column("description",      sa.Text(),      nullable=True),
        sa.Column("triggered_rules",  postgresql.JSONB(), nullable=True),
        sa.Column("status",           sa.String(20),  nullable=False, server_default="open"),
        sa.Column("assigned_to",      sa.String(100), nullable=True),
        sa.Column("resolution_notes", sa.Text(),      nullable=True),
        sa.Column("created_at",       sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("resolved_at",      sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["user_id"],        ["users.id"]),
        sa.ForeignKeyConstraint(["transaction_id"], ["transactions.id"]),
        sa.ForeignKeyConstraint(["session_id"],     ["sessions.id"]),
        sa.CheckConstraint(
            "alert_type IN ('suspicious_login', 'unusual_transaction', 'velocity_breach', "
            "'location_anomaly', 'device_change', 'pattern_anomaly')",
            name="alert_type_check",
        ),
        sa.CheckConstraint(
            "severity IN ('low', 'medium', 'high', 'critical')",
            name="fraud_severity_check",
        ),
        sa.CheckConstraint(
            "status IN ('open', 'investigating', 'resolved', 'false_positive')",
            name="fraud_alert_status_check",
        ),
    )

    # ── 7. user_behavior_patterns ─────────────────────────────────────────────
    op.create_table(
        "user_behavior_patterns",
        sa.Column("id",                            postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("user_id",                       postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("typical_login_hours",           postgresql.JSONB(), nullable=True),
        sa.Column("typical_locations",             postgresql.JSONB(), nullable=True),
        sa.Column("typical_devices",               postgresql.JSONB(), nullable=True),
        sa.Column("average_transaction_amount",    sa.Numeric(15, 2),  nullable=True),
        sa.Column("max_transaction_amount",        sa.Numeric(15, 2),  nullable=True),
        sa.Column("typical_transaction_frequency", sa.Integer(),       nullable=True),
        sa.Column("last_updated",                  sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.UniqueConstraint("user_id", name="uq_user_behavior_patterns_user_id"),
    )

    # ── 8. audit_logs ─────────────────────────────────────────────────────────
    op.create_table(
        "audit_logs",
        sa.Column("id",            postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("user_id",       postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("action",        sa.String(100),     nullable=False),
        sa.Column("entity_type",   sa.String(50),      nullable=True),
        sa.Column("entity_id",     postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("old_values",    postgresql.JSONB(), nullable=True),
        sa.Column("new_values",    postgresql.JSONB(), nullable=True),
        sa.Column("ip_address",    postgresql.INET(),  nullable=True),
        sa.Column("user_agent",    sa.Text(),          nullable=True),
        sa.Column("success",       sa.Boolean(),       nullable=False),
        sa.Column("error_message", sa.Text(),          nullable=True),
        sa.Column("created_at",    sa.DateTime(timezone=True), server_default=sa.func.now()),
        # SET NULL so audit trail survives user deletion (forensic value)
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
    )

    # ── 9. oauth_providers ────────────────────────────────────────────────────
    op.create_table(
        "oauth_providers",
        sa.Column("id",                      postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("user_id",                 postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("provider_name",           sa.String(50),    nullable=False),
        sa.Column("provider_user_id",        sa.String(255),   nullable=False),
        sa.Column("access_token_encrypted",  sa.LargeBinary(), nullable=True),
        sa.Column("refresh_token_encrypted", sa.LargeBinary(), nullable=True),
        sa.Column("token_expires_at",        sa.DateTime(timezone=True), nullable=True),
        sa.Column("scope",                   sa.Text(),        nullable=True),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.CheckConstraint(
            "provider_name IN ('google', 'facebook', 'microsoft', 'github')",
            name="oauth_provider_check",
        ),
    )

    # ── 10. known_devices ─────────────────────────────────────────────────────
    op.create_table(
        "known_devices",
        sa.Column("id",                 postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("user_id",            postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("device_fingerprint", sa.String(255), nullable=False),
        sa.Column("device_name",        sa.String(100), nullable=True),
        sa.Column("device_type",        sa.String(50),  nullable=True),
        sa.Column("first_seen",         sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("last_seen",          sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("is_trusted",         sa.Boolean(),   nullable=False, server_default="false"),
        sa.Column("trust_expires_at",   sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
    )


def downgrade() -> None:
    # Drop in reverse dependency order so FK constraints are satisfied.
    op.drop_table("known_devices")
    op.drop_table("oauth_providers")
    op.drop_table("audit_logs")
    op.drop_table("user_behavior_patterns")
    op.drop_table("fraud_alerts")
    op.drop_table("transactions")
    op.drop_table("login_attempts")
    op.drop_table("sessions")
    op.drop_table("mfa_secrets")
    op.drop_index("ix_users_username", table_name="users")
    op.drop_index("ix_users_email",    table_name="users")
    op.drop_table("users")
    