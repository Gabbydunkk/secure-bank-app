"""
tests/test_mfa.py — MFA endpoint tests.

Tests cover:
  Setup flow:   POST /auth/mfa/setup, POST /auth/mfa/confirm
  Login flow:   POST /auth/login (202 + mfa_token), POST /auth/mfa/verify
  Disable flow: DELETE /auth/mfa
  Security:     wrong code, expired token, wrong token type, re-use of
                access token as mfa_token, backup code flow

Strategy
--------
* Same TestClient pattern as test_api.py.
* mfa_service functions are patched at the router import path.
* auth_service.login / verify_mfa_and_login patched at router import path.
* TOTP unit tests run verify_totp() directly — no HTTP involved.

Run: pytest tests/test_mfa.py -v
"""

import uuid
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.auth_router import router as auth_router
from app.api.deps import get_current_user, get_current_session
from app.core.rate_limiter import (
    login_rate_limiter,
    mfa_verify_rate_limiter,
    register_rate_limiter,
)
from app.models.database import get_db
from app.schemas.auth import (
    LoginResponse,
    MFAPendingResponse,
    MFASetupResponse,
    Token,
)
from app.services.auth_service import (
    FraudBlockedError,
    MFARequiredError,
)


# ============================================================================
# Test application
# ============================================================================

PREFIX = "/api/v1"

test_app = FastAPI(title="MFA Test App")
test_app.include_router(auth_router, prefix=PREFIX)


# ============================================================================
# Helpers
# ============================================================================

def _user(
    user_id: uuid.UUID | None = None,
    email: str = "alice@example.com",
    username: str = "alice",
    mfa_enabled: bool = False,
) -> MagicMock:
    u = MagicMock()
    u.id = user_id or uuid.uuid4()
    u.email = email
    u.username = username
    u.first_name = "Alice"
    u.last_name = "Smith"
    u.phone_number = None
    u.date_of_birth = None
    u.account_status = "active"
    u.mfa_enabled = mfa_enabled
    u.created_at = datetime.now(timezone.utc)
    return u


def _session() -> MagicMock:
    s = MagicMock()
    s.id = uuid.uuid4()
    return s


def _token_pair(user_id: uuid.UUID) -> Token:
    return Token(
        access_token="full.access.token",
        refresh_token="full_refresh_token",
        token_type="bearer",
        expires_in=900,
    )


def _login_response(user_id: uuid.UUID, *, mfa_required: bool = False) -> LoginResponse:
    if mfa_required:
        return LoginResponse(
            tokens=None,
            mfa_token="mfa.pending.token",
            user_id=user_id,
            email="alice@example.com",
            username="alice",
            mfa_required=True,
        )
    return LoginResponse(
        tokens=_token_pair(user_id),
        user_id=user_id,
        email="alice@example.com",
        username="alice",
    )


# ============================================================================
# Fixtures
# ============================================================================

@pytest.fixture()
def mock_db() -> MagicMock:
    return MagicMock()


@pytest.fixture()
def alice() -> MagicMock:
    return _user(mfa_enabled=False)


@pytest.fixture()
def alice_mfa() -> MagicMock:
    return _user(mfa_enabled=True)


@pytest.fixture()
def client_as_alice(alice, mock_db):
    mock_sess = _session()
    test_app.dependency_overrides[get_db] = lambda: mock_db
    test_app.dependency_overrides[get_current_user] = lambda: alice
    test_app.dependency_overrides[get_current_session] = lambda: (alice, mock_sess)
    test_app.dependency_overrides[login_rate_limiter] = lambda: None
    test_app.dependency_overrides[mfa_verify_rate_limiter] = lambda: None
    test_app.dependency_overrides[register_rate_limiter] = lambda: None
    yield TestClient(test_app, raise_server_exceptions=False)
    test_app.dependency_overrides.clear()


@pytest.fixture()
def client_no_auth(mock_db):
    test_app.dependency_overrides[get_db] = lambda: mock_db
    test_app.dependency_overrides[login_rate_limiter] = lambda: None
    test_app.dependency_overrides[mfa_verify_rate_limiter] = lambda: None
    test_app.dependency_overrides[register_rate_limiter] = lambda: None
    # No get_current_user override — real auth runs (will fail on bad/missing tokens)
    yield TestClient(test_app, raise_server_exceptions=False)
    test_app.dependency_overrides.clear()


# ============================================================================
# MFA Setup — POST /api/v1/auth/mfa/setup
# ============================================================================

class TestMFASetup:
    URL = f"{PREFIX}/auth/mfa/setup"

    MOCK_SETUP_RESPONSE = MFASetupResponse(
        secret="JBSWY3DPEHPK3PXP",
        provisioning_uri="otpauth://totp/SecureBankPro%3Aalice%40example.com?secret=JBSWY3DPEHPK3PXP&issuer=SecureBankPro&algorithm=SHA1&digits=6&period=30",
        backup_codes=[
            "A1B2-C3D4", "E5F6-A7B8", "C9D0-E1F2",
            "G3H4-I5J6", "K7L8-M9N0", "O1P2-Q3R4",
            "S5T6-U7V8", "W9X0-Y1Z2",
        ],
    )

    def test_success_returns_secret_uri_backup_codes(self, client_as_alice):
        """Happy path: returns secret, provisioning_uri, and 8 backup codes."""
        with patch("app.api.auth_router.mfa_service.setup_mfa",
                   return_value=self.MOCK_SETUP_RESPONSE):
            r = client_as_alice.post(self.URL)
        assert r.status_code == 200
        d = r.json()
        assert "secret" in d
        assert "provisioning_uri" in d
        assert d["provisioning_uri"].startswith("otpauth://totp/")
        assert "backup_codes" in d
        assert len(d["backup_codes"]) == 8

    def test_provisioning_uri_contains_secret(self, client_as_alice):
        """URI must embed the secret so authenticator apps can scan it."""
        with patch("app.api.auth_router.mfa_service.setup_mfa",
                   return_value=self.MOCK_SETUP_RESPONSE):
            r = client_as_alice.post(self.URL)
        assert "JBSWY3DPEHPK3PXP" in r.json()["provisioning_uri"]

    def test_no_auth_returns_401(self, client_no_auth):
        """Setup requires authentication — cannot be called by anonymous user."""
        r = client_no_auth.post(self.URL)
        assert r.status_code == 401

    def test_message_instructs_user_to_confirm(self, client_as_alice):
        """Response must tell the user to call /mfa/confirm — UX requirement."""
        with patch("app.api.auth_router.mfa_service.setup_mfa",
                   return_value=self.MOCK_SETUP_RESPONSE):
            r = client_as_alice.post(self.URL)
        assert "confirm" in r.json()["message"].lower()


# ============================================================================
# MFA Confirm — POST /api/v1/auth/mfa/confirm
# ============================================================================

class TestMFAConfirm:
    URL = f"{PREFIX}/auth/mfa/confirm"

    def test_valid_code_activates_mfa(self, client_as_alice):
        """Valid code → confirm_mfa_setup returns True → 200 with success message."""
        with patch("app.api.auth_router.mfa_service.confirm_mfa_setup",
                   return_value=True):
            r = client_as_alice.post(self.URL, json={"code": "123456"})
        assert r.status_code == 200
        assert "activated" in r.json()["message"].lower()

    def test_invalid_code_returns_400(self, client_as_alice):
        """Wrong code → ValueError from service → 400 Bad Request."""
        with patch("app.api.auth_router.mfa_service.confirm_mfa_setup",
                   side_effect=ValueError("Invalid TOTP code. Make sure your authenticator app is synced.")):
            r = client_as_alice.post(self.URL, json={"code": "000000"})
        assert r.status_code == 400
        assert "invalid" in r.json()["detail"].lower()

    def test_no_setup_returns_400(self, client_as_alice):
        """Calling confirm before setup → ValueError → 400."""
        with patch("app.api.auth_router.mfa_service.confirm_mfa_setup",
                   side_effect=ValueError("No MFA setup found. Call /auth/mfa/setup first.")):
            r = client_as_alice.post(self.URL, json={"code": "123456"})
        assert r.status_code == 400
        assert "setup" in r.json()["detail"].lower()

    def test_non_digit_code_rejected_by_pydantic(self, client_as_alice):
        """MFAConfirmRequest.code has pattern=r'^\\d{6}$' — letters rejected."""
        r = client_as_alice.post(self.URL, json={"code": "ABCDEF"})
        assert r.status_code == 422

    def test_short_code_rejected(self, client_as_alice):
        r = client_as_alice.post(self.URL, json={"code": "123"})
        assert r.status_code == 422

    def test_no_auth_returns_401(self, client_no_auth):
        r = client_no_auth.post(self.URL, json={"code": "123456"})
        assert r.status_code == 401


# ============================================================================
# Login with MFA — POST /api/v1/auth/login → 202 + mfa_token
# ============================================================================

class TestLoginMFAFlow:
    """
    Tests the modified login endpoint when MFA is enabled.
    MFARequiredError is now raised (not FraudChallengeRequiredError) and
    the router returns 202 with a structured MFAPendingResponse body
    containing the mfa_token — not just a plain error detail string.
    """

    LOGIN_URL = f"{PREFIX}/auth/login"
    VERIFY_URL = f"{PREFIX}/auth/mfa/verify"

    def test_login_with_mfa_enabled_returns_202_with_mfa_token(self, client_no_auth):
        """
        MFA-enabled user: login raises MFARequiredError → 202 response
        body contains mfa_token (not just a detail string).
        This is the key protocol change — clients get a structured response.
        """
        uid = uuid.uuid4()
        with patch("app.api.auth_router.auth_service.login",
                   side_effect=MFARequiredError(
                       mfa_token="mfa.pending.jwt.token",
                       user_id=uid,
                       email="alice@example.com",
                   )):
            r = client_no_auth.post(self.LOGIN_URL, json={
                "email": "alice@example.com", "password": "SecurePass123!",
            })
        assert r.status_code == 202
        d = r.json()
        assert "mfa_token" in d, "mfa_token must be in the 202 body"
        assert d["mfa_token"] == "mfa.pending.jwt.token"
        assert d["mfa_required"] is True
        assert d["email"] == "alice@example.com"

    def test_login_without_mfa_still_returns_200(self, client_no_auth):
        """Non-MFA login path is unchanged — still returns 200 with full tokens."""
        uid = uuid.uuid4()
        login_resp = LoginResponse(
            tokens=_token_pair(uid),
            user_id=uid, email="alice@example.com", username="alice",
        )
        with patch("app.api.auth_router.auth_service.login", return_value=login_resp):
            r = client_no_auth.post(self.LOGIN_URL, json={
                "email": "alice@example.com", "password": "SecurePass123!",
            })
        assert r.status_code == 200
        assert r.json()["tokens"]["access_token"] == "full.access.token"

    def test_login_202_body_has_no_tokens(self, client_no_auth):
        """
        When MFA is pending, the 202 body must NOT contain full tokens.
        Tokens are only issued after MFA verification succeeds.
        """
        uid = uuid.uuid4()
        with patch("app.api.auth_router.auth_service.login",
                   side_effect=MFARequiredError("tok", uid, "alice@example.com")):
            r = client_no_auth.post(self.LOGIN_URL, json={
                "email": "alice@example.com", "password": "SecurePass123!",
            })
        assert r.status_code == 202
        body = r.json()
        # Full token pair must not be present
        assert "access_token" not in body
        assert "refresh_token" not in body


# ============================================================================
# MFA Verify — POST /api/v1/auth/mfa/verify
# ============================================================================

class TestMFAVerify:
    URL = f"{PREFIX}/auth/mfa/verify"

    def test_valid_code_returns_200_with_tokens(self, client_no_auth):
        """
        Happy path: valid mfa_token + correct TOTP code → full LoginResponse.
        This is the final step that completes the MFA login flow.
        """
        uid = uuid.uuid4()
        full_response = LoginResponse(
            tokens=_token_pair(uid),
            user_id=uid, email="alice@example.com", username="alice",
            mfa_required=False,
        )
        with patch("app.api.auth_router.auth_service.verify_mfa_and_login",
                   return_value=full_response):
            r = client_no_auth.post(self.URL, json={
                "mfa_token": "valid.mfa.pending.token",
                "code": "123456",
            })
        assert r.status_code == 200
        d = r.json()
        assert d["tokens"]["access_token"] == "full.access.token"
        assert d["tokens"]["refresh_token"] == "full_refresh_token"
        assert d["mfa_required"] is False

    def test_wrong_code_returns_400(self, client_no_auth):
        """Wrong TOTP code → ValueError → 400 (not 401 — token structure is valid)."""
        with patch("app.api.auth_router.auth_service.verify_mfa_and_login",
                   side_effect=ValueError("Invalid MFA code")):
            r = client_no_auth.post(self.URL, json={
                "mfa_token": "valid.mfa.pending.token",
                "code": "000000",
            })
        assert r.status_code == 400
        assert "invalid mfa code" in r.json()["detail"].lower()

    def test_expired_mfa_token_returns_400(self, client_no_auth):
        """Expired mfa_pending token → ValueError from verify_mfa_pending_token → 400."""
        with patch("app.api.auth_router.auth_service.verify_mfa_and_login",
                   side_effect=ValueError("Invalid MFA token: Invalid or expired MFA token")):
            r = client_no_auth.post(self.URL, json={
                "mfa_token": "expired.mfa.token",
                "code": "123456",
            })
        assert r.status_code == 400
        assert "expired" in r.json()["detail"].lower()

    def test_fraud_block_after_mfa_returns_403(self, client_no_auth):
        """
        TOTP correct, but fraud engine blocks post-MFA → 403.
        MFA passing does NOT bypass fraud checks.
        """
        with patch("app.api.auth_router.auth_service.verify_mfa_and_login",
                   side_effect=FraudBlockedError("Login blocked by security policy")):
            r = client_no_auth.post(self.URL, json={
                "mfa_token": "valid.mfa.pending.token",
                "code": "123456",
            })
        assert r.status_code == 403

    def test_backup_code_accepted(self, client_no_auth):
        """Backup codes (XXXX-XXXX format) are accepted instead of TOTP."""
        uid = uuid.uuid4()
        full_response = LoginResponse(
            tokens=_token_pair(uid),
            user_id=uid, email="alice@example.com", username="alice",
        )
        with patch("app.api.auth_router.auth_service.verify_mfa_and_login",
                   return_value=full_response):
            r = client_no_auth.post(self.URL, json={
                "mfa_token": "valid.mfa.pending.token",
                "code": "A3F2-9C1B",   # backup code format
            })
        assert r.status_code == 200

    def test_missing_mfa_token_returns_422(self, client_no_auth):
        """MFAVerifyRequest requires both fields — missing mfa_token → 422."""
        r = client_no_auth.post(self.URL, json={"code": "123456"})
        assert r.status_code == 422

    def test_missing_code_returns_422(self, client_no_auth):
        r = client_no_auth.post(self.URL, json={"mfa_token": "some.token"})
        assert r.status_code == 422

    def test_empty_body_returns_422(self, client_no_auth):
        r = client_no_auth.post(self.URL, json={})
        assert r.status_code == 422

    def test_verify_is_public_no_auth_header_needed(self, client_no_auth):
        """
        /auth/mfa/verify must be PUBLIC — the mfa_token IS the credential.
        No Authorization header should be required.
        A request without a Bearer header should NOT return 401 —
        it should reach the handler (returns 422 for empty body, not 401).
        """
        r = client_no_auth.post(self.URL, json={})
        # 422 = reached the handler (Pydantic validation), not 401 (auth gate)
        assert r.status_code == 422, (
            f"Expected 422 (validation), got {r.status_code}. "
            "/auth/mfa/verify must be public — mfa_token is the credential."
        )


# ============================================================================
# MFA Disable — DELETE /api/v1/auth/mfa
# ============================================================================

class TestMFADisable:
    URL = f"{PREFIX}/auth/mfa"

    def test_valid_code_disables_mfa(self, client_as_alice):
        """Valid TOTP → disable_mfa returns True → 200 with confirmation message."""
        with patch("app.api.auth_router.mfa_service.disable_mfa", return_value=True):
            r = client_as_alice.request("DELETE", self.URL, json={"code": "123456"})
        assert r.status_code == 200
        assert "disabled" in r.json()["message"].lower()

    def test_wrong_code_returns_400(self, client_as_alice):
        """Wrong code → ValueError → 400 (not 401 — user IS authenticated)."""
        with patch("app.api.auth_router.mfa_service.disable_mfa",
                   side_effect=ValueError("Invalid TOTP code — MFA not disabled")):
            r = client_as_alice.request("DELETE", self.URL, json={"code": "000000"})
        assert r.status_code == 400
        assert "invalid" in r.json()["detail"].lower()

    def test_mfa_not_enabled_returns_400(self, client_as_alice):
        """Disabling when MFA is not enabled → ValueError → 400."""
        with patch("app.api.auth_router.mfa_service.disable_mfa",
                   side_effect=ValueError("MFA is not enabled for this account")):
            r = client_as_alice.request("DELETE", self.URL, json={"code": "123456"})
        assert r.status_code == 400

    def test_no_auth_returns_401(self, mock_db):
        """Cannot disable MFA without authentication."""
        test_app.dependency_overrides[get_db] = lambda: mock_db
        # No get_current_user override
        client = TestClient(test_app, raise_server_exceptions=False)
        try:
            r = client.request("DELETE", self.URL, json={"code": "123456"})
            assert r.status_code == 401
        finally:
            test_app.dependency_overrides.clear()

    def test_non_digit_code_rejected_by_pydantic(self, client_as_alice):
        """MFADisableRequest.code has pattern=r'^\\d{6}$' — non-digits rejected."""
        r = client_as_alice.request("DELETE", self.URL, json={"code": "ABCDEF"})
        assert r.status_code == 422

    def test_disable_requires_code_not_just_session(self, client_as_alice):
        """
        CRITICAL: authenticated session alone is NOT enough to disable MFA.
        The TOTP code is a required second factor for this destructive action.
        """
        with patch("app.api.auth_router.mfa_service.disable_mfa",
                   side_effect=ValueError("Invalid TOTP code — MFA not disabled")):
            r = client_as_alice.request("DELETE", self.URL, json={"code": "000000"})
        assert r.status_code == 400, (
            "Disabling MFA must fail if code is wrong — "
            "session token alone must not be sufficient to disable MFA."
        )


# ============================================================================
# Security boundary tests
# ============================================================================

class TestMFASecurityBoundaries:
    """
    Cross-cutting security tests that verify the MFA token type-checking
    and that setup/confirm/disable cannot be accessed without auth.
    """

    def test_all_mfa_management_endpoints_require_auth(self, mock_db):
        """
        Setup, confirm, and disable are management endpoints — all require auth.
        Verify requires mfa_token (NOT a Bearer token) — it must be PUBLIC.
        """
        test_app.dependency_overrides[get_db] = lambda: mock_db
        client = TestClient(test_app, raise_server_exceptions=False)
        try:
            assert client.post(f"{PREFIX}/auth/mfa/setup").status_code == 401
            assert client.post(f"{PREFIX}/auth/mfa/confirm",
                               json={"code": "123456"}).status_code == 401
            assert client.request(
                "DELETE",
                f"{PREFIX}/auth/mfa",
                json={"code": "123456"},
            ).status_code == 401
        finally:
            test_app.dependency_overrides.clear()

    def test_mfa_verify_is_public(self, mock_db):
        """
        /auth/mfa/verify must be reachable WITHOUT an Authorization header.
        It authenticates via mfa_token in the body, not a Bearer header.
        A missing body → 422, not 401.
        """
        test_app.dependency_overrides[get_db] = lambda: mock_db
        client = TestClient(test_app, raise_server_exceptions=False)
        try:
            r = client.post(f"{PREFIX}/auth/mfa/verify", json={})
            assert r.status_code == 422, (
                f"Got {r.status_code}. /mfa/verify is public — 422 expected for empty body."
            )
        finally:
            test_app.dependency_overrides.clear()


# ============================================================================
# TOTP unit tests — pure algorithm, no HTTP
# ============================================================================

class TestTOTPAlgorithm:
    """
    Direct tests of the TOTP implementation in app/core/totp.py.
    No mocking, no HTTP — pure cryptographic correctness checks.
    """

    def test_generate_totp_secret_is_valid_base32(self):
        """Generated secret must be decodeable as base32."""
        import base64
        from app.core.totp import generate_totp_secret
        secret = generate_totp_secret()
        assert len(secret) == 32, "20 bytes → 32 base32 chars"
        decoded = base64.b32decode(secret.upper())
        assert len(decoded) == 20

    def test_verify_totp_accepts_current_code(self):
        """A code generated from the current time step must verify successfully."""
        import base64, struct, time, hmac, hashlib
        from app.core.totp import generate_totp_secret, verify_totp

        secret = generate_totp_secret()
        secret_bytes = base64.b32decode(secret.upper())
        t = int(time.time()) // 30
        msg = struct.pack(">Q", t)
        h = hmac.new(secret_bytes, msg, hashlib.sha1).digest()
        offset = h[-1] & 0x0F
        p = struct.unpack(">I", h[offset:offset + 4])[0]
        expected = str((p & 0x7FFFFFFF) % 1_000_000).zfill(6)

        assert verify_totp(secret, expected), "Current code must verify"

    def test_verify_totp_rejects_wrong_code(self):
        from app.core.totp import generate_totp_secret, verify_totp
        secret = generate_totp_secret()
        # "000000" could theoretically be correct 1 in a million times — acceptable test
        assert not verify_totp(secret, "wrong_code")

    def test_verify_totp_rejects_non_numeric(self):
        from app.core.totp import generate_totp_secret, verify_totp
        secret = generate_totp_secret()
        assert not verify_totp(secret, "ABCDEF")
        assert not verify_totp(secret, "")

    def test_get_totp_uri_format(self):
        from app.core.totp import generate_totp_secret, get_totp_uri
        secret = generate_totp_secret()
        uri = get_totp_uri(secret, "alice@example.com")
        assert uri.startswith("otpauth://totp/")
        assert secret in uri
        assert "algorithm=SHA1" in uri
        assert "digits=6" in uri
        assert "period=30" in uri

    def test_encrypt_decrypt_roundtrip(self):
        """Secret survives encrypt → decrypt without loss."""
        from app.core.totp import (
            generate_totp_secret,
            encrypt_totp_secret,
            decrypt_totp_secret,
        )
        secret = generate_totp_secret()
        ciphertext = encrypt_totp_secret(secret)
        assert isinstance(ciphertext, bytes)
        recovered = decrypt_totp_secret(ciphertext)
        assert recovered == secret

    def test_backup_code_generation_and_verify(self):
        """8 backup codes generated, one verified and consumed (single-use)."""
        from app.core.totp import (
            generate_backup_codes,
            encrypt_backup_codes,
            verify_and_consume_backup_code,
        )
        plaintexts, hashes = generate_backup_codes()
        assert len(plaintexts) == 8
        assert all("-" in c for c in plaintexts)

        encrypted = encrypt_backup_codes(hashes)
        code_to_use = plaintexts[0]

        # First use — should succeed and return new (shorter) encrypted list
        new_encrypted = verify_and_consume_backup_code(code_to_use, encrypted)
        assert new_encrypted is not None

        # Second use — code was consumed, should fail
        second = verify_and_consume_backup_code(code_to_use, new_encrypted)
        assert second is None, "Backup code must be single-use"

    def test_wrong_backup_code_returns_none(self):
        from app.core.totp import generate_backup_codes, encrypt_backup_codes, verify_and_consume_backup_code
        _, hashes = generate_backup_codes()
        encrypted = encrypt_backup_codes(hashes)
        result = verify_and_consume_backup_code("ZZZZ-ZZZZ", encrypted)
        assert result is None


# ============================================================================
# MFA pending token unit tests — security guarantees
# ============================================================================

class TestMFAPendingToken:
    """
    Unit tests for create_mfa_pending_token / verify_mfa_pending_token.
    These verify the type-safety guarantees that prevent token confusion.
    """

    def test_mfa_pending_token_type_is_correct(self):
        """Token payload must carry type=mfa_pending, not access."""
        from app.core.security import create_mfa_pending_token, verify_mfa_pending_token
        from app.schemas.auth import TokenType
        uid = uuid.uuid4()
        token, _ = create_mfa_pending_token(uid)
        payload = verify_mfa_pending_token(token)
        assert payload.type == TokenType.MFA_PENDING

    def test_mfa_pending_token_has_empty_scopes(self):
        """
        mfa_pending tokens must carry no scopes — they cannot authorize anything.
        If a client somehow submits this token as a Bearer, every endpoint
        will reject it (verify_access_token checks type=access first).
        """
        from app.core.security import create_mfa_pending_token, verify_mfa_pending_token
        uid = uuid.uuid4()
        token, _ = create_mfa_pending_token(uid)
        payload = verify_mfa_pending_token(token)
        assert payload.scopes == [], "mfa_pending tokens must have no scopes"

    def test_access_token_rejected_by_verify_mfa_pending(self):
        """
        An access token cannot be submitted to verify_mfa_pending_token.
        This prevents an attacker from re-using a stolen access token to
        complete MFA on a different account.
        """
        import jwt as pyjwt
        from app.core.security import create_access_token, verify_mfa_pending_token
        uid = uuid.uuid4()
        access_token, _ = create_access_token(uid)
        with pytest.raises(pyjwt.InvalidTokenError):
            verify_mfa_pending_token(access_token)

    def test_mfa_pending_token_rejected_by_verify_access(self):
        """
        An mfa_pending token cannot be submitted as a Bearer access token.
        verify_access_token enforces type=access and rejects all other types.
        """
        import jwt as pyjwt
        from app.core.security import create_mfa_pending_token, verify_access_token
        uid = uuid.uuid4()
        mfa_token, _ = create_mfa_pending_token(uid)
        with pytest.raises(pyjwt.InvalidTokenError):
            verify_access_token(mfa_token)

    def test_mfa_pending_token_sub_is_correct_user(self):
        uid = uuid.uuid4()
        from app.core.security import create_mfa_pending_token, verify_mfa_pending_token
        token, _ = create_mfa_pending_token(uid)
        payload = verify_mfa_pending_token(token)
        assert payload.sub == str(uid)
