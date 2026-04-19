"""
app/services/admin_service.py — Admin user management business logic.

Responsibilities:
  list_users()              → paginated user list with optional filters
  get_user()                → fetch a single user by ID
  update_account_status()   → suspend / lock / close / reactivate an account
  update_user_role()        → promote/demote user role
  invalidate_user_sessions()→ force-logout all active sessions
  get_user_audit_logs()     → admin view of any user's audit trail

Design decisions:
  - All write operations record an AuditLog entry for full traceability.
    A banking system must be able to answer "who changed this account and when".
  - update_account_status() calls invalidate_user_sessions() automatically when
    an account is suspended/locked/closed — a disabled account must not retain
    active sessions that could still be used until JWT expiry.
  - Admins cannot change their own role (prevents accidental self-demotion or
    lock-out). Validated at the service layer so the rule applies regardless of
    which router calls this function.
  - update_user_role() does NOT invalidate sessions. The new role takes effect
    at the next token refresh (refresh_tokens re-derives scopes from user.role).
    This is intentional: immediate revocation would require a DB check on every
    request, which we avoid by design.

Custom exceptions (map cleanly to HTTP status codes in the router):
  AdminTargetNotFoundError  → 404
  AdminSelfModifyError      → 403
  AdminInvalidStatusError   → 422
"""

from datetime import datetime, timezone
from threading import Lock
from typing import Any, Optional
import uuid

from sqlalchemy import and_, or_
from sqlalchemy.orm import Session

from app.models.user import AuditLog, Session as SessionModel, User
from app.schemas.user import UserResponse


# ─────────────────────────────────────────────────────────────────────────────
# Custom exceptions
# ─────────────────────────────────────────────────────────────────────────────

class AdminTargetNotFoundError(ValueError):
    """Raised when the target user does not exist."""
    pass


class AdminSelfModifyError(ValueError):
    """Raised when an admin tries to modify their own account."""
    pass


class AdminInvalidStatusError(ValueError):
    """Raised when the requested account_status is not a valid transition."""
    pass


class AdminInvalidPolicyError(ValueError):
    """Raised when submitted system policy values are invalid."""
    pass


# ─────────────────────────────────────────────────────────────────────────────
# Valid account status values (mirrors DB CHECK constraint)
# ─────────────────────────────────────────────────────────────────────────────

VALID_STATUSES = {"active", "suspended", "locked", "closed"}
VALID_ROLES    = {"user", "analyst", "admin"}


# ---------------------------------------------------------------------------
# In-memory system policy store for admin console demo workflow.
# NOTE: This is process-local (resets on server restart). For production,
# move to a dedicated DB table.
# ---------------------------------------------------------------------------
_POLICY_LOCK = Lock()
_SYSTEM_POLICY_SETTINGS: dict[str, Any] = {
    "daily_withdrawal_limit": 10_000_000,
    "global_rate_limit": 50_000,
    "multi_sig_internal_ops": True,
    "forced_24h_password_cycle": False,
    "updated_at": None,
}


# ─────────────────────────────────────────────────────────────────────────────
# Internal helpers
# ─────────────────────────────────────────────────────────────────────────────

def _audit(
    db: Session,
    admin_id: uuid.UUID,
    action: str,
    target_user_id: uuid.UUID,
    old_values: Optional[dict] = None,
    new_values: Optional[dict] = None,
    ip_address: Optional[str] = None,
) -> None:
    """Add an AuditLog entry for an admin action (no commit — caller commits)."""
    db.add(AuditLog(
        user_id=admin_id,
        action=action,
        entity_type="user",
        entity_id=target_user_id,
        old_values=old_values,
        new_values=new_values,
        ip_address=ip_address,
        success=True,
    ))


def get_system_policy_settings() -> dict[str, Any]:
    """Return current system policy values for admin UI."""
    with _POLICY_LOCK:
        return dict(_SYSTEM_POLICY_SETTINGS)


def update_system_policy_settings(
    db: Session,
    admin_id: uuid.UUID,
    *,
    daily_withdrawal_limit: Optional[int] = None,
    global_rate_limit: Optional[int] = None,
    multi_sig_internal_ops: Optional[bool] = None,
    forced_24h_password_cycle: Optional[bool] = None,
    ip_address: Optional[str] = None,
) -> dict[str, Any]:
    """
    Update in-memory system policy settings and record an audit log.
    """
    updates: dict[str, Any] = {}
    if daily_withdrawal_limit is not None:
        if daily_withdrawal_limit <= 0:
            raise AdminInvalidPolicyError("daily_withdrawal_limit must be greater than 0")
        updates["daily_withdrawal_limit"] = int(daily_withdrawal_limit)
    if global_rate_limit is not None:
        if global_rate_limit <= 0:
            raise AdminInvalidPolicyError("global_rate_limit must be greater than 0")
        updates["global_rate_limit"] = int(global_rate_limit)
    if multi_sig_internal_ops is not None:
        updates["multi_sig_internal_ops"] = bool(multi_sig_internal_ops)
    if forced_24h_password_cycle is not None:
        updates["forced_24h_password_cycle"] = bool(forced_24h_password_cycle)

    if not updates:
        return get_system_policy_settings()

    now = datetime.now(timezone.utc)
    with _POLICY_LOCK:
        old_values = dict(_SYSTEM_POLICY_SETTINGS)
        _SYSTEM_POLICY_SETTINGS.update(updates)
        _SYSTEM_POLICY_SETTINGS["updated_at"] = now
        new_values = dict(_SYSTEM_POLICY_SETTINGS)

    db.add(
        AuditLog(
            user_id=admin_id,
            action="admin_system_policy_update",
            entity_type="system_policy",
            entity_id=None,
            old_values=old_values,
            new_values=new_values,
            ip_address=ip_address,
            success=True,
        )
    )
    db.commit()
    return new_values


# ─────────────────────────────────────────────────────────────────────────────
# Read operations
# ─────────────────────────────────────────────────────────────────────────────

def list_users(
    db: Session,
    *,
    page: int = 1,
    page_size: int = 20,
    role_filter: Optional[str] = None,
    status_filter: Optional[str] = None,
    search: Optional[str] = None,
) -> dict:
    """
    Paginated list of all users.

    Filters (all optional, combinable):
      role_filter:   exact match on role ('user', 'analyst', 'admin')
      status_filter: exact match on account_status
      search:        case-insensitive substring on email or username

    Returns a dict with 'users' (list of User ORM objects) and 'total' (int).
    """
    page = max(1, page)
    page_size = max(1, min(page_size, 100))
    offset = (page - 1) * page_size

    query = db.query(User)

    if role_filter:
        query = query.filter(User.role == role_filter)
    if status_filter:
        query = query.filter(User.account_status == status_filter)
    if search:
        like = f"%{search}%"
        query = query.filter(
            (User.email.ilike(like)) | (User.username.ilike(like))
        )

    total = query.count()
    users = query.order_by(User.created_at.desc()).offset(offset).limit(page_size).all()

    return {"users": users, "total": total}


def get_user(db: Session, target_user_id: uuid.UUID) -> User:
    """
    Fetch a single user by ID.
    Raises AdminTargetNotFoundError if not found.
    """
    user = db.query(User).filter(User.id == target_user_id).first()
    if not user:
        raise AdminTargetNotFoundError(f"User {target_user_id} not found")
    return user


def get_user_audit_logs(
    db: Session,
    target_user_id: uuid.UUID,
    *,
    page: int = 1,
    page_size: int = 20,
) -> dict:
    """
    Admin view of any user's audit trail (no ownership restriction).
    Returns dict with 'logs' and 'total'.
    """
    from app.models.user import AuditLog as AuditLogModel
    page = max(1, page)
    page_size = max(1, min(page_size, 100))
    offset = (page - 1) * page_size

    query = (
        db.query(AuditLogModel)
        .filter(
            or_(
                # Actions performed by the target user
                AuditLogModel.user_id == target_user_id,
                # Admin actions performed on the target user entity
                and_(
                    AuditLogModel.entity_type == "user",
                    AuditLogModel.entity_id == target_user_id,
                ),
            )
        )
        .order_by(AuditLogModel.created_at.desc())
    )
    total = query.count()
    logs = query.offset(offset).limit(page_size).all()
    return {"logs": logs, "total": total}


# ─────────────────────────────────────────────────────────────────────────────
# Write operations
# ─────────────────────────────────────────────────────────────────────────────

def invalidate_user_sessions(
    db: Session,
    target_user_id: uuid.UUID,
    *,
    commit: bool = False,
) -> int:
    """
    Force-logout by setting is_active=False and logout_at=now on all active
    sessions for the target user.

    Returns the number of sessions invalidated.
    commit=False (default) so the caller can bundle this with other writes.
    """
    now = datetime.now(timezone.utc)
    sessions = (
        db.query(SessionModel)
        .filter(
            SessionModel.user_id == target_user_id,
            SessionModel.is_active.is_(True),
        )
        .all()
    )
    for session in sessions:
        session.is_active = False
        session.logout_at = now

    if commit:
        db.commit()

    return len(sessions)


def force_logout_user_sessions(
    db: Session,
    admin_id: uuid.UUID,
    target_user_id: uuid.UUID,
    *,
    ip_address: Optional[str] = None,
) -> int:
    """
    Admin-triggered force logout with audit trail.

    Ensures the target user exists, invalidates active sessions, records an
    AuditLog entry, and commits atomically.
    """
    get_user(db, target_user_id)  # raises AdminTargetNotFoundError if missing
    count = invalidate_user_sessions(db, target_user_id, commit=False)
    _audit(
        db,
        admin_id,
        action="admin_force_logout",
        target_user_id=target_user_id,
        old_values=None,
        new_values={"sessions_invalidated": count},
        ip_address=ip_address,
    )
    db.commit()
    return count


def update_account_status(
    db: Session,
    admin_id: uuid.UUID,
    target_user_id: uuid.UUID,
    new_status: str,
    *,
    reason: Optional[str] = None,
    ip_address: Optional[str] = None,
) -> User:
    """
    Change a user's account_status (suspend / lock / close / reactivate).

    Side effects:
      - If new_status is not 'active', all active sessions are invalidated.
        A suspended user must not retain working tokens.
      - AuditLog entry recorded with old and new status.

    Raises:
      AdminTargetNotFoundError  — target user not found
      AdminSelfModifyError      — admin cannot change their own status
      AdminInvalidStatusError   — new_status is not a valid value
    """
    if new_status not in VALID_STATUSES:
        raise AdminInvalidStatusError(
            f"Invalid status '{new_status}'. Must be one of: {', '.join(sorted(VALID_STATUSES))}"
        )
    if admin_id == target_user_id:
        raise AdminSelfModifyError("Admins cannot change their own account status")

    user = get_user(db, target_user_id)

    old_status = user.account_status
    user.account_status = new_status

    # Clear lock state when reactivating
    if new_status == "active":
        user.locked_until = None
        user.failed_login_attempts = 0

    # Force-logout if disabling — do before commit so sessions land together
    sessions_invalidated = 0
    if new_status != "active":
        sessions_invalidated = invalidate_user_sessions(db, target_user_id, commit=False)

    _audit(
        db, admin_id,
        action=f"admin_status_change",
        target_user_id=target_user_id,
        old_values={"account_status": old_status},
        new_values={
            "account_status": new_status,
            "reason": reason,
            "sessions_invalidated": sessions_invalidated,
        },
        ip_address=ip_address,
    )

    db.commit()
    db.refresh(user)
    return user


def update_user_role(
    db: Session,
    admin_id: uuid.UUID,
    target_user_id: uuid.UUID,
    new_role: str,
    *,
    ip_address: Optional[str] = None,
) -> User:
    """
    Change a user's role ('user', 'analyst', 'admin').

    The new role takes effect at the user's next token refresh — existing
    sessions are NOT invalidated because doing so would require a DB lookup
    on every API request. If immediate revocation is needed, call
    invalidate_user_sessions() explicitly after this function.

    Raises:
      AdminTargetNotFoundError — target user not found
      AdminSelfModifyError     — admin cannot change their own role
      AdminInvalidStatusError  — new_role is not a valid value
    """
    if new_role not in VALID_ROLES:
        raise AdminInvalidStatusError(
            f"Invalid role '{new_role}'. Must be one of: {', '.join(sorted(VALID_ROLES))}"
        )
    if admin_id == target_user_id:
        raise AdminSelfModifyError("Admins cannot change their own role")

    user = get_user(db, target_user_id)
    old_role = user.role
    user.role = new_role

    _audit(
        db, admin_id,
        action="admin_role_change",
        target_user_id=target_user_id,
        old_values={"role": old_role},
        new_values={"role": new_role},
        ip_address=ip_address,
    )

    db.commit()
    db.refresh(user)
    return user
    
