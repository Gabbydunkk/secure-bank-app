"""
app/services/behavior_service.py — User behaviour pattern baseline updates.

Called by transaction_service.process_transaction() when a transaction reaches
status='completed'. Pending and flagged amounts are deliberately excluded:
  - Pending: not yet verified as legitimate
  - Flagged: fraud-suspected — must never raise the scoring ceiling
  - Blocked: never reaches this function

Statistics maintained (all in UserBehaviorPattern):
  average_transaction_amount   — Exponential Moving Average (EMA, α=0.2)
  max_transaction_amount       — high-watermark, reset to current if stale
  typical_transaction_frequency — simple count of completed transactions
  typical_locations            — de-duplicated list of recent (country, city) pairs
  typical_devices              — de-duplicated list of recent fingerprints
  last_updated                 — timestamp of the last update

Design decisions:

EMA instead of simple running mean:
  EMA weights recent transactions more than old ones. This means:
    - A user who normally sends £50 but starts sending £500 is flagged.
    - A user who legitimately upgrades to £500 monthly payments gradually
      trains the baseline upward without permanently triggering the rule.
  α=0.2 means the newest transaction contributes 20% of the new average,
  and the last ~5 transactions carry ~67% of the total weight.

Max with staleness reset:
  A pure running max only grows. If a user sent one large wire transfer
  two years ago, that amount becomes the permanent ceiling and the rule
  never fires again for anything smaller. Staleness reset: if the pattern
  has not been updated in MAX_STALENESS_DAYS, the max resets to the current
  amount. This keeps the rule useful for dormant-then-active accounts.

Bounded location and device lists:
  Keeps the last MAX_RECENT_ENTRIES unique values. These give PatternAnomalyRule
  explainable context ("user usually transacts from GB, now from RU") without
  requiring a separate analytics job or time-series table.

Commit=False (default):
  The caller (transaction_service) controls the transaction boundary so the
  baseline update is atomic with the audit log entry.
"""

import json
from datetime import datetime, timedelta, timezone
from decimal import Decimal, ROUND_HALF_UP
from typing import Any, Optional
import uuid

from sqlalchemy.orm import Session

from app.models.user import UserBehaviorPattern


# ─────────────────────────────────────────────────────────────────────────────
# Constants
# ─────────────────────────────────────────────────────────────────────────────

# EMA smoothing factor: 0.2 means newest transaction = 20% of new average.
# Higher α = faster adaptation (more reactive, less stable).
# Lower α = slower adaptation (more stable, slower to adjust to new normal).
EMA_ALPHA: float = 0.2

# If pattern.last_updated is older than this, reset max_transaction_amount
# to the current transaction amount. Prevents a single historical outlier
# from permanently suppressing the fraud rule.
MAX_STALENESS_DAYS: int = 90

# Maximum number of unique locations / devices stored in the JSONB arrays.
# Older entries drop off the end when the list exceeds this size.
MAX_RECENT_ENTRIES: int = 10


# ─────────────────────────────────────────────────────────────────────────────
# Internal helpers
# ─────────────────────────────────────────────────────────────────────────────

def _ema(current: Decimal, new_value: Decimal, alpha: float = EMA_ALPHA) -> Decimal:
    """
    Exponential moving average:
      new_ema = alpha * new_value + (1 - alpha) * current_ema

    Returns a Decimal rounded to 2 decimal places.
    """
    result = Decimal(str(alpha)) * new_value + Decimal(str(1 - alpha)) * current
    return result.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def _is_stale(last_updated: Optional[datetime]) -> bool:
    """Return True if last_updated is older than MAX_STALENESS_DAYS."""
    if last_updated is None:
        return True
    now = datetime.now(timezone.utc)
    # Ensure last_updated is tz-aware for comparison
    if last_updated.tzinfo is None:
        last_updated = last_updated.replace(tzinfo=timezone.utc)
    return (now - last_updated) > timedelta(days=MAX_STALENESS_DAYS)


def _update_bounded_list(existing_value: Optional[Any], new_entry: Optional[str]) -> list[str]:
    """
    Add new_entry to a bounded, de-duplicated list stored as a Python list.

    - Skips None or empty entries.
    - Moves existing entry to the front (most-recent-first order).
    - Trims to MAX_RECENT_ENTRIES, dropping the oldest.

    Returns the updated Python list for storage in the JSONB column.
    """
    if not new_entry:
        if isinstance(existing_value, list):
            return list(existing_value)
        if isinstance(existing_value, str):
            try:
                parsed = json.loads(existing_value)
                return parsed if isinstance(parsed, list) else []
            except (json.JSONDecodeError, TypeError):
                return []
        return []

    if isinstance(existing_value, list):
        items = list(existing_value)
    elif isinstance(existing_value, str):
        try:
            parsed = json.loads(existing_value)
            items = parsed if isinstance(parsed, list) else []
        except (json.JSONDecodeError, TypeError):
            items = []
    else:
        items = []

    # De-duplicate: move to front if already present
    if new_entry in items:
        items.remove(new_entry)
    items.insert(0, new_entry)

    # Trim to bounded size
    items = items[:MAX_RECENT_ENTRIES]
    return items


# ─────────────────────────────────────────────────────────────────────────────
# Public API
# ─────────────────────────────────────────────────────────────────────────────

def update_behavior_pattern(
    db: Session,
    user_id: uuid.UUID,
    amount: Decimal,
    *,
    location_country: Optional[str] = None,
    location_city: Optional[str] = None,
    device_fingerprint: Optional[str] = None,
    commit: bool = False,
) -> UserBehaviorPattern:
    """
    Update or create a UserBehaviorPattern after a COMPLETED transaction.

    Must only be called when txn.status == 'completed'. Pending or flagged
    amounts must not be learned from — they could be fraud probing attempts.

    Args:
        db:                 SQLAlchemy session
        user_id:            the transacting user
        amount:             the completed transaction amount (Decimal)
        location_country:   2-letter ISO country code from the transaction
        location_city:      city name from the transaction (may be None)
        device_fingerprint: hashed device identifier from the transaction
        commit:             if True, commit after update (default False)

    Returns the updated or newly created UserBehaviorPattern row.
    """
    now = datetime.now(timezone.utc)
    amount_decimal = Decimal(str(amount))

    # Build location label (e.g. "GB:London") for the bounded list
    location_label: Optional[str] = None
    if location_country:
        location_label = (
            f"{location_country.upper()}:{location_city}"
            if location_city
            else location_country.upper()
        )

    pattern = (
        db.query(UserBehaviorPattern)
        .filter(UserBehaviorPattern.user_id == user_id)
        .first()
    )

    if pattern is None:
        # ── First completed transaction — create baseline ─────────────────
        pattern = UserBehaviorPattern(
            user_id=user_id,
            average_transaction_amount=amount_decimal,
            max_transaction_amount=amount_decimal,
            typical_transaction_frequency=1,
            typical_locations=[location_label] if location_label else [],
            typical_devices=[device_fingerprint] if device_fingerprint else [],
            last_updated=now,
        )
        db.add(pattern)

    else:
        # ── Update existing baseline ──────────────────────────────────────

        # 1. EMA for average
        current_avg = Decimal(str(pattern.average_transaction_amount or amount_decimal))
        pattern.average_transaction_amount = _ema(current_avg, amount_decimal)

        # 2. Max with staleness reset
        #    If stale, treat this transaction as the new baseline max.
        #    Otherwise take the higher of current max and new amount.
        if _is_stale(pattern.last_updated):
            pattern.max_transaction_amount = amount_decimal
        else:
            current_max = Decimal(str(pattern.max_transaction_amount or 0))
            pattern.max_transaction_amount = max(current_max, amount_decimal)

        # 3. Frequency counter
        pattern.typical_transaction_frequency = (
            (pattern.typical_transaction_frequency or 0) + 1
        )

        # 4. Bounded location list (most-recent-first, de-duplicated)
        pattern.typical_locations = _update_bounded_list(
            pattern.typical_locations, location_label
        )

        # 5. Bounded device list
        pattern.typical_devices = _update_bounded_list(
            pattern.typical_devices, device_fingerprint
        )

        pattern.last_updated = now

    if commit:
        db.commit()
        db.refresh(pattern)

    return pattern
