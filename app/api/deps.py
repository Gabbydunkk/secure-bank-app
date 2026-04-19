"""
FastAPI dependency injection for JWT authentication.
Used by routers to protect endpoints — just add `current_user: User = Depends(get_current_user)`.

Design:
- get_current_user       → validates JWT, returns User (active accounts only)
- get_current_session    → also validates the session is still active in DB (revocation check)
- require_scope          → factory that enforces a specific JWT scope (least-privilege)
- get_optional_user      → returns None instead of raising 401 (for public-but-personalized routes)
"""

import jwt as pyjwt
from datetime import datetime, timezone
from fastapi import Depends, HTTPException, Request, Security, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from sqlalchemy.orm import Session

from app.core.security import hash_token, verify_access_token
from app.models.database import get_db
from app.models.user import Session as SessionModel, User
from app.schemas.auth import SCOPE_MFA_ELEVATED, SCOPE_READ_ONLY, SCOPE_TRANSFER_AUTHORIZED
from app.schemas.auth import SCOPE_ANALYST, SCOPE_ADMIN


# ---------------------------------------------------------------------------
# Bearer token extractor — reads "Authorization: Bearer <token>" header
# ---------------------------------------------------------------------------

# auto_error=False so we can return a clean 401 with our own message format
bearer_scheme = HTTPBearer(auto_error=False)


def _extract_token(
    credentials: HTTPAuthorizationCredentials | None,
) -> str:
    """Pull raw token string from Authorization header, or raise 401."""
    if credentials is None or credentials.scheme.lower() != "bearer":
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing or invalid Authorization header. Use: Bearer <token>",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return credentials.credentials


# ---------------------------------------------------------------------------
# Core dependency: validate JWT → return User
# ---------------------------------------------------------------------------

def get_current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
    db: Session = Depends(get_db),
) -> User:
    """
    Dependency: decode and validate the JWT access token, then load the user from DB.

    Steps:
      1. Extract Bearer token from Authorization header.
      2. Decode and validate the JWT (signature, expiry, type=access).
      3. Load the user from the database by UUID (sub claim).
      4. Reject if account is not active.

    Raises HTTP 401 for invalid/expired tokens.
    Raises HTTP 403 for suspended/locked/closed accounts.
    """
    token = _extract_token(credentials)

    try:
        payload = verify_access_token(token)
    except pyjwt.InvalidTokenError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=str(exc),
            headers={"WWW-Authenticate": "Bearer"},
        )

    user = db.query(User).filter(User.id == payload.sub).first()
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User not found",
            headers={"WWW-Authenticate": "Bearer"},
        )
    if user.account_status != "active":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"Account is {user.account_status}",
        )
    return user


# ---------------------------------------------------------------------------
# Stricter dependency: validate JWT + verify session is still active in DB
# (catches revoked tokens after logout)
# ---------------------------------------------------------------------------

def get_current_session(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
    db: Session = Depends(get_db),
) -> tuple[User, SessionModel]:
    """
    Dependency: like get_current_user but also checks the session is still alive in DB.
    Use this for sensitive operations (logout, transfer authorization) where token
    revocation must be respected immediately.

    Returns (user, session) tuple.
    """
    token = _extract_token(credentials)

    try:
        payload = verify_access_token(token)
    except pyjwt.InvalidTokenError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=str(exc),
            headers={"WWW-Authenticate": "Bearer"},
        )

    # Look up the session by token hash — this is how we enforce revocation
    token_hash = hash_token(token)
    session = (
        db.query(SessionModel)
        .filter(
            SessionModel.access_token_hash == token_hash,
            SessionModel.is_active.is_(True),
            SessionModel.expires_at > datetime.now(timezone.utc),
        )
        .first()
    )
    if session is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Session not found or has been revoked",
            headers={"WWW-Authenticate": "Bearer"},
        )

    user = db.query(User).filter(User.id == session.user_id).first()
    if user is None or user.account_status != "active":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="User account is no longer active",
        )
    return user, session


# ---------------------------------------------------------------------------
# Scope enforcement — factory function for least-privilege checks
# ---------------------------------------------------------------------------

def require_scope(required_scope: str):
    """
    Dependency factory: enforce that the JWT contains a specific scope.

    Usage in a router:
        @router.post("/transfer")
        def create_transfer(
            _: None = Depends(require_scope(SCOPE_TRANSFER_AUTHORIZED)),
            current_user: User = Depends(get_current_user),
        ):
            ...

    Raises HTTP 403 if the token's scopes list does not contain required_scope.
    """

    def _check(
        credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
    ) -> None:
        token = _extract_token(credentials)
        try:
            payload = verify_access_token(token)
        except pyjwt.InvalidTokenError as exc:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail=str(exc),
                headers={"WWW-Authenticate": "Bearer"},
            )
        if required_scope not in payload.scopes:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Insufficient permissions. Required scope: '{required_scope}'",
            )

    return _check


# Stable named dependency for transfer authorization checks.
# Named object is easier to override in tests than inline require_scope(...) closures.
require_transfer_authorized = require_scope(SCOPE_TRANSFER_AUTHORIZED)


# ---------------------------------------------------------------------------
# Optional user — returns None for unauthenticated requests instead of 401
# Useful for endpoints that work for both guests and logged-in users
# ---------------------------------------------------------------------------

def get_optional_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
    db: Session = Depends(get_db),
) -> User | None:
    """
    Dependency: returns the authenticated User or None (never raises 401).
    Use for public endpoints that can be personalized for logged-in users.
    """
    if credentials is None:
        return None
    try:
        return get_current_user(credentials=credentials, db=db)
    except HTTPException:
        return None


# ---------------------------------------------------------------------------
# IP address extraction helper (used by routers for audit/fraud context)
# ---------------------------------------------------------------------------

def get_client_ip(request: Request) -> str | None:
    """
    Extract the real client IP from the request.
    Checks X-Forwarded-For first (set by reverse proxies like nginx/AWS ALB),
    then falls back to the direct connection IP.

    NOTE: In production, only trust X-Forwarded-For if your load balancer sets it.
    """
    forwarded_for = request.headers.get("X-Forwarded-For")
    if forwarded_for:
        # X-Forwarded-For: client, proxy1, proxy2 → take the first (real client)
        return forwarded_for.split(",")[0].strip()
    return request.client.host if request.client else None

# ---------------------------------------------------------------------------
# Role-based authorization — scope hierarchy enforcement
#
# Why a hierarchy instead of plain require_scope("analyst")?
#
#   require_scope() is a closure factory — each call creates a new function
#   object, which makes it impossible to override cleanly in tests via
#   app.dependency_overrides (the key must match the exact function object
#   registered in the route's dependency list).
#
#   require_analyst is a named module-level function: one stable object.
#   Tests can replace it with a single line:
#       app.dependency_overrides[require_analyst] = lambda: None   # allow
#       app.dependency_overrides[require_analyst] = _deny          # deny
#
#   The rank table makes admin tokens automatically satisfy analyst checks
#   without needing to list both scopes in the token.
# ---------------------------------------------------------------------------

_SCOPE_RANK: dict[str, int] = {
    SCOPE_READ_ONLY:            1,
    SCOPE_TRANSFER_AUTHORIZED:  2,
    SCOPE_MFA_ELEVATED:         3,
    SCOPE_ANALYST:              4,
    SCOPE_ADMIN:                5,
}


def _highest_rank(scopes: list[str]) -> int:
    """Return the highest privilege rank found in the token's scope list."""
    return max((_SCOPE_RANK.get(s, 0) for s in scopes), default=0)


def require_analyst(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
) -> None:
    """
    Dependency: JWT must carry 'analyst' or 'admin' scope (rank >= 4).

    Used on endpoints that fraud analysts operate, e.g.:
        POST /transactions/{id}/block
        PATCH /fraud/alerts/{id}/status  (future)

    HTTP responses:
      401 — token missing or cryptographically invalid
      403 — token valid but scopes are below analyst level

    Usage in a router:
        @router.post("/{id}/block", dependencies=[Depends(require_analyst)])
        def block_transaction(...): ...
    """
    token = _extract_token(credentials)
    try:
        payload = verify_access_token(token)
    except pyjwt.InvalidTokenError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=str(exc),
            headers={"WWW-Authenticate": "Bearer"},
        )
    if _highest_rank(payload.scopes) < _SCOPE_RANK[SCOPE_ANALYST]:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=(
                "Insufficient permissions. "
                "This action requires the 'analyst' or 'admin' role."
            ),
        )


def require_admin(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
) -> None:
    """
    Dependency: JWT must carry 'admin' scope (rank 5).
    Use on system-configuration and user-management endpoints.
    Same test-override pattern as require_analyst applies.
    """
    token = _extract_token(credentials)
    try:
        payload = verify_access_token(token)
    except pyjwt.InvalidTokenError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=str(exc),
            headers={"WWW-Authenticate": "Bearer"},
        )
    if _highest_rank(payload.scopes) < _SCOPE_RANK[SCOPE_ADMIN]:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=(
                "Insufficient permissions. "
                "This action requires the 'admin' role."
            ),
        )
        
