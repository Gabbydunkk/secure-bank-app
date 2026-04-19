"""
Transaction service: create, fetch, list, and process transactions.
Follows the same patterns as auth_service.py:
  - Single-responsibility functions
  - Fraud check BEFORE any DB write
  - Atomic commits (transaction + fraud alert + audit log in one db.commit())
  - Custom exceptions so the API layer can map to HTTP status codes cleanly
"""
from datetime import datetime, timezone
from typing import Optional
import uuid

from sqlalchemy.orm import Session

from app.models.user import AuditLog, Transaction
from app.schemas.transaction import (
    TransactionCreate,
    TransactionListResponse,
    TransactionResponse,
)
from app.schemas.fraud import FraudRuleInput
from app.services.behavior_service import update_behavior_pattern
from app.services.fraud_service import FraudService


# =============================================================================
# Custom exceptions — map directly to HTTP status codes in the router
# =============================================================================

class TransactionBlockedError(ValueError):
    """Raised when the fraud engine blocks a transaction outright (score ≥ BLOCK)."""
    pass


class TransactionNotFoundError(ValueError):
    """Raised when the requested transaction does not exist for this user."""
    pass


class TransactionStateError(ValueError):
    """Raised when a state transition is invalid (e.g. completing an already-failed txn)."""
    pass


# =============================================================================
# Internal helpers
# =============================================================================

def _build_audit_log(
    user_id: uuid.UUID,
    action: str,
    entity_id: uuid.UUID,
    old_values: Optional[dict] = None,
    new_values: Optional[dict] = None,
    ip_address: Optional[str] = None,
    user_agent: Optional[str] = None,
    success: bool = True,
    error_message: Optional[str] = None,
    entity_type: str = "transaction",
) -> AuditLog:
    """Build an AuditLog ORM object without adding it to the session."""
    return AuditLog(
        user_id=user_id,
        action=action,
        entity_type=entity_type,
        entity_id=entity_id,
        old_values=old_values,
        new_values=new_values,
        ip_address=ip_address,
        user_agent=user_agent,
        success=success,
        error_message=error_message,
    )


def _transaction_snapshot(txn: Transaction) -> dict:
    """Return a JSON-serialisable snapshot of the key transaction fields for audit logs."""
    return {
        "status": txn.status,
        "fraud_check_status": txn.fraud_check_status,
        "risk_score": txn.risk_score,
        "amount": str(txn.amount),
        "currency": txn.currency,
    }


# =============================================================================
# Create transaction
# =============================================================================

def create_transaction(
    db: Session,
    user_id: uuid.UUID,
    data: TransactionCreate,
    *,
    ip_address: Optional[str] = None,
    user_agent: Optional[str] = None,
    device_fingerprint: Optional[str] = None,
    location_country: Optional[str] = None,
    location_city: Optional[str] = None,
    fraud_service: Optional[FraudService] = None,
) -> TransactionResponse:
    """
    Create a new transaction after running the fraud engine.

    Flow:
      1. Run fraud rules (with transaction context).
      2. If blocked → log audit failure + commit alert → raise TransactionBlockedError.
      3. If flagged/challenge → insert with status='flagged', fraud_check_status='flagged'.
         (challenge for transactions is treated as a flagged transaction that must be reviewed)
      4. If allowed → insert with status='pending', fraud_check_status='approved'.
      5. Commit transaction + fraud alert + audit log atomically.

    Caller must ensure the user is authorized to create transactions (e.g. via JWT scopes).
    """
    _fraud_service = fraud_service or FraudService()

    fraud_input = FraudRuleInput(
        user_id=user_id,
        transaction_amount=float(data.amount),
        transaction_type=data.transaction_type,
        ip_address=ip_address,
        device_fingerprint=device_fingerprint,
        location_country=location_country,
        location_city=location_city,
    )

    fraud_result, fraud_alert = _fraud_service.evaluate(
        db,
        fraud_input,
        create_alert_if_required=True,
        commit_alert=False,   # we commit atomically below
    )

    if fraud_result.action == "block":
        # Persist blocked transactions for visibility in history and analyst workflows.
        txn = Transaction(
            user_id=user_id,
            transaction_type=data.transaction_type,
            amount=data.amount,
            currency=data.currency,
            recipient_account=data.recipient_account,
            recipient_name=data.recipient_name,
            description=data.description,
            status="blocked",
            risk_score=fraud_result.score,
            fraud_check_status="blocked",
            device_fingerprint=device_fingerprint,
            ip_address=ip_address,
            location_country=location_country,
            location_city=location_city,
        )
        db.add(txn)
        db.flush()

        if fraud_alert is not None:
            fraud_alert.transaction_id = txn.id

        audit = _build_audit_log(
            user_id=user_id,
            action="transaction_blocked",
            entity_id=txn.id,
            new_values=_transaction_snapshot(txn),
            ip_address=ip_address,
            user_agent=user_agent,
            success=False,
            error_message="Transaction blocked by fraud policy",
        )
        db.add(audit)
        db.commit()
        raise TransactionBlockedError("Transaction blocked by security policy")

    # Determine transaction and fraud_check status
    # For now, "challenge" is treated like "flag": create a flagged transaction
    # that requires review or step-up before completion.
    if fraud_result.action in ("flag", "challenge"):
        txn_status = "flagged"
        fraud_check_status = "flagged"
    else:
        txn_status = "pending"
        fraud_check_status = "approved"

    txn = Transaction(
        user_id=user_id,
        transaction_type=data.transaction_type,
        amount=data.amount,
        currency=data.currency,
        recipient_account=data.recipient_account,
        recipient_name=data.recipient_name,
        description=data.description,
        status=txn_status,
        risk_score=fraud_result.score,
        fraud_check_status=fraud_check_status,
        device_fingerprint=device_fingerprint,
        ip_address=ip_address,
        location_country=location_country,
        location_city=location_city,
    )
    db.add(txn)
    db.flush()   # get txn.id before audit log

    # Wire fraud alert to the transaction now that we have an id
    if fraud_alert is not None:
        fraud_alert.transaction_id = txn.id

    audit = _build_audit_log(
        user_id=user_id,
        action="transaction_create",
        entity_id=txn.id,
        new_values=_transaction_snapshot(txn),
        ip_address=ip_address,
        user_agent=user_agent,
        success=True,
    )
    db.add(audit)
    db.commit()
    db.refresh(txn)
    return TransactionResponse.model_validate(txn)


# =============================================================================
# Read transaction(s)
# =============================================================================

def get_transaction(
    db: Session,
    transaction_id: uuid.UUID,
    user_id: uuid.UUID,
) -> TransactionResponse:
    """
    Fetch a single transaction by id.
    Enforces ownership: user_id must match so users can only see their own transactions.
    Raises TransactionNotFoundError if not found or not owned by this user.
    """
    txn = (
        db.query(Transaction)
        .filter(
            Transaction.id == transaction_id,
            Transaction.user_id == user_id,
        )
        .first()
    )
    if not txn:
        raise TransactionNotFoundError("Transaction not found")
    return TransactionResponse.model_validate(txn)


def list_transactions(
    db: Session,
    user_id: uuid.UUID,
    page: int = 1,
    page_size: int = 20,
) -> TransactionListResponse:
    """
    Paginated list of transactions for a user, newest first.
    page is 1-indexed.
    """
    page = max(1, page)
    page_size = max(1, min(page_size, 100))   # guard against absurd page sizes
    offset = (page - 1) * page_size

    base_query = (
        db.query(Transaction)
        .filter(Transaction.user_id == user_id)
        .order_by(Transaction.created_at.desc())
    )
    total = base_query.count()
    transactions = base_query.offset(offset).limit(page_size).all()

    rows = [TransactionResponse.model_validate(t) for t in transactions]
    return TransactionListResponse(items=rows, transactions=rows, total=total)


def list_transactions_for_review(
    db: Session,
    *,
    page: int = 1,
    page_size: int = 20,
    status_filter: Optional[str] = None,
    min_risk_score: Optional[int] = None,
) -> TransactionListResponse:
    """
    Analyst/admin global review list (no ownership restriction).
    Supports optional status + minimum risk filters for triage workflows.
    """
    page = max(1, page)
    page_size = max(1, min(page_size, 100))
    offset = (page - 1) * page_size

    query = db.query(Transaction)
    if status_filter:
        query = query.filter(Transaction.status == status_filter)
    if min_risk_score is not None:
        query = query.filter(Transaction.risk_score >= min_risk_score)

    query = query.order_by(Transaction.created_at.desc())
    total = query.count()
    transactions = query.offset(offset).limit(page_size).all()
    rows = [TransactionResponse.model_validate(t) for t in transactions]
    return TransactionListResponse(items=rows, transactions=rows, total=total)


def get_transaction_for_review(
    db: Session,
    transaction_id: uuid.UUID,
) -> TransactionResponse:
    """
    Analyst/admin transaction fetch without ownership restriction.
    """
    txn = db.query(Transaction).filter(Transaction.id == transaction_id).first()
    if not txn:
        raise TransactionNotFoundError("Transaction not found")
    return TransactionResponse.model_validate(txn)


# =============================================================================
# State transitions
# =============================================================================

# Valid state machine edges: current_status → allowed next statuses
_VALID_TRANSITIONS: dict[str, set[str]] = {
    "pending":    {"processing", "failed", "blocked"},
    "processing": {"completed", "failed"},
    "flagged":    {"blocked", "pending"},   # analyst can clear flag or escalate to blocked
    "completed":  set(),                    # terminal
    "failed":     set(),                    # terminal
    "blocked":    set(),                    # terminal
}


def _transition(txn: Transaction, new_status: str) -> None:
    """
    Apply a status transition, raising TransactionStateError if invalid.

    Note: design choice – once a transaction enters 'processing', it cannot be
    manually blocked via state machine (only completed or failed). If business
    rules change, update _VALID_TRANSITIONS accordingly.
    """
    allowed = _VALID_TRANSITIONS.get(txn.status, set())
    if new_status not in allowed:
        raise TransactionStateError(
            f"Cannot transition transaction from '{txn.status}' to '{new_status}'"
        )
    txn.status = new_status


def process_transaction(
    db: Session,
    transaction_id: uuid.UUID,
    user_id: uuid.UUID,
    *,
    ip_address: Optional[str] = None,
    user_agent: Optional[str] = None,
) -> TransactionResponse:
    """
    Advance a pending transaction through the processing state machine.
    pending → processing → completed  (happy path)
    pending → failed                  (on any processing error)

    This function performs the processing step synchronously.
    For production, replace the body with an async task dispatch
    (e.g. push to Celery / ARQ queue) and set status='processing' immediately.
    """
    txn = (
        db.query(Transaction)
        .filter(Transaction.id == transaction_id, Transaction.user_id == user_id)
        .first()
    )
    if not txn:
        raise TransactionNotFoundError("Transaction not found")

    # Idempotency / terminal states: if already completed/failed/blocked, return as-is.
    if txn.status in {"completed", "failed", "blocked"}:
        return TransactionResponse.model_validate(txn)
    if txn.status == "flagged":
        raise TransactionStateError(
            "Flagged transactions require manual review before processing"
        )

    old_snapshot = _transaction_snapshot(txn)

    # pending → processing
    _transition(txn, "processing")
    txn.processed_at = datetime.now(timezone.utc)

    try:
        # ── Placeholder for real processing logic ──────────────────────────
        # e.g.: call payment rail, update ledger, send confirmation email.
        # Intentionally broad try/except so any processing/integration error
        # marks the transaction as failed and is recorded in the audit log.
        # In a production system, prefer catching specific exception types
        # for external dependencies and re-raising unexpected bugs.
        # ──────────────────────────────────────────────────────────────────
        if txn.transaction_type in {"transfer", "payment"} and not txn.recipient_account:
            raise ValueError("recipient_account is required for transfer/payment")
        if txn.amount <= 0:
            raise ValueError("transaction amount must be positive")
        if txn.fraud_check_status == "flagged":
            raise ValueError("transaction is flagged and cannot be auto-processed")

        # processing → completed
        _transition(txn, "completed")
        txn.completed_at = datetime.now(timezone.utc)


        # Update behaviour baseline now that the transaction is confirmed.
        # Only completed transactions are trusted signals — pending and
        # flagged amounts must never train the pattern (fraud probing risk).
        # commit=False: atomic with the audit log commit below.

        update_behavior_pattern(
            db,
            user_id=user_id,
            amount=txn.amount,
            location_country=txn.location_country,
            location_city=txn.location_city,
            device_fingerprint=txn.device_fingerprint,
            commit=False,
        )
        

        audit = _build_audit_log(
            user_id=user_id,
            action="transaction_completed",
            entity_id=txn.id,
            old_values=old_snapshot,
            new_values=_transaction_snapshot(txn),
            ip_address=ip_address,
            user_agent=user_agent,
            success=True,
        )

    except Exception as exc:  # noqa: BLE001
        txn.status = "failed"
        audit = _build_audit_log(
            user_id=user_id,
            action="transaction_failed",
            entity_id=txn.id,
            old_values=old_snapshot,
            new_values=_transaction_snapshot(txn),
            ip_address=ip_address,
            user_agent=user_agent,
            success=False,
            error_message=str(exc),
        )

    db.add(audit)
    db.commit()
    db.refresh(txn)
    return TransactionResponse.model_validate(txn)


def block_transaction(
    db: Session,
    transaction_id: uuid.UUID,
    blocked_by_user_id: uuid.UUID,
    *,
    reason: Optional[str] = None,
    ip_address: Optional[str] = None,
    user_agent: Optional[str] = None,
) -> TransactionResponse:
    """
    Manually block a flagged or pending transaction (used by fraud analysts / admins).
    Does NOT enforce ownership — caller must ensure the user has admin/analyst permissions.
    """
    txn = db.query(Transaction).filter(Transaction.id == transaction_id).first()
    if not txn:
        raise TransactionNotFoundError("Transaction not found")

    old_snapshot = _transaction_snapshot(txn)
    _transition(txn, "blocked")
    txn.fraud_check_status = "blocked"

    audit = _build_audit_log(
        user_id=blocked_by_user_id,
        action="transaction_blocked_manual",
        entity_id=txn.id,
        old_values=old_snapshot,
        new_values={**_transaction_snapshot(txn), "reason": reason},
        ip_address=ip_address,
        user_agent=user_agent,
        success=True,
    )
    db.add(audit)
    db.commit()
    db.refresh(txn)
    return TransactionResponse.model_validate(txn)


def clear_flagged_transaction(
    db: Session,
    transaction_id: uuid.UUID,
    cleared_by_user_id: uuid.UUID,
    *,
    reason: Optional[str] = None,
    ip_address: Optional[str] = None,
    user_agent: Optional[str] = None,
) -> TransactionResponse:
    """
    Manually clear a flagged transaction back to pending for processing.

    This is an analyst/admin review action:
      flagged -> pending and fraud_check_status -> approved

    It intentionally does not enforce ownership. Caller must enforce
    analyst/admin authorization at the router layer.
    """
    txn = db.query(Transaction).filter(Transaction.id == transaction_id).first()
    if not txn:
        raise TransactionNotFoundError("Transaction not found")

    if txn.status not in {"flagged", "blocked"}:
        raise TransactionStateError(
            f"Only flagged/blocked transactions can be cleared (current status: '{txn.status}')"
        )

    old_snapshot = _transaction_snapshot(txn)
    if txn.status == "flagged":
        _transition(txn, "pending")
    else:
        txn.status = "pending"
    txn.fraud_check_status = "approved"

    audit = _build_audit_log(
        user_id=cleared_by_user_id,
        action="transaction_cleared_manual",
        entity_id=txn.id,
        old_values=old_snapshot,
        new_values={**_transaction_snapshot(txn), "reason": reason},
        ip_address=ip_address,
        user_agent=user_agent,
        success=True,
    )
    db.add(audit)
    db.commit()
    db.refresh(txn)
    return TransactionResponse.model_validate(txn)
