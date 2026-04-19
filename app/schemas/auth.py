"""
Auth schemas for JWT tokens, login response, MFA, and session handling.
Supports Login endpoint, JWT + session creation, and MFA verification workflow.
Implements least-privilege via scopes for critical banking operations.
"""
from enum import Enum
from pydantic import BaseModel, Field, field_validator
from typing import Optional
import uuid
import re


class TokenType(str, Enum):
    """
    Mandatory token type — prevents token confusion in critical flows.

    ACCESS      → short-lived API credential (15 min). Authorizes endpoints.
    REFRESH     → long-lived rotation token (7 days). Only for /auth/refresh.
    MFA_PENDING → ephemeral step-up ticket (5 min). Only for /auth/mfa/verify.
                  Cannot be used as an API access token — verify_access_token
                  explicitly rejects it so it can never bypass authentication.
    """
    ACCESS      = "access"
    REFRESH     = "refresh"
    MFA_PENDING = "mfa_pending"


# Scope constants — privilege hierarchy
# rank: read_only(1) < transfer_authorized(2) < mfa_elevated(3) < analyst(4) < admin(5)
# Higher rank automatically satisfies every lower rank check (see deps.py).
SCOPE_READ_ONLY           = "read_only"
SCOPE_TRANSFER_AUTHORIZED = "transfer_authorized"
SCOPE_MFA_ELEVATED        = "mfa_elevated"
SCOPE_ANALYST             = "analyst"
SCOPE_ADMIN               = "admin"


class Token(BaseModel):
    """JWT access token + refresh token pair — issued on successful login."""
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    expires_in: int = Field(..., description="Access token lifetime in seconds")


class TokenPayload(BaseModel):
    """
    Decoded JWT payload — used internally for validation.
    exp/iat are Unix timestamps (int). iat required for token age and audit.
    """
    sub: str
    exp: int
    iat: int
    session_id: Optional[uuid.UUID] = None
    type: TokenType
    scopes: list[str] = Field(default_factory=lambda: [SCOPE_READ_ONLY])

    @field_validator("type", mode="before")
    @classmethod
    def parse_token_type(cls, v):
        if isinstance(v, TokenType):
            return v
        if isinstance(v, str):
            return TokenType(v)
        raise ValueError("type must be 'access', 'refresh', or 'mfa_pending'")

    @field_validator("sub")
    @classmethod
    def sub_must_be_valid_uuid(cls, v: str) -> str:
        try:
            uuid.UUID(str(v))
        except (ValueError, TypeError):
            raise ValueError("sub must be a valid UUID string")
        return v

    @field_validator("session_id", mode="before")
    @classmethod
    def parse_session_id(cls, v):
        if v is None:
            return None
        if isinstance(v, uuid.UUID):
            return v
        return uuid.UUID(str(v))


class LoginResponse(BaseModel):
    """
    Full response for successful login — tokens + user info.
    tokens is None when mfa_required=True (tokens are withheld until MFA passes).
    """
    tokens: Optional[Token] = None
    mfa_token: Optional[str] = None
    user_id: uuid.UUID
    email: str
    username: str
    mfa_required: bool = False
    mfa_setup_required: bool = False
    risk_flagged: bool = False


class MFAPendingResponse(BaseModel):
    """
    Body of the 202 response when MFA verification is required.
    Client must call POST /auth/mfa/verify with mfa_token + code.
    mfa_token expires in MFA_PENDING_EXPIRE_MINUTES (default 5 minutes).
    """
    mfa_required: bool = True
    mfa_token: str = Field(..., description="Short-lived pre-auth JWT for /auth/mfa/verify")
    user_id: uuid.UUID
    email: str
    message: str = "MFA verification required. Submit code to /auth/mfa/verify."


class MFASetupResponse(BaseModel):
    """
    Returned by POST /auth/mfa/setup.
    secret and backup_codes are shown ONCE — the client must store them.
    After this response, only encrypted/hashed versions remain on the server.
    """
    secret: str = Field(..., description="Base32 TOTP secret — show once, then discard")
    provisioning_uri: str = Field(..., description="otpauth:// URI for QR code generation")
    backup_codes: list[str] = Field(
        ..., description="8 single-use backup codes — cannot be retrieved again"
    )
    message: str = (
        "Save your backup codes securely. "
        "Scan the QR code, then call /auth/mfa/confirm with your first code to activate MFA."
    )


class MFAConfirmRequest(BaseModel):
    """POST /auth/mfa/confirm — proves the user scanned the QR code correctly."""
    code: str = Field(..., min_length=6, max_length=6, pattern=r"^\d{6}$")


class MFAVerifyRequest(BaseModel):
    """
    POST /auth/mfa/verify — completes a pending MFA login.
    code: 6-digit TOTP or backup code (XXXX-XXXX format).
    """
    mfa_token: str = Field(..., min_length=1)
    code: str = Field(..., min_length=6, max_length=17)


class MFADisableRequest(BaseModel):
    """DELETE /auth/mfa — requires valid TOTP to prevent account lockout."""
    code: str = Field(..., min_length=6, max_length=6, pattern=r"^\d{6}$")


class MFACodeVerify(BaseModel):
    """Legacy alias — use MFAConfirmRequest for new code."""
    code: str = Field(..., min_length=6, max_length=6, pattern=r"^\d{6}$")


class RefreshTokenRequest(BaseModel):
    """Request body for POST /auth/refresh."""
    refresh_token: str = Field(..., min_length=1)


class ChangePasswordRequest(BaseModel):
    """POST /auth/change-password payload."""
    current_password: str = Field(..., min_length=1)
    new_password: str = Field(..., min_length=12)

    @field_validator("new_password")
    @classmethod
    def password_complexity(cls, v: str) -> str:
        if not re.search(r"[A-Z]", v):
            raise ValueError("Password must contain at least one uppercase letter")
        if not re.search(r"[a-z]", v):
            raise ValueError("Password must contain at least one lowercase letter")
        if not re.search(r"[0-9]", v):
            raise ValueError("Password must contain at least one number")
        if not re.search(r"[!@#$%^&*(),.?\":{}|<>]", v):
            raise ValueError("Password must contain at least one special character")
        return v


class ForgotAccessRequest(BaseModel):
    """POST /auth/forgot-access payload."""
    email: str = Field(..., min_length=3, max_length=255)


class ForgotAccessResponse(BaseModel):
    """
    Generic response for forgot-access to avoid user enumeration.
    reset_token is only returned in tutorial/dev flows for demo UX.
    """
    message: str
    reset_token: Optional[str] = None


class ResetAccessRequest(BaseModel):
    """POST /auth/reset-access payload."""
    reset_token: str = Field(..., min_length=1)
    new_password: str = Field(..., min_length=12)

    @field_validator("new_password")
    @classmethod
    def reset_password_complexity(cls, v: str) -> str:
        if not re.search(r"[A-Z]", v):
            raise ValueError("Password must contain at least one uppercase letter")
        if not re.search(r"[a-z]", v):
            raise ValueError("Password must contain at least one lowercase letter")
        if not re.search(r"[0-9]", v):
            raise ValueError("Password must contain at least one number")
        if not re.search(r"[!@#$%^&*(),.?\":{}|<>]", v):
            raise ValueError("Password must contain at least one special character")
        return v
    
