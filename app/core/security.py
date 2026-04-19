"""
Security utilities:
- Password hashing (bcrypt)
- JWT access token creation (aligned with TokenPayload schema)
- MFA pending token creation (short-lived, type=mfa_pending)
- Secure refresh token generation
- Token hashing
- Token verification with TokenPayload validation
"""

from datetime import datetime, timedelta, timezone
from typing import Optional
import uuid

import jwt
from passlib.context import CryptContext
from hashlib import sha256
import secrets

from app.core.config import settings
from app.schemas.auth import TokenPayload, TokenType, SCOPE_READ_ONLY

# =====================================================
# PASSWORD HASHING
# =====================================================

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


def get_password_hash(password: str) -> str:
    """Hash a plain-text password using bcrypt."""
    return pwd_context.hash(password)


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """Verify a plain-text password against a bcrypt hash."""
    return pwd_context.verify(plain_password, hashed_password)


# =====================================================
# JWT CONFIGURATION
# =====================================================

ALGORITHM = settings.ALGORITHM


def create_access_token(
    user_id: str | uuid.UUID,
    session_id: Optional[uuid.UUID] = None,
    scopes: Optional[list[str]] = None,
) -> tuple[str, datetime]:
    """
    Create short-lived JWT access token.
    Aligned with TokenPayload: int timestamps, mandatory type, scopes for least-privilege.
    """
    now = datetime.now(timezone.utc)
    expire = now + timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)

    payload = {
        "sub": str(user_id),
        "exp": int(expire.timestamp()),
        "iat": int(now.timestamp()),
        "type": TokenType.ACCESS.value,
        "scopes": scopes if scopes is not None else [SCOPE_READ_ONLY],
    }
    if session_id is not None:
        payload["session_id"] = str(session_id)

    encoded_jwt = jwt.encode(payload, settings.SECRET_KEY, algorithm=ALGORITHM)
    return encoded_jwt, expire


# =====================================================
# MFA PENDING TOKEN
# =====================================================

def create_mfa_pending_token(user_id: str | uuid.UUID) -> tuple[str, datetime]:
    """
    Create a short-lived MFA pending token issued after password verification.

    This token is NOT an access token — it cannot authorize any API endpoint.
    Its sole purpose: prove the user passed the password check, so the MFA
    verification endpoint (/auth/mfa/verify) can trust the user_id claim
    without requiring them to send their password again.

    type = "mfa_pending" — verify_access_token explicitly rejects this type,
    so even if a client submits it as a Bearer token, every protected endpoint
    will return 401. There is no way to use this token as an API credential.

    Lifetime: MFA_PENDING_EXPIRE_MINUTES (default 5 minutes) — short enough
    to prevent replay if intercepted, long enough for the user to pick up
    their phone and enter the code.
    """
    now = datetime.now(timezone.utc)
    expire = now + timedelta(minutes=settings.MFA_PENDING_EXPIRE_MINUTES)

    payload = {
        "sub": str(user_id),
        "exp": int(expire.timestamp()),
        "iat": int(now.timestamp()),
        "type": TokenType.MFA_PENDING.value,
        "scopes": [],    # Explicitly empty — this token authorizes NOTHING
    }

    encoded_jwt = jwt.encode(payload, settings.SECRET_KEY, algorithm=ALGORITHM)
    return encoded_jwt, expire


def verify_mfa_pending_token(token: str) -> TokenPayload:
    """
    Decode and validate an MFA pending token.

    Raises jwt.InvalidTokenError if:
      - Token signature is invalid
      - Token is expired
      - Token type is not 'mfa_pending' (prevents access tokens being used here)

    Type check is critical: without it, a leaked access token could be submitted
    to /auth/mfa/verify and the handler would trust the user_id inside it.
    """
    try:
        payload = jwt.decode(token, settings.SECRET_KEY, algorithms=[ALGORITHM])
        parsed = TokenPayload(**payload)

        if parsed.type != TokenType.MFA_PENDING:
            raise jwt.InvalidTokenError(
                "Invalid token type: expected mfa_pending token"
            )

        return parsed

    except jwt.InvalidTokenError:
        raise jwt.InvalidTokenError("Invalid or expired MFA token")


# =====================================================
# REFRESH TOKEN GENERATION
# =====================================================

def create_refresh_token() -> str:
    """Generate secure random refresh token (NOT a JWT)."""
    return secrets.token_urlsafe(64)


def hash_token(token: str) -> str:
    """Hash refresh token before storing in database."""
    return sha256(token.encode()).hexdigest()


# =====================================================
# TOKEN VERIFICATION
# =====================================================

def verify_access_token(token: str) -> TokenPayload:
    """
    Decode and validate access token.
    Returns TokenPayload if valid (enforces type=access, UUID sub, required iat).
    Explicitly rejects mfa_pending tokens — they cannot be used as API credentials.
    Raises jwt.InvalidTokenError on invalid/expired token.
    """
    try:
        payload = jwt.decode(token, settings.SECRET_KEY, algorithms=[ALGORITHM])
        parsed = TokenPayload(**payload)

        if parsed.type != TokenType.ACCESS:
            raise jwt.InvalidTokenError("Invalid token type: expected access token")

        return parsed

    except jwt.InvalidTokenError:
        raise jwt.InvalidTokenError("Invalid or expired token")


def create_password_reset_token(email: str, expires_minutes: int = 15) -> tuple[str, datetime]:
    """
    Create short-lived password-reset token.
    Uses a distinct token type to prevent cross-use with access tokens.
    """
    now = datetime.now(timezone.utc)
    expire = now + timedelta(minutes=expires_minutes)
    payload = {
        "sub": email,
        "exp": int(expire.timestamp()),
        "iat": int(now.timestamp()),
        "type": "password_reset",
    }
    encoded = jwt.encode(payload, settings.SECRET_KEY, algorithm=ALGORITHM)
    return encoded, expire


def verify_password_reset_token(token: str) -> str:
    """
    Validate password-reset token and return email (sub).
    Raises jwt.InvalidTokenError for invalid/expired/type mismatch.
    """
    try:
        payload = jwt.decode(token, settings.SECRET_KEY, algorithms=[ALGORITHM])
        if payload.get("type") != "password_reset":
            raise jwt.InvalidTokenError("Invalid token type")
        email = payload.get("sub")
        if not isinstance(email, str) or not email:
            raise jwt.InvalidTokenError("Invalid token subject")
        return email
    except jwt.InvalidTokenError:
        raise jwt.InvalidTokenError("Invalid or expired reset token")
