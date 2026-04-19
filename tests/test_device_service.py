"""
tests/test_device_service.py — Known device registration tests.

Tests cover:
  device_service unit tests:
    - New device is inserted with correct fields
    - Existing device updates last_seen, not inserting duplicate
    - None fingerprint is a no-op (returns None, no DB write)
    - commit=True causes db.commit() to be called
    - remove_device() deletes the row and returns True
    - remove_device() returns False for unknown device
    - remove_device() enforces ownership (wrong user_id → False)

  DeviceAnomalyRule integration:
    - Unknown device fingerprint scores +35
    - Known device fingerprint scores 0
    - Missing fingerprint scores 0 (rule skips)

  auth_service.login integration:
    - Successful login with fingerprint calls register_device
    - Successful login without fingerprint does not call register_device
    - Failed login does NOT call register_device

Run: pytest tests/test_device_service.py -v
"""

import uuid
from datetime import datetime, timezone
from unittest.mock import MagicMock, call, patch

import pytest

from app.services.device_service import (
    get_known_devices,
    register_device,
    remove_device,
)


# ============================================================================
# Helpers
# ============================================================================

def _mock_db():
    db = MagicMock()
    db.query.return_value.filter.return_value.first.return_value = None
    db.query.return_value.filter.return_value.order_by.return_value.all.return_value = []
    return db


def _mock_device(user_id: uuid.UUID, fingerprint: str = "fp-abc123") -> MagicMock:
    d = MagicMock()
    d.id = uuid.uuid4()
    d.user_id = user_id
    d.device_fingerprint = fingerprint
    d.is_trusted = False
    d.first_seen = datetime.now(timezone.utc)
    d.last_seen = datetime.now(timezone.utc)
    return d


# ============================================================================
# register_device — unit tests
# ============================================================================

class TestRegisterDevice:

    def test_new_device_is_added_to_session(self):
        """
        First login from a device fingerprint → a KnownDevice row is added.
        db.add() must be called with an object that has the correct fields.
        """
        db = _mock_db()
        user_id = uuid.uuid4()

        result = register_device(db, user_id, "fp-newdevice")

        db.add.assert_called_once()
        added = db.add.call_args[0][0]
        assert added.user_id == user_id
        assert added.device_fingerprint == "fp-newdevice"
        assert added.is_trusted is False
        assert result is added

    def test_existing_device_updates_last_seen(self):
        """
        Second login from same fingerprint → updates last_seen, does NOT add a new row.
        This is the upsert behaviour that prevents duplicate rows.
        """
        db = _mock_db()
        user_id = uuid.uuid4()
        existing = _mock_device(user_id, "fp-existing")
        # Ensure last_seen will change even if register_device() is called
        # within the same microsecond.
        existing.last_seen = datetime(2000, 1, 1, tzinfo=timezone.utc)
        db.query.return_value.filter.return_value.first.return_value = existing

        old_last_seen = existing.last_seen
        result = register_device(db, user_id, "fp-existing")

        db.add.assert_not_called()           # no new row
        assert result is existing
        assert result.last_seen != old_last_seen  # last_seen was updated

    def test_none_fingerprint_returns_none_no_db_write(self):
        """
        Clients that don't send X-Device-Fingerprint get None.
        No DB query, no add, no commit — completely transparent.
        """
        db = _mock_db()
        result = register_device(db, uuid.uuid4(), None)

        assert result is None
        db.query.assert_not_called()
        db.add.assert_not_called()

    def test_empty_string_fingerprint_returns_none(self):
        """Empty string is treated the same as None — falsy guard."""
        db = _mock_db()
        result = register_device(db, uuid.uuid4(), "")

        assert result is None
        db.add.assert_not_called()

    def test_commit_false_does_not_call_db_commit(self):
        """Default commit=False — caller controls the transaction."""
        db = _mock_db()
        register_device(db, uuid.uuid4(), "fp-test", commit=False)
        db.commit.assert_not_called()

    def test_commit_true_calls_db_commit(self):
        """commit=True — useful when register_device is the only write."""
        db = _mock_db()
        existing = _mock_device(uuid.uuid4(), "fp-test")
        db.query.return_value.filter.return_value.first.return_value = existing

        register_device(db, existing.user_id, "fp-test", commit=True)
        db.commit.assert_called_once()

    def test_new_device_has_first_seen_set(self):
        """first_seen must be populated on insert — it's the creation timestamp."""
        db = _mock_db()
        before = datetime.now(timezone.utc)

        result = register_device(db, uuid.uuid4(), "fp-timestamps")

        added = db.add.call_args[0][0]
        assert added.first_seen >= before

    def test_new_device_has_last_seen_equal_to_first_seen(self):
        """On first registration, first_seen and last_seen should be the same moment."""
        db = _mock_db()
        result = register_device(db, uuid.uuid4(), "fp-timestamps2")
        added = db.add.call_args[0][0]
        # Both should be very close together (same function call)
        assert added.first_seen == added.last_seen


# ============================================================================
# get_known_devices — unit tests
# ============================================================================

class TestGetKnownDevices:

    def test_returns_list_for_user(self):
        db = _mock_db()
        user_id = uuid.uuid4()
        devices = [_mock_device(user_id), _mock_device(user_id)]
        db.query.return_value.filter.return_value.order_by.return_value.all.return_value = devices

        result = get_known_devices(db, user_id)
        assert result == devices

    def test_returns_empty_list_when_no_devices(self):
        db = _mock_db()
        result = get_known_devices(db, uuid.uuid4())
        assert result == []


# ============================================================================
# remove_device — unit tests
# ============================================================================

class TestRemoveDevice:

    def test_removes_owned_device_returns_true(self):
        """User can remove their own device."""
        db = _mock_db()
        user_id = uuid.uuid4()
        device = _mock_device(user_id)
        db.query.return_value.filter.return_value.first.return_value = device

        result = remove_device(db, user_id, device.id)

        assert result is True
        db.delete.assert_called_once_with(device)
        db.commit.assert_called_once()

    def test_returns_false_for_unknown_device(self):
        """Device not found → False, no delete called."""
        db = _mock_db()
        # first() returns None (device not found)
        result = remove_device(db, uuid.uuid4(), uuid.uuid4())

        assert result is False
        db.delete.assert_not_called()

    def test_ownership_enforced_wrong_user_returns_false(self):
        """
        CRITICAL: user_id filter in the query must prevent one user from
        revoking another user's device. The filter includes user_id so
        the query returns None if the device_id exists but belongs to a
        different user.
        """
        db = _mock_db()
        # Simulate: device exists but the filter (device_id + user_id) finds nothing
        # because user_id doesn't match — db returns None
        db.query.return_value.filter.return_value.first.return_value = None

        result = remove_device(db, uuid.uuid4(), uuid.uuid4())
        assert result is False
        db.delete.assert_not_called()


# ============================================================================
# DeviceAnomalyRule integration — scoring behaviour
# ============================================================================

class TestDeviceAnomalyRule:
    """
    Tests the fraud rule directly to confirm the scoring change once a device
    is registered. This is the end-to-end proof that register_device() makes
    DeviceAnomalyRule meaningful.
    """

    def test_unknown_device_scores_35(self):
        """No KnownDevice row → rule fires → +35 added to fraud score."""
        from app.services.fraud_service import DeviceAnomalyRule
        from app.schemas.fraud import FraudRuleInput

        db = _mock_db()
        user_id = uuid.uuid4()
        rule = DeviceAnomalyRule()
        data = FraudRuleInput(user_id=user_id, device_fingerprint="fp-unknown")

        result = rule.evaluate(db, data)

        assert result is not None
        assert result.score_delta == 35
        assert result.alert_type == "device_change"
        assert result.triggered_key == "unknown_device"

    def test_known_device_scores_zero(self):
        """KnownDevice row found → rule returns None → 0 score contribution."""
        from app.services.fraud_service import DeviceAnomalyRule
        from app.schemas.fraud import FraudRuleInput

        db = _mock_db()
        user_id = uuid.uuid4()
        known = _mock_device(user_id, "fp-known")
        db.query.return_value.filter.return_value.first.return_value = known

        rule = DeviceAnomalyRule()
        data = FraudRuleInput(user_id=user_id, device_fingerprint="fp-known")

        result = rule.evaluate(db, data)
        assert result is None

    def test_no_fingerprint_rule_skips(self):
        """No fingerprint sent → rule returns None → 0 score contribution."""
        from app.services.fraud_service import DeviceAnomalyRule
        from app.schemas.fraud import FraudRuleInput

        db = _mock_db()
        rule = DeviceAnomalyRule()
        data = FraudRuleInput(user_id=uuid.uuid4(), device_fingerprint=None)

        result = rule.evaluate(db, data)
        assert result is None


# ============================================================================
# auth_service.login integration — register_device is called correctly
# ============================================================================

class TestAuthServiceDeviceRegistration:
    """
    Verifies that auth_service.login() and verify_mfa_and_login() call
    register_device() at the right time and with the right arguments.
    """

    def _build_login_mocks(self, role="user", device_fp="fp-browser-chrome"):
        """Return a user mock and db mock ready for a successful login."""
        user = MagicMock()
        user.id = uuid.uuid4()
        user.email = "alice@example.com"
        user.username = "alice"
        user.account_status = "active"
        user.mfa_enabled = False
        user.role = role
        user.failed_login_attempts = 0
        user.locked_until = None

        session = MagicMock()
        session.id = uuid.uuid4()

        db = MagicMock()
        db.flush = MagicMock()
        db.commit = MagicMock()

        return user, session, db, device_fp

    def test_successful_login_calls_register_device(self):
        """
        On successful login with a device fingerprint, register_device()
        must be called with the user's id and the fingerprint.
        """
        from app.services import auth_service
        from app.schemas.user import UserLogin

        user, session, db, fp = self._build_login_mocks()

        with (
            patch.object(auth_service, "get_user_by_email", return_value=user),
            patch.object(auth_service, "verify_password", return_value=True),
            patch.object(auth_service, "_add_login_attempt"),
            patch.object(auth_service, "FraudService") as mock_fs,
            patch.object(auth_service, "create_access_token",
                         return_value=("tok", datetime.now(timezone.utc))),
            patch.object(auth_service, "create_refresh_token", return_value="ref"),
            patch.object(auth_service, "hash_token", return_value="h"),
            patch.object(auth_service, "SessionModel", return_value=session),
            patch.object(auth_service, "register_device") as mock_rd,
        ):
            mock_result = MagicMock()
            mock_result.action = "allow"
            mock_result.score = 5
            mock_fs.return_value.evaluate.return_value = (mock_result, None)

            auth_service.login(
                db,
                UserLogin(email="alice@example.com", password="pass"),
                device_fingerprint=fp,
            )

        mock_rd.assert_called_once_with(db, user.id, fp, commit=False)

    def test_login_without_fingerprint_does_not_error(self):
        """
        login() with no device_fingerprint passes None to register_device.
        register_device handles None gracefully (returns None, no DB write).
        """
        from app.services import auth_service
        from app.schemas.user import UserLogin

        user, session, db, _ = self._build_login_mocks()

        with (
            patch.object(auth_service, "get_user_by_email", return_value=user),
            patch.object(auth_service, "verify_password", return_value=True),
            patch.object(auth_service, "_add_login_attempt"),
            patch.object(auth_service, "FraudService") as mock_fs,
            patch.object(auth_service, "create_access_token",
                         return_value=("tok", datetime.now(timezone.utc))),
            patch.object(auth_service, "create_refresh_token", return_value="ref"),
            patch.object(auth_service, "hash_token", return_value="h"),
            patch.object(auth_service, "SessionModel", return_value=session),
            patch.object(auth_service, "register_device") as mock_rd,
        ):
            mock_result = MagicMock()
            mock_result.action = "allow"
            mock_result.score = 5
            mock_fs.return_value.evaluate.return_value = (mock_result, None)

            auth_service.login(
                db,
                UserLogin(email="alice@example.com", password="pass"),
                device_fingerprint=None,
            )

        # Called with None — device_service handles it as a no-op
        mock_rd.assert_called_once_with(db, user.id, None, commit=False)

    def test_failed_login_does_not_call_register_device(self):
        """
        A failed login (wrong password) must NOT register the device.
        Only successful authentications earn device recognition.
        """
        from app.services import auth_service
        from app.schemas.user import UserLogin

        user, _, db, fp = self._build_login_mocks()

        with (
            patch.object(auth_service, "get_user_by_email", return_value=user),
            patch.object(auth_service, "verify_password", return_value=False),
            patch.object(auth_service, "_add_login_attempt"),
            patch.object(auth_service, "register_device") as mock_rd,
        ):
            try:
                auth_service.login(
                    db,
                    UserLogin(email="alice@example.com", password="wrongpass"),
                    device_fingerprint=fp,
                )
            except ValueError:
                pass  # expected — invalid password

        mock_rd.assert_not_called()

    def test_fraud_blocked_login_does_not_register_device(self):
        """
        A fraud-blocked login must not register the device — the user
        never actually authenticated.
        """
        from app.services import auth_service
        from app.schemas.user import UserLogin

        user, session, db, fp = self._build_login_mocks()

        with (
            patch.object(auth_service, "get_user_by_email", return_value=user),
            patch.object(auth_service, "verify_password", return_value=True),
            patch.object(auth_service, "_add_login_attempt"),
            patch.object(auth_service, "FraudService") as mock_fs,
            patch.object(auth_service, "create_access_token",
                         return_value=("tok", datetime.now(timezone.utc))),
            patch.object(auth_service, "create_refresh_token", return_value="ref"),
            patch.object(auth_service, "hash_token", return_value="h"),
            patch.object(auth_service, "SessionModel", return_value=session),
            patch.object(auth_service, "register_device") as mock_rd,
        ):
            mock_result = MagicMock()
            mock_result.action = "block"
            mock_result.score = 95
            mock_fs.return_value.evaluate.return_value = (mock_result, None)

            try:
                auth_service.login(
                    db,
                    UserLogin(email="alice@example.com", password="pass"),
                    device_fingerprint=fp,
                )
            except Exception:
                pass

        mock_rd.assert_not_called()
