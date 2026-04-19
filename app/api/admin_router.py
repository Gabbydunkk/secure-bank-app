"""
app/api/admin_router.py — Admin user management endpoints.

All endpoints require admin scope (require_admin dependency).
Any authenticated user without admin scope receives 403 before any business
logic runs.

Endpoints:
  GET    /admin/users/                     → list all users (paginated, filterable)
  GET    /admin/users/{user_id}            → get a single user
  PATCH  /admin/users/{user_id}/status     → change account status
  PATCH  /admin/users/{user_id}/role       → change user role
  DELETE /admin/users/{user_id}/sessions   → force-logout all sessions
  GET    /admin/users/{user_id}/audit-logs → view any user's audit trail
"""

import uuid
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.api.deps import get_client_ip, get_current_user, require_admin
from app.models.database import get_db
from app.models.user import AuditLog, User
from app.schemas.audit import AuditLogListResponse, AuditLogResponse
from app.schemas.user import UserResponse
from app.services.admin_service import (
    AdminInvalidPolicyError,
    AdminInvalidStatusError,
    AdminSelfModifyError,
    AdminTargetNotFoundError,
    force_logout_user_sessions,
    get_system_policy_settings,
    get_user,
    get_user_audit_logs,
    list_users,
    update_account_status,
    update_system_policy_settings,
    update_user_role,
)

# ---------------------------------------------------------------------------
# Router — all routes under /admin, all require admin scope
# ---------------------------------------------------------------------------

router = APIRouter(
    prefix="/admin",
    tags=["admin"],
    dependencies=[Depends(require_admin)],
    # The dependencies list here applies require_admin to EVERY route in this
    # router, so we don't have to repeat it on each endpoint decorator.
    # A token without admin scope receives 403 before the handler runs.
)


@router.get(
    "/audit-logs",
    response_model=AuditLogListResponse,
    summary="View system-wide audit logs (admin)",
)
def get_system_audit_logs(
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=200),
    action_filter: Optional[str] = Query(default=None, alias="action"),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> AuditLogListResponse:
    """
    System-wide audit stream for admin operations consoles.
    """
    page = max(1, page)
    page_size = max(1, min(page_size, 200))
    offset = (page - 1) * page_size

    query = db.query(AuditLog)
    if action_filter:
        query = query.filter(AuditLog.action.ilike(f"%{action_filter}%"))
    total = query.count()
    logs = query.order_by(AuditLog.created_at.desc()).offset(offset).limit(page_size).all()
    return AuditLogListResponse(
        logs=[AuditLogResponse.model_validate(log, from_attributes=True) for log in logs],
        total=total,
    )


# ---------------------------------------------------------------------------
# Inline response schemas
# ---------------------------------------------------------------------------

class UserListResponse(BaseModel):
    items: list[UserResponse]
    total: int
    # Legacy compatibility for clients expecting "users".
    users: list[UserResponse]


class StatusUpdateBody(BaseModel):
    """Request body for PATCH /admin/users/{id}/status."""
    status: str
    reason: Optional[str] = None


class RoleUpdateBody(BaseModel):
    """Request body for PATCH /admin/users/{id}/role."""
    role: str


class SessionInvalidationResponse(BaseModel):
    sessions_invalidated: int
    message: str


class SystemPolicySettingsResponse(BaseModel):
    daily_withdrawal_limit: int
    global_rate_limit: int
    multi_sig_internal_ops: bool
    forced_24h_password_cycle: bool
    updated_at: Optional[str] = None


class SystemPolicySettingsUpdateBody(BaseModel):
    daily_withdrawal_limit: Optional[int] = None
    global_rate_limit: Optional[int] = None
    multi_sig_internal_ops: Optional[bool] = None
    forced_24h_password_cycle: Optional[bool] = None


@router.get(
    "/system/settings",
    response_model=SystemPolicySettingsResponse,
    summary="Get admin system policy settings",
)
def get_system_settings() -> SystemPolicySettingsResponse:
    data = get_system_policy_settings()
    updated_at = data.get("updated_at")
    return SystemPolicySettingsResponse(
        daily_withdrawal_limit=int(data["daily_withdrawal_limit"]),
        global_rate_limit=int(data["global_rate_limit"]),
        multi_sig_internal_ops=bool(data["multi_sig_internal_ops"]),
        forced_24h_password_cycle=bool(data["forced_24h_password_cycle"]),
        updated_at=updated_at.isoformat() if updated_at else None,
    )


@router.patch(
    "/system/settings",
    response_model=SystemPolicySettingsResponse,
    summary="Update admin system policy settings",
)
def patch_system_settings(
    body: SystemPolicySettingsUpdateBody,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> SystemPolicySettingsResponse:
    try:
        data = update_system_policy_settings(
            db,
            admin_id=current_user.id,
            daily_withdrawal_limit=body.daily_withdrawal_limit,
            global_rate_limit=body.global_rate_limit,
            multi_sig_internal_ops=body.multi_sig_internal_ops,
            forced_24h_password_cycle=body.forced_24h_password_cycle,
            ip_address=get_client_ip(request),
        )
    except AdminInvalidPolicyError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc))

    updated_at = data.get("updated_at")
    return SystemPolicySettingsResponse(
        daily_withdrawal_limit=int(data["daily_withdrawal_limit"]),
        global_rate_limit=int(data["global_rate_limit"]),
        multi_sig_internal_ops=bool(data["multi_sig_internal_ops"]),
        forced_24h_password_cycle=bool(data["forced_24h_password_cycle"]),
        updated_at=updated_at.isoformat() if updated_at else None,
    )


# ---------------------------------------------------------------------------
# GET /admin/users/
# ---------------------------------------------------------------------------

@router.get(
    "/users/",
    response_model=UserListResponse,
    summary="List all users (admin)",
)
def list_all_users(
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    role: Optional[str] = Query(default=None, description="Filter by role: user, analyst, admin"),
    account_status: Optional[str] = Query(default=None, description="Filter by account_status"),
    search: Optional[str] = Query(default=None, description="Search by email or username"),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> UserListResponse:
    """
    Return a paginated list of all users in the system.

    Filters are optional and combinable:
      - role:           exact match ('user', 'analyst', 'admin')
      - account_status: exact match ('active', 'suspended', 'locked', 'closed')
      - search:         case-insensitive substring on email or username

    Newest accounts first. Requires admin scope.
    """
    result = list_users(
        db,
        page=page,
        page_size=page_size,
        role_filter=role,
        status_filter=account_status,
        search=search,
    )
    rows = [UserResponse.model_validate(u, from_attributes=True) for u in result["users"]]
    return UserListResponse(items=rows, users=rows, total=result["total"])


# ---------------------------------------------------------------------------
# GET /admin/users/{user_id}
# ---------------------------------------------------------------------------

@router.get(
    "/users/{user_id}",
    response_model=UserResponse,
    summary="Get a single user by ID (admin)",
)
def get_single_user(
    user_id: uuid.UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> UserResponse:
    """
    Retrieve full profile of any user by UUID.
    Returns 404 if the user does not exist.
    """
    try:
        user = get_user(db, user_id)
    except AdminTargetNotFoundError:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
    return UserResponse.model_validate(user, from_attributes=True)


# ---------------------------------------------------------------------------
# PATCH /admin/users/{user_id}/status
# ---------------------------------------------------------------------------

@router.patch(
    "/users/{user_id}/status",
    response_model=UserResponse,
    summary="Change a user's account status (admin)",
)
def change_account_status(
    user_id: uuid.UUID,
    body: StatusUpdateBody,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> UserResponse:
    """
    Change a user's account_status.

    Valid transitions:
      active → suspended  (e.g. suspicious activity detected)
      active → locked     (e.g. manual lock by admin)
      active → closed     (e.g. account deletion request)
      suspended → active  (e.g. investigation cleared)
      locked → active     (e.g. manual unlock)

    Side effects:
      - Non-active status: ALL active sessions are immediately invalidated.
        The user's existing tokens stop working at the next request.
      - Reactivation (→ active): clears locked_until and failed_login_attempts.

    Raises 403 if the admin attempts to change their own account status.
    Raises 404 if the target user does not exist.
    Raises 422 if the requested status is not a valid value.
    """
    try:
        user = update_account_status(
            db,
            admin_id=current_user.id,
            target_user_id=user_id,
            new_status=body.status,
            reason=body.reason,
            ip_address=get_client_ip(request),
        )
    except AdminTargetNotFoundError:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
    except AdminSelfModifyError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc))
    except AdminInvalidStatusError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc))
    return UserResponse.model_validate(user, from_attributes=True)


# ---------------------------------------------------------------------------
# PATCH /admin/users/{user_id}/role
# ---------------------------------------------------------------------------

@router.patch(
    "/users/{user_id}/role",
    response_model=UserResponse,
    summary="Change a user's role (admin)",
)
def change_user_role(
    user_id: uuid.UUID,
    body: RoleUpdateBody,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> UserResponse:
    """
    Promote or demote a user's role.

    Valid roles: user, analyst, admin

    The new role takes effect at the user's NEXT token refresh — existing
    tokens retain their current scopes until refreshed. This is by design:
    immediate scope revocation would require a DB hit on every API request.

    If immediate revocation is required (e.g. analyst suspected of misconduct),
    call DELETE /admin/users/{id}/sessions after this endpoint to force-logout.

    Raises 403 if the admin attempts to change their own role.
    Raises 404 if the target user does not exist.
    Raises 422 if the requested role is not valid.
    """
    try:
        user = update_user_role(
            db,
            admin_id=current_user.id,
            target_user_id=user_id,
            new_role=body.role,
            ip_address=get_client_ip(request),
        )
    except AdminTargetNotFoundError:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
    except AdminSelfModifyError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc))
    except AdminInvalidStatusError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc))
    return UserResponse.model_validate(user, from_attributes=True)


# ---------------------------------------------------------------------------
# DELETE /admin/users/{user_id}/sessions
# ---------------------------------------------------------------------------

@router.delete(
    "/users/{user_id}/sessions",
    response_model=SessionInvalidationResponse,
    summary="Force-logout all active sessions for a user (admin)",
)
def force_logout_user(
    user_id: uuid.UUID,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> SessionInvalidationResponse:
    """
    Immediately invalidate all active sessions for a user.

    This is the emergency kill-switch for a compromised account.
    After this call, every existing JWT for this user will fail the session
    liveness check in get_current_session() and return 401.

    Note: this does NOT change the account_status. The user can still log in
    and create new sessions unless account_status is also changed. To fully
    lock out an account, call PATCH /admin/users/{id}/status (which calls
    this automatically) or call both endpoints in sequence.

    Returns the number of sessions invalidated.
    """
    try:
        count = force_logout_user_sessions(
            db,
            admin_id=current_user.id,
            target_user_id=user_id,
            ip_address=get_client_ip(request),
        )
    except AdminTargetNotFoundError:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
    return SessionInvalidationResponse(
        sessions_invalidated=count,
        message=f"Invalidated {count} active session(s) for user {user_id}.",
    )


# ---------------------------------------------------------------------------
# GET /admin/users/{user_id}/audit-logs
# ---------------------------------------------------------------------------

@router.get(
    "/users/{user_id}/audit-logs",
    response_model=AuditLogListResponse,
    summary="View any user's audit trail (admin)",
)
def get_audit_logs(
    user_id: uuid.UUID,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> AuditLogListResponse:
    """
    Retrieve the complete audit trail for any user — not restricted to their
    own logs like the user-facing /audit/logs/ endpoint.

    Admins need this to investigate incidents: "what did this user do before
    their account was flagged?" and "which admin changed this account status?"

    Returns 404 if the target user does not exist.
    """
    try:
        get_user(db, user_id)
    except AdminTargetNotFoundError:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")

    result = get_user_audit_logs(db, user_id, page=page, page_size=page_size)
    return AuditLogListResponse(
        logs=[AuditLogResponse.model_validate(log, from_attributes=True) for log in result["logs"]],
        total=result["total"],
    )
    
