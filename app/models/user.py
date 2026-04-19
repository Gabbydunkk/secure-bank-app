"""
app/models/user.py — SQLAlchemy ORM models.
All tables map directly to schema.sql.
"""
import uuid
from sqlalchemy import (
    Column, String, Boolean, Integer, DateTime, Date,
    ForeignKey, CheckConstraint, Text, Numeric, LargeBinary
)
from sqlalchemy.dialects.postgresql import UUID, INET, JSONB
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from .database import Base

# ==========================================
# 1. USERS
# ==========================================

class User(Base):
    __tablename__ = "users"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)

    email    = Column(String(255), unique=True, index=True, nullable=False)
    username = Column(String(100), unique=True, index=True, nullable=False)
    password_hash = Column(String(255), nullable=False)

    first_name   = Column(String(100), nullable=False)
    last_name    = Column(String(100), nullable=False)
    phone_number = Column(String(20))
    date_of_birth = Column(Date)

    # ── Role-based access control ──────────────────────────────────────────
    # role drives which JWT scopes are issued at login (see auth_service._scopes_for_user).
    #
    #   "user"    → read_only scope only              (default for all new accounts)
    #   "analyst" → read_only + transfer + analyst    (fraud team)
    #   "admin"   → all scopes including admin        (platform operators)
    #
    # The DB constraint enforces the allowed values so a typo can never
    # silently grant read_only access where analyst was intended.
    role = Column(String(20), default="user", server_default="user", nullable=False)

    account_status  = Column(String(20), default="active", nullable=False)
    email_verified  = Column(Boolean, default=False)
    phone_verified  = Column(Boolean, default=False)
    mfa_enabled     = Column(Boolean, default=False)

    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())
    last_login = Column(DateTime(timezone=True))

    failed_login_attempts = Column(Integer, default=0)
    locked_until          = Column(DateTime(timezone=True))

    __table_args__ = (
        CheckConstraint(
            "account_status IN ('active', 'suspended', 'locked', 'closed')",
            name="account_status_check",
        ),
        CheckConstraint(
            "role IN ('user', 'analyst', 'admin')",
            name="user_role_check",
        ),
    )

    # Relationships
    mfa_secrets       = relationship("MFASecret",            back_populates="user", cascade="all, delete-orphan")
    sessions          = relationship("Session",              back_populates="user", cascade="all, delete-orphan")
    login_attempts    = relationship("LoginAttempt",         back_populates="user")
    transactions      = relationship("Transaction",          back_populates="user")
    fraud_alerts      = relationship("FraudAlert",           back_populates="user")
    behavior_patterns = relationship("UserBehaviorPattern",  back_populates="user", uselist=False)
    audit_logs        = relationship("AuditLog",             back_populates="user")
    oauth_providers   = relationship("OAuthProvider",        back_populates="user")
    known_devices     = relationship("KnownDevice",          back_populates="user")


# ==========================================
# 2. MFA
# ==========================================

class MFASecret(Base):
    __tablename__ = "mfa_secrets"

    id      = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False)

    mfa_type              = Column(String(20), nullable=False)
    secret_encrypted      = Column(LargeBinary, nullable=False)
    backup_codes_encrypted = Column(LargeBinary)

    is_active  = Column(Boolean, default=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    last_used  = Column(DateTime(timezone=True))

    __table_args__ = (
        CheckConstraint(
            "mfa_type IN ('totp', 'sms', 'email')",
            name="mfa_type_check",
        ),
    )

    user = relationship("User", back_populates="mfa_secrets")


# ==========================================
# 3. SESSIONS
# ==========================================

class Session(Base):
    __tablename__ = "sessions"

    id      = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False)

    access_token_hash  = Column(String(255), nullable=False)
    refresh_token_hash = Column(String(255))

    device_fingerprint = Column(String(255))
    ip_address         = Column(INET)
    user_agent         = Column(Text)

    location_country = Column(String(2))
    location_city    = Column(String(100))

    is_active  = Column(Boolean, default=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    expires_at = Column(DateTime(timezone=True), nullable=False)
    last_activity = Column(DateTime(timezone=True), server_default=func.now())
    logout_at  = Column(DateTime(timezone=True))

    user = relationship("User", back_populates="sessions")


# ==========================================
# 4. LOGIN ATTEMPTS
# ==========================================

class LoginAttempt(Base):
    __tablename__ = "login_attempts"

    id      = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"))

    email      = Column(String(255))
    ip_address = Column(INET, nullable=False)
    user_agent = Column(Text)

    success        = Column(Boolean, nullable=False)
    failure_reason = Column(String(100))

    mfa_required = Column(Boolean, default=False)
    mfa_success  = Column(Boolean)

    location_country = Column(String(2))
    location_city    = Column(String(100))

    attempted_at = Column(DateTime(timezone=True), server_default=func.now())

    user = relationship("User", back_populates="login_attempts")


# ==========================================
# 5. TRANSACTIONS
# ==========================================

class Transaction(Base):
    __tablename__ = "transactions"

    id      = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)

    transaction_type = Column(String(50), nullable=False)
    amount           = Column(Numeric(15, 2), nullable=False)
    currency         = Column(String(3), default="USD")

    recipient_account = Column(String(100))
    recipient_name    = Column(String(200))
    description       = Column(Text)

    status             = Column(String(20), default="pending")
    risk_score         = Column(Integer)
    fraud_check_status = Column(String(20), default="pending")

    __table_args__ = (
        CheckConstraint(
            "transaction_type IN ('transfer', 'payment', 'withdrawal', 'deposit')",
            name="transaction_type_check",
        ),
        CheckConstraint(
            "status IN ('pending', 'processing', 'completed', 'failed', 'blocked', 'flagged')",
            name="transaction_status_check",
        ),
        CheckConstraint(
            "fraud_check_status IN ('pending', 'approved', 'flagged', 'blocked')",
            name="fraud_check_status_check",
        ),
        CheckConstraint("amount > 0",                             name="amount_positive_check"),
        CheckConstraint("risk_score >= 0 AND risk_score <= 100",  name="risk_score_range_check"),
    )

    device_fingerprint = Column(String(255))
    ip_address         = Column(INET)
    location_country   = Column(String(2))
    location_city      = Column(String(100))

    created_at   = Column(DateTime(timezone=True), server_default=func.now())
    processed_at = Column(DateTime(timezone=True))
    completed_at = Column(DateTime(timezone=True))

    user   = relationship("User",        back_populates="transactions")
    alerts = relationship("FraudAlert",  back_populates="transaction")


# ==========================================
# 6. FRAUD ALERTS
# ==========================================

class FraudAlert(Base):
    __tablename__ = "fraud_alerts"

    id             = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id        = Column(UUID(as_uuid=True), ForeignKey("users.id"))
    transaction_id = Column(UUID(as_uuid=True), ForeignKey("transactions.id"))
    session_id     = Column(UUID(as_uuid=True), ForeignKey("sessions.id"))

    alert_type = Column(String(50), nullable=False)
    severity   = Column(String(20), nullable=False)
    risk_score = Column(Integer)

    description    = Column(Text)
    triggered_rules = Column(JSONB)

    status           = Column(String(20), default="open")
    assigned_to      = Column(String(100))
    resolution_notes = Column(Text)

    created_at  = Column(DateTime(timezone=True), server_default=func.now())
    resolved_at = Column(DateTime(timezone=True))

    __table_args__ = (
        CheckConstraint(
            "alert_type IN ('suspicious_login', 'unusual_transaction', 'velocity_breach', "
            "'location_anomaly', 'device_change', 'pattern_anomaly')",
            name="alert_type_check",
        ),
        CheckConstraint(
            "severity IN ('low', 'medium', 'high', 'critical')",
            name="fraud_severity_check",
        ),
        CheckConstraint(
            "status IN ('open', 'investigating', 'resolved', 'false_positive')",
            name="fraud_alert_status_check",
        ),
    )

    user        = relationship("User",        back_populates="fraud_alerts")
    transaction = relationship("Transaction", back_populates="alerts")


# ==========================================
# 7. BEHAVIOR PATTERNS
# ==========================================

class UserBehaviorPattern(Base):
    __tablename__ = "user_behavior_patterns"

    id      = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), unique=True)

    typical_login_hours = Column(JSONB)
    typical_locations   = Column(JSONB)
    typical_devices     = Column(JSONB)

    average_transaction_amount   = Column(Numeric(15, 2))
    max_transaction_amount       = Column(Numeric(15, 2))
    typical_transaction_frequency = Column(Integer)

    last_updated = Column(DateTime(timezone=True), server_default=func.now())

    user = relationship("User", back_populates="behavior_patterns")


# ==========================================
# 8. AUDIT LOGS
# ==========================================

class AuditLog(Base):
    __tablename__ = "audit_logs"

    id      = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id"))

    action      = Column(String(100), nullable=False)
    entity_type = Column(String(50))
    entity_id   = Column(UUID(as_uuid=True))

    old_values = Column(JSONB)
    new_values = Column(JSONB)

    ip_address = Column(INET)
    user_agent = Column(Text)

    success       = Column(Boolean, nullable=False)
    error_message = Column(Text)

    created_at = Column(DateTime(timezone=True), server_default=func.now())

    user = relationship("User", back_populates="audit_logs")


# ==========================================
# 9. OAUTH PROVIDERS
# ==========================================

class OAuthProvider(Base):
    __tablename__ = "oauth_providers"

    id      = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False)

    provider_name    = Column(String(50), nullable=False)
    provider_user_id = Column(String(255), nullable=False)

    access_token_encrypted  = Column(LargeBinary)
    refresh_token_encrypted = Column(LargeBinary)
    token_expires_at        = Column(DateTime(timezone=True))
    scope                   = Column(Text)

    __table_args__ = (
        CheckConstraint(
            "provider_name IN ('google', 'facebook', 'microsoft', 'github')",
            name="oauth_provider_check",
        ),
    )

    user = relationship("User", back_populates="oauth_providers")


# ==========================================
# 10. KNOWN DEVICES
# ==========================================

class KnownDevice(Base):
    __tablename__ = "known_devices"

    id      = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False)

    device_fingerprint = Column(String(255), nullable=False)
    device_name        = Column(String(100))
    device_type        = Column(String(50))

    first_seen = Column(DateTime(timezone=True), server_default=func.now())
    last_seen  = Column(DateTime(timezone=True), server_default=func.now())

    is_trusted       = Column(Boolean, default=False)
    trust_expires_at = Column(DateTime(timezone=True))

    user = relationship("User", back_populates="known_devices")
    
