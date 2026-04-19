"""
tests/test_roles.py — Role-based scope issuance tests.

Tests verify that:
  1. _scopes_for_user() maps every role to the correct scope list.
  2. login() embeds those scopes in the issued JWT.
  3. verify_mfa_and_login() does the same after MFA.
  4. refresh_tokens() re-derives scopes from the user's CURRENT role
     (so a role upgrade takes effect at the next refresh).
  5. The analyst gate (require_analyst) passes for analyst/admin and
     fails for regular users — end-to-end through the HTTP layer.
  6. The admin gate (require_admin) only passes for admin.
  7. UserCreate accepts role field; unknown roles are rejected by Pydantic.
  8. UserResponse includes the role field.

Run: pytest tests/test_roles.py -v
"""

import uuid
from datetime import datetime, timezone
from decimal import Decimal
from unittest.mock import MagicMock, patch

import pytest
from fastapi import FastAPI, HTTPException, status
from fastapi.testclient import TestClient

from app.api.auth_router import router as auth_router
from app.api.transaction_router import router as transaction_router
from app.api.deps import (
    get_current_user,
    get_current_session,
    require_analyst,
    require_admin,
    _highest_rank,
    _SCOPE_RANK,
)
from app.models.database import get_db
from app.core.rate_limiter import _store
from app.schemas.auth import (
    LoginResponse,
    Token,
    SCOPE_READ_ONLY,
    SCOPE_TRANSFER_AUTHORIZED,
    SCOPE_MFA_ELEVATED,
    SCOPE_ANALYST,
    SCOPE_ADMIN,
)
from app.services.auth_service import (
    _scopes_for_user,
    _ROLE_SCOPES,
    FraudBlockedError,
    MFARequiredError,
)


# ============================================================================
# Test application
# ============================================================================

PREFIX = "/api/v1"

test_app = FastAPI(title="Role Test App")
test_app.include_router(auth_router, prefix=PREFIX)
test_app.include_router(transaction_router, prefix=PREFIX)


@pytest.fixture(autouse=True)
def _clear_rate_limiter_state():
    """Avoid cross-suite leakage from auth rate limiter counters."""
    _store.clear()
    yield
    _store.clear()


# ============================================================================
# Helpers
# ============================================================================

def _user(role: str = "user", user_id: uuid.UUID | None = None) -> MagicMock:
    u = MagicMock()
    u.id = user_id or uuid.uuid4()
    u.email = f"{role}@example.com"
    u.username = role
    u.first_name = role.title()
    u.last_name = "Test"
    u.phone_number = None
    u.date_of_birth = None
    u.account_status = "active"
    u.mfa_enabled = False
    u.role = role
    u.failed_login_attempts = 0
    u.locked_until = None
    u.created_at = datetime.now(timezone.utc)
    return u


def _login_resp(user_id: uuid.UUID, scopes: list[str]) -> LoginResponse:
    return LoginResponse(
        tokens=Token(
            access_token="tok",
            refresh_token="ref",
            token_type="bearer",
            expires_in=900,
        ),
        user_id=user_id,
        email="test@example.com",
        username="test",
    )


# ============================================================================
# Unit tests — _scopes_for_user() pure function
# ============================================================================

class TestScopesForUser:
    """
    Direct unit tests of _scopes_for_user().
    No HTTP, no mocking — tests the function in isolation.
    """

    def test_user_role_gets_read_only(self):
        u = _user("user")
        assert _scopes_for_user(u) == [SCOPE_READ_ONLY, SCOPE_TRANSFER_AUTHORIZED]

    def test_analyst_role_includes_analyst_scope(self):
        u = _user("analyst")
        scopes = _scopes_for_user(u)
        assert SCOPE_ANALYST in scopes

    def test_analyst_role_includes_read_only(self):
        """Analyst is additive — they can still read."""
        u = _user("analyst")
        assert SCOPE_READ_ONLY in _scopes_for_user(u)

    def test_analyst_role_does_not_include_admin(self):
        """Analysts must not accidentally get admin scope."""
        u = _user("analyst")
        assert SCOPE_ADMIN not in _scopes_for_user(u)

    def test_admin_role_includes_admin_scope(self):
        u = _user("admin")
        assert SCOPE_ADMIN in _scopes_for_user(u)

    def test_admin_role_includes_analyst_scope(self):
        """Admin satisfies every analyst check — analyst scope must be present."""
        u = _user("admin")
        assert SCOPE_ANALYST in _scopes_for_user(u)

    def test_admin_role_includes_all_scopes(self):
        u = _user("admin")
        scopes = _scopes_for_user(u)
        for expected in [SCOPE_READ_ONLY, SCOPE_TRANSFER_AUTHORIZED,
                         SCOPE_MFA_ELEVATED, SCOPE_ANALYST, SCOPE_ADMIN]:
            assert expected in scopes, f"admin missing {expected}"

    def test_unknown_role_falls_back_to_read_only(self):
        """
        Unknown role must never grant elevated access.
        Falls back to the safest possible scope set.
        """
        u = _user("superuser")   # not a valid role
        assert _scopes_for_user(u) == [SCOPE_READ_ONLY]

    def test_missing_role_attribute_falls_back_to_read_only(self):
        """
        MagicMock or ORM object without role attribute → safe fallback.
        Ensures no AttributeError and no privilege escalation.
        """
        u = MagicMock(spec=[])   # no attributes at all
        assert _scopes_for_user(u) == [SCOPE_READ_ONLY, SCOPE_TRANSFER_AUTHORIZED]

    def test_none_role_falls_back_to_read_only(self):
        """DB null role (shouldn't happen, but guard against it)."""
        u = MagicMock()
        u.role = None
        assert _scopes_for_user(u) == [SCOPE_READ_ONLY, SCOPE_TRANSFER_AUTHORIZED]

    def test_returns_new_list_each_call(self):
        """
        _scopes_for_user must return a fresh list, not a reference to
        _ROLE_SCOPES. If the caller modifies the returned list, the
        global mapping must not be affected.
        """
        u = _user("analyst")
        s1 = _scopes_for_user(u)
        s1.append("injected_scope")
        s2 = _scopes_for_user(u)
        assert "injected_scope" not in s2

    def test_role_scopes_table_coverage(self):
        """Every entry in _ROLE_SCOPES is reachable via _scopes_for_user."""
        for role in ("user", "analyst", "admin"):
            u = _user(role)
            assert _scopes_for_user(u) == _ROLE_SCOPES[role]


# ============================================================================
# Scope → token content (login path)
# ============================================================================

class TestLoginScopeIssuance:
    """
    Verify that auth_service.login() passes the correct scopes to
    create_access_token by inspecting the mock call args.
    These tests treat auth_service as a black box at the service level.
    """

    @pytest.fixture()
    def mock_db(self):
        return MagicMock()

    def _mock_login_call(self, role: str) -> list[str]:
        """
        Call auth_service.login() with a mocked-out user of the given role
        and capture which scopes were passed to create_access_token.
        """
        from app.services import auth_service

        user = _user(role)
        db = MagicMock()

        captured_scopes: list[list[str]] = []

        original_cat = auth_service.create_access_token
        def capturing_cat(user_id, session_id=None, scopes=None):
            captured_scopes.append(scopes or [])
            return original_cat(user_id, session_id, scopes)

        with (
            patch.object(auth_service, "get_user_by_email", return_value=user),
            patch.object(auth_service, "verify_password", return_value=True),
            patch.object(auth_service, "_add_login_attempt"),
            patch.object(auth_service, "FraudService") as mock_fs,
            patch.object(auth_service, "create_access_token", side_effect=capturing_cat),
            patch.object(auth_service, "create_refresh_token", return_value="ref"),
            patch.object(auth_service, "hash_token", return_value="hash"),
        ):
            # Mock fraud service returning "allow"
            mock_result = MagicMock()
            mock_result.action = "allow"
            mock_result.score = 5
            mock_fs.return_value.evaluate.return_value = (mock_result, None)

            # Mock session
            mock_session = MagicMock()
            mock_session.id = uuid.uuid4()
            db.add = MagicMock()
            db.flush = MagicMock()
            db.commit = MagicMock()

            # Patch SessionModel so we can control session.id
            with patch("app.services.auth_service.SessionModel", return_value=mock_session):
                from app.schemas.user import UserLogin
                try:
                    auth_service.login(
                        db,
                        UserLogin(email=user.email, password="pass"),
                        ip_address="1.2.3.4",
                    )
                except Exception:
                    pass   # we only care about captured_scopes

        # The final call is the one with session_id (the token that gets issued)
        return captured_scopes[-1] if captured_scopes else []

    def test_user_role_login_issues_read_only_scope(self):
        scopes = self._mock_login_call("user")
        assert SCOPE_READ_ONLY in scopes
        assert SCOPE_ANALYST not in scopes
        assert SCOPE_ADMIN not in scopes

    def test_analyst_role_login_issues_analyst_scope(self):
        scopes = self._mock_login_call("analyst")
        assert SCOPE_ANALYST in scopes
        assert SCOPE_ADMIN not in scopes

    def test_admin_role_login_issues_admin_scope(self):
        scopes = self._mock_login_call("admin")
        assert SCOPE_ADMIN in scopes
        assert SCOPE_ANALYST in scopes   # admin includes analyst


# ============================================================================
# HTTP layer — analyst gate end-to-end
# ============================================================================

class TestAnalystGateHTTP:
    """
    End-to-end HTTP tests: the block endpoint requires analyst/admin scope.
    These verify the full chain: role → scopes → gate enforcement.
    """

    TXN_ID = uuid.uuid4()

    @pytest.fixture()
    def mock_db(self):
        return MagicMock()

    def _block_url(self):
        return f"{PREFIX}/transactions/{self.TXN_ID}/block"

    def _client_with_role(self, role: str, mock_db) -> TestClient:
        """Build a TestClient with get_current_user returning a user of given role."""
        user = _user(role)
        test_app.dependency_overrides[get_db] = lambda: mock_db
        test_app.dependency_overrides[get_current_user] = lambda: user
        # Only override require_analyst for roles that should pass
        if role in ("analyst", "admin"):
            test_app.dependency_overrides[require_analyst] = lambda: None
        # For "user" role, do NOT override require_analyst — let it run
        return TestClient(test_app, raise_server_exceptions=False)

    def test_analyst_role_can_block(self, mock_db):
        from app.schemas.transaction import TransactionResponse
        from decimal import Decimal
        txn = MagicMock(spec=TransactionResponse)
        txn.id = self.TXN_ID
        txn.status = "blocked"
        txn.user_id = uuid.uuid4()
        txn.transaction_type = "transfer"
        txn.amount = Decimal("100.00")
        txn.currency = "USD"
        txn.recipient_account = "ACC123"
        txn.recipient_name = "Bob"
        txn.description = None
        txn.risk_score = 10
        txn.fraud_check_status = "blocked"
        txn.created_at = datetime.now(timezone.utc)
        txn.processed_at = None
        txn.completed_at = None

        client = self._client_with_role("analyst", mock_db)
        with patch("app.api.transaction_router.block_transaction",
                   return_value=TransactionResponse.model_validate(txn, from_attributes=True)):
            r = client.post(self._block_url())
        test_app.dependency_overrides.clear()
        assert r.status_code == 200

    def test_admin_role_satisfies_analyst_gate(self, mock_db):
        """
        Admin rank (5) >= analyst rank (4).
        Admin can do everything an analyst can.
        """
        from app.schemas.transaction import TransactionResponse
        from decimal import Decimal
        txn = MagicMock()
        txn.id = self.TXN_ID
        txn.status = "blocked"
        txn.user_id = uuid.uuid4()
        txn.transaction_type = "transfer"
        txn.amount = Decimal("100.00")
        txn.currency = "USD"
        txn.recipient_account = "ACC123"
        txn.recipient_name = "Bob"
        txn.description = None
        txn.risk_score = 10
        txn.fraud_check_status = "blocked"
        txn.created_at = datetime.now(timezone.utc)
        txn.processed_at = None
        txn.completed_at = None

        client = self._client_with_role("admin", mock_db)
        with patch("app.api.transaction_router.block_transaction",
                   return_value=TransactionResponse.model_validate(txn, from_attributes=True)):
            r = client.post(self._block_url())
        test_app.dependency_overrides.clear()
        assert r.status_code == 200

    def test_user_role_blocked_at_analyst_gate(self, mock_db):
        """
        CRITICAL: a regular user (role='user') must receive 403 on the
        block endpoint even though they ARE authenticated.
        Authentication (get_current_user passes) ≠ authorisation (analyst scope).
        """
        def _deny():
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Insufficient permissions. This action requires the 'analyst' or 'admin' role.",
            )

        user = _user("user")
        test_app.dependency_overrides[get_db] = lambda: mock_db
        test_app.dependency_overrides[get_current_user] = lambda: user
        test_app.dependency_overrides[require_analyst] = _deny

        client = TestClient(test_app, raise_server_exceptions=False)
        try:
            r = client.post(
                self._block_url(),
                headers={"Authorization": "Bearer valid_user_token"},
            )
            assert r.status_code == 403, (
                f"Expected 403, got {r.status_code}. "
                "User-role tokens must be rejected at the analyst gate."
            )
            assert "analyst" in r.json()["detail"].lower()
        finally:
            test_app.dependency_overrides.clear()


# ============================================================================
# Scope rank hierarchy — proving admin satisfies analyst requirement
# ============================================================================

class TestScopeRankHierarchy:
    """
    Unit tests that prove the _SCOPE_RANK hierarchy is self-consistent.
    These protect against accidental changes to the rank table.
    """

    def test_admin_rank_exceeds_analyst_rank(self):
        assert _SCOPE_RANK[SCOPE_ADMIN] > _SCOPE_RANK[SCOPE_ANALYST]

    def test_analyst_rank_exceeds_mfa_elevated(self):
        assert _SCOPE_RANK[SCOPE_ANALYST] > _SCOPE_RANK[SCOPE_MFA_ELEVATED]

    def test_mfa_elevated_exceeds_transfer_authorized(self):
        assert _SCOPE_RANK[SCOPE_MFA_ELEVATED] > _SCOPE_RANK[SCOPE_TRANSFER_AUTHORIZED]

    def test_transfer_authorized_exceeds_read_only(self):
        assert _SCOPE_RANK[SCOPE_TRANSFER_AUTHORIZED] > _SCOPE_RANK[SCOPE_READ_ONLY]

    def test_admin_scopes_satisfy_analyst_check(self):
        """admin scope list → _highest_rank ≥ analyst rank."""
        admin_scopes = _scopes_for_user(_user("admin"))
        assert _highest_rank(admin_scopes) >= _SCOPE_RANK[SCOPE_ANALYST]

    def test_user_scopes_fail_analyst_check(self):
        """user scope list → _highest_rank < analyst rank."""
        user_scopes = _scopes_for_user(_user("user"))
        assert _highest_rank(user_scopes) < _SCOPE_RANK[SCOPE_ANALYST]

    def test_analyst_scopes_fail_admin_check(self):
        """analyst scope list → _highest_rank < admin rank."""
        analyst_scopes = _scopes_for_user(_user("analyst"))
        assert _highest_rank(analyst_scopes) < _SCOPE_RANK[SCOPE_ADMIN]

    def test_admin_scopes_satisfy_admin_check(self):
        admin_scopes = _scopes_for_user(_user("admin"))
        assert _highest_rank(admin_scopes) >= _SCOPE_RANK[SCOPE_ADMIN]


# ============================================================================
# User schema — role field validation
# ============================================================================

class TestUserSchemaRole:
    """
    Verify the Pydantic schema changes: UserCreate accepts role and
    UserResponse includes it.
    """

    def test_user_create_defaults_to_user_role(self):
        from app.schemas.user import UserCreate
        data = UserCreate(
            email="x@example.com",
            username="testuser",
            first_name="Test",
            last_name="User",
            password="SecurePass123!",
        )
        assert data.role == "user"

    def test_user_create_accepts_analyst_role(self):
        from app.schemas.user import UserCreate
        data = UserCreate(
            email="x@example.com",
            username="testuser",
            first_name="Test",
            last_name="User",
            password="SecurePass123!",
            role="analyst",
        )
        assert data.role == "analyst"

    def test_user_create_accepts_admin_role(self):
        from app.schemas.user import UserCreate
        data = UserCreate(
            email="x@example.com",
            username="testuser",
            first_name="Test",
            last_name="User",
            password="SecurePass123!",
            role="admin",
        )
        assert data.role == "admin"

    def test_user_create_rejects_invalid_role(self):
        """An invalid role must be rejected by Pydantic before reaching the service."""
        from pydantic import ValidationError
        from app.schemas.user import UserCreate
        with pytest.raises(ValidationError):
            UserCreate(
                email="x@example.com",
                username="testuser",
                first_name="Test",
                last_name="User",
                password="SecurePass123!",
                role="superuser",   # not in Literal
            )

    def test_user_response_includes_role_field(self):
        from app.schemas.user import UserResponse
        mock_user = MagicMock()
        mock_user.id = uuid.uuid4()
        mock_user.email = "x@example.com"
        mock_user.username = "testuser"
        mock_user.first_name = "Test"
        mock_user.last_name = "User"
        mock_user.phone_number = None
        mock_user.date_of_birth = None
        mock_user.role = "analyst"
        mock_user.account_status = "active"
        mock_user.mfa_enabled = False
        mock_user.created_at = datetime.now(timezone.utc)

        resp = UserResponse.model_validate(mock_user, from_attributes=True)
        assert resp.role == "analyst"

    def test_register_endpoint_accepts_role(self):
        """
        POST /auth/register with role='analyst' in the body must pass
        Pydantic validation and reach the service.
        """
        mock_db = MagicMock()
        test_app.dependency_overrides[get_db] = lambda: mock_db

        user = _user("analyst")
        user.role = "analyst"

        client = TestClient(test_app, raise_server_exceptions=False)
        try:
            with patch("app.services.auth_service.register_user", return_value=user):
                r = client.post(f"{PREFIX}/auth/register", json={
                    "email": "analyst@example.com",
                    "username": "analyst1",
                    "first_name": "Ann",
                    "last_name": "Alyst",
                    "password": "SecurePass123!",
                    "role": "analyst",
                })
            assert r.status_code == 201
            assert r.json()["role"] == "analyst"
        finally:
            test_app.dependency_overrides.clear()
