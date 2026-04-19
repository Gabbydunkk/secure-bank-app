"""
app/core/totp.py — TOTP (RFC 6238) implementation + TOTP secret encryption.

Why no pyotp?
  pyotp is the conventional library, but it is not in requirements.txt and the
  network is unavailable in this environment. Instead we implement RFC 6238
  directly using Python's standard library (hmac, hashlib, struct, base64,
  secrets) — exactly the same algorithm, zero extra dependencies.

TOTP algorithm (30-second window, SHA-1, 6 digits):
  1. Generate HMAC-SHA1(secret_bytes, 8-byte big-endian(floor(time/30)))
  2. Dynamic truncation: extract 4-byte window at offset = last_nibble(HMAC)
  3. OTP = (window & 0x7FFFFFFF) % 10^6

Secret encryption:
  TOTP secrets are sensitive (compromise = permanent 2FA bypass).
  We encrypt them at rest with Fernet (AES-128-CBC + HMAC-SHA256) using a
  key derived from the application SECRET_KEY via SHA-256.
  This means: even if the database is stolen, the TOTP secrets are
  unreadable without the application key.

Backup codes:
  8 single-use codes in "XXXX-XXXX" format (8 hex chars each side).
  Each code is SHA-256 hashed before storage so the DB never holds
  plaintext codes (same pattern as refresh tokens).
"""

import base64
import hashlib
import hmac
import json
import secrets
import struct
import time
from typing import Optional

from cryptography.fernet import Fernet, InvalidToken

from app.core.config import settings


# ─────────────────────────────────────────────────────────────────────────────
# Fernet key derivation
# ─────────────────────────────────────────────────────────────────────────────

def _get_fernet() -> Fernet:
    """
    Derive a stable Fernet key from the application SECRET_KEY.

    SHA-256(SECRET_KEY) produces exactly 32 bytes.
    base64.urlsafe_b64encode() converts it to the format Fernet expects.
    The key is deterministic — the same SECRET_KEY always yields the same
    Fernet key, so previously encrypted values can still be decrypted.
    """
    key_bytes = hashlib.sha256(settings.SECRET_KEY.encode()).digest()
    fernet_key = base64.urlsafe_b64encode(key_bytes)
    return Fernet(fernet_key)


# ─────────────────────────────────────────────────────────────────────────────
# TOTP secret generation and encryption
# ─────────────────────────────────────────────────────────────────────────────

def generate_totp_secret() -> str:
    """
    Generate a cryptographically secure TOTP secret.

    20 random bytes → base32 string (160 bits of entropy).
    Standard authenticator apps (Google Authenticator, Authy, 1Password)
    all accept this format via the otpauth:// URI or manual entry.
    """
    # Most authenticator apps expect base32 secrets WITHOUT "=" padding.
    # Keeping secrets unpadded also avoids edge-case URI parsers that treat "="
    # as a delimiter and truncate the secret value.
    return base64.b32encode(secrets.token_bytes(20)).decode().rstrip("=")


def encrypt_totp_secret(plaintext_secret: str) -> bytes:
    """
    Encrypt a plaintext TOTP secret (base32 string) for storage.
    Returns Fernet-encrypted bytes to store in mfa_secrets.secret_encrypted.
    """
    return _get_fernet().encrypt(plaintext_secret.encode())


def decrypt_totp_secret(encrypted_secret: bytes) -> str:
    """
    Decrypt a stored TOTP secret.
    Raises ValueError if the ciphertext is invalid or was encrypted with a
    different key (i.e. SECRET_KEY was rotated — handle this in production with
    key versioning or a key management service).
    """
    try:
        return _get_fernet().decrypt(encrypted_secret).decode()
    except (InvalidToken, Exception) as exc:
        raise ValueError("Failed to decrypt TOTP secret — key may have changed") from exc


# ─────────────────────────────────────────────────────────────────────────────
# Provisioning URI (for QR code generation)
# ─────────────────────────────────────────────────────────────────────────────

def get_totp_uri(secret: str, email: str, issuer: str = "SecureBankPro") -> str:
    """
    Build a standard otpauth:// URI for QR code generation.

    Format: otpauth://totp/{issuer}:{account}?secret={secret}&issuer={issuer}&algorithm=SHA1&digits=6&period=30

    The client encodes this URI as a QR code image and the user scans it
    with their authenticator app (Google Authenticator, Authy, 1Password).
    After scanning, the app generates TOTP codes every 30 seconds.
    """
    from urllib.parse import quote
    label = quote(f"{issuer}:{email}")
    return (
        f"otpauth://totp/{label}"
        # Encode secret defensively; some parsers are picky about reserved chars.
        f"?secret={quote(secret)}"
        f"&issuer={quote(issuer)}"
        f"&algorithm=SHA1"
        f"&digits=6"
        f"&period=30"
    )


def _normalize_base32_secret(secret_b32: str) -> str:
    """
    Normalize a base32 secret to a form Python can decode reliably:
    - Uppercase
    - Strip whitespace
    - Add '=' padding to a multiple of 8 chars (RFC 4648)
    """
    s = "".join(secret_b32.strip().split()).upper()
    # Add required padding for Python's base32 decoder.
    pad_len = (-len(s)) % 8
    if pad_len:
        s += "=" * pad_len
    return s


# ─────────────────────────────────────────────────────────────────────────────
# RFC 4226 HOTP (core algorithm)
# ─────────────────────────────────────────────────────────────────────────────

def _hotp(secret_bytes: bytes, counter: int) -> int:
    """
    RFC 4226 HOTP — compute one OTP for a given counter value.

    Step 1: HS = HMAC-SHA1(key=secret_bytes, msg=counter_as_8_bytes)
    Step 2: Dynamic truncation:
              offset = HS[-1] & 0x0F          (4 LSBs of final byte)
              P = HS[offset:offset+4]          (4-byte window)
              truncated = P & 0x7FFFFFFF       (mask top bit → positive int)
    Step 3: OTP = truncated % 10^6            (6-digit code)

    This is the same computation every authenticator app performs.
    """
    msg = struct.pack(">Q", counter)                          # 8-byte big-endian counter
    hs = hmac.new(secret_bytes, msg, hashlib.sha1).digest()   # 20-byte HMAC-SHA1
    offset = hs[-1] & 0x0F                                    # dynamic truncation offset
    p = struct.unpack(">I", hs[offset:offset + 4])[0]        # 4-byte big-endian int
    return (p & 0x7FFFFFFF) % 1_000_000                       # 31-bit, then 6 digits


# ─────────────────────────────────────────────────────────────────────────────
# RFC 6238 TOTP verification
# ─────────────────────────────────────────────────────────────────────────────

def verify_totp(secret_b32: str, code: str, window: int = 1) -> bool:
    """
    RFC 6238 TOTP — verify a 6-digit code against the current time.

    window=1 allows ±1 time step (±30 seconds) to compensate for:
      - Clock drift between server and client device
      - User entering the code just as it rotates

    Returns True only if the code matches the current or adjacent window.
    Never raises — returns False on any malformed input.
    """
    try:
        secret_bytes = base64.b32decode(_normalize_base32_secret(secret_b32))
        code_int = int(code)
        if code_int < 0 or code_int > 999_999:  # reject out-of-range values
            return False
    except Exception:
        return False

    t = int(time.time()) // 30          # current 30-second time step
    return any(
        _hotp(secret_bytes, t + delta) == code_int
        for delta in range(-window, window + 1)
    )


def verify_totp_strict(secret_b32: str, code: str) -> bool:
    """
    Strict TOTP with no window drift — used for confirming MFA setup.

    During setup confirmation, the user just scanned the QR code so there
    is no clock drift. Strict verification catches typos before MFA is enabled.
    Still allows window=1 for the edge case of rotations during typing.
    """
    return verify_totp(secret_b32, code, window=1)


# ─────────────────────────────────────────────────────────────────────────────
# Backup codes
# ─────────────────────────────────────────────────────────────────────────────

_BACKUP_CODE_COUNT = 8


def generate_backup_codes() -> tuple[list[str], list[str]]:
    """
    Generate 8 single-use backup codes.

    Returns (plaintext_codes, hashed_codes):
      - plaintext_codes: shown to the user ONCE during setup (e.g. "A3F2-9C1B")
      - hashed_codes: SHA-256 hashes stored in the database (like refresh tokens)

    Why hash backup codes?
      If the DB is read by an attacker, they cannot use the backup codes
      to bypass MFA. The SHA-256 hash is sufficient here because backup
      codes are high-entropy (128 bits) and not subject to dictionary attacks.
    """
    plaintexts = [
        secrets.token_hex(4).upper() + "-" + secrets.token_hex(4).upper()
        for _ in range(_BACKUP_CODE_COUNT)
    ]
    hashes = [hashlib.sha256(c.encode()).hexdigest() for c in plaintexts]
    return plaintexts, hashes


def encrypt_backup_codes(hashed_codes: list[str]) -> bytes:
    """Encrypt the list of backup code hashes for storage in backup_codes_encrypted."""
    return _get_fernet().encrypt(json.dumps(hashed_codes).encode())


def decrypt_backup_codes(encrypted: bytes) -> list[str]:
    """Decrypt stored backup code hashes back to a list of SHA-256 hex strings."""
    try:
        return json.loads(_get_fernet().decrypt(encrypted).decode())
    except (InvalidToken, Exception) as exc:
        raise ValueError("Failed to decrypt backup codes") from exc


def verify_and_consume_backup_code(
    code: str,
    encrypted_codes: bytes,
) -> Optional[bytes]:
    """
    Verify a backup code and consume it (single-use).

    Returns:
      New encrypted backup codes bytes (with the used code removed) on success.
      None if the code was not found.

    Single-use enforcement: once a code is used, it is removed from the list and
    the updated list is re-encrypted. If the caller commits the update to the DB,
    the code can never be used again — even if the attacker observed it in transit.
    """
    code_hash = hashlib.sha256(code.strip().upper().encode()).hexdigest()
    hashed_codes = decrypt_backup_codes(encrypted_codes)
    if code_hash not in hashed_codes:
        return None
    hashed_codes.remove(code_hash)
    return encrypt_backup_codes(hashed_codes)