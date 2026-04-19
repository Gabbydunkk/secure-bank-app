"""
app/services/mfa_service.py — MFA business logic.

Responsibilities (Single Responsibility per function):
  setup_mfa()            → create MFASecret row + return secret/URI/backup codes (once)
  confirm_mfa_setup()    → verify first TOTP code → enable mfa on user
  get_active_mfa_secret()→ load the active TOTP secret for a user
  verify_mfa_code()      → verify TOTP or backup code for login
  disable_mfa()          → verify TOTP → set mfa_enabled=False + deactivate secret

Design decisions:
  - setup does NOT set mfa_enabled=True. Only confirm_mfa_setup() does.
    This prevents users locking themselves out if they mistype the secret.
  - verify_mfa_code() updates last_used on the MFASecret for audit.
  - All DB commits follow the "caller controls commit" pattern only where
    atomicity with other writes is needed (verify_mfa_code, used in login).
"""

from datetime import datetime, timezone
from typing import Optional
import uuid

from sqlalchemy.orm import Session

from app.core.totp import (
    decrypt_backup_codes,
    decrypt_totp_secret,
    encrypt_backup_codes,
    encrypt_totp_secret,
    generate_backup_codes,
    generate_totp_secret,
    get_totp_uri,
    verify_and_consume_backup_code,
    verify_totp,
    verify_totp_strict,
)
from app.models.user import MFASecret, User
from app.schemas.auth import MFASetupResponse


# =============================================================================
# Setup
# =============================================================================

def setup_mfa(db: Session, user: User) -> MFASetupResponse:
    """
    Generate a new TOTP secret and store it encrypted in mfa_secrets.

    Does NOT enable MFA yet — the user must call confirm_mfa_setup() with a
    valid code to prove they scanned the QR correctly before we activate MFA.

    If the user already has a pending (not-yet-confirmed) MFA secret, it is
    deactivated and replaced. This handles the case where the user lost access
    to their authenticator before confirming.

    Returns MFASetupResponse with:
      - secret:           base32 string shown ONCE (user must save this)
      - provisioning_uri: otpauth:// URL for QR code generation client-side
      - backup_codes:     8 single-use codes shown ONCE (store securely)
    """
    # Deactivate any existing TOTP secret (e.g. re-setup after phone loss)
    existing = (
        db.query(MFASecret)
        .filter(MFASecret.user_id == user.id, MFASecret.mfa_type == "totp")
        .all()
    )
    for old in existing:
        old.is_active = False

    # Generate new secret + backup codes
    secret_b32 = generate_totp_secret()
    uri = get_totp_uri(secret_b32, user.email)
    plaintext_codes, hashed_codes = generate_backup_codes()

    # Store encrypted
    mfa_secret = MFASecret(
        user_id=user.id,
        mfa_type="totp",
        secret_encrypted=encrypt_totp_secret(secret_b32),
        backup_codes_encrypted=encrypt_backup_codes(hashed_codes),
        is_active=True,
    )
    db.add(mfa_secret)
    db.commit()
    db.refresh(mfa_secret)

    return MFASetupResponse(
        secret=secret_b32,
        provisioning_uri=uri,
        backup_codes=plaintext_codes,
    )


# =============================================================================
# Confirm setup
# =============================================================================

def confirm_mfa_setup(db: Session, user: User, code: str) -> bool:
    """
    Verify the first TOTP code after setup — if valid, enable MFA on the user.

    This two-step flow (setup → confirm) proves the user successfully:
      1. Received the secret
      2. Added it to their authenticator app
      3. Can generate valid codes

    Without this step, a user could enable MFA and immediately lock themselves
    out if they lost the QR code or mistyped the secret.

    Returns True on success, raises ValueError on failure.
    """
    mfa_secret = get_active_mfa_secret(db, user.id)
    if mfa_secret is None:
        raise ValueError("No MFA setup found. Call /auth/mfa/setup first.")

    try:
        secret_b32 = decrypt_totp_secret(mfa_secret.secret_encrypted)
    except ValueError as exc:
        # Most common cause: SECRET_KEY changed or a different instance is running
        # with a different SECRET_KEY, making existing ciphertext undecryptable.
        raise ValueError(
            "MFA configuration error: unable to read your MFA secret. "
            "Please re-enroll MFA."
        ) from exc

    if not verify_totp_strict(secret_b32, code):
        raise ValueError("Invalid TOTP code. Make sure your authenticator app is synced.")

    # Code is valid — activate MFA for the user
    user.mfa_enabled = True
    mfa_secret.last_used = datetime.now(timezone.utc)
    db.commit()
    return True


# =============================================================================
# Lookup
# =============================================================================

def get_active_mfa_secret(db: Session, user_id: uuid.UUID) -> Optional[MFASecret]:
    """
    Return the active TOTP MFASecret for a user, or None if not set up.
    Only one active TOTP secret per user is expected at any time.
    """
    return (
        db.query(MFASecret)
        .filter(
            MFASecret.user_id == user_id,
            MFASecret.mfa_type == "totp",
            MFASecret.is_active.is_(True),
        )
        .order_by(MFASecret.created_at.desc())
        .first()
    )


# =============================================================================
# Verify (used during login)
# =============================================================================

def verify_mfa_code(
    db: Session,
    user_id: uuid.UUID,
    code: str,
    *,
    commit: bool = True,
) -> bool:
    """
    Verify a TOTP code or backup code during login.

    Accepts two code formats:
      - 6-digit TOTP:    "123456"
      - Backup code:     "A3F2-9C1B" (single-use, consumed on success)

    commit=False allows the caller to bundle this update into a larger
    transaction (e.g. the login service commits session + last_used together).

    Returns True on success. Raises ValueError if no MFA secret is found.
    Returns False on wrong code (caller handles the response, e.g. 401).
    """
    mfa_secret = get_active_mfa_secret(db, user_id)
    if mfa_secret is None:
        raise ValueError("MFA is enabled but no active secret found — contact support")

    # Try TOTP first (6-digit numeric codes only)
    if code.isdigit() and len(code) == 6:
        try:
            secret_b32 = decrypt_totp_secret(mfa_secret.secret_encrypted)
        except ValueError as exc:
            raise ValueError(
                "MFA configuration error: unable to read your MFA secret. "
                "Please re-enroll MFA."
            ) from exc
        if not verify_totp(secret_b32, code):
            return False
        mfa_secret.last_used = datetime.now(timezone.utc)
        if commit:
            db.commit()
        return True

    # Try backup code (XXXX-XXXX format)
    if mfa_secret.backup_codes_encrypted:
        new_encrypted = verify_and_consume_backup_code(
            code, mfa_secret.backup_codes_encrypted
        )
        if new_encrypted is not None:
            # Consume: replace stored list with the one-shorter list
            mfa_secret.backup_codes_encrypted = new_encrypted
            mfa_secret.last_used = datetime.now(timezone.utc)
            if commit:
                db.commit()
            return True

    return False


# =============================================================================
# Disable
# =============================================================================

def disable_mfa(db: Session, user: User, code: str) -> bool:
    """
    Disable MFA for a user after verifying their current TOTP code.

    Requires a valid TOTP to prevent an attacker who stole a session token
    from silently disabling MFA and then logging in without a code.

    Returns True on success. Raises ValueError on any error.
    """
    mfa_secret = get_active_mfa_secret(db, user.id)
    if mfa_secret is None:
        raise ValueError("MFA is not enabled for this account")

    try:
        secret_b32 = decrypt_totp_secret(mfa_secret.secret_encrypted)
    except ValueError as exc:
        raise ValueError(
            "MFA configuration error: unable to read your MFA secret. "
            "Please re-enroll MFA."
        ) from exc
    if not verify_totp(secret_b32, code):
        raise ValueError("Invalid TOTP code — MFA not disabled")

    # Deactivate secret and disable MFA on user
    mfa_secret.is_active = False
    user.mfa_enabled = False
    db.commit()
    return True
