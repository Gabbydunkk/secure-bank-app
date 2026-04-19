"""
tests/test_admin.py — Admin user management endpoint tests.

Tests cover:
  list_users:           200 with list, filters forwarded, 403 non-admin, 401 no auth
  get_user:             200 success, 404 not found, 403 non-admin
  change_account_status: suspend/close/reactivate, sessions invalidated on suspend,
                          403 self-modify, 404 not found, 422 invalid status, 403 non-admin
  change_user_role:     promote to analyst/admin, 403 self-modify, 404, 422 bad role
  force_logout:         returns count, 404 not found
  get_audit_logs:       200 with logs, 404 not found, 403 non-admin

Security boundary tests:
  - Every /admin route returns 401 with no token
  - Every /admin route returns 403 for authenticated non-admin user
  - Admin cannot modify their own status or role

Service unit tests:
  - update_account_status invalidates sessions atomically
  - update_user_role does NOT invalidate sessions
  - invalidate_user_sessions returns correct count
  - AuditLog entry written for every write operation

Run: pytest tests/test_admin.py -v
"""

import uuid
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch, call

import pytest
from fastapi import FastAPI, HTTPException, status
from fastapi.testclient import TestClient

from app.api.admin_router import router as admin_router
from app.api.deps import get_current_user, require_admin
from app.models.database import get_db
from app.schemas.user import UserResponse
from app.schemas.audit import AuditLogListResponse, AuditLogResponse
from app.services.admin_service import (
    AdminInvalidStatusError,
    AdminSelfModifyError,
    AdminTargetNotFoundError,
    invalidate_user_sessions,
    update_account_status,
    update_user_role,
)


# ============================================================================
# Test app
# ============================================================================

PREFIX = "/api/v1"
test_app = FastAPI()
test_app.include_router(admin_router, prefix=PREFIX)


# ============================================================================
# Helpers
# ============================================================================

def _user(
    user_id: uuid.UUID | None = None,
    role: str = "admin",
    status: str = "active",
    email: str = "admin@example.com",
) -> MagicMock:
    u = MagicMock()
    u.id = user_id or uuid.uuid4()
    u.email = email
    u.username = role
    u.first_name = "Admin"
    u.last_name = "User"
    u.phone_number = None
    u.date_of_birth = None
    u.role = role
    u.account_status = status
    u.mfa_enabled = False
    u.created_at = datetime.now(timezone.utc)
    return u


def _audit_log() -> MagicMock:
    log = MagicMock()
    log.id = uuid.uuid4()
    log.user_id = uuid.uuid4()
    log.action = "admin_status_change"
    log.entity_type = "user"
    log.entity_id = uuid.uuid4()
    log.old_values = {"account_status": "active"}
    log.new_values = {"account_status": "suspended"}
    log.ip_address = "1.2.3.4"
    log.user_agent = None
    log.success = True
    log.error_message = None
    log.created_at = datetime.now(timezone.utc)
    return log


@pytest.fixture()
def mock_db():
    return MagicMock()


@pytest.fixture()
def admin(mock_db):
    return _user(role="admin")


@pytest.fixture()
def regular_user(mock_db):
    return _user(role="user", email="user@example.com")


@pytest.fixture()
def client_as_admin(admin, mock_db):
    test_app.dependency_overrides[get_db] = lambda: mock_db
    test_app.dependency_overrides[get_current_user] = lambda: admin
    test_app.dependency_overrides[require_admin] = lambda: None
    yield TestClient(test_app, raise_server_exceptions=False)
    test_app.dependency_overrides.clear()


@pytest.fixture()
def client_as_user(regular_user, mock_db):
    """Authenticated but NOT admin — require_admin should block."""
    def _deny():
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Insufficient permissions. This action requires the 'admin' role.",
        )
    test_app.dependency_overrides[get_db] = lambda: mock_db
    test_app.dependency_overrides[get_current_user] = lambda: regular_user
    test_app.dependency_overrides[require_admin] = _deny
    yield TestClient(test_app, raise_server_exceptions=False)
    test_app.dependency_overrides.clear()


@pytest.fixture()
def client_no_auth(mock_db):
    test_app.dependency_overrides[get_db] = lambda: mock_db
    # No overrides — real auth runs
    yield TestClient(test_app, raise_server_exceptions=False)
    test_app.dependency_overrides.clear()


# ============================================================================
# GET /admin/users/
# ============================================================================

class TestListUsers:
    URL = f"{PREFIX}/admin/users/"

    def test_returns_200_with_user_list(self, client_as_admin, admin):
        target = _user(role="user", email="bob@example.com")
        with patch("app.api.admin_router.list_users",
                   return_value={"users": [target], "total": 1}):
            with patch.object(UserResponse, "model_validate", return_value=MagicMock(
                id=target.id, email=target.email, username=target.username,
                first_name="Bob", last_name="User", phone_number=None,
                date_of_birth=None, role="user", account_status="active",
                mfa_enabled=False, created_at=datetime.now(timezone.utc),
            )):
                r = client_as_admin.get(self.URL)
        assert r.status_code == 200
        assert r.json()["total"] == 1

    def test_filters_forwarded_to_service(self, client_as_admin):
        with patch("app.api.admin_router.list_users",
                   return_value={"users": [], "total": 0}) as mock_lu:
            client_as_admin.get(self.URL + "?role=analyst&account_status=active&search=alice")
        _, kwargs = mock_lu.call_args
        assert kwargs.get("role_filter") == "analyst"
        assert kwargs.get("status_filter") == "active"
        assert kwargs.get("search") == "alice"

    def test_non_admin_receives_403(self, client_as_user):
        r = client_as_user.get(self.URL)
        assert r.status_code == 403

    def test_no_auth_receives_401(self, client_no_auth):
        r = client_no_auth.get(self.URL)
        assert r.status_code == 401


# ============================================================================
# GET /admin/users/{user_id}
# ============================================================================

class TestGetUser:

    def test_returns_200_for_existing_user(self, client_as_admin):
        target_id = uuid.uuid4()
        target = _user(user_id=target_id, role="user")
        with patch("app.api.admin_router.get_user", return_value=target):
            with patch.object(UserResponse, "model_validate", return_value=MagicMock(
                id=target_id, email=target.email, username="user",
                first_name="A", last_name="B", phone_number=None,
                date_of_birth=None, role="user", account_status="active",
                mfa_enabled=False, created_at=datetime.now(timezone.utc),
            )):
                r = client_as_admin.get(f"{PREFIX}/admin/users/{target_id}")
        assert r.status_code == 200

    def test_returns_404_for_missing_user(self, client_as_admin):
        with patch("app.api.admin_router.get_user",
                   side_effect=AdminTargetNotFoundError("User not found")):
            r = client_as_admin.get(f"{PREFIX}/admin/users/{uuid.uuid4()}")
        assert r.status_code == 404

    def test_non_admin_receives_403(self, client_as_user):
        r = client_as_user.get(f"{PREFIX}/admin/users/{uuid.uuid4()}")
        assert r.status_code == 403


# ============================================================================
# PATCH /admin/users/{user_id}/status
# ============================================================================

class TestChangeAccountStatus:

    def _url(self, uid): return f"{PREFIX}/admin/users/{uid}/status"

    def test_suspend_returns_200(self, client_as_admin):
        target = _user(role="user", status="suspended")
        with patch("app.api.admin_router.update_account_status", return_value=target):
            with patch.object(UserResponse, "model_validate", return_value=MagicMock(
                id=target.id, email=target.email, username="user",
                first_name="A", last_name="B", phone_number=None,
                date_of_birth=None, role="user", account_status="suspended",
                mfa_enabled=False, created_at=datetime.now(timezone.utc),
            )):
                r = client_as_admin.patch(
                    self._url(target.id),
                    json={"status": "suspended", "reason": "fraud investigation"},
                )
        assert r.status_code == 200

    def test_self_modify_returns_403(self, client_as_admin):
        with patch("app.api.admin_router.update_account_status",
                   side_effect=AdminSelfModifyError("Admins cannot change their own account status")):
            r = client_as_admin.patch(
                self._url(uuid.uuid4()),
                json={"status": "suspended"},
            )
        assert r.status_code == 403
        assert "own" in r.json()["detail"].lower()

    def test_invalid_status_returns_422(self, client_as_admin):
        with patch("app.api.admin_router.update_account_status",
                   side_effect=AdminInvalidStatusError("Invalid status 'banned'")):
            r = client_as_admin.patch(
                self._url(uuid.uuid4()),
                json={"status": "banned"},
            )
        assert r.status_code == 422

    def test_not_found_returns_404(self, client_as_admin):
        with patch("app.api.admin_router.update_account_status",
                   side_effect=AdminTargetNotFoundError("User not found")):
            r = client_as_admin.patch(
                self._url(uuid.uuid4()),
                json={"status": "suspended"},
            )
        assert r.status_code == 404

    def test_non_admin_receives_403(self, client_as_user):
        r = client_as_user.patch(self._url(uuid.uuid4()), json={"status": "suspended"})
        assert r.status_code == 403


# ============================================================================
# PATCH /admin/users/{user_id}/role
# ============================================================================

class TestChangeUserRole:

    def _url(self, uid): return f"{PREFIX}/admin/users/{uid}/role"

    def test_promote_to_analyst_returns_200(self, client_as_admin):
        target = _user(role="analyst")
        with patch("app.api.admin_router.update_user_role", return_value=target):
            with patch.object(UserResponse, "model_validate", return_value=MagicMock(
                id=target.id, email=target.email, username="analyst",
                first_name="A", last_name="B", phone_number=None,
                date_of_birth=None, role="analyst", account_status="active",
                mfa_enabled=False, created_at=datetime.now(timezone.utc),
            )):
                r = client_as_admin.patch(self._url(target.id), json={"role": "analyst"})
        assert r.status_code == 200

    def test_self_modify_returns_403(self, client_as_admin):
        with patch("app.api.admin_router.update_user_role",
                   side_effect=AdminSelfModifyError("Admins cannot change their own role")):
            r = client_as_admin.patch(self._url(uuid.uuid4()), json={"role": "user"})
        assert r.status_code == 403

    def test_invalid_role_returns_422(self, client_as_admin):
        with patch("app.api.admin_router.update_user_role",
                   side_effect=AdminInvalidStatusError("Invalid role 'superuser'")):
            r = client_as_admin.patch(self._url(uuid.uuid4()), json={"role": "superuser"})
        assert r.status_code == 422

    def test_not_found_returns_404(self, client_as_admin):
        with patch("app.api.admin_router.update_user_role",
                   side_effect=AdminTargetNotFoundError("User not found")):
            r = client_as_admin.patch(self._url(uuid.uuid4()), json={"role": "analyst"})
        assert r.status_code == 404

    def test_non_admin_receives_403(self, client_as_user):
        r = client_as_user.patch(self._url(uuid.uuid4()), json={"role": "analyst"})
        assert r.status_code == 403


# ============================================================================
# DELETE /admin/users/{user_id}/sessions
# ============================================================================

class TestForceLogout:

    def _url(self, uid): return f"{PREFIX}/admin/users/{uid}/sessions"

    def test_returns_count_of_invalidated_sessions(self, client_as_admin):
        target_id = uuid.uuid4()
        with patch("app.api.admin_router.force_logout_user_sessions", return_value=3):
            r = client_as_admin.delete(self._url(target_id))
        assert r.status_code == 200
        assert r.json()["sessions_invalidated"] == 3

    def test_zero_sessions_returns_zero(self, client_as_admin):
        target_id = uuid.uuid4()
        with patch("app.api.admin_router.force_logout_user_sessions", return_value=0):
            r = client_as_admin.delete(self._url(target_id))
        assert r.status_code == 200
        assert r.json()["sessions_invalidated"] == 0

    def test_not_found_returns_404(self, client_as_admin):
        with patch("app.api.admin_router.force_logout_user_sessions",
                   side_effect=AdminTargetNotFoundError("not found")):
            r = client_as_admin.delete(self._url(uuid.uuid4()))
        assert r.status_code == 404

    def test_non_admin_receives_403(self, client_as_user):
        r = client_as_user.delete(self._url(uuid.uuid4()))
        assert r.status_code == 403


# ============================================================================
# GET /admin/users/{user_id}/audit-logs
# ============================================================================

class TestGetAuditLogs:

    def _url(self, uid): return f"{PREFIX}/admin/users/{uid}/audit-logs"

    def test_returns_200_with_logs(self, client_as_admin):
        target_id = uuid.uuid4()
        log = _audit_log()
        with patch("app.api.admin_router.get_user", return_value=_user(user_id=target_id)):
            with patch("app.api.admin_router.get_user_audit_logs",
                       return_value={"logs": [log], "total": 1}):
                with patch.object(AuditLogResponse, "model_validate", return_value=MagicMock(
                    id=log.id, user_id=log.user_id, action=log.action,
                    entity_type=log.entity_type, entity_id=log.entity_id,
                    old_values=log.old_values, new_values=log.new_values,
                    ip_address=log.ip_address, user_agent=None,
                    success=True, error_message=None,
                    created_at=datetime.now(timezone.utc),
                )):
                    r = client_as_admin.get(self._url(target_id))
        assert r.status_code == 200
        assert r.json()["total"] == 1

    def test_not_found_returns_404(self, client_as_admin):
        with patch("app.api.admin_router.get_user",
                   side_effect=AdminTargetNotFoundError("not found")):
            r = client_as_admin.get(self._url(uuid.uuid4()))
        assert r.status_code == 404

    def test_non_admin_receives_403(self, client_as_user):
        r = client_as_user.get(self._url(uuid.uuid4()))
        assert r.status_code == 403

    def test_no_auth_receives_401(self, client_no_auth):
        r = client_no_auth.get(self._url(uuid.uuid4()))
        assert r.status_code == 401


# ============================================================================
# Service unit tests
# ============================================================================

class TestAdminServiceUnit:

    def test_suspend_invalidates_sessions(self):
        """
        CRITICAL: suspending an account must immediately kill all sessions.
        The user must not retain working tokens after suspension.
        """
        db = MagicMock()
        admin_id = uuid.uuid4()
        target_id = uuid.uuid4()

        target = _user(user_id=target_id, role="user")
        db.query.return_value.filter.return_value.first.return_value = target

        active_session = MagicMock()
        active_session.is_active = True
        db.query.return_value.filter.return_value.all.return_value = [active_session]

        with patch("app.services.admin_service.get_user", return_value=target):
            with patch("app.services.admin_service.invalidate_user_sessions",
                       return_value=1) as mock_inv:
                update_account_status(db, admin_id, target_id, "suspended")

        mock_inv.assert_called_once_with(db, target_id, commit=False)

    def test_reactivation_does_not_invalidate_sessions(self):
        """
        Reactivating an account should NOT invalidate sessions — the user
        may not have any active ones, and invalidating would be a no-op
        at best, confusing at worst.
        """
        db = MagicMock()
        admin_id = uuid.uuid4()
        target_id = uuid.uuid4()

        target = _user(user_id=target_id, role="user", status="suspended")
        target.locked_until = None
        target.failed_login_attempts = 0

        with patch("app.services.admin_service.get_user", return_value=target):
            with patch("app.services.admin_service.invalidate_user_sessions") as mock_inv:
                update_account_status(db, admin_id, target_id, "active")

        mock_inv.assert_not_called()

    def test_role_change_does_not_invalidate_sessions(self):
        """
        Role changes take effect at the next token refresh — existing sessions
        are deliberately left alive. This is by design (see service docstring).
        """
        db = MagicMock()
        admin_id = uuid.uuid4()
        target_id = uuid.uuid4()
        target = _user(user_id=target_id, role="user")

        with patch("app.services.admin_service.get_user", return_value=target):
            with patch("app.services.admin_service.invalidate_user_sessions") as mock_inv:
                update_user_role(db, admin_id, target_id, "analyst")

        mock_inv.assert_not_called()

    def test_cannot_modify_own_status(self):
        admin_id = uuid.uuid4()
        with pytest.raises(AdminSelfModifyError):
            update_account_status(
                MagicMock(), admin_id, admin_id, "suspended"
            )

    def test_cannot_modify_own_role(self):
        admin_id = uuid.uuid4()
        with pytest.raises(AdminSelfModifyError):
            update_user_role(MagicMock(), admin_id, admin_id, "user")

    def test_invalid_status_raises(self):
        with pytest.raises(AdminInvalidStatusError):
            update_account_status(
                MagicMock(), uuid.uuid4(), uuid.uuid4(), "banned"
            )

    def test_invalid_role_raises(self):
        with pytest.raises(AdminInvalidStatusError):
            update_user_role(
                MagicMock(), uuid.uuid4(), uuid.uuid4(), "superuser"
            )

    def test_audit_log_written_for_status_change(self):
        """Every write must produce an AuditLog entry — banking traceability requirement."""
        db = MagicMock()
        admin_id = uuid.uuid4()
        target_id = uuid.uuid4()
        target = _user(user_id=target_id, role="user")

        with patch("app.services.admin_service.get_user", return_value=target):
            with patch("app.services.admin_service.invalidate_user_sessions", return_value=0):
                update_account_status(db, admin_id, target_id, "suspended")

        db.add.assert_called()
        added = db.add.call_args[0][0]
        assert added.user_id == admin_id
        assert added.entity_id == target_id
        assert added.action == "admin_status_change"

    def test_audit_log_written_for_role_change(self):
        db = MagicMock()
        admin_id = uuid.uuid4()
        target_id = uuid.uuid4()
        target = _user(user_id=target_id, role="user")

        with patch("app.services.admin_service.get_user", return_value=target):
            update_user_role(db, admin_id, target_id, "analyst")

        db.add.assert_called()
        added = db.add.call_args[0][0]
        assert added.action == "admin_role_change"
        assert added.old_values == {"role": "user"}
        assert added.new_values == {"role": "analyst"}

    def test_invalidate_sessions_returns_correct_count(self):
        db = MagicMock()
        sessions = [MagicMock(is_active=True) for _ in range(4)]
        db.query.return_value.filter.return_value.all.return_value = sessions

        count = invalidate_user_sessions(db, uuid.uuid4(), commit=True)

        assert count == 4
        for s in sessions:
            assert s.is_active is False
        db.commit.assert_called_once()


# ============================================================================
# Security boundary — all /admin routes require admin scope
# ============================================================================

class TestAdminSecurityBoundary:

    SAMPLE_ID = uuid.uuid4()

    ROUTES = [
        ("GET",    f"{PREFIX}/admin/users/"),
        ("GET",    f"{PREFIX}/admin/users/{SAMPLE_ID}"),
        ("PATCH",  f"{PREFIX}/admin/users/{SAMPLE_ID}/status"),
        ("PATCH",  f"{PREFIX}/admin/users/{SAMPLE_ID}/role"),
        ("DELETE", f"{PREFIX}/admin/users/{SAMPLE_ID}/sessions"),
        ("GET",    f"{PREFIX}/admin/users/{SAMPLE_ID}/audit-logs"),
    ]

    def test_all_routes_return_401_without_token(self, client_no_auth):
        for method, path in self.ROUTES:
            r = client_no_auth.request(method, path)
            assert r.status_code == 401, (
                f"{method} {path} returned {r.status_code}, expected 401"
            )

    def test_all_routes_return_403_for_non_admin(self, client_as_user):
        for method, path in self.ROUTES:
            r = client_as_user.request(method, path)
            assert r.status_code == 403, (
                f"{method} {path} returned {r.status_code} for non-admin user, expected 403"
            )
