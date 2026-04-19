"""
Fraud Router — HTTP endpoints for viewing and managing fraud alerts.

Endpoints:
  GET  /fraud/alerts/              → list fraud alerts for the current user
  GET  /fraud/alerts/{id}          → get a single fraud alert
  PATCH /fraud/alerts/{id}/status  → update alert status (analyst/admin action)
"""

import uuid
from typing import Literal, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.api.deps import get_current_user, require_analyst
from app.models.database import get_db
from app.models.user import FraudAlert, User
from app.schemas.fraud import FraudAlertResponse, FraudAlertStatus

# ---------------------------------------------------------------------------
# Router setup
# ---------------------------------------------------------------------------

router = APIRouter(prefix="/fraud", tags=["fraud"])


# ---------------------------------------------------------------------------
# Inline response schema for paginated list
# ---------------------------------------------------------------------------

class FraudAlertListResponse(BaseModel):
    items: list[FraudAlertResponse]
    total: int
    # Legacy compatibility for clients expecting "alerts".
    alerts: list[FraudAlertResponse]


# ---------------------------------------------------------------------------
# GET /fraud/alerts/
# List fraud alerts for the authenticated user
# ---------------------------------------------------------------------------

@router.get(
    "/alerts/",
    response_model=FraudAlertListResponse,
    summary="List fraud alerts for the authenticated user",
)
def list_alerts(
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    status_filter: Optional[str] = Query(
        default=None,
        alias="status",
        description="Filter by alert status: open, investigating, resolved, false_positive",
    ),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> FraudAlertListResponse:
    """
    Return a paginated list of fraud alerts associated with the current user.

    Users can only see their OWN alerts — ownership enforced by filtering on user_id.
    Optionally filter by alert status.
    """
    page = max(1, page)
    page_size = max(1, min(page_size, 100))
    offset = (page - 1) * page_size

    # Ownership rule:
    # - user: only own alerts
    # - analyst/admin: global view for review workflows
    query = db.query(FraudAlert)
    if getattr(current_user, "role", "user") not in {"analyst", "admin"}:
        query = query.filter(FraudAlert.user_id == current_user.id)

    if status_filter:
        # Validate status value against allowed literals before querying
        allowed = {"open", "investigating", "resolved", "false_positive"}
        if status_filter not in allowed:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=f"Invalid status. Must be one of: {', '.join(sorted(allowed))}",
            )
        query = query.filter(FraudAlert.status == status_filter)

    total = query.count()
    alerts = (
        query.order_by(FraudAlert.created_at.desc())
        .offset(offset)
        .limit(page_size)
        .all()
    )

    rows = [FraudAlertResponse.model_validate(a) for a in alerts]
    return FraudAlertListResponse(items=rows, alerts=rows, total=total)


# ---------------------------------------------------------------------------
# GET /fraud/alerts/{alert_id}
# Get a single fraud alert
# ---------------------------------------------------------------------------

@router.get(
    "/alerts/{alert_id}",
    response_model=FraudAlertResponse,
    summary="Get a single fraud alert by ID",
)
def get_alert(
    alert_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> FraudAlertResponse:
    """
    Retrieve a single fraud alert.
    Returns 404 if the alert doesn't exist OR belongs to another user.
    (Same ownership enforcement pattern as transactions — prevent enumeration attacks)
    """
    query = db.query(FraudAlert).filter(FraudAlert.id == alert_id)
    if getattr(current_user, "role", "user") not in {"analyst", "admin"}:
        query = query.filter(FraudAlert.user_id == current_user.id)
    alert = query.first()
    if alert is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Fraud alert not found",
        )
    return FraudAlertResponse.model_validate(alert)


# ---------------------------------------------------------------------------
# PATCH /fraud/alerts/{alert_id}/status
# Update alert status (analyst / admin action)
# ---------------------------------------------------------------------------

class AlertStatusUpdate(BaseModel):
    """Request body for updating a fraud alert's status."""
    status: FraudAlertStatus          # must be a valid status literal from schema
    resolution_notes: Optional[str] = None  # analyst notes (required when resolving)
    assigned_to: Optional[str] = None       # analyst username/id taking ownership


@router.patch(
    "/alerts/{alert_id}/status",
    response_model=FraudAlertResponse,
    summary="Update fraud alert status (analyst action)",
    dependencies=[Depends(require_analyst)],
)
def update_alert_status(
    alert_id: uuid.UUID,
    body: AlertStatusUpdate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> FraudAlertResponse:
    """
    Update the status of a fraud alert.

    Typical analyst workflow:
      open → investigating  (analyst picks up the case)
      investigating → resolved / false_positive  (case closed)

    Requires analyst or admin scope (require_analyst dependency).

    If resolving (status=resolved or false_positive), resolution_notes should be provided.
    """
    # We do NOT enforce ownership here intentionally — analysts manage alerts
    # for all users, not just their own. In production, add role check here.
    alert = db.query(FraudAlert).filter(FraudAlert.id == alert_id).first()
    if alert is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Fraud alert not found",
        )

    # Business rule: resolution_notes should be provided when closing a case
    if body.status in ("resolved", "false_positive") and not body.resolution_notes:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="resolution_notes is required when resolving or marking as false_positive",
        )

    # Apply updates
    alert.status = body.status
    if body.resolution_notes is not None:
        alert.resolution_notes = body.resolution_notes
    if body.assigned_to is not None:
        alert.assigned_to = body.assigned_to

    # Set resolved_at timestamp when closing
    if body.status in ("resolved", "false_positive"):
        from datetime import datetime, timezone
        alert.resolved_at = datetime.now(timezone.utc)

    db.commit()
    db.refresh(alert)
    return FraudAlertResponse.model_validate(alert)
