"""
tests/test_api.py — API tests for auth and transaction endpoints.

Strategy
--------
* Builds a self-contained test FastAPI app from the real router modules.
  No dependency on app.api.main or app.main (avoids DB startup event).
* app.dependency_overrides replaces get_db, get_current_user,
  get_current_session, and require_analyst — tests never touch a real DB
  and never need a real JWT.
* Service-layer functions are patched with unittest.mock.patch so each
  test controls exactly what is returned or raised.
* Fixtures follow the pattern: set overrides → yield client → clear overrides.

Run:  pytest tests/test_api.py -v
"""

import uuid
from datetime import datetime, timezone
from decimal import Decimal
from unittest.mock import MagicMock, patch

import pytest
from fastapi import FastAPI, HTTPException, status
from fastapi.testclient import TestClient

# ── Real router modules (the actual production code under test) ──────────────
from app.api.auth_router import router as auth_router
from app.api.transaction_router import router as transaction_router
from app.api.fraud_router import router as fraud_router
from app.api.audit_router import router as audit_router
from app.core.rate_limiter import (
    login_rate_limiter,
    mfa_verify_rate_limiter,
    register_rate_limiter,
)

# ── Dependency functions used as override keys ───────────────────────────────
from app.api.deps import (
    get_current_session,
    get_current_user,
    require_analyst,
    require_transfer_authorized,
)
from app.models.database import get_db

# ── Schema types returned by mocked services ────────────────────────────────
from app.schemas.auth import LoginResponse, Token
from app.schemas.transaction import TransactionListResponse, TransactionResponse

# ── Exception types the services raise ──────────────────────────────────────
from app.services.auth_service import FraudBlockedError, FraudChallengeRequiredError
from app.services.transaction_service import (
    TransactionBlockedError,
    TransactionNotFoundError,
    TransactionStateError,
)


# ============================================================================
# Test application — routers mounted with /api/v1 prefix, no startup events
# ============================================================================

PREFIX = "/api/v1"

test_app = FastAPI(title="Test Banking API")
test_app.include_router(auth_router, prefix=PREFIX)
test_app.include_router(transaction_router, prefix=PREFIX)
test_app.include_router(fraud_router, prefix=PREFIX)
test_app.include_router(audit_router, prefix=PREFIX)

# Public health routes (mirrors app/main.py)
@test_app.get("/")
def root():
    return {"message": "Secure Banking API is running"}

@test_app.get("/health")
def health():
    return {"status": "ok"}


# ============================================================================
# Mock-object builders
# ============================================================================

def _user(
    user_id: uuid.UUID | None = None,
    email: str = "alice@example.com",
    username: str = "alice",
    account_status: str = "active",
    mfa_enabled: bool = False,
) -> MagicMock:
    """Build a mock User ORM object with every field tests might read."""
    u = MagicMock()
    u.id = user_id or uuid.uuid4()
    u.email = email
    u.username = username
    u.first_name = "Alice"
    u.last_name = "Smith"
    u.phone_number = None
    u.date_of_birth = None
    u.account_status = account_status
    u.mfa_enabled = mfa_enabled
    u.role = "user"
    u.created_at = datetime.now(timezone.utc)
    return u


def _session(session_id: uuid.UUID | None = None) -> MagicMock:
    s = MagicMock()
    s.id = session_id or uuid.uuid4()
    return s


def _txn_orm(
    user_id: uuid.UUID,
    txn_id: uuid.UUID | None = None,
    status_val: str = "pending",
    amount: Decimal = Decimal("250.00"),
    txn_type: str = "transfer",
) -> MagicMock:
    """Build a mock Transaction ORM object compatible with TransactionResponse."""
    t = MagicMock()
    t.id = txn_id or uuid.uuid4()
    t.user_id = user_id
    t.transaction_type = txn_type
    t.amount = amount
    t.currency = "USD"
    t.recipient_account = "ACC-9876"
    t.recipient_name = "Bob"
    t.description = "test transfer"
    t.status = status_val
    t.risk_score = 10
    t.fraud_check_status = "approved"
    t.created_at = datetime.now(timezone.utc)
    t.processed_at = None
    t.completed_at = None
    return t


def _txn_response(user_id: uuid.UUID, **kwargs) -> TransactionResponse:
    """Return a real TransactionResponse Pydantic model from mock ORM data."""
    return TransactionResponse.model_validate(_txn_orm(user_id, **kwargs), from_attributes=True)


def _login_response(user_id: uuid.UUID) -> LoginResponse:
    return LoginResponse(
        tokens=Token(
            access_token="dummy.access.token",
            refresh_token="dummy_refresh_token",
            token_type="bearer",
            expires_in=900,
        ),
        user_id=user_id,
        email="alice@example.com",
        username="alice",
        mfa_required=False,
        mfa_setup_required=False,
        risk_flagged=False,
    )


# ============================================================================
# Pytest fixtures — dependency overrides
# ============================================================================

@pytest.fixture()
def mock_db() -> MagicMock:
    """Reusable mock database session — never hits a real DB."""
    return MagicMock()


@pytest.fixture()
def alice() -> MagicMock:
    """Standard active regular user (no analyst scope)."""
    return _user()


@pytest.fixture()
def client_as_alice(alice, mock_db):
    """
    TestClient authenticated as a regular user.
    get_current_user   → alice
    get_current_session → (alice, mock_session)  [for logout endpoint]
    get_db             → mock_db
    require_analyst    is NOT overridden here — use client_as_analyst for that.
    """
    mock_sess = _session()
    test_app.dependency_overrides[get_db] = lambda: mock_db
    test_app.dependency_overrides[get_current_user] = lambda: alice
    test_app.dependency_overrides[get_current_session] = lambda: (alice, mock_sess)
    test_app.dependency_overrides[require_transfer_authorized] = lambda: None
    test_app.dependency_overrides[login_rate_limiter] = lambda: None
    test_app.dependency_overrides[mfa_verify_rate_limiter] = lambda: None
    test_app.dependency_overrides[register_rate_limiter] = lambda: None
    yield TestClient(test_app, raise_server_exceptions=False)
    test_app.dependency_overrides.clear()


@pytest.fixture()
def client_as_analyst(alice, mock_db):
    """
    TestClient where require_analyst is overridden to a no-op (allow).
    Models a token that carries analyst or admin scope.
    """
    mock_sess = _session()
    test_app.dependency_overrides[get_db] = lambda: mock_db
    test_app.dependency_overrides[get_current_user] = lambda: alice
    test_app.dependency_overrides[get_current_session] = lambda: (alice, mock_sess)
    test_app.dependency_overrides[require_analyst] = lambda: None  # pass silently
    test_app.dependency_overrides[require_transfer_authorized] = lambda: None
    test_app.dependency_overrides[login_rate_limiter] = lambda: None
    test_app.dependency_overrides[mfa_verify_rate_limiter] = lambda: None
    test_app.dependency_overrides[register_rate_limiter] = lambda: None
    test_app.dependency_overrides[require_transfer_authorized] = lambda: None
    yield TestClient(test_app, raise_server_exceptions=False)
    test_app.dependency_overrides.clear()


@pytest.fixture()
def client_no_auth():
    """
    TestClient with NO dependency overrides.
    The real auth layer runs; requests without a valid JWT receive 401.
    """
    test_app.dependency_overrides.clear()
    test_app.dependency_overrides[login_rate_limiter] = lambda: None
    test_app.dependency_overrides[mfa_verify_rate_limiter] = lambda: None
    test_app.dependency_overrides[register_rate_limiter] = lambda: None
    yield TestClient(test_app, raise_server_exceptions=False)
    test_app.dependency_overrides.clear()


# ============================================================================
# AUTH — register
# ============================================================================

class TestRegister:
    """POST /api/v1/auth/register"""

    URL = f"{PREFIX}/auth/register"

    VALID_BODY = {
        "email": "new@example.com",
        "username": "newuser",
        "first_name": "New",
        "last_name": "User",
        "password": "SecurePass123!",
    }

    def test_success_201_excludes_password(self, client_no_auth):
        """Happy path: new user created, password never in response."""
        mock_user = _user(email="new@example.com", username="newuser")
        with patch("app.services.auth_service.register_user", return_value=mock_user):
            r = client_no_auth.post(self.URL, json=self.VALID_BODY)
        assert r.status_code == 201
        data = r.json()
        assert data["email"] == "new@example.com"
        assert "password" not in data
        assert "password_hash" not in data

    def test_duplicate_email_returns_409(self, client_no_auth):
        """auth_service raises ValueError → auth_router maps to 409 Conflict."""
        with patch("app.services.auth_service.register_user",
                   side_effect=ValueError("Email already registered")):
            r = client_no_auth.post(self.URL, json=self.VALID_BODY)
        assert r.status_code == 409
        assert "Email already registered" in r.json()["detail"]

    def test_duplicate_username_returns_409(self, client_no_auth):
        with patch("app.services.auth_service.register_user",
                   side_effect=ValueError("Username already taken")):
            r = client_no_auth.post(self.URL, json={**self.VALID_BODY, "username": "taken"})
        assert r.status_code == 409

    def test_weak_password_returns_422(self, client_no_auth):
        """Pydantic password_complexity validator rejects weak passwords before service."""
        r = client_no_auth.post(self.URL, json={**self.VALID_BODY, "password": "weak"})
        assert r.status_code == 422

    def test_missing_email_returns_422(self, client_no_auth):
        body = {k: v for k, v in self.VALID_BODY.items() if k != "email"}
        r = client_no_auth.post(self.URL, json=body)
        assert r.status_code == 422

    def test_underage_user_returns_422(self, client_no_auth):
        """Pydantic verify_age validator rejects users under 18."""
        r = client_no_auth.post(self.URL, json={**self.VALID_BODY,
                                                 "date_of_birth": "2015-01-01"})
        assert r.status_code == 422

    def test_no_body_returns_422(self, client_no_auth):
        r = client_no_auth.post(self.URL, json={})
        assert r.status_code == 422


# ============================================================================
# AUTH — login
# ============================================================================

class TestLogin:
    """POST /api/v1/auth/login"""

    URL = f"{PREFIX}/auth/login"

    def test_success_200_contains_tokens(self, client_no_auth):
        """Correct credentials → 200 with both tokens, no password in body."""
        uid = uuid.uuid4()
        with patch("app.services.auth_service.login", return_value=_login_response(uid)):
            r = client_no_auth.post(self.URL, json={
                "email": "alice@example.com", "password": "SecurePass123!",
            })
        assert r.status_code == 200
        d = r.json()
        assert "tokens" in d
        assert d["tokens"]["token_type"] == "bearer"
        assert d["tokens"]["access_token"] != ""
        assert d["tokens"]["refresh_token"] != ""
        assert "password" not in d

    def test_risk_flagged_field_propagated(self, client_no_auth):
        """risk_flagged=True is forwarded to client so it can require MFA for transfers."""
        uid = uuid.uuid4()
        resp = _login_response(uid)
        resp.risk_flagged = True
        with patch("app.services.auth_service.login", return_value=resp):
            r = client_no_auth.post(self.URL, json={
                "email": "alice@example.com", "password": "SecurePass123!",
            })
        assert r.status_code == 200
        assert r.json()["risk_flagged"] is True

    def test_invalid_credentials_returns_401(self, client_no_auth):
        """Wrong password → ValueError → 401 Unauthorized."""
        with patch("app.services.auth_service.login",
                   side_effect=ValueError("Invalid email/username or password")):
            r = client_no_auth.post(self.URL, json={
                "email": "alice@example.com", "password": "WrongPass1!",
            })
        assert r.status_code == 401

    def test_fraud_block_returns_403(self, client_no_auth):
        """Fraud engine hard-blocked this login — no tokens issued → 403."""
        with patch("app.services.auth_service.login",
                   side_effect=FraudBlockedError("Login blocked by security policy")):
            r = client_no_auth.post(self.URL, json={
                "email": "alice@example.com", "password": "SecurePass123!",
            })
        assert r.status_code == 403
        assert "blocked" in r.json()["detail"].lower()

    def test_unavailable_fraud_challenge_returns_403(self, client_no_auth):
        """Fraud challenge without an MFA method fails closed instead of returning a broken 202."""
        with patch("app.services.auth_service.login",
                   side_effect=FraudChallengeRequiredError("Security challenge required, but no MFA method is enabled")):
            r = client_no_auth.post(self.URL, json={
                "email": "alice@example.com", "password": "SecurePass123!",
            })
        assert r.status_code == 403
        assert "challenge" in r.json()["detail"].lower()

    def test_locked_account_returns_401(self, client_no_auth):
        with patch("app.services.auth_service.login",
                   side_effect=ValueError("Account is temporarily locked")):
            r = client_no_auth.post(self.URL, json={
                "email": "alice@example.com", "password": "SecurePass123!",
            })
        assert r.status_code == 401
        assert "locked" in r.json()["detail"].lower()

    def test_username_login_supported(self, client_no_auth):
        """UserLogin schema accepts username instead of email."""
        uid = uuid.uuid4()
        with patch("app.services.auth_service.login", return_value=_login_response(uid)):
            r = client_no_auth.post(self.URL, json={
                "username": "alice", "password": "SecurePass123!",
            })
        assert r.status_code == 200

    def test_no_identifier_returns_422(self, client_no_auth):
        """Pydantic model_validator rejects body with neither email nor username."""
        r = client_no_auth.post(self.URL, json={"password": "SecurePass123!"})
        assert r.status_code == 422


# ============================================================================
# AUTH — refresh
# ============================================================================

class TestRefresh:
    """POST /api/v1/auth/refresh"""

    URL = f"{PREFIX}/auth/refresh"

    def test_success_rotates_both_tokens(self, client_no_auth):
        """Valid refresh token → new access + new refresh token (rotation)."""
        new_token = Token(
            access_token="new.access.token",
            refresh_token="new_refresh_token",
            token_type="bearer",
            expires_in=900,
        )
        with patch("app.services.auth_service.refresh_tokens", return_value=new_token):
            r = client_no_auth.post(self.URL, json={"refresh_token": "old_valid_token"})
        assert r.status_code == 200
        d = r.json()
        assert d["access_token"] == "new.access.token"
        assert d["refresh_token"] == "new_refresh_token"

    def test_invalid_token_returns_401(self, client_no_auth):
        with patch("app.services.auth_service.refresh_tokens",
                   side_effect=ValueError("Invalid or expired refresh token")):
            r = client_no_auth.post(self.URL, json={"refresh_token": "bad_token"})
        assert r.status_code == 401

    def test_missing_body_returns_422(self, client_no_auth):
        r = client_no_auth.post(self.URL, json={})
        assert r.status_code == 422


# ============================================================================
# AUTH — logout
# ============================================================================

class TestLogout:
    """POST /api/v1/auth/logout  (returns 204 No Content)"""

    URL = f"{PREFIX}/auth/logout"

    def test_success_returns_204(self, client_as_alice):
        """Authenticated session invalidated → 204, empty body."""
        with patch("app.services.auth_service.logout", return_value=True):
            r = client_as_alice.post(self.URL,
                                     headers={"Authorization": "Bearer any_token"})
        assert r.status_code == 204
        assert r.content == b""

    def test_no_token_returns_401(self, client_no_auth):
        """No Authorization header → 401 before any session logic runs."""
        r = client_no_auth.post(self.URL)
        assert r.status_code == 401


# ============================================================================
# AUTH — me
# ============================================================================

class TestGetMe:
    """GET /api/v1/auth/me"""

    URL = f"{PREFIX}/auth/me"

    def test_returns_current_user_profile(self, client_as_alice, alice):
        r = client_as_alice.get(self.URL,
                                headers={"Authorization": "Bearer any_token"})
        assert r.status_code == 200
        assert r.json()["email"] == alice.email
        assert "password" not in r.json()
        assert "password_hash" not in r.json()

    def test_no_token_returns_401(self, client_no_auth):
        r = client_no_auth.get(self.URL)
        assert r.status_code == 401


# ============================================================================
# TRANSACTIONS — create
# ============================================================================

class TestCreateTransaction:
    """POST /api/v1/transactions/"""

    URL = f"{PREFIX}/transactions/"

    def test_success_returns_201_pending(self, client_as_alice, alice):
        """Clean transaction → fraud score low → status=pending → 201."""
        txn = _txn_response(alice.id, status_val="pending")
        with patch("app.api.transaction_router.create_transaction", return_value=txn):
            r = client_as_alice.post(self.URL, json={
                "transaction_type": "transfer",
                "amount": "250.00",
                "currency": "USD",
                "recipient_account": "ACC-9876",
                "recipient_name": "Bob",
            })
        assert r.status_code == 201
        d = r.json()
        assert d["status"] == "pending"
        assert float(d["amount"]) == 250.0
        assert d["currency"] == "USD"

    def test_high_risk_creates_flagged_transaction(self, client_as_alice, alice):
        """Fraud score >= FLAG threshold → transaction created with status=flagged."""
        txn = _txn_response(alice.id, status_val="flagged")
        with patch("app.api.transaction_router.create_transaction", return_value=txn):
            r = client_as_alice.post(self.URL, json={
                "transaction_type": "transfer",
                "amount": "15000.00",
                "currency": "USD",
            })
        assert r.status_code == 201
        assert r.json()["status"] == "flagged"

    def test_fraud_blocked_returns_403(self, client_as_alice):
        """Fraud score >= BLOCK threshold → no row created → 403."""
        with patch("app.api.transaction_router.create_transaction",
                   side_effect=TransactionBlockedError("Transaction blocked by security policy")):
            r = client_as_alice.post(self.URL, json={
                "transaction_type": "transfer",
                "amount": "99999.00",
            })
        assert r.status_code == 403
        assert "blocked" in r.json()["detail"].lower()

    def test_zero_amount_rejected_by_pydantic(self, client_as_alice):
        """TransactionCreate.amount has gt=0; Pydantic rejects before service."""
        r = client_as_alice.post(self.URL, json={
            "transaction_type": "transfer", "amount": "0",
        })
        assert r.status_code == 422

    def test_negative_amount_returns_422(self, client_as_alice):
        r = client_as_alice.post(self.URL, json={
            "transaction_type": "transfer", "amount": "-50.00",
        })
        assert r.status_code == 422

    def test_invalid_transaction_type_returns_422(self, client_as_alice):
        """TransactionType is a Literal; unknown value rejected by Pydantic."""
        r = client_as_alice.post(self.URL, json={
            "transaction_type": "wire", "amount": "100.00",
        })
        assert r.status_code == 422

    def test_deposit_without_recipient_is_valid(self, client_as_alice, alice):
        """recipient_account is Optional — deposits don't require it."""
        txn = _txn_response(alice.id, txn_type="deposit")
        with patch("app.api.transaction_router.create_transaction", return_value=txn):
            r = client_as_alice.post(self.URL, json={
                "transaction_type": "deposit", "amount": "500.00",
            })
        assert r.status_code == 201

    def test_no_auth_returns_401(self, client_no_auth):
        r = client_no_auth.post(self.URL, json={
            "transaction_type": "transfer", "amount": "100.00",
        })
        assert r.status_code == 401


# ============================================================================
# TRANSACTIONS — list
# ============================================================================

class TestListTransactions:
    """GET /api/v1/transactions/"""

    URL = f"{PREFIX}/transactions/"

    def test_success_returns_200_with_list(self, client_as_alice, alice):
        txn = _txn_response(alice.id)
        mock_list = TransactionListResponse(transactions=[txn], total=1)
        with patch("app.api.transaction_router.list_transactions", return_value=mock_list):
            r = client_as_alice.get(self.URL)
        assert r.status_code == 200
        d = r.json()
        assert d["total"] == 1
        assert len(d["transactions"]) == 1

    def test_empty_list_returns_200(self, client_as_alice):
        mock_list = TransactionListResponse(transactions=[], total=0)
        with patch("app.api.transaction_router.list_transactions", return_value=mock_list):
            r = client_as_alice.get(self.URL)
        assert r.status_code == 200
        assert r.json()["total"] == 0

    def test_pagination_params_forwarded_to_service(self, client_as_alice):
        mock_list = TransactionListResponse(transactions=[], total=0)
        with patch("app.api.transaction_router.list_transactions",
                   return_value=mock_list) as m:
            client_as_alice.get(self.URL + "?page=3&page_size=5")
        _, kw = m.call_args
        assert kw.get("page") == 3
        assert kw.get("page_size") == 5

    def test_page_size_over_100_returns_422(self, client_as_alice):
        """Query param le=100 enforced by FastAPI before the handler runs."""
        r = client_as_alice.get(self.URL + "?page_size=999")
        assert r.status_code == 422

    def test_no_auth_returns_401(self, client_no_auth):
        r = client_no_auth.get(self.URL)
        assert r.status_code == 401


# ============================================================================
# TRANSACTIONS — get single
# ============================================================================

class TestGetTransaction:
    """GET /api/v1/transactions/{transaction_id}"""

    def test_success_returns_200(self, client_as_alice, alice):
        txn = _txn_response(alice.id)
        with patch("app.api.transaction_router.get_transaction", return_value=txn):
            r = client_as_alice.get(f"{PREFIX}/transactions/{txn.id}")
        assert r.status_code == 200
        assert r.json()["id"] == str(txn.id)

    def test_not_found_returns_404(self, client_as_alice):
        """
        Returns 404 whether the transaction doesn't exist OR belongs to
        another user — ownership-via-404 prevents ID enumeration attacks.
        """
        with patch("app.api.transaction_router.get_transaction",
                   side_effect=TransactionNotFoundError("Transaction not found")):
            r = client_as_alice.get(f"{PREFIX}/transactions/{uuid.uuid4()}")
        assert r.status_code == 404

    def test_invalid_uuid_returns_422(self, client_as_alice):
        """FastAPI path param validation rejects non-UUID strings."""
        r = client_as_alice.get(f"{PREFIX}/transactions/not-a-uuid")
        assert r.status_code == 422

    def test_no_auth_returns_401(self, client_no_auth):
        r = client_no_auth.get(f"{PREFIX}/transactions/{uuid.uuid4()}")
        assert r.status_code == 401


# ============================================================================
# TRANSACTIONS — process
# ============================================================================

class TestProcessTransaction:
    """POST /api/v1/transactions/{transaction_id}/process"""

    def test_success_completes_transaction(self, client_as_alice, alice):
        txn = _txn_response(alice.id, status_val="completed")
        with patch("app.api.transaction_router.process_transaction", return_value=txn):
            r = client_as_alice.post(f"{PREFIX}/transactions/{txn.id}/process")
        assert r.status_code == 200
        assert r.json()["status"] == "completed"

    def test_flagged_transaction_returns_409(self, client_as_alice, alice):
        """Flagged transactions cannot be auto-processed — analyst must review first."""
        txn = _txn_orm(alice.id, status_val="flagged")
        with patch("app.api.transaction_router.process_transaction",
                   side_effect=TransactionStateError(
                       "Flagged transactions require manual review before processing"
                   )):
            r = client_as_alice.post(f"{PREFIX}/transactions/{txn.id}/process")
        assert r.status_code == 409
        assert "flagged" in r.json()["detail"].lower()

    def test_not_found_returns_404(self, client_as_alice):
        with patch("app.api.transaction_router.process_transaction",
                   side_effect=TransactionNotFoundError("Transaction not found")):
            r = client_as_alice.post(f"{PREFIX}/transactions/{uuid.uuid4()}/process")
        assert r.status_code == 404

    def test_terminal_state_is_idempotent(self, client_as_alice, alice):
        """Completed/failed/blocked transactions return current state without error."""
        txn = _txn_response(alice.id, status_val="completed")
        with patch("app.api.transaction_router.process_transaction", return_value=txn):
            r = client_as_alice.post(f"{PREFIX}/transactions/{txn.id}/process")
        assert r.status_code == 200

    def test_no_auth_returns_401(self, client_no_auth):
        r = client_no_auth.post(f"{PREFIX}/transactions/{uuid.uuid4()}/process")
        assert r.status_code == 401


# ============================================================================
# TRANSACTIONS — block  ← primary target of this step
# ============================================================================

class TestBlockTransaction:
    """
    POST /api/v1/transactions/{transaction_id}/block

    Authorization: requires analyst or admin scope (require_analyst dependency).
    This class verifies both the happy paths AND the security boundaries.
    """

    def _url(self, txn_id: uuid.UUID) -> str:
        return f"{PREFIX}/transactions/{txn_id}/block"

    # ── Happy paths ──────────────────────────────────────────────────────────

    def test_analyst_can_block(self, client_as_analyst, alice):
        """Analyst-scoped token + valid transaction → 200, status=blocked."""
        txn = _txn_response(alice.id, status_val="blocked")
        with patch("app.api.transaction_router.block_transaction", return_value=txn):
            r = client_as_analyst.post(self._url(txn.id),
                                       params={"reason": "Suspicious pattern"})
        assert r.status_code == 200
        assert r.json()["status"] == "blocked"

    def test_reason_query_param_is_optional(self, client_as_analyst, alice):
        """reason is Query(default=None) — omitting it is valid."""
        txn = _txn_response(alice.id, status_val="blocked")
        with patch("app.api.transaction_router.block_transaction", return_value=txn):
            r = client_as_analyst.post(self._url(txn.id))  # no reason
        assert r.status_code == 200

    def test_admin_token_satisfies_analyst_requirement(self, mock_db, alice):
        """
        Admin scope rank (5) >= analyst rank (4).
        Proves scope HIERARCHY — admin can do everything analyst can.
        """
        test_app.dependency_overrides[get_db] = lambda: mock_db
        test_app.dependency_overrides[get_current_user] = lambda: alice
        test_app.dependency_overrides[require_analyst] = lambda: None  # admin rank >= analyst
        client = TestClient(test_app, raise_server_exceptions=False)
        txn = _txn_response(alice.id, status_val="blocked")
        try:
            with patch("app.api.transaction_router.block_transaction", return_value=txn):
                r = client.post(self._url(txn.id))
            assert r.status_code == 200
        finally:
            test_app.dependency_overrides.clear()

    # ── Authorization failures ────────────────────────────────────────────────

    def test_regular_user_receives_403(self, mock_db, alice):
        """
        CRITICAL: authenticated user without analyst scope → 403.

        Being logged in (get_current_user passes) is NOT sufficient.
        require_analyst is a SEPARATE gate that checks scope, and it
        runs BEFORE the handler body — so the service is never called.

        This is the central security guarantee of this step.
        """
        def _deny():
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=(
                    "Insufficient permissions. "
                    "This action requires the 'analyst' or 'admin' role."
                ),
            )

        test_app.dependency_overrides[get_db] = lambda: mock_db
        test_app.dependency_overrides[get_current_user] = lambda: alice
        test_app.dependency_overrides[require_analyst] = _deny  # ← scope check fails
        client = TestClient(test_app, raise_server_exceptions=False)
        try:
            r = client.post(self._url(uuid.uuid4()),
                            headers={"Authorization": "Bearer regular_user_token"})
            assert r.status_code == 403
            assert "analyst" in r.json()["detail"].lower()
        finally:
            test_app.dependency_overrides.clear()

    def test_no_auth_returns_401(self, client_no_auth):
        """No Authorization header → 401 before require_analyst even runs."""
        r = client_no_auth.post(self._url(uuid.uuid4()))
        assert r.status_code == 401

    # ── Service error paths ──────────────────────────────────────────────────

    def test_not_found_returns_404(self, client_as_analyst):
        with patch("app.api.transaction_router.block_transaction",
                   side_effect=TransactionNotFoundError("Transaction not found")):
            r = client_as_analyst.post(self._url(uuid.uuid4()))
        assert r.status_code == 404

    def test_completed_transaction_returns_409(self, client_as_analyst, alice):
        """Cannot transition out of terminal state → TransactionStateError → 409."""
        txn = _txn_orm(alice.id, status_val="completed")
        with patch("app.api.transaction_router.block_transaction",
                   side_effect=TransactionStateError(
                       "Cannot transition transaction from 'completed' to 'blocked'"
                   )):
            r = client_as_analyst.post(self._url(txn.id))
        assert r.status_code == 409
        assert "completed" in r.json()["detail"].lower()

    def test_already_blocked_returns_409(self, client_as_analyst, alice):
        txn = _txn_orm(alice.id, status_val="blocked")
        with patch("app.api.transaction_router.block_transaction",
                   side_effect=TransactionStateError(
                       "Cannot transition transaction from 'blocked' to 'blocked'"
                   )):
            r = client_as_analyst.post(self._url(txn.id))
        assert r.status_code == 409


# ============================================================================
# Security boundaries — cross-cutting regression tests
# ============================================================================

class TestSecurityBoundaries:
    """
    Every protected endpoint must return 401 with no token.
    Every public endpoint must return 200 with no token.
    register and login must return 422 (not 401) — proves they are public.
    block must return 403 for authenticated-but-not-analyst user.

    Add new routes to PROTECTED_ROUTES the moment they are created.
    """

    TXN_ID = uuid.uuid4()

    PROTECTED = [
        ("POST", f"{PREFIX}/auth/logout"),
        ("GET",  f"{PREFIX}/auth/me"),
        ("POST", f"{PREFIX}/transactions/"),
        ("GET",  f"{PREFIX}/transactions/"),
        ("GET",  f"{PREFIX}/transactions/{TXN_ID}"),
        ("POST", f"{PREFIX}/transactions/{TXN_ID}/process"),
        ("POST", f"{PREFIX}/transactions/{TXN_ID}/block"),
        ("GET",  f"{PREFIX}/fraud/alerts/"),
        ("GET",  f"{PREFIX}/audit/logs/"),
    ]

    PUBLIC = [
        ("GET", "/"),
        ("GET", "/health"),
    ]

    def test_protected_routes_return_401_without_token(self, client_no_auth):
        """
        Regression guard: if any protected route is accidentally made public
        (e.g. auth dependency removed), this test catches it immediately.
        """
        for method, path in self.PROTECTED:
            r = client_no_auth.request(method, path)
            assert r.status_code == 401, (
                f"{method} {path} returned {r.status_code} — "
                "expected 401. Is auth protection missing on this route?"
            )

    def test_public_routes_return_200_without_token(self, client_no_auth):
        for method, path in self.PUBLIC:
            r = client_no_auth.request(method, path)
            assert r.status_code == 200, (
                f"{method} {path} returned {r.status_code}, expected 200"
            )

    def test_register_and_login_are_public_not_401(self, client_no_auth):
        """
        Public routes reached with empty body return 422 (Pydantic validation),
        NOT 401. 422 proves the request reached the handler — auth not required.
        """
        reg   = client_no_auth.post(f"{PREFIX}/auth/register", json={})
        login = client_no_auth.post(f"{PREFIX}/auth/login",    json={})
        assert reg.status_code   == 422, f"register: got {reg.status_code}"
        assert login.status_code == 422, f"login: got {login.status_code}"

    def test_block_requires_analyst_scope_not_just_authentication(self, mock_db, alice):
        """
        Authenticated (get_current_user passes) but non-analyst scope → 403.
        Being logged in is NECESSARY but NOT SUFFICIENT for the block endpoint.
        This is the most important security boundary test in this file.
        """
        def _deny():
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=(
                    "Insufficient permissions. "
                    "This action requires the 'analyst' or 'admin' role."
                ),
            )

        test_app.dependency_overrides[get_db] = lambda: mock_db
        test_app.dependency_overrides[get_current_user] = lambda: alice
        test_app.dependency_overrides[require_analyst] = _deny
        client = TestClient(test_app, raise_server_exceptions=False)
        try:
            r = client.post(
                f"{PREFIX}/transactions/{uuid.uuid4()}/block",
                headers={"Authorization": "Bearer valid_but_low_privilege_token"},
            )
            assert r.status_code == 403, (
                f"Expected 403, got {r.status_code}. "
                "Block endpoint must enforce analyst scope beyond basic auth."
            )
        finally:
            test_app.dependency_overrides.clear()


# ============================================================================
# Unit tests — scope rank logic (no HTTP, pure function tests)
# ============================================================================

class TestScopeRank:
    """
    Directly test _highest_rank and the require_analyst / require_admin
    scope-check logic — isolates the authorization algorithm from HTTP layer.
    """

    def test_read_only_rank_is_1(self):
        from app.api.deps import _highest_rank
        assert _highest_rank(["read_only"]) == 1

    def test_analyst_rank_is_4(self):
        from app.api.deps import _highest_rank
        assert _highest_rank(["analyst"]) == 4

    def test_admin_rank_is_5(self):
        from app.api.deps import _highest_rank
        assert _highest_rank(["admin"]) == 5

    def test_admin_satisfies_analyst_check(self):
        """Core hierarchy guarantee: admin rank (5) >= analyst rank (4)."""
        from app.api.deps import _highest_rank, _SCOPE_RANK, SCOPE_ANALYST
        assert _highest_rank(["admin"]) >= _SCOPE_RANK[SCOPE_ANALYST]

    def test_transfer_authorized_does_not_satisfy_analyst(self):
        from app.api.deps import _highest_rank, _SCOPE_RANK, SCOPE_ANALYST
        assert _highest_rank(["transfer_authorized"]) < _SCOPE_RANK[SCOPE_ANALYST]

    def test_multiple_scopes_picks_highest(self):
        from app.api.deps import _highest_rank
        assert _highest_rank(["read_only", "transfer_authorized"]) == 2

    def test_unknown_scope_has_rank_zero(self):
        from app.api.deps import _highest_rank
        assert _highest_rank(["unknown_scope"]) == 0

    def test_empty_scopes_has_rank_zero(self):
        from app.api.deps import _highest_rank
        assert _highest_rank([]) == 0
    
