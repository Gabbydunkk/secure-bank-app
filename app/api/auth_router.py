"""
Auth Router — HTTP endpoints for registration, login, token refresh, and logout.
Maps HTTP requests → auth_service functions → HTTP responses.

Endpoints:
  POST /auth/register      → create new user account
  POST /auth/login         → authenticate and receive JWT tokens
  POST /auth/refresh       → exchange refresh token for new token pair
  POST /auth/logout        → invalidate current session
  GET  /auth/me            → return current authenticated user's profile
"""

from fastapi import APIRouter, Depends, HTTPException, Request, status
from app.core.rate_limiter import (
    login_rate_limiter,
    mfa_verify_rate_limiter,
    register_rate_limiter,
)
from sqlalchemy.orm import Session

from app.api.deps import get_client_ip, get_current_session, get_current_user
from app.models.database import get_db
from app.models.user import User
from app.schemas.auth import (
    ChangePasswordRequest,
    ForgotAccessRequest,
    ForgotAccessResponse,
    LoginResponse,
    MFAConfirmRequest,
    MFADisableRequest,
    MFAPendingResponse,
    MFASetupResponse,
    MFAVerifyRequest,
    ResetAccessRequest,
    RefreshTokenRequest,
    Token,
)
from app.schemas.user import UserCreate, UserLogin, UserResponse
from app.services import auth_service, mfa_service
from app.services.auth_service import (
    FraudBlockedError,
    FraudChallengeRequiredError,
    InvalidMFATokenError,
    MFARequiredError,
)

# Frontend risk-context header contract (all optional):
# - X-Device-Fingerprint: stable, non-PII device identifier string/hash.
# - X-Location-Country: ISO 3166-1 alpha-2 code (e.g. "GB", "US").
# - X-Location-City: free-text city label (e.g. "London").
# These are read by /auth/login and /auth/mfa/verify for fraud scoring context.

# ---------------------------------------------------------------------------
# Router setup
# prefix="/auth" means all routes below are /auth/register, /auth/login, etc.
# tags=["auth"] groups them in the auto-generated Swagger UI docs
# ---------------------------------------------------------------------------

router = APIRouter(prefix="/auth", tags=["auth"])


# ---------------------------------------------------------------------------
# POST /auth/register
# ---------------------------------------------------------------------------

@router.post(
    "/register",
    response_model=UserResponse,        # what we return (excludes password_hash)
    status_code=status.HTTP_201_CREATED,  # 201 = resource created
    summary="Register a new user account",
    dependencies=[Depends(register_rate_limiter)],
)
def register(
    data: UserCreate,           # request body — Pydantic validates password complexity, age, etc.
    db: Session = Depends(get_db),   # injected DB session
) -> UserResponse:
    """
    Create a new user account.

    - Validates password strength (12+ chars, uppercase, lowercase, digit, special char)
    - Validates user is 18+
    - Hashes password with bcrypt before storage (plain password never touches the DB)
    - Raises 409 if email or username is already taken
    """
    try:
        user = auth_service.register_user(db, data)
    except ValueError as exc:
        # auth_service raises ValueError for duplicate email/username
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=str(exc),
        )
    return user


# ---------------------------------------------------------------------------
# POST /auth/login
# ---------------------------------------------------------------------------

@router.post(
    "/login",
    response_model=LoginResponse,
    summary="Authenticate and receive JWT tokens",
    dependencies=[Depends(login_rate_limiter)],
)
def login(
    data: UserLogin,
    request: Request,           # needed to extract IP and User-Agent for fraud/audit
    db: Session = Depends(get_db),
) -> LoginResponse:
    """
    Authenticate a user and return access + refresh tokens.

    Flow:
    1. Validate credentials (email/username + password)
    2. Check account status and lock state
    3. Run fraud engine — may block or challenge the login
    4. Create session + issue JWT access token + refresh token

    HTTP status codes:
    - 200 OK → tokens issued (check risk_flagged field in response)
    - 401 Unauthorized → invalid credentials or account locked
    - 403 Forbidden → fraud block or account suspended
    - 202 Accepted → MFA challenge required (client must call /auth/mfa/verify)
    """
    ip = get_client_ip(request)
    user_agent = request.headers.get("User-Agent")
    device_fingerprint = request.headers.get("X-Device-Fingerprint")
    location_country = request.headers.get("X-Location-Country")
    location_city = request.headers.get("X-Location-City")

    try:
        response = auth_service.login(
            db,
            data,
            ip_address=ip,
            user_agent=user_agent,
            device_fingerprint=device_fingerprint,
            location_country=location_country,
            location_city=location_city,
        )
    except MFARequiredError as exc:
        # Password correct, MFA pending — return 202 with mfa_token in body.
        # The client submits mfa_token + 6-digit code to POST /auth/mfa/verify.
        # Using JSONResponse here because FastAPI's default error response
        # would discard our structured MFAPendingResponse body.
        from fastapi.responses import JSONResponse
        body = MFAPendingResponse(
            mfa_token=exc.mfa_token,
            user_id=exc.user_id,
            email=exc.email,
        )
        return JSONResponse(
            status_code=status.HTTP_202_ACCEPTED,
            content=body.model_dump(mode="json"),
        )
    except FraudBlockedError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc))
    except FraudChallengeRequiredError as exc:
        # Fraud challenge (NOT MFA) — no mfa_token issued
        raise HTTPException(status_code=status.HTTP_202_ACCEPTED, detail=str(exc))
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=str(exc),
            headers={"WWW-Authenticate": "Bearer"},
        )

    return response


# ---------------------------------------------------------------------------
# POST /auth/refresh
# ---------------------------------------------------------------------------

@router.post(
    "/refresh",
    response_model=Token,
    summary="Exchange refresh token for a new token pair",
)
def refresh(
    body: RefreshTokenRequest,
    db: Session = Depends(get_db),
) -> Token:
    """
    Issue a new access token and rotate the refresh token.

    Refresh token rotation means:
    - Old refresh token is invalidated
    - New refresh token is issued
    - This limits the damage if a refresh token is stolen

    Raises 401 if refresh token is invalid, expired, or already used.
    """
    try:
        tokens = auth_service.refresh_tokens(db, body.refresh_token)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=str(exc),
            headers={"WWW-Authenticate": "Bearer"},
        )
    return tokens


# ---------------------------------------------------------------------------
# POST /auth/logout
# ---------------------------------------------------------------------------

@router.post(
    "/logout",
    status_code=status.HTTP_204_NO_CONTENT,  # 204 = success, no body
    summary="Invalidate current session (logout)",
)
def logout(
    request: Request,
    # get_current_session validates the JWT AND checks the session is alive in DB
    user_and_session: tuple = Depends(get_current_session),
    db: Session = Depends(get_db),
) -> None:
    """
    Log out the current user by invalidating their active session.

    Uses get_current_session (not just get_current_user) so that:
    - The session is confirmed active before invalidating
    - Token revocation takes effect immediately (hash lookup)

    Returns 204 No Content on success — no body needed.
    """
    user, session = user_and_session
    auth_service.logout(db, session.id)
    # 204 = return None, FastAPI handles the empty response


# ---------------------------------------------------------------------------
# POST /auth/change-password
# ---------------------------------------------------------------------------

@router.post(
    "/change-password",
    status_code=status.HTTP_200_OK,
    summary="Change current user's password and revoke other sessions",
)
def change_password(
    body: ChangePasswordRequest,
    user_and_session: tuple = Depends(get_current_session),
    db: Session = Depends(get_db),
) -> dict:
    """
    Change password for the authenticated user.

    Security behavior:
    - Verifies current password.
    - Stores new password as a bcrypt hash.
    - Invalidates all active sessions except the current one.
    """
    user, session = user_and_session
    try:
        auth_service.change_password(
            db,
            user=user,
            current_password=body.current_password,
            new_password=body.new_password,
            keep_session_id=session.id,
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        )
    return {"message": "Password changed successfully. Other sessions were signed out."}


# ---------------------------------------------------------------------------
# POST /auth/forgot-access
# ---------------------------------------------------------------------------

@router.post(
    "/forgot-access",
    response_model=ForgotAccessResponse,
    summary="Request password reset token",
)
def forgot_access(
    body: ForgotAccessRequest,
    db: Session = Depends(get_db),
) -> ForgotAccessResponse:
    """
    Start forgot-access flow.
    Always returns generic success text to avoid user enumeration.
    In APP_ENV=Tutorial, includes reset_token for demo workflows.
    """
    import os
    return auth_service.request_forgot_access(
        db,
        body.email,
        return_token_for_demo=(os.environ.get("APP_ENV") == "Tutorial"),
    )


# ---------------------------------------------------------------------------
# POST /auth/reset-access
# ---------------------------------------------------------------------------

@router.post(
    "/reset-access",
    status_code=status.HTTP_200_OK,
    summary="Reset password with reset token",
)
def reset_access(
    body: ResetAccessRequest,
    db: Session = Depends(get_db),
) -> dict:
    """
    Complete forgot-access flow with reset token.
    """
    try:
        auth_service.reset_access_with_token(db, body.reset_token, body.new_password)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))
    except Exception:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid or expired reset token")
    return {"message": "Access password reset successfully. Please log in again."}


# ---------------------------------------------------------------------------
# GET /auth/me
# ---------------------------------------------------------------------------

@router.get(
    "/me",
    response_model=UserResponse,
    summary="Get the currently authenticated user's profile",
)
def get_me(
    current_user: User = Depends(get_current_user),  # JWT validation happens here
) -> UserResponse:
    """
    Return the profile of the currently authenticated user.

    No DB query needed here — get_current_user already loaded the user from DB
    and passed it as a dependency. FastAPI's dependency injection handles this
    efficiently (the DB query runs once, not twice).

    Raises 401 if token is missing/invalid/expired.
    Raises 403 if account is suspended/locked/closed.
    """
    return current_user

# ---------------------------------------------------------------------------
# POST /auth/mfa/setup
# ---------------------------------------------------------------------------

@router.post(
    "/mfa/setup",
    response_model=MFASetupResponse,
    status_code=status.HTTP_200_OK,
    summary="Set up TOTP MFA for the authenticated user",
)
def mfa_setup(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> MFASetupResponse:
    """
    Generate a new TOTP secret and return it for QR scanning.

    The response contains:
      - secret:           base32 TOTP secret (show once — cannot be retrieved again)
      - provisioning_uri: otpauth:// URL — encode as QR code client-side
      - backup_codes:     8 single-use emergency codes (show once — store securely)

    MFA is NOT active yet after this call. The user must call
    POST /auth/mfa/confirm with their first code to activate it.

    Calling this again before confirming replaces the pending secret.
    Calling this again after confirming also replaces it — useful for
    re-enrollment after a phone replacement.

    Requires: active authenticated session (any scope).
    """
    return mfa_service.setup_mfa(db, current_user)


# ---------------------------------------------------------------------------
# POST /auth/mfa/confirm
# ---------------------------------------------------------------------------

@router.post(
    "/mfa/confirm",
    status_code=status.HTTP_200_OK,
    summary="Confirm MFA setup with first TOTP code — activates MFA",
)
def mfa_confirm(
    body: MFAConfirmRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    """
    Verify the first TOTP code after setup to activate MFA.

    This two-step flow proves the user:
      1. Received the secret
      2. Successfully added it to their authenticator app
      3. Can generate valid codes before we lock MFA in

    After this call, every login will require a TOTP code.

    Raises 400 if:
      - No setup has been initiated (call /auth/mfa/setup first)
      - The code is incorrect (wrong app, wrong account, clock skew > 30s)

    Requires: active authenticated session (any scope).
    """
    try:
        mfa_service.confirm_mfa_setup(db, current_user, body.code)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        )
    return {"message": "MFA activated successfully. All future logins will require a TOTP code."}


# ---------------------------------------------------------------------------
# POST /auth/mfa/verify
# ---------------------------------------------------------------------------

@router.post(
    "/mfa/verify",
    response_model=LoginResponse,
    status_code=status.HTTP_200_OK,
    summary="Complete MFA login — exchange mfa_token + code for full tokens",
    dependencies=[Depends(mfa_verify_rate_limiter)],
)
def mfa_verify(
    body: MFAVerifyRequest,
    request: Request,
    db: Session = Depends(get_db),
) -> LoginResponse:
    """
    Complete the MFA login flow started by POST /auth/login (202 response).

    Accepts:
      - mfa_token: the short-lived JWT from the 202 login response (expires in 5 min)
      - code:      6-digit TOTP OR backup code ("XXXX-XXXX" format)

    On success: returns a full LoginResponse with access + refresh tokens.

    HTTP status codes:
      200 OK         → MFA verified, tokens issued
      400 Bad Request→ wrong TOTP code or expired mfa_token
      401 Unauthorized → mfa_token is cryptographically invalid or wrong type
      403 Forbidden  → fraud engine blocked post-MFA

    This endpoint is PUBLIC (no auth dependency) because the mfa_token
    itself is the credential. The handler explicitly validates its type
    so it cannot be called with a regular access token.
    """
    ip = get_client_ip(request)
    user_agent = request.headers.get("User-Agent")
    device_fingerprint = request.headers.get("X-Device-Fingerprint")
    location_country = request.headers.get("X-Location-Country")
    location_city = request.headers.get("X-Location-City")

    try:
        return auth_service.verify_mfa_and_login(
            db,
            mfa_token=body.mfa_token,
            code=body.code,
            ip_address=ip,
            user_agent=user_agent,
            device_fingerprint=device_fingerprint,
            location_country=location_country,
            location_city=location_city,
        )
    except FraudBlockedError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc))
    except InvalidMFATokenError as exc:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=str(exc))
    except ValueError as exc:
        # Wrong code, expired token, account inactive
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))


# ---------------------------------------------------------------------------
# DELETE /auth/mfa
# ---------------------------------------------------------------------------

@router.delete(
    "/mfa",
    status_code=status.HTTP_200_OK,
    summary="Disable MFA — requires current TOTP code",
)
def mfa_disable(
    body: MFADisableRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    """
    Disable MFA on the authenticated account.

    Requires a valid TOTP code to prevent an attacker who stole a session
    token from silently removing MFA and then logging in without a code.
    This is a critical security boundary: possession of a session token
    alone is NOT sufficient to disable MFA.

    After disabling, future logins will not require a code.
    To re-enable, call /auth/mfa/setup + /auth/mfa/confirm.

    Raises 400 if:
      - MFA is not currently enabled on the account
      - The TOTP code is incorrect

    Requires: active authenticated session (any scope).
    """
    try:
        mfa_service.disable_mfa(db, current_user, body.code)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        )
    return {"message": "MFA disabled. You can re-enable it at any time via /auth/mfa/setup."}
    
