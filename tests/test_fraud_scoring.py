from app.services.fraud_service import _score_to_action, _score_to_severity


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
