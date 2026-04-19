"""
Auth service: registration, login, token refresh, logout.
Uses security (hashing, JWT), sessions, and login attempt tracking.
"""
from datetime import datetime, timedelta, timezone
from typing import Optional
import uuid

from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.security import (
    create_access_token,
    create_mfa_pending_token,
    create_password_reset_token,
    create_refresh_token,
    get_password_hash,
    hash_token,
    verify_password_reset_token,
    verify_mfa_pending_token,
    verify_password,
)
from app.models.user import KnownDevice, LoginAttempt, MFASecret, Session as SessionModel, User
from app.schemas.auth import (
    ForgotAccessResponse,
    LoginResponse,
    MFAPendingResponse,
    SCOPE_READ_ONLY,
    SCOPE_TRANSFER_AUTHORIZED,
    SCOPE_MFA_ELEVATED,
    SCOPE_ANALYST,
    SCOPE_ADMIN,
    Token,
)
from app.schemas.user import UserCreate, UserLogin
from app.services.fraud_service import FraudService
from app.services.device_service import register_device
from app.schemas.fraud import FraudRuleInput


# =============================================================================
# Role → scope mapping
# =============================================================================

# Translates a user's DB role into the JWT scopes list embedded in their token.
# This is the single source of truth for what each role can do.
# Changing analyst permissions = edit one entry in this dict.
_ROLE_SCOPES: dict[str, list[str]] = {
    "user": [
        SCOPE_READ_ONLY,
        SCOPE_TRANSFER_AUTHORIZED,
    ],
    "analyst": [
        SCOPE_READ_ONLY,
        SCOPE_TRANSFER_AUTHORIZED,   # analysts can initiate transactions
        SCOPE_ANALYST,               # satisfies require_analyst gate
    ],
    "admin": [
        SCOPE_READ_ONLY,
        SCOPE_TRANSFER_AUTHORIZED,
        SCOPE_MFA_ELEVATED,
        SCOPE_ANALYST,               # admin satisfies every analyst check
        SCOPE_ADMIN,                 # satisfies require_admin gate
    ],
}


def _scopes_for_user(user) -> list[str]:
    """
    Return the JWT scope list for a user based on their DB role.

    Uses getattr with a safe default so this works with both real ORM
    objects and MagicMock test objects — missing role attribute safely
    falls back to read_only rather than raising AttributeError.

    An unrecognised role also falls back to read_only: a misconfigured
    role never accidentally grants elevated privileges.
    """
    role = getattr(user, "role", "user") or "user"
    return list(_ROLE_SCOPES.get(role, [SCOPE_READ_ONLY]))


# =============================================================================
# User lookup (Single Responsibility: resolve user by identifier)
# =============================================================================

def get_user_by_email(db: Session, email: str) -> Optional[User]:
    """Return user by email or None."""
    return db.query(User).filter(User.email == email).first()


def get_user_by_username(db: Session, username: str) -> Optional[User]:
    """Return user by username or None."""
    return db.query(User).filter(User.username == username).first()


def get_user_by_id(db: Session, user_id: uuid.UUID) -> Optional[User]:
    """Return user by id or None."""
    return db.query(User).filter(User.id == user_id).first()


# =============================================================================
# Registration
# =============================================================================

def register_user(db: Session, data: UserCreate) -> User:
    """
    Create a new user with hashed password.
    Raises ValueError if email or username already exists.
    """
    if get_user_by_email(db, data.email):
        raise ValueError("Email already registered")
    if get_user_by_username(db, data.username):
        raise ValueError("Username already taken")

    user = User(
        email=data.email,
        username=data.username,
        password_hash=get_password_hash(data.password),
        first_name=data.first_name,
        last_name=data.last_name,
        phone_number=data.phone_number,
        date_of_birth=data.date_of_birth,
        account_status="active",
        # role defaults to "user" in the DB column, but honour whatever
        # was passed — admin tooling can seed analyst/admin accounts this way.
        role=getattr(data, "role", "user") or "user",
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


# =============================================================================
# Login: credentials → session + tokens
# =============================================================================

def _resolve_user(db: Session, login: UserLogin) -> Optional[User]:
    """Resolve user from email or username."""
    if login.email:
        return get_user_by_email(db, login.email)
    if login.username:
        return get_user_by_username(db, login.username)
    return None


def _add_login_attempt(
    db: Session,
    user_id: Optional[uuid.UUID],
    email: Optional[str],
    ip_address: Optional[str],
    user_agent: Optional[str],
    success: bool,
    failure_reason: Optional[str] = None,
    mfa_required: bool = False,
    mfa_success: Optional[bool] = None,
) -> None:
    """Add one login attempt to the session (no commit – caller commits for atomicity)."""
    attempt = LoginAttempt(
        user_id=user_id,
        email=email,
        ip_address=ip_address or "0.0.0.0",
        user_agent=user_agent,
        success=success,
        failure_reason=failure_reason,
        mfa_required=mfa_required,
        mfa_success=mfa_success,
    )
    db.add(attempt)


# Custom error for fraud challenge (API can return 403 with code for MFA step-up)
class FraudChallengeRequiredError(ValueError):
    """Raised when fraud engine requires MFA challenge before issuing tokens."""
    pass


class FraudBlockedError(ValueError):
    """Raised when login is blocked by fraud policy."""
    pass


class MFARequiredError(Exception):
    """
    Raised when login succeeds but MFA verification is still needed.

    Unlike FraudChallengeRequiredError (which is a hard fraud gate),
    MFARequiredError means the user's credentials are valid — they just
    need to prove their second factor. The mfa_token is a short-lived
    JWT the client uses to call /auth/mfa/verify.
    """
    def __init__(self, mfa_token: str, user_id: uuid.UUID, email: str) -> None:
        self.mfa_token = mfa_token
        self.user_id = user_id
        self.email = email
        super().__init__("MFA verification required")


class InvalidMFATokenError(ValueError):
    """Raised when the mfa_pending token is invalid or expired."""
    pass


def login(
    db: Session,
    login_data: UserLogin,
    *,
    ip_address: Optional[str] = None,
    user_agent: Optional[str] = None,
    device_fingerprint: Optional[str] = None,
    location_country: Optional[str] = None,
    location_city: Optional[str] = None,
    fraud_service: Optional[FraudService] = None,
) -> LoginResponse:
    """
    Authenticate user, run fraud check, then create session + tokens if allowed.
    - block: no session, no tokens, attempt + alert committed, FraudBlockedError.
    - challenge: no session, no tokens, attempt + alert committed, FraudChallengeRequiredError.
    - flag / allow: session + tokens in one atomic commit; risk_flagged=True when flag.
    """
    user = _resolve_user(db, login_data)
    email_used = login_data.email or (user.email if user else None)
    now = datetime.now(timezone.utc)

    if not user:
        _add_login_attempt(
            db, user_id=None, email=email_used, ip_address=ip_address,
            user_agent=user_agent, success=False, failure_reason="user_not_found",
        )
        db.commit()
        raise ValueError("Invalid email/username or password")

    if not verify_password(login_data.password, user.password_hash):
        user.failed_login_attempts = (user.failed_login_attempts or 0) + 1
        failure_reason = "invalid_password"
        if user.failed_login_attempts >= settings.MAX_FAILED_LOGIN_ATTEMPTS:
            user.locked_until = now + timedelta(minutes=settings.ACCOUNT_LOCK_MINUTES)
            failure_reason = "account_locked_due_to_failed_logins"
        _add_login_attempt(
            db, user_id=user.id, email=user.email, ip_address=ip_address,
            user_agent=user_agent, success=False, failure_reason=failure_reason,
        )
        db.commit()
        raise ValueError("Invalid email/username or password")

    if user.account_status != "active":
        _add_login_attempt(
            db, user_id=user.id, email=user.email, ip_address=ip_address,
            user_agent=user_agent, success=False, failure_reason=f"account_{user.account_status}",
        )
        db.commit()
        raise ValueError(f"Account is {user.account_status}")

    if user.locked_until and user.locked_until > now:
        _add_login_attempt(
            db, user_id=user.id, email=user.email, ip_address=ip_address,
            user_agent=user_agent, success=False, failure_reason="account_locked",
        )
        db.commit()
        raise ValueError("Account is temporarily locked")
    if user.locked_until and user.locked_until <= now:
        user.locked_until = None
        user.failed_login_attempts = 0

    # MFA enabled: password check passed, but do not issue full tokens yet.
    # Issue a short-lived mfa_pending token so the client can call
    # POST /auth/mfa/verify without re-sending the password.
    if user.mfa_enabled:
        mfa_token, _ = create_mfa_pending_token(user.id)
        _add_login_attempt(
            db, user_id=user.id, email=user.email, ip_address=ip_address,
            user_agent=user_agent, success=False,
            failure_reason="mfa_verification_required",
            mfa_required=True,
            mfa_success=False,
        )
        db.commit()
        raise MFARequiredError(
            mfa_token=mfa_token, user_id=user.id, email=user.email
        )

    # Fraud check before session creation (alert added to db with commit_alert=False)
    fraud = fraud_service or FraudService()
    fraud_input = FraudRuleInput(
        user_id=user.id,
        ip_address=ip_address,
        device_fingerprint=device_fingerprint,
        location_country=location_country,
        location_city=location_city,
    )
    fraud_result, _ = fraud.evaluate(
        db, fraud_input,
        create_alert_if_required=True,
        commit_alert=False,
    )

    if fraud_result.action == "block":
        _add_login_attempt(
            db, user_id=user.id, email=user.email, ip_address=ip_address,
            user_agent=user_agent, success=False, failure_reason="fraud_block",
        )
        db.commit()
        raise FraudBlockedError("Login blocked by security policy")

    if fraud_result.action == "challenge":
        _add_login_attempt(
            db, user_id=user.id, email=user.email, ip_address=ip_address,
            user_agent=user_agent, success=False, failure_reason="fraud_challenge_required",
        )
        db.commit()
        raise FraudChallengeRequiredError("Security challenge required")

    # allow or flag: create session + tokens in one transaction
    scopes = _scopes_for_user(user)
    access_token, _ = create_access_token(
        user_id=user.id, session_id=None, scopes=scopes,
    )
    refresh_token = create_refresh_token()
    refresh_expires_at = now + timedelta(days=settings.REFRESH_TOKEN_EXPIRE_DAYS)
    session = SessionModel(
        user_id=user.id,
        access_token_hash=hash_token(access_token),
        refresh_token_hash=hash_token(refresh_token),
        device_fingerprint=device_fingerprint,
        ip_address=ip_address,
        user_agent=user_agent,
        location_country=location_country,
        location_city=location_city,
        is_active=True,
        expires_at=refresh_expires_at,
    )
    db.add(session)
    db.flush()

    access_token, _ = create_access_token(
        user_id=user.id, session_id=session.id, scopes=scopes,
    )
    session.access_token_hash = hash_token(access_token)
    session.refresh_token_hash = hash_token(refresh_token)
    session.last_activity = now

    _add_login_attempt(
        db, user_id=user.id, email=user.email, ip_address=ip_address,
        user_agent=user_agent, success=True, mfa_required=user.mfa_enabled,
    )
    user.last_login = now
    user.failed_login_attempts = 0
    user.locked_until = None

    # Register the device so DeviceAnomalyRule knows it next time.
    # commit=False — included in the same db.commit() below.
    register_device(db, user.id, device_fingerprint, commit=False)

    db.commit()

    expires_in_seconds = int(settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60)
    tokens = Token(
        access_token=access_token,
        refresh_token=refresh_token,
        token_type="bearer",
        expires_in=expires_in_seconds,
    )
    return LoginResponse(
        tokens=tokens,
        user_id=user.id,
        email=user.email,
        username=user.username,
        mfa_required=user.mfa_enabled,
        mfa_setup_required=False,
        risk_flagged=(fraud_result.action == "flag"),
    )


# =============================================================================
# Token refresh
# =============================================================================

def refresh_tokens(db: Session, refresh_token_raw: str) -> Token:
    """
    Issue new access and refresh tokens using a valid refresh token.
    Looks up session by refresh_token_hash, then updates session with new token hashes.
    Raises ValueError if refresh token is invalid or session expired/inactive.
    """
    refresh_hash = hash_token(refresh_token_raw)
    session = (
        db.query(SessionModel)
        .filter(
            SessionModel.refresh_token_hash == refresh_hash,
            SessionModel.is_active.is_(True),
            SessionModel.expires_at > datetime.now(timezone.utc),
        )
        .first()
    )

    if not session:
        raise ValueError("Invalid or expired refresh token")

    user = get_user_by_id(db, session.user_id)
    if not user or user.account_status != "active":
        session.is_active = False
        db.commit()
        raise ValueError("User no longer active")

    # Re-derive scopes from the user's current role so that
    # role changes take effect at the next token refresh.
    access_token, _ = create_access_token(
        user_id=user.id,
        session_id=session.id,
        scopes=_scopes_for_user(user),
    )
    new_refresh = create_refresh_token()
    session.access_token_hash = hash_token(access_token)
    session.refresh_token_hash = hash_token(new_refresh)
    session.expires_at = datetime.now(timezone.utc) + timedelta(days=settings.REFRESH_TOKEN_EXPIRE_DAYS)
    session.last_activity = datetime.now(timezone.utc)
    db.commit()

    expires_in_seconds = int(settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60)
    return Token(
        access_token=access_token,
        refresh_token=new_refresh,
        token_type="bearer",
        expires_in=expires_in_seconds,
    )


def request_forgot_access(
    db: Session,
    email: str,
    *,
    return_token_for_demo: bool = False,
) -> ForgotAccessResponse:
    """
    Generate password-reset token for existing user.
    Always returns a generic response to prevent account enumeration.
    """
    generic_message = "If an account exists for this email, reset instructions have been generated."
    user = get_user_by_email(db, email)
    if not user:
        return ForgotAccessResponse(message=generic_message)

    token, _ = create_password_reset_token(user.email)
    return ForgotAccessResponse(
        message=generic_message,
        reset_token=token if return_token_for_demo else None,
    )


def reset_access_with_token(db: Session, reset_token: str, new_password: str) -> None:
    """
    Reset password using a valid reset token and revoke active sessions.
    """
    email = verify_password_reset_token(reset_token)
    user = get_user_by_email(db, email)
    if not user:
        raise ValueError("Invalid reset token")
    if user.account_status == "closed":
        raise ValueError("Account is closed")

    user.password_hash = get_password_hash(new_password)
    user.failed_login_attempts = 0
    user.locked_until = None

    # Revoke all active sessions after password reset.
    sessions = (
        db.query(SessionModel)
        .filter(
            SessionModel.user_id == user.id,
            SessionModel.is_active.is_(True),
        )
        .all()
    )
    now = datetime.now(timezone.utc)
    for session in sessions:
        session.is_active = False
        session.logout_at = now

    db.commit()


# =============================================================================
# Logout (invalidate session)
# =============================================================================

def logout(db: Session, session_id: uuid.UUID) -> bool:
    """
    Mark session as inactive and set logout_at.
    Returns True if session was found and invalidated, False otherwise.
    """
    session = db.query(SessionModel).filter(
        SessionModel.id == session_id,
        SessionModel.is_active.is_(True),
    ).first()

    if not session:
        return False

    session.is_active = False
    session.logout_at = datetime.now(timezone.utc)
    db.commit()
    return True


def logout_by_access_token(db: Session, access_token: str) -> bool:
    """
    Invalidate the session that holds the given access token (by hash).
    Returns True if a session was invalidated, False otherwise.
    """
    token_hash = hash_token(access_token)
    session = db.query(SessionModel).filter(
        SessionModel.access_token_hash == token_hash,
        SessionModel.is_active.is_(True),
    ).first()

    if not session:
        return False

    session.is_active = False
    session.logout_at = datetime.now(timezone.utc)
    db.commit()
    return True


def change_password(
    db: Session,
    user: User,
    current_password: str,
    new_password: str,
    *,
    keep_session_id: Optional[uuid.UUID] = None,
) -> None:
    """
    Change user password and invalidate all other active sessions.

    keep_session_id keeps the current session alive so the password-change
    request can return successfully without immediately logging out the caller.
    """
    if not verify_password(current_password, user.password_hash):
        raise ValueError("Current password is incorrect")
    if verify_password(new_password, user.password_hash):
        raise ValueError("New password must be different from current password")

    user.password_hash = get_password_hash(new_password)
    user.updated_at = datetime.now(timezone.utc)

    sessions = (
        db.query(SessionModel)
        .filter(
            SessionModel.user_id == user.id,
            SessionModel.is_active.is_(True),
        )
        .all()
    )
    for session in sessions:
        if keep_session_id is not None and session.id == keep_session_id:
            continue
        session.is_active = False
        session.logout_at = datetime.now(timezone.utc)

    db.commit()


def update_profile(
    db: Session,
    user: User,
    *,
    first_name: Optional[str] = None,
    last_name: Optional[str] = None,
    phone_number: Optional[str] = None,
    date_of_birth=None,
) -> User:
    """Update editable self-service profile fields."""
    if first_name is not None:
        user.first_name = first_name
    if last_name is not None:
        user.last_name = last_name
    if phone_number is not None:
        user.phone_number = phone_number
    if date_of_birth is not None:
        user.date_of_birth = date_of_birth
    user.updated_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(user)
    return user


# =============================================================================
# MFA verification + login completion
# =============================================================================

def verify_mfa_and_login(
    db: Session,
    mfa_token: str,
    code: str,
    *,
    ip_address: Optional[str] = None,
    user_agent: Optional[str] = None,
    device_fingerprint: Optional[str] = None,
    location_country: Optional[str] = None,
    location_city: Optional[str] = None,
    fraud_service: Optional[FraudService] = None,
) -> LoginResponse:
    """
    Complete the login flow after successful MFA verification.

    Flow:
      1. Decode and validate the mfa_pending JWT (type check prevents
         access tokens being submitted here).
      2. Load and verify the user is still active.
      3. Verify the TOTP code (or backup code) via mfa_service.
      4. Run fraud check (same as non-MFA login path).
      5. On allow/flag: create session + issue full access + refresh tokens.
      6. Log all outcomes in LoginAttempt for audit.

    Raises:
      jwt.InvalidTokenError  — mfa_token is invalid or expired
      ValueError             — wrong TOTP code, user not found, account inactive,
                               fraud block, or no active MFA secret
    """
    import jwt as pyjwt
    from app.core.security import verify_mfa_pending_token
    from app.services import mfa_service

    # Step 1: validate mfa_pending token
    try:
        payload = verify_mfa_pending_token(mfa_token)
    except pyjwt.InvalidTokenError as exc:
        raise InvalidMFATokenError("MFA verification session is invalid or expired. Please sign in again.") from exc

    user_id = uuid.UUID(payload.sub)

    # Step 2: load user
    user = get_user_by_id(db, user_id)
    if not user:
        raise ValueError("User not found")
    if user.account_status != "active":
        raise ValueError(f"Account is {user.account_status}")

    now = datetime.now(timezone.utc)

    # Step 3: verify TOTP code (commit=False — we commit everything together below)
    try:
        code_valid = mfa_service.verify_mfa_code(db, user_id, code, commit=False)
    except ValueError as exc:
        # No active MFA secret found — config error, log and surface as 500-ish
        _add_login_attempt(
            db, user_id=user.id, email=user.email, ip_address=ip_address,
            user_agent=user_agent, success=False,
            failure_reason="mfa_secret_not_found",
            mfa_required=True, mfa_success=False,
        )
        db.commit()
        raise

    if not code_valid:
        _add_login_attempt(
            db, user_id=user.id, email=user.email, ip_address=ip_address,
            user_agent=user_agent, success=False,
            failure_reason="invalid_mfa_code",
            mfa_required=True, mfa_success=False,
        )
        db.commit()
        raise ValueError("Invalid MFA code")

    # Step 4: fraud check (same as non-MFA login path)
    fraud = fraud_service or FraudService()
    fraud_input = FraudRuleInput(
        user_id=user.id,
        ip_address=ip_address,
        device_fingerprint=device_fingerprint,
        location_country=location_country,
        location_city=location_city,
    )
    fraud_result, _ = fraud.evaluate(
        db, fraud_input,
        create_alert_if_required=True,
        commit_alert=False,
    )

    if fraud_result.action == "block":
        _add_login_attempt(
            db, user_id=user.id, email=user.email, ip_address=ip_address,
            user_agent=user_agent, success=False, failure_reason="fraud_block",
            mfa_required=True, mfa_success=True,
        )
        db.commit()
        raise FraudBlockedError("Login blocked by security policy")

    # Step 5: create session + issue tokens atomically
    scopes = _scopes_for_user(user)
    access_token, _ = create_access_token(
        user_id=user.id, session_id=None, scopes=scopes,
    )
    refresh_token = create_refresh_token()
    refresh_expires_at = now + timedelta(days=settings.REFRESH_TOKEN_EXPIRE_DAYS)

    session = SessionModel(
        user_id=user.id,
        access_token_hash=hash_token(access_token),
        refresh_token_hash=hash_token(refresh_token),
        device_fingerprint=device_fingerprint,
        ip_address=ip_address,
        user_agent=user_agent,
        location_country=location_country,
        location_city=location_city,
        is_active=True,
        expires_at=refresh_expires_at,
    )
    db.add(session)
    db.flush()  # get session.id

    # Reissue access token with session_id now that we have it
    access_token, _ = create_access_token(
        user_id=user.id, session_id=session.id, scopes=scopes,
    )
    session.access_token_hash = hash_token(access_token)
    session.last_activity = now

    # Step 6: log success
    _add_login_attempt(
        db, user_id=user.id, email=user.email, ip_address=ip_address,
        user_agent=user_agent, success=True,
        mfa_required=True, mfa_success=True,
    )
    user.last_login = now
    user.failed_login_attempts = 0
    user.locked_until = None

    # Register the device — same atomic commit as the session row.
    register_device(db, user.id, device_fingerprint, commit=False)

    db.commit()

    expires_in_seconds = int(settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60)
    tokens = Token(
        access_token=access_token,
        refresh_token=refresh_token,
        token_type="bearer",
        expires_in=expires_in_seconds,
    )
    return LoginResponse(
        tokens=tokens,
        user_id=user.id,
        email=user.email,
        username=user.username,
        mfa_required=False,   # MFA is now complete — tokens issued
        mfa_setup_required=False,
        risk_flagged=(fraud_result.action == "flag"),
    )
    
