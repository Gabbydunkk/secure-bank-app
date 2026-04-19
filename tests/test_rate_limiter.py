"""
tests/test_rate_limiter.py — Rate limiter tests.

Tests cover:
  Unit (check_rate_limit directly):
    - Requests under the limit pass through
    - Request at limit passes; request over limit returns 429
    - Sliding window: old requests expire and new ones are allowed
    - 429 response includes Retry-After header
    - 429 response includes X-RateLimit-Limit and X-RateLimit-Window headers
    - Different IPs have independent counters
    - Different endpoints have independent counters
    - reset_rate_limit clears the counter

  HTTP (via TestClient):
    - POST /auth/login returns 429 after 5 attempts from same IP
    - POST /auth/mfa/verify returns 429 after 5 attempts
    - POST /auth/register returns 429 after 3 attempts
    - Rate limit does not fire when dependency is overridden (test mode)

Run: pytest tests/test_rate_limiter.py -v
"""

import time
import uuid
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

import pytest
from fastapi import FastAPI, Request
from fastapi.testclient import TestClient

from app.core.rate_limiter import (
    RateLimiter,
    check_rate_limit,
    login_rate_limiter,
    mfa_verify_rate_limiter,
    register_rate_limiter,
    reset_rate_limit,
    _store,
)
from app.api.auth_router import router as auth_router
from app.api.deps import get_current_user, get_current_session
from app.models.database import get_db
from app.schemas.auth import LoginResponse, Token


# ============================================================================
# Helpers
# ============================================================================

PREFIX = "/api/v1"

test_app = FastAPI()
test_app.include_router(auth_router, prefix=PREFIX)


def _mock_request(ip: str = "1.2.3.4") -> MagicMock:
    """Build a minimal mock Request with a controllable client IP."""
    req = MagicMock(spec=Request)
    req.client = MagicMock()
    req.client.host = ip
    req.headers = {}
    return req


def _clear_limiter(endpoint: str, ip: str = "1.2.3.4") -> None:
    """Clear stored timestamps for a given (ip, endpoint) key."""
    key = f"{ip}:{endpoint}"
    _store[key].clear()


def _clear_limiter_endpoint_all_ips(endpoint: str) -> None:
    """Clear limiter state for an endpoint across all IP keys."""
    suffix = f":{endpoint}"
    for key in list(_store.keys()):
        if key.endswith(suffix):
            _store[key].clear()


def _login_response() -> LoginResponse:
    return LoginResponse(
        tokens=Token(
            access_token="tok",
            refresh_token="ref",
            token_type="bearer",
            expires_in=900,
        ),
        user_id=uuid.uuid4(),
        email="alice@example.com",
        username="alice",
    )


# ============================================================================
# Unit tests — check_rate_limit() directly
# ============================================================================

class TestCheckRateLimitUnit:

    def setup_method(self):
        """Clear state before each test."""
        _clear_limiter("test_endpoint")
        _clear_limiter("test_endpoint", ip="5.5.5.5")

    def test_single_request_allowed(self):
        req = _mock_request()
        # Should not raise
        check_rate_limit(req, "test_endpoint", max_requests=3, window_seconds=60)

    def test_requests_up_to_limit_all_pass(self):
        req = _mock_request()
        for _ in range(3):
            check_rate_limit(req, "test_endpoint", max_requests=3, window_seconds=60)
        # Third request should have passed without exception

    def test_request_over_limit_raises_429(self):
        from fastapi import HTTPException
        req = _mock_request()
        for _ in range(3):
            check_rate_limit(req, "test_endpoint", max_requests=3, window_seconds=60)
        with pytest.raises(HTTPException) as exc_info:
            check_rate_limit(req, "test_endpoint", max_requests=3, window_seconds=60)
        assert exc_info.value.status_code == 429

    def test_retry_after_header_present_on_429(self):
        from fastapi import HTTPException
        req = _mock_request()
        for _ in range(2):
            check_rate_limit(req, "test_endpoint", max_requests=2, window_seconds=60)
        with pytest.raises(HTTPException) as exc_info:
            check_rate_limit(req, "test_endpoint", max_requests=2, window_seconds=60)
        assert "Retry-After" in exc_info.value.headers
        assert int(exc_info.value.headers["Retry-After"]) > 0

    def test_x_ratelimit_headers_present(self):
        from fastapi import HTTPException
        req = _mock_request()
        for _ in range(2):
            check_rate_limit(req, "test_endpoint", max_requests=2, window_seconds=60)
        with pytest.raises(HTTPException) as exc_info:
            check_rate_limit(req, "test_endpoint", max_requests=2, window_seconds=60)
        headers = exc_info.value.headers
        assert headers["X-RateLimit-Limit"] == "2"
        assert headers["X-RateLimit-Window"] == "60"

    def test_different_ips_have_independent_counters(self):
        """IP 1.2.3.4 exhausting its limit must not affect 5.5.5.5."""
        from fastapi import HTTPException
        req_a = _mock_request("1.2.3.4")
        req_b = _mock_request("5.5.5.5")

        # Exhaust IP A
        for _ in range(2):
            check_rate_limit(req_a, "test_endpoint", max_requests=2, window_seconds=60)
        with pytest.raises(HTTPException):
            check_rate_limit(req_a, "test_endpoint", max_requests=2, window_seconds=60)

        # IP B should still be allowed
        check_rate_limit(req_b, "test_endpoint", max_requests=2, window_seconds=60)

    def test_different_endpoints_have_independent_counters(self):
        """Exhausting /login limit must not affect /register limit."""
        from fastapi import HTTPException
        req = _mock_request()
        _clear_limiter("endpoint_a")
        _clear_limiter("endpoint_b")

        for _ in range(2):
            check_rate_limit(req, "endpoint_a", max_requests=2, window_seconds=60)
        with pytest.raises(HTTPException):
            check_rate_limit(req, "endpoint_a", max_requests=2, window_seconds=60)

        # endpoint_b counter is independent
        check_rate_limit(req, "endpoint_b", max_requests=2, window_seconds=60)

    def test_old_requests_expire_and_new_ones_pass(self):
        """
        Sliding window: timestamps older than window_seconds are discarded.
        After expiry, the counter effectively resets.
        Patching time.monotonic to simulate time passing without actually sleeping.
        """
        import app.core.rate_limiter as rl_module
        req = _mock_request()
        _clear_limiter("expiry_test")

        base_time = 1000.0

        with patch.object(rl_module, "time") as mock_time:
            mock_time.monotonic.return_value = base_time
            # Fill the window
            for _ in range(2):
                check_rate_limit(req, "expiry_test", max_requests=2, window_seconds=60)

            # Advance time past the window
            mock_time.monotonic.return_value = base_time + 61

            # Old timestamps are now outside window — should be allowed again
            check_rate_limit(req, "expiry_test", max_requests=2, window_seconds=60)

    def test_reset_clears_counter(self):
        req = _mock_request()
        for _ in range(2):
            check_rate_limit(req, "test_endpoint", max_requests=2, window_seconds=60)

        reset_rate_limit(req, "test_endpoint")

        # After reset, counter is clear — 2 more allowed
        check_rate_limit(req, "test_endpoint", max_requests=2, window_seconds=60)
        check_rate_limit(req, "test_endpoint", max_requests=2, window_seconds=60)


# ============================================================================
# RateLimiter class
# ============================================================================

class TestRateLimiterClass:

    def test_callable_passes_under_limit(self):
        limiter = RateLimiter("class_test", max_requests=3, window_seconds=60)
        req = _mock_request("9.9.9.9")
        _clear_limiter("class_test", ip="9.9.9.9")
        limiter(req)   # should not raise

    def test_callable_raises_429_over_limit(self):
        from fastapi import HTTPException
        limiter = RateLimiter("class_test2", max_requests=1, window_seconds=60)
        req = _mock_request("9.9.9.9")
        _clear_limiter("class_test2", ip="9.9.9.9")
        limiter(req)
        with pytest.raises(HTTPException) as exc_info:
            limiter(req)
        assert exc_info.value.status_code == 429

    def test_pre_configured_login_limiter_has_correct_settings(self):
        assert login_rate_limiter.max_requests == 5
        assert login_rate_limiter.window_seconds == 60
        assert login_rate_limiter.endpoint_name == "login"

    def test_pre_configured_mfa_limiter_has_correct_settings(self):
        assert mfa_verify_rate_limiter.max_requests == 5
        assert mfa_verify_rate_limiter.window_seconds == 300
        assert mfa_verify_rate_limiter.endpoint_name == "mfa_verify"

    def test_pre_configured_register_limiter_has_correct_settings(self):
        assert register_rate_limiter.max_requests == 3
        assert register_rate_limiter.window_seconds == 3600
        assert register_rate_limiter.endpoint_name == "register"


# ============================================================================
# HTTP integration — rate limit fires through the full FastAPI stack
# ============================================================================

class TestRateLimitHTTP:
    """
    These tests drive the full HTTP stack to confirm rate limiting
    is wired into the router decorators correctly.
    The auth service calls are mocked so tests don't need a DB.
    """

    @pytest.fixture(autouse=True)
    def setup_db_override(self):
        test_app.dependency_overrides[get_db] = lambda: MagicMock()
        yield
        test_app.dependency_overrides.clear()

    @pytest.fixture()
    def client(self):
        return TestClient(test_app, raise_server_exceptions=False)

    def _clear_all(self):
        for ep in ("login", "mfa_verify", "register"):
            _clear_limiter_endpoint_all_ips(ep)

    def test_login_returns_429_after_5_attempts(self, client):
        """
        POST /auth/login allows 5 attempts then returns 429.
        The 6th request must be blocked regardless of credentials.
        """
        self._clear_all()
        with patch("app.services.auth_service.login",
                   side_effect=Exception("ignore")):
            for i in range(5):
                r = client.post(f"{PREFIX}/auth/login",
                                json={"email": "x@x.com", "password": "pass"})
                assert r.status_code != 429, f"blocked early on attempt {i+1}"

            # 6th should be rate-limited
            r = client.post(f"{PREFIX}/auth/login",
                            json={"email": "x@x.com", "password": "pass"})
            assert r.status_code == 429
            assert "Retry-After" in r.headers

    def test_login_429_message_is_informative(self, client):
        self._clear_all()
        with patch("app.services.auth_service.login",
                   side_effect=Exception("ignore")):
            for _ in range(5):
                client.post(f"{PREFIX}/auth/login",
                            json={"email": "x@x.com", "password": "pass"})
            r = client.post(f"{PREFIX}/auth/login",
                            json={"email": "x@x.com", "password": "pass"})
        assert r.status_code == 429
        detail = r.json()["detail"]
        assert "5" in detail           # max_requests
        assert "60" in detail          # window_seconds

    def test_mfa_verify_returns_429_after_5_attempts(self, client):
        self._clear_all()
        with patch("app.services.auth_service.verify_mfa_and_login",
                   side_effect=Exception("ignore")):
            for i in range(5):
                r = client.post(f"{PREFIX}/auth/mfa/verify",
                                json={"mfa_token": "tok", "code": "123456"})
                assert r.status_code != 429, f"blocked early on attempt {i+1}"

            r = client.post(f"{PREFIX}/auth/mfa/verify",
                            json={"mfa_token": "tok", "code": "123456"})
            assert r.status_code == 429

    def test_register_returns_429_after_3_attempts(self, client):
        self._clear_all()
        valid_body = {
            "email": "new@x.com", "username": "newuser",
            "first_name": "A", "last_name": "B",
            "password": "SecurePass123!",
        }
        with patch("app.services.auth_service.register_user",
                   side_effect=Exception("ignore")):
            for i in range(3):
                r = client.post(f"{PREFIX}/auth/register", json=valid_body)
                assert r.status_code != 429, f"blocked early on attempt {i+1}"

            r = client.post(f"{PREFIX}/auth/register", json=valid_body)
            assert r.status_code == 429

    def test_rate_limit_can_be_disabled_for_tests(self):
        """
        When rate limiters are overridden in dependency_overrides, they
        are completely bypassed — tests can hit endpoints freely.
        This is the standard pattern for the rest of the test suite.
        """
        test_app.dependency_overrides[login_rate_limiter] = lambda: None

        mock_db = MagicMock()
        test_app.dependency_overrides[get_db] = lambda: mock_db

        self._clear_all()
        client = TestClient(test_app, raise_server_exceptions=False)

        with patch("app.services.auth_service.login",
                   side_effect=Exception("ignore")):
            # Hit 10 times — should never get 429
            for _ in range(10):
                r = client.post(f"{PREFIX}/auth/login",
                                json={"email": "x@x.com", "password": "pass"})
                assert r.status_code != 429

        test_app.dependency_overrides.clear()
