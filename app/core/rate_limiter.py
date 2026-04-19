"""
app/core/rate_limiter.py — In-memory sliding window rate limiter.

Why in-memory and not Redis?
  Redis would be the right choice for a multi-process production deployment
  (rate limit state must be shared across workers). For a single-process
  deployment (one Uvicorn worker) or during development, in-memory is
  sufficient and adds zero infrastructure dependencies.

  The limiter is designed so the storage backend can be swapped out: replace
  _store with a Redis-backed implementation and the FastAPI dependency
  (RateLimiter) stays unchanged.

Algorithm: sliding window counter
  For each (key, endpoint) pair, we keep a deque of request timestamps.
  On each request:
    1. Discard timestamps older than window_seconds.
    2. If len(deque) >= max_requests → reject with 429.
    3. Otherwise append now and allow.

  This is an O(n) per request where n = requests in the window, but n is
  bounded by max_requests (typically 5-20), so it's effectively O(1).

  A fixed window counter (simpler) allows up to 2× the limit at window
  boundaries. The sliding window has no such burst. For a login endpoint
  protecting against credential stuffing, the sliding window is preferable.

Thread safety:
  Python's GIL makes deque.append() and len() effectively atomic for
  single-process deployments. For multi-threaded ASGI servers (Uvicorn with
  multiple threads), a threading.Lock per key would be required. The current
  implementation is safe for Uvicorn's default async single-thread model.

Key format:
  "{client_ip}:{endpoint_name}"  — limits per IP per endpoint.
  This prevents one abusive client from exhausting the global limit, while
  allowing the same IP to hit different endpoints at full speed.
"""

import threading
import time
from collections import defaultdict, deque
from typing import Optional

from fastapi import HTTPException, Request, status


# ─────────────────────────────────────────────────────────────────────────────
# In-memory store
# ─────────────────────────────────────────────────────────────────────────────

# deque of float timestamps (time.monotonic()) per (ip, endpoint) key
_store: dict[str, deque] = defaultdict(deque)

# One lock per key avoids a global lock becoming a bottleneck under load
_locks: dict[str, threading.Lock] = defaultdict(threading.Lock)


def _get_client_key(request: Request, endpoint_name: str) -> str:
    """
    Build a per-IP, per-endpoint key.
    X-Forwarded-For is checked first (set by nginx/ALB in production).
    Falls back to the direct connection IP for local development.
    """
    forwarded_for = request.headers.get("X-Forwarded-For")
    if forwarded_for:
        ip = forwarded_for.split(",")[0].strip()
    else:
        ip = request.client.host if request.client else "unknown"

    return f"{ip}:{endpoint_name}"


def check_rate_limit(
    request: Request,
    endpoint_name: str,
    max_requests: int,
    window_seconds: int,
) -> None:
    """
    Sliding window rate limit check. Raises HTTP 429 if limit exceeded.

    Args:
        request:        FastAPI Request (used to extract client IP)
        endpoint_name:  stable string identifying the endpoint (e.g. "login")
        max_requests:   maximum number of requests allowed in the window
        window_seconds: length of the sliding window in seconds

    Raises:
        HTTPException(429) with Retry-After header when limit is exceeded.
    """
    key = _get_client_key(request, endpoint_name)
    now = time.monotonic()
    cutoff = now - window_seconds

    with _locks[key]:
        timestamps = _store[key]

        # Remove timestamps outside the current window
        while timestamps and timestamps[0] < cutoff:
            timestamps.popleft()

        if len(timestamps) >= max_requests:
            # Calculate how long until the oldest request ages out
            retry_after = int(timestamps[0] - cutoff) + 1
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail=(
                    f"Too many requests. Maximum {max_requests} attempts "
                    f"per {window_seconds} seconds."
                ),
                headers={
                    "Retry-After": str(retry_after),
                    "X-RateLimit-Limit": str(max_requests),
                    "X-RateLimit-Window": str(window_seconds),
                },
            )

        timestamps.append(now)


def reset_rate_limit(request: Request, endpoint_name: str) -> None:
    """
    Clear rate limit state for a client/endpoint pair.
    Used in tests to ensure a clean slate between test cases.
    Not called in production code.
    """
    key = _get_client_key(request, endpoint_name)
    with _locks[key]:
        _store[key].clear()


# ─────────────────────────────────────────────────────────────────────────────
# FastAPI dependency factories
# ─────────────────────────────────────────────────────────────────────────────

class RateLimiter:
    """
    FastAPI dependency that applies a sliding window rate limit.

    Usage in a router:

        @router.post("/login")
        def login(
            request: Request,
            _: None = Depends(RateLimiter("login", max_requests=5, window_seconds=60)),
        ):
            ...

    Each RateLimiter instance is a stable callable so it can be overridden
    in tests via app.dependency_overrides:

        app.dependency_overrides[login_limiter] = lambda: None  # disable in tests
    """

    def __init__(
        self,
        endpoint_name: str,
        max_requests: int,
        window_seconds: int,
    ) -> None:
        self.endpoint_name = endpoint_name
        self.max_requests = max_requests
        self.window_seconds = window_seconds

    def __call__(self, request: Request) -> None:
        check_rate_limit(
            request,
            self.endpoint_name,
            self.max_requests,
            self.window_seconds,
        )


# ─────────────────────────────────────────────────────────────────────────────
# Pre-configured limiters for each sensitive endpoint
#
# Defined here (not in the router) so tests can import and override them
# individually. If defined inline in the router decorator, they become
# anonymous lambda-equivalents that cannot be targeted by dependency_overrides.
# ─────────────────────────────────────────────────────────────────────────────

# POST /auth/login
# 5 attempts per minute per IP.
# Rationale: a human can mistype a password 5 times in a minute.
# A credential-stuffing bot can attempt thousands. This stops the latter
# without locking out the former.
login_rate_limiter = RateLimiter(
    endpoint_name="login",
    max_requests=5,
    window_seconds=60,
)

# POST /auth/mfa/verify
# 5 attempts per 5 minutes per IP.
# MFA codes rotate every 30 seconds (3 valid codes in a 5-minute window at
# most, counting the ±1 drift window). 5 attempts is generous for legitimate
# use while blocking brute-force across the ~1,000,000 possible 6-digit codes.
mfa_verify_rate_limiter = RateLimiter(
    endpoint_name="mfa_verify",
    max_requests=5,
    window_seconds=300,
)

# POST /auth/register
# 3 registrations per hour per IP.
# Prevents automated account creation / fake account farms.
register_rate_limiter = RateLimiter(
    endpoint_name="register",
    max_requests=3,
    window_seconds=3600,
)