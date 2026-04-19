"""
app/services/device_service.py — Known device registration and lookup.

Responsibilities:
  register_device()       → upsert a KnownDevice row after successful login
  get_known_devices()     → list all known devices for a user
  remove_device()         → let a user revoke a device

Why this matters for fraud scoring:
  DeviceAnomalyRule in fraud_service.py queries KnownDevice to check whether
  the current device fingerprint has been seen before. Without this service
  writing to that table, every device looks new on every request — the rule
  always fires and adds +35 to the fraud score, making it meaningless noise.

  Once register_device() is called after each successful login:
    - Second login from the same device: score contribution = 0 (known device)
    - Login from a new device:           score contribution = +35 (unknown)
    - Login from a new device after MFA: still +35 until that device is registered

Design decisions:
  - Upsert pattern (check-then-insert or update) rather than plain insert, so
    logging in twice from the same device produces one row, not two.
  - last_seen is always updated on upsert so analysts can see recent activity.
  - is_trusted defaults to False — devices are recognised but not trusted
    until explicitly marked (future feature: trust a device for 30 days).
  - The call is a no-op when device_fingerprint is None (mobile clients that
    don't send the X-Device-Fingerprint header won't error out).
  - commit=False follows the same pattern as other services — the caller
    (auth_service) controls the transaction boundary.
"""

from datetime import datetime, timezone
from typing import Optional
import uuid

from sqlalchemy.orm import Session

from app.models.user import KnownDevice


def register_device(
    db: Session,
    user_id: uuid.UUID,
    device_fingerprint: Optional[str],
    *,
    commit: bool = False,
) -> Optional[KnownDevice]:
    """
    Record a device fingerprint against a user after successful login.

    If the device is already known, updates last_seen only.
    If it is new, inserts a row with is_trusted=False.

    commit=False (default) — the caller commits so this write is atomic
    with the session row and login attempt record.

    Returns the KnownDevice row (new or existing), or None if no fingerprint
    was provided (so callers don't need to guard against None).
    """
    if not device_fingerprint:
        return None

    now = datetime.now(timezone.utc)

    existing = (
        db.query(KnownDevice)
        .filter(
            KnownDevice.user_id == user_id,
            KnownDevice.device_fingerprint == device_fingerprint,
        )
        .first()
    )

    if existing:
        # Device already known — update last_seen so the activity is visible
        # to analysts reviewing the device list.
        existing.last_seen = now
        device = existing
    else:
        # First time seeing this device fingerprint for this user.
        # is_trusted=False: recognised but not yet elevated to trusted status.
        device = KnownDevice(
            user_id=user_id,
            device_fingerprint=device_fingerprint,
            is_trusted=False,
            first_seen=now,
            last_seen=now,
        )
        db.add(device)

    if commit:
        db.commit()
        db.refresh(device)

    return device


def get_known_devices(db: Session, user_id: uuid.UUID) -> list[KnownDevice]:
    """
    Return all known devices for a user, most recently seen first.
    Used by future account management endpoints.
    """
    return (
        db.query(KnownDevice)
        .filter(KnownDevice.user_id == user_id)
        .order_by(KnownDevice.last_seen.desc())
        .all()
    )


def remove_device(
    db: Session,
    user_id: uuid.UUID,
    device_id: uuid.UUID,
) -> bool:
    """
    Remove a known device (user-initiated revocation).

    Ownership check: user_id must match so users can only remove their own
    devices. Returns True if a row was deleted, False if not found.

    After removal, the next login from this fingerprint will be treated as
    a new device by DeviceAnomalyRule and scored accordingly (+35).
    """
    device = (
        db.query(KnownDevice)
        .filter(
            KnownDevice.id == device_id,
            KnownDevice.user_id == user_id,   # ownership enforced here
        )
        .first()
    )
    if not device:
        return False

    db.delete(device)
    db.commit()
    return True