"""
Transaction Router — HTTP endpoints for creating and managing financial transactions.

Endpoints:
  POST /transactions/              → create a new transaction (fraud-checked)
  GET  /transactions/              → list user's transactions (paginated)
  GET  /transactions/{id}          → get a single transaction
  POST /transactions/{id}/process  → advance transaction through state machine
  POST /transactions/{id}/block    → manually block a transaction (admin/analyst)
"""

import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy.orm import Session

from app.api.deps import (
    get_client_ip,
    get_current_user,
    require_analyst,
    require_transfer_authorized,
)
from app.models.database import get_db
from app.models.user import User
from app.schemas.transaction import (
    TransactionCreate,
    TransactionListResponse,
    TransactionResponse,
)
from app.services.transaction_service import (
    clear_flagged_transaction,
    TransactionBlockedError,
    TransactionNotFoundError,
    TransactionStateError,
    block_transaction,
    create_transaction,
    get_transaction_for_review,
    get_transaction,
    list_transactions_for_review,
    list_transactions,
    process_transaction,
)

# ---------------------------------------------------------------------------
# Router setup
# ---------------------------------------------------------------------------

router = APIRouter(prefix="/transactions", tags=["transactions"])


# ---------------------------------------------------------------------------
# POST /transactions/
# Create a new transaction
# ---------------------------------------------------------------------------

@router.post(
    "/",
    response_model=TransactionResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create a new financial transaction",
    dependencies=[Depends(require_transfer_authorized)],
    # ^ require_scope enforces that the JWT has 'transfer_authorized' scope
    # A basic read-only token CANNOT create transactions — least-privilege in action
)
def create(
    data: TransactionCreate,         # request body with amount, type, recipient, etc.
    request: Request,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> TransactionResponse:
    """
    Submit a new transaction. The fraud engine runs before any DB write.

    - If fraud score ≥ BLOCK threshold: transaction is rejected (403)
    - If fraud score ≥ FLAG threshold: transaction created with status='flagged'
    - If fraud score < FLAG threshold: transaction created with status='pending'

    Requires authenticated active user with transfer_authorized scope.
    """
    ip = get_client_ip(request)
    user_agent = request.headers.get("User-Agent")
    device_fingerprint = request.headers.get("X-Device-Fingerprint")
    location_country = request.headers.get("X-Location-Country")
    location_city = request.headers.get("X-Location-City")

    try:
        txn = create_transaction(
            db,
            user_id=current_user.id,
            data=data,
            ip_address=ip,
            user_agent=user_agent,
            device_fingerprint=device_fingerprint,
            location_country=location_country,
            location_city=location_city,
        )
    except TransactionBlockedError as exc:
        # Fraud engine blocked this transaction outright
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=str(exc),
        )
    except ValueError as exc:
        # Validation errors from the service layer
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(exc),
        )

    return txn


# ---------------------------------------------------------------------------
# GET /transactions/
# List transactions (paginated, newest first)
# ---------------------------------------------------------------------------

@router.get(
    "/",
    response_model=TransactionListResponse,
    summary="List transactions for the authenticated user",
)
def list_user_transactions(
    page: int = Query(default=1, ge=1, description="Page number (1-indexed)"),
    page_size: int = Query(default=20, ge=1, le=100, description="Items per page (max 100)"),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> TransactionListResponse:
    """
    Return a paginated list of the authenticated user's transactions, newest first.

    Query params:
    - page: which page to return (default 1)
    - page_size: how many per page (default 20, max 100)

    Users can only see their own transactions — ownership is enforced in the service layer.
    """
    return list_transactions(db, user_id=current_user.id, page=page, page_size=page_size)


@router.get(
    "/review",
    response_model=TransactionListResponse,
    summary="List transactions for analyst/admin review",
    dependencies=[Depends(require_analyst)],
)
def list_review_transactions(
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    status_filter: str | None = Query(default=None, alias="status"),
    min_risk_score: int | None = Query(default=None, ge=0, le=100),
    db: Session = Depends(get_db),
) -> TransactionListResponse:
    """
    Global transaction feed for analyst/admin triage.
    Includes transactions across all users.
    """
    return list_transactions_for_review(
        db,
        page=page,
        page_size=page_size,
        status_filter=status_filter,
        min_risk_score=min_risk_score,
    )


# ---------------------------------------------------------------------------
# GET /transactions/{transaction_id}
# Get a single transaction
# ---------------------------------------------------------------------------

@router.get(
    "/{transaction_id}",
    response_model=TransactionResponse,
    summary="Get a single transaction by ID",
)
def get_one(
    transaction_id: uuid.UUID,   # FastAPI auto-validates this is a valid UUID
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> TransactionResponse:
    """
    Retrieve a single transaction by its UUID.
    Returns 404 if the transaction does not exist OR belongs to another user.
    (Ownership check prevents users from probing other users' transaction IDs)
    """
    try:
        return get_transaction(db, transaction_id=transaction_id, user_id=current_user.id)
    except TransactionNotFoundError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Transaction not found",
        )


@router.get(
    "/review-item/{transaction_id}",
    response_model=TransactionResponse,
    summary="Get a transaction for analyst/admin review",
    dependencies=[Depends(require_analyst)],
)
def get_one_for_review(
    transaction_id: uuid.UUID,
    db: Session = Depends(get_db),
) -> TransactionResponse:
    try:
        return get_transaction_for_review(db, transaction_id=transaction_id)
    except TransactionNotFoundError:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Transaction not found")


# ---------------------------------------------------------------------------
# POST /transactions/{transaction_id}/process
# Advance a pending transaction through the state machine
# ---------------------------------------------------------------------------

@router.post(
    "/{transaction_id}/process",
    response_model=TransactionResponse,
    summary="Process a pending transaction",
)
def process(
    transaction_id: uuid.UUID,
    request: Request,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> TransactionResponse:
    """
    Advance a pending transaction through the processing state machine:
      pending → processing → completed (happy path)
      pending → failed (on any error)

    Flagged transactions raise 409 — they require manual review first.
    Terminal states (completed/failed/blocked) return current state idempotently.

    Requires authenticated active user.
    """
    ip = get_client_ip(request)
    user_agent = request.headers.get("User-Agent")

    try:
        return process_transaction(
            db,
            transaction_id=transaction_id,
            user_id=current_user.id,
            ip_address=ip,
            user_agent=user_agent,
        )
    except TransactionNotFoundError:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Transaction not found")
    except TransactionStateError as exc:
        # Invalid state transition — e.g. trying to process a flagged transaction
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc))


# ---------------------------------------------------------------------------
# POST /transactions/{transaction_id}/block
# Manually block a flagged transaction (admin/analyst action)
# ---------------------------------------------------------------------------

from pydantic import BaseModel

class BlockReasonBody(BaseModel):
    reason: str | None = None


@router.post(
    "/{transaction_id}/clear",
    response_model=TransactionResponse,
    summary="Clear a flagged transaction for processing (analyst/admin action)",
    dependencies=[Depends(require_analyst)],
)
def clear_flag(
    transaction_id: uuid.UUID,
    request: Request,
    body: BlockReasonBody = BlockReasonBody(),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> TransactionResponse:
    """
    Clear a flagged transaction back to pending so it can be processed.

    AUTHORIZATION: analyst or admin scope required.
    """
    ip = get_client_ip(request)
    user_agent = request.headers.get("User-Agent")

    try:
        return clear_flagged_transaction(
            db,
            transaction_id=transaction_id,
            cleared_by_user_id=current_user.id,
            reason=body.reason,
            ip_address=ip,
            user_agent=user_agent,
        )
    except TransactionNotFoundError:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Transaction not found")
    except TransactionStateError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc))


@router.post(
    "/review-item/{transaction_id}/process",
    response_model=TransactionResponse,
    summary="Process transaction as analyst/admin",
    dependencies=[Depends(require_analyst)],
)
def process_for_review(
    transaction_id: uuid.UUID,
    request: Request,
    db: Session = Depends(get_db),
) -> TransactionResponse:
    """
    Analyst/admin processing endpoint without ownership restriction.
    """
    from app.models.user import Transaction as TransactionModel

    txn = db.query(TransactionModel).filter(TransactionModel.id == transaction_id).first()
    if not txn:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Transaction not found")

    ip = get_client_ip(request)
    user_agent = request.headers.get("User-Agent")
    try:
        return process_transaction(
            db,
            transaction_id=transaction_id,
            user_id=txn.user_id,
            ip_address=ip,
            user_agent=user_agent,
        )
    except TransactionStateError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc))


@router.post(
    "/{transaction_id}/block",
    response_model=TransactionResponse,
    summary="Manually block a transaction (analyst/admin action)",
    dependencies=[Depends(require_analyst)],
    # require_analyst enforces scope rank >= 4 (analyst or admin).
    # Regular user tokens carry 'read_only' or 'transfer_authorized' (rank <= 2)
    # and receive HTTP 403 before any business logic executes.
    # An admin token (rank 5) satisfies this check automatically.
    # Two-layer protection:
    #   Layer 1 — require_analyst (dependencies=[...]): stateless scope check on JWT.
    #   Layer 2 — get_current_user (function param):    identity + session liveness check.
)
def block(
    transaction_id: uuid.UUID,
    request: Request,
    body: BlockReasonBody = BlockReasonBody(),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> TransactionResponse:
    """
    Manually block a pending or flagged transaction.

    AUTHORIZATION: analyst or admin scope required (HTTP 403 otherwise).

    This endpoint intentionally does NOT enforce ownership — a fraud analyst
    can block any user's transaction. That is the correct analyst workflow.
    Audit log records which analyst performed the action (blocked_by_user_id).

    Raises 401 — token missing or invalid.
    Raises 403 — authenticated but lacks analyst/admin scope.
    Raises 404 — transaction not found.
    Raises 409 — transaction is already in a terminal state (completed/failed/blocked).
    """
    ip = get_client_ip(request)
    user_agent = request.headers.get("User-Agent")

    try:
        return block_transaction(
            db,
            transaction_id=transaction_id,
            blocked_by_user_id=current_user.id,
            reason=body.reason,
            ip_address=ip,
            user_agent=user_agent,
        )
    except TransactionNotFoundError:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Transaction not found")
    except TransactionStateError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc))
        
