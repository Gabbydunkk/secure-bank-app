"""
Audit Log Router — HTTP endpoints for viewing the audit trail.

Endpoints:
  GET /audit/logs/      → list audit logs for the current user (paginated)
  GET /audit/logs/{id}  → get a single audit log entry

Audit logs are IMMUTABLE — no create/update/delete endpoints here.
The service layer writes logs; users can only READ their own history.
"""

import uuid
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.models.database import get_db
from app.models.user import AuditLog, User
from app.schemas.audit import AuditLogListResponse, AuditLogResponse

# ---------------------------------------------------------------------------
# Router setup
# ---------------------------------------------------------------------------

router = APIRouter(prefix="/audit", tags=["audit"])


# ---------------------------------------------------------------------------
# GET /audit/logs/
# Paginated list of audit logs for the current user
# ---------------------------------------------------------------------------

@router.get(
    "/logs/",
    response_model=AuditLogListResponse,
    summary="List audit logs for the authenticated user",
)
def list_audit_logs(
    page: int = Query(default=1, ge=1, description="Page number (1-indexed)"),
    page_size: int = Query(default=20, ge=1, le=100, description="Results per page (max 100)"),
    action_filter: Optional[str] = Query(
        default=None,
        alias="action",
        description="Filter by action type e.g. 'transaction_create', 'transaction_completed'",
    ),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> AuditLogListResponse:
    """
    Return a paginated, newest-first list of audit log entries for the current user.

    Audit logs record every sensitive action:
    - transaction_create, transaction_completed, transaction_failed, transaction_blocked
    - login_success, login_failed, account_locked (written by auth_service)

    Users can only see their OWN audit logs — user_id filter enforces this.
    Optionally filter by action type.

    The audit log is append-only — no entries can be deleted or modified.
    """
    page = max(1, page)
    page_size = max(1, min(page_size, 100))
    offset = (page - 1) * page_size

    # Always scope to the authenticated user
    query = (
        db.query(AuditLog)
        .filter(AuditLog.user_id == current_user.id)
    )

    if action_filter:
        # Partial match allows filtering by prefix e.g. "transaction" returns all tx logs
        query = query.filter(AuditLog.action.ilike(f"%{action_filter}%"))

    total = query.count()
    logs = (
        query.order_by(AuditLog.created_at.desc())
        .offset(offset)
        .limit(page_size)
        .all()
    )

    rows = [AuditLogResponse.model_validate(log) for log in logs]
    return AuditLogListResponse(items=rows, logs=rows, total=total)


# ---------------------------------------------------------------------------
# GET /audit/logs/{log_id}
# Single audit log entry
# ---------------------------------------------------------------------------

@router.get(
    "/logs/{log_id}",
    response_model=AuditLogResponse,
    summary="Get a single audit log entry by ID",
)
def get_audit_log(
    log_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> AuditLogResponse:
    """
    Retrieve a single audit log entry.

    Returns 404 if the log doesn't exist OR belongs to another user.
    Same ownership-via-404 pattern used throughout — prevents user enumeration.
    """
    log = (
        db.query(AuditLog)
        .filter(
            AuditLog.id == log_id,
            AuditLog.user_id == current_user.id,  # ownership enforced here
        )
        .first()
    )
    if log is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Audit log entry not found",
        )
    return AuditLogResponse.model_validate(log)
