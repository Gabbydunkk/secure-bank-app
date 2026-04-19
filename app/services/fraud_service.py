"""
Fraud detection service – rule engine and alert creation.
Designed with SOLID: rule interface, pluggable rules, engine, and alert persistence.
"""
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any, Optional, Protocol
import uuid

from sqlalchemy.orm import Session
from sqlalchemy import func

from app.core.config import settings
from app.models.user import (
    FraudAlert,
    KnownDevice,
    LoginAttempt,
    UserBehaviorPattern,
)
from app.schemas.fraud import (
    AlertType,
    FraudAlertCreate,
    FraudEvaluationResult,
    FraudRuleInput,
    FraudSeverity,
)


# =============================================================================
# SOLID – Single responsibility: one result type per rule evaluation
# =============================================================================

@dataclass
class RuleResult:
    """Result of a single fraud rule evaluation."""
    score_delta: int
    severity: FraudSeverity
    alert_type: AlertType
    description: str
    triggered_key: str
    extra: dict[str, Any] = field(default_factory=dict)


# =============================================================================
# SOLID – Interface segregation + Dependency inversion: depend on abstraction
# =============================================================================

class IFraudRule(Protocol):
    """Protocol for a single fraud rule. New rules can be added without changing the engine."""

    def evaluate(self, db: Session, data: FraudRuleInput) -> Optional[RuleResult]:
        """Evaluate rule; return None if rule does not apply."""
        ...


# =============================================================================
# SOLID – Open/Closed: concrete rules are open for extension, engine closed for modification
# =============================================================================

class LocationRule:
    """Hard rule: restricted or high-risk locations (countries from config)."""

    HIGH_RISK_SCORE = 50

    def evaluate(self, db: Session, data: FraudRuleInput) -> Optional[RuleResult]:
        if not data.location_country:
            return None
        country = (data.location_country or "").upper()[:2]
        if country not in settings.fraud_restricted_countries_set:
            return None
        return RuleResult(
            score_delta=self.HIGH_RISK_SCORE,
            severity="high",
            alert_type="location_anomaly",
            description=f"Login or transaction from restricted location: {country}",
            triggered_key="restricted_location",
        )


class VelocityRule:
    """Velocity check: too many login attempts in a short window (from config)."""

    SCORE_DELTA = 40

    def evaluate(self, db: Session, data: FraudRuleInput) -> Optional[RuleResult]:
        window = settings.FRAUD_VELOCITY_WINDOW_MINUTES
        threshold = settings.FRAUD_VELOCITY_THRESHOLD_ATTEMPTS
        since = datetime.now(timezone.utc) - timedelta(minutes=window)
        attempt_count = (
            db.query(LoginAttempt)
            .filter(
                LoginAttempt.user_id == data.user_id,
                LoginAttempt.attempted_at >= since,
                LoginAttempt.success.is_(False),
            )
            .count()
        )
        distinct_ip_count = (
            db.query(func.count(func.distinct(LoginAttempt.ip_address)))
            .filter(
                LoginAttempt.user_id == data.user_id,
                LoginAttempt.attempted_at >= since,
                LoginAttempt.success.is_(False),
            )
            .scalar()
            or 0
        )
        if attempt_count < threshold or distinct_ip_count < 2:
            return None
        return RuleResult(
            score_delta=self.SCORE_DELTA,
            severity="high",
            alert_type="velocity_breach",
            description=(
                f"High velocity from multiple IPs: {attempt_count} failed attempts "
                f"across {distinct_ip_count} IPs in last {window} minutes"
            ),
            triggered_key="high_velocity_attempts",
            extra={
                "attempt_count": attempt_count,
                "distinct_ip_count": distinct_ip_count,
                "window_minutes": window,
            },
        )


class LargeAmountRule:
    """Flags transactions above configured threshold."""

    SCORE_DELTA = 30

    def evaluate(self, db: Session, data: FraudRuleInput) -> Optional[RuleResult]:
        threshold = settings.FRAUD_LARGE_AMOUNT_THRESHOLD
        if data.transaction_amount is None or data.transaction_amount <= threshold:
            return None
        return RuleResult(
            score_delta=self.SCORE_DELTA,
            severity="medium",
            alert_type="unusual_transaction",
            description=f"Large transaction amount: {data.transaction_amount}",
            triggered_key="large_transaction",
            extra={"amount": data.transaction_amount, "threshold": threshold},
        )


class DeviceAnomalyRule:
    """Flags requests from device fingerprints not recorded for the user."""

    SCORE_DELTA = 35

    def evaluate(self, db: Session, data: FraudRuleInput) -> Optional[RuleResult]:
        if not data.device_fingerprint:
            return None
        known = (
            db.query(KnownDevice)
            .filter(
                KnownDevice.user_id == data.user_id,
                KnownDevice.device_fingerprint == data.device_fingerprint,
            )
            .first()
        )
        if known is not None:
            return None
        return RuleResult(
            score_delta=self.SCORE_DELTA,
            severity="medium",
            alert_type="device_change",
            description="Login or transaction from an unknown device fingerprint",
            triggered_key="unknown_device",
            extra={"device_fingerprint": data.device_fingerprint},
        )


class PatternAnomalyRule:
    """Uses UserBehaviorPattern: transaction or login outside typical pattern."""

    SCORE_DELTA = 25

    def evaluate(self, db: Session, data: FraudRuleInput) -> Optional[RuleResult]:
        pattern = (
            db.query(UserBehaviorPattern)
            .filter(UserBehaviorPattern.user_id == data.user_id)
            .first()
        )
        if not pattern or not pattern.max_transaction_amount:
            return None
        max_allowed = float(pattern.max_transaction_amount)
        if data.transaction_amount is not None and data.transaction_amount > max_allowed:
            return RuleResult(
                score_delta=self.SCORE_DELTA,
                severity="medium",
                alert_type="pattern_anomaly",
                description=f"Transaction exceeds user's typical max: {data.transaction_amount} > {max_allowed}",
                triggered_key="pattern_anomaly_amount",
                extra={
                    "amount": data.transaction_amount,
                    "typical_max": max_allowed,
                },
            )
        return None


# =============================================================================
# Severity ranking – correct comparison (not lexicographic tuple)
# =============================================================================

SEVERITY_RANK: dict[str, int] = {
    "low": 1,
    "medium": 2,
    "high": 3,
    "critical": 4,
}


def _severity_rank(s: str) -> int:
    return SEVERITY_RANK.get(s, 0)


# =============================================================================
# Fraud rule engine – runs all rules and aggregates result (Single Responsibility)
# =============================================================================

def _score_to_severity(score: int) -> FraudSeverity:
    if score >= settings.FRAUD_SCORE_BLOCK:
        return "critical"
    if score >= settings.FRAUD_SCORE_CHALLENGE:
        return "high"
    if score >= settings.FRAUD_SCORE_FLAG:
        return "medium"
    return "low"


def _score_to_action(score: int) -> str:
    if score >= settings.FRAUD_SCORE_BLOCK:
        return "block"
    if score >= settings.FRAUD_SCORE_CHALLENGE:
        return "challenge"
    if score >= settings.FRAUD_SCORE_FLAG:
        return "flag"
    return "allow"


class FraudRuleEngine:
    """
    Evaluates a list of fraud rules and returns a single risk result.
    Depends on IFraudRule (abstraction); new rules can be added without changing this class.
    """

    def __init__(self, rules: Optional[list[IFraudRule]] = None):
        self._rules = rules or [
            LocationRule(),
            VelocityRule(),
            LargeAmountRule(),
            DeviceAnomalyRule(),
            PatternAnomalyRule(),
        ]

    def evaluate(self, db: Session, data: FraudRuleInput) -> FraudEvaluationResult:
        total_score = 0
        triggered: dict[str, int] = {}
        descriptions: list[str] = []
        max_severity_rank = 0
        alert_type_from_max: AlertType = "pattern_anomaly"

        for rule in self._rules:
            result = rule.evaluate(db, data)
            if result is None:
                continue
            total_score += result.score_delta
            triggered[result.triggered_key] = result.score_delta
            descriptions.append(result.description)
            r = _severity_rank(result.severity)
            if r > max_severity_rank:
                max_severity_rank = r
                alert_type_from_max = result.alert_type

        total_score = min(total_score, 100)
        severity: FraudSeverity = _score_to_severity(total_score)
        action = _score_to_action(total_score)
        alert_required = total_score >= settings.FRAUD_SCORE_FLAG
        chosen_alert_type: AlertType = alert_type_from_max

        return FraudEvaluationResult(
            score=total_score,
            severity=severity,
            action=action,
            triggered_factors=triggered,
            alert_required=alert_required,
            description="; ".join(descriptions) if descriptions else None,
            alert_type=chosen_alert_type,
        )


# =============================================================================
# Alert persistence – Single Responsibility: only creates fraud alerts in DB
# =============================================================================

class FraudAlertService:
    """Creates and persists fraud alerts. No evaluation logic. Caller controls commit for atomicity."""

    def create_alert(
        self,
        db: Session,
        data: FraudAlertCreate,
        *,
        commit: bool = True,
    ) -> FraudAlert:
        alert = FraudAlert(
            user_id=data.user_id,
            transaction_id=data.transaction_id,
            session_id=data.session_id,
            alert_type=data.alert_type,
            severity=data.severity,
            risk_score=data.risk_score,
            description=data.description,
            triggered_rules=data.triggered_rules,
            status="open",
        )
        db.add(alert)
        if commit:
            db.commit()
            db.refresh(alert)
        return alert

    def create_alert_from_evaluation(
        self,
        db: Session,
        evaluation: FraudEvaluationResult,
        user_id: Optional[uuid.UUID] = None,
        transaction_id: Optional[uuid.UUID] = None,
        session_id: Optional[uuid.UUID] = None,
        *,
        commit: bool = True,
    ) -> FraudAlert:
        """Build FraudAlertCreate from FraudRuleEngine result and persist."""
        create = FraudAlertCreate(
            user_id=user_id,
            transaction_id=transaction_id,
            session_id=session_id,
            alert_type=evaluation.alert_type,
            severity=evaluation.severity,
            risk_score=evaluation.score,
            description=evaluation.description,
            triggered_rules=evaluation.triggered_factors,
        )
        return self.create_alert(db, create, commit=commit)


# =============================================================================
# Facade – one entry point for “evaluate and optionally create alert”
# =============================================================================

class FraudService:
    """
    Facade for fraud detection: runs the rule engine and optionally persists an alert.
    Depends on FraudRuleEngine and FraudAlertService (Dependency Inversion).
    """

    def __init__(
        self,
        engine: Optional[FraudRuleEngine] = None,
        alert_service: Optional[FraudAlertService] = None,
    ):
        self._engine = engine or FraudRuleEngine()
        self._alert_service = alert_service or FraudAlertService()

    def evaluate(
        self,
        db: Session,
        data: FraudRuleInput,
        *,
        user_id: Optional[uuid.UUID] = None,
        transaction_id: Optional[uuid.UUID] = None,
        session_id: Optional[uuid.UUID] = None,
        create_alert_if_required: bool = True,
        commit_alert: bool = True,
    ) -> tuple[FraudEvaluationResult, Optional[FraudAlert]]:
        """
        Run fraud rules and optionally create an alert when risk is above threshold.
        If commit_alert=False, alert is added to db but not committed (for atomicity with caller).
        Returns (evaluation_result, alert or None).
        """
        result = self._engine.evaluate(db, data)
        alert = None
        if create_alert_if_required and result.alert_required:
            alert = self._alert_service.create_alert_from_evaluation(
                db,
                result,
                user_id=data.user_id or user_id,
                transaction_id=transaction_id,
                session_id=session_id,
                commit=commit_alert,
            )
        return result, alert