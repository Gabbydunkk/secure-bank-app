import uuid
from unittest.mock import MagicMock

from app.schemas.fraud import FraudRuleInput
from app.services.fraud_service import VelocityRule, _score_to_action, _score_to_severity


def test_score_to_action_thresholds():
    assert _score_to_action(10) == "allow"
    assert _score_to_action(40) == "flag"
    assert _score_to_action(70) == "challenge"
    assert _score_to_action(90) == "block"


def test_score_to_severity_thresholds():
    assert _score_to_severity(10) == "low"
    assert _score_to_severity(40) == "medium"
    assert _score_to_severity(70) == "high"
    assert _score_to_severity(90) == "critical"


def _fraud_input() -> FraudRuleInput:
    return FraudRuleInput(
        user_id=uuid.uuid4(),
        ip_address="10.0.0.10",
        location_country="GB",
        location_city="London",
        device_fingerprint="fp-demo",
    )


def _mock_db_for_velocity(attempt_count: int, distinct_ip_count: int) -> MagicMock:
    db = MagicMock()
    attempts_query = MagicMock()
    attempts_query.filter.return_value.count.return_value = attempt_count

    ip_query = MagicMock()
    ip_query.filter.return_value.scalar.return_value = distinct_ip_count

    db.query.side_effect = [attempts_query, ip_query]
    return db


def test_velocity_rule_triggers_on_threshold_with_multiple_ips():
    rule = VelocityRule()
    db = _mock_db_for_velocity(attempt_count=5, distinct_ip_count=3)

    result = rule.evaluate(db, _fraud_input())

    assert result is not None
    assert result.triggered_key == "high_velocity_attempts"
    assert result.alert_type == "velocity_breach"
    assert result.extra["attempt_count"] == 5
    assert result.extra["distinct_ip_count"] == 3


def test_velocity_rule_does_not_trigger_for_single_ip():
    rule = VelocityRule()
    db = _mock_db_for_velocity(attempt_count=8, distinct_ip_count=1)

    result = rule.evaluate(db, _fraud_input())

    assert result is None


def test_velocity_rule_does_not_trigger_below_attempt_threshold():
    rule = VelocityRule()
    db = _mock_db_for_velocity(attempt_count=1, distinct_ip_count=3)

    result = rule.evaluate(db, _fraud_input())

    assert result is None
