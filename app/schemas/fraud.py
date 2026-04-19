"""
Fraud alert schemas for fraud rule engine and investigation.
Aligns with schema.sql fraud_alerts table.
"""
from pydantic import BaseModel, ConfigDict, Field
from datetime import datetime
from typing import Any, Literal, Optional
import uuid


# Enums matching schema.sql CHECK constraints
AlertType = Literal[
    "suspicious_login",
    "unusual_transaction",
    "velocity_breach",
    "location_anomaly",
    "device_change",
    "pattern_anomaly",
]
FraudSeverity = Literal["low", "medium", "high", "critical"]
FraudAlertStatus = Literal["open", "investigating", "resolved", "false_positive"]


# ======================================
# FRAUD ALERT (created by fraud rule engine)
# ======================================

class FraudAlertCreate(BaseModel):
    """Schema for creating fraud alert - used by fraud rule engine."""
    user_id: Optional[uuid.UUID] = None
    transaction_id: Optional[uuid.UUID] = None
    session_id: Optional[uuid.UUID] = None
    alert_type: AlertType
    severity: FraudSeverity
    risk_score: Optional[int] = Field(None, ge=0, le=100)
    description: Optional[str] = None
    triggered_rules: Optional[dict[str, Any]] = None


class FraudAlertResponse(BaseModel):
    """Schema for returning fraud alert data."""
    id: uuid.UUID
    user_id: Optional[uuid.UUID] = None
    transaction_id: Optional[uuid.UUID] = None
    session_id: Optional[uuid.UUID] = None
    alert_type: AlertType
    severity: FraudSeverity
    risk_score: Optional[int] = None
    description: Optional[str] = None
    triggered_rules: Optional[dict[str, Any]] = None
    status: FraudAlertStatus
    assigned_to: Optional[str] = None
    resolution_notes: Optional[str] = None
    created_at: datetime
    resolved_at: Optional[datetime] = None

    model_config = ConfigDict(from_attributes=True)


class FraudRuleInput(BaseModel):
    """Input context for fraud rule evaluation - passed to rule engine."""
    user_id: uuid.UUID
    transaction_amount: Optional[float] = None
    transaction_type: Optional[str] = None
    ip_address: Optional[str] = None
    device_fingerprint: Optional[str] = None
    location_country: Optional[str] = None
    location_city: Optional[str] = None


# Used both as engine output (domain) and API response (DTO). Change domain logic
# with care so API contract stays stable.
class FraudEvaluationResult(BaseModel):
    """Result of fraud rule engine evaluation – score, action, and optional alert."""
    score: int
    severity: str  # "low" | "medium" | "high" | "critical"
    action: str  # "allow" | "flag" | "challenge" | "block"
    triggered_factors: dict[str, int] = Field(default_factory=dict)
    alert_required: bool = False
    description: Optional[str] = None
    alert_type: AlertType = "pattern_anomaly"
