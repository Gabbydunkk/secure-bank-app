"""
tests/test_behavior_service.py — Behaviour pattern baseline tests.

Covers:
  EMA average calculation
  Max with staleness reset
  Frequency increment
  Bounded location list (de-duplicated, capped, most-recent-first)
  Bounded device list
  First transaction creates row correctly
  commit=False / True
  PatternAnomalyRule integration
  transaction_service.process_transaction() hooks at completion only

Run: pytest tests/test_behavior_service.py -v
"""

import json
import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from unittest.mock import MagicMock, patch

import pytest

from app.services.behavior_service import (
    EMA_ALPHA,
    MAX_RECENT_ENTRIES,
    MAX_STALENESS_DAYS,
    _ema,
    _is_stale,
    _update_bounded_list,
    update_behavior_pattern,
)


# ============================================================================
# Helpers
# ============================================================================

def _mock_db(existing_pattern=None):
    db = MagicMock()
    db.query.return_value.filter.return_value.first.return_value = existing_pattern
    return db


def _pattern(
    avg="100.00",
    max_amt="200.00",
    freq=5,
    locations=None,
    devices=None,
    last_updated=None,
):
    p = MagicMock()
    p.average_transaction_amount = Decimal(avg)
    p.max_transaction_amount = Decimal(max_amt)
    p.typical_transaction_frequency = freq
    p.typical_locations = json.dumps(locations or [])
    p.typical_devices = json.dumps(devices or [])
    p.last_updated = last_updated or datetime.now(timezone.utc)
    return p


# ============================================================================
# Unit — pure helper functions
# ============================================================================

class TestEMA:

    def test_basic_ema(self):
        """EMA(100, 200, α=0.2) = 0.2*200 + 0.8*100 = 120.00"""
        result = _ema(Decimal("100"), Decimal("200"), alpha=0.2)
        assert result == Decimal("120.00")

    def test_ema_rounds_to_two_decimals(self):
        result = _ema(Decimal("99.99"), Decimal("100.01"), alpha=0.2)
        assert result == Decimal("99.99")

    def test_ema_weights_recent_more(self):
        """After a spike, EMA moves toward the spike but doesn't jump fully."""
        result = _ema(Decimal("100"), Decimal("1000"), alpha=0.2)
        assert Decimal("100") < result < Decimal("1000")

    def test_ema_default_alpha(self):
        """Default α is EMA_ALPHA (0.2)."""
        result = _ema(Decimal("100"), Decimal("200"))
        expected = Decimal(str(EMA_ALPHA)) * Decimal("200") + Decimal(str(1 - EMA_ALPHA)) * Decimal("100")
        assert result == expected.quantize(Decimal("0.01"))


class TestIsStale:

    def test_none_is_stale(self):
        assert _is_stale(None) is True

    def test_old_date_is_stale(self):
        old = datetime.now(timezone.utc) - timedelta(days=MAX_STALENESS_DAYS + 1)
        assert _is_stale(old) is True

    def test_recent_date_is_not_stale(self):
        recent = datetime.now(timezone.utc) - timedelta(days=1)
        assert _is_stale(recent) is False

    def test_exactly_at_boundary_is_not_stale(self):
        boundary = datetime.now(timezone.utc) - timedelta(days=MAX_STALENESS_DAYS - 1)
        assert _is_stale(boundary) is False

    def test_naive_datetime_treated_as_utc(self):
        """Naive datetimes (no tzinfo) should not raise — treated as UTC."""
        naive_old = datetime.utcnow() - timedelta(days=MAX_STALENESS_DAYS + 1)
        assert _is_stale(naive_old) is True


class TestUpdateBoundedList:

    def test_adds_new_entry(self):
        result = _update_bounded_list("[]", "GB:London")
        assert result == ["GB:London"]

    def test_deduplicates_existing_entry(self):
        existing = json.dumps(["GB:London", "US:NYC"])
        result = _update_bounded_list(existing, "US:NYC")
        items = result
        assert items.count("US:NYC") == 1

    def test_moves_existing_entry_to_front(self):
        """Most-recently-seen entry should be first."""
        existing = json.dumps(["GB:London", "US:NYC", "DE:Berlin"])
        result = _update_bounded_list(existing, "US:NYC")
        items = result
        assert items[0] == "US:NYC"

    def test_trims_to_max_entries(self):
        entries = [f"C{i}:City{i}" for i in range(MAX_RECENT_ENTRIES)]
        existing = json.dumps(entries)
        result = _update_bounded_list(existing, "NEW:Entry")
        items = result
        assert len(items) == MAX_RECENT_ENTRIES
        assert items[0] == "NEW:Entry"

    def test_none_entry_returns_unchanged(self):
        existing = json.dumps(["GB:London"])
        result = _update_bounded_list(existing, None)
        assert result == ["GB:London"]

    def test_empty_string_entry_returns_unchanged(self):
        existing = json.dumps(["GB:London"])
        result = _update_bounded_list(existing, "")
        assert result == ["GB:London"]

    def test_handles_none_existing(self):
        result = _update_bounded_list(None, "GB:London")
        assert result == ["GB:London"]


# ============================================================================
# update_behavior_pattern — integration
# ============================================================================

class TestUpdateBehaviorPattern:

    def test_first_transaction_creates_row(self):
        """No existing pattern → new UserBehaviorPattern row added."""
        db = _mock_db(None)
        uid = uuid.uuid4()

        update_behavior_pattern(db, uid, Decimal("250.00"),
                                location_country="GB", location_city="London",
                                device_fingerprint="fp-chrome")

        db.add.assert_called_once()
        added = db.add.call_args[0][0]
        assert added.user_id == uid
        assert added.average_transaction_amount == Decimal("250.00")
        assert added.max_transaction_amount == Decimal("250.00")
        assert added.typical_transaction_frequency == 1
        assert "GB:London" in added.typical_locations
        assert "fp-chrome" in added.typical_devices

    def test_ema_applied_on_second_transaction(self):
        """EMA(100, 300, α=0.2) = 140.00"""
        existing = _pattern(avg="100.00", max_amt="100.00", freq=1)
        db = _mock_db(existing)

        update_behavior_pattern(db, uuid.uuid4(), Decimal("300.00"))

        assert existing.average_transaction_amount == Decimal("140.00")

    def test_max_updated_when_exceeded(self):
        existing = _pattern(max_amt="200.00")
        db = _mock_db(existing)

        update_behavior_pattern(db, uuid.uuid4(), Decimal("500.00"))

        assert existing.max_transaction_amount == Decimal("500.00")

    def test_max_not_updated_when_not_exceeded(self):
        existing = _pattern(max_amt="500.00")
        db = _mock_db(existing)

        update_behavior_pattern(db, uuid.uuid4(), Decimal("50.00"))

        assert existing.max_transaction_amount == Decimal("500.00")

    def test_max_resets_on_stale_pattern(self):
        """
        CRITICAL: a stale pattern's max resets to the current amount.
        Without this, a single old large transaction permanently suppresses
        the fraud rule for all future transactions.
        """
        stale_time = datetime.now(timezone.utc) - timedelta(days=MAX_STALENESS_DAYS + 1)
        existing = _pattern(max_amt="10000.00", last_updated=stale_time)
        db = _mock_db(existing)

        update_behavior_pattern(db, uuid.uuid4(), Decimal("250.00"))

        # Max resets to the new amount, not the old £10,000 outlier
        assert existing.max_transaction_amount == Decimal("250.00")

    def test_frequency_increments(self):
        existing = _pattern(freq=7)
        db = _mock_db(existing)

        update_behavior_pattern(db, uuid.uuid4(), Decimal("100.00"))

        assert existing.typical_transaction_frequency == 8

    def test_location_added_to_list(self):
        existing = _pattern(locations=["US:NYC"])
        db = _mock_db(existing)

        update_behavior_pattern(db, uuid.uuid4(), Decimal("100.00"),
                                location_country="GB", location_city="London")

        locs = existing.typical_locations
        assert "GB:London" in locs
        assert "US:NYC" in locs

    def test_device_added_to_list(self):
        existing = _pattern(devices=["fp-old"])
        db = _mock_db(existing)

        update_behavior_pattern(db, uuid.uuid4(), Decimal("100.00"),
                                device_fingerprint="fp-new")

        devices = existing.typical_devices
        assert "fp-new" in devices
        assert "fp-old" in devices

    def test_location_deduplication(self):
        existing = _pattern(locations=["GB:London", "US:NYC"])
        db = _mock_db(existing)

        update_behavior_pattern(db, uuid.uuid4(), Decimal("100.00"),
                                location_country="GB", location_city="London")

        locs = existing.typical_locations
        assert locs.count("GB:London") == 1

    def test_most_recent_location_is_first(self):
        existing = _pattern(locations=["US:NYC", "DE:Berlin"])
        db = _mock_db(existing)

        update_behavior_pattern(db, uuid.uuid4(), Decimal("100.00"),
                                location_country="GB", location_city="London")

        locs = existing.typical_locations
        assert locs[0] == "GB:London"

    def test_location_without_city(self):
        """Country-only location stored as just the country code."""
        existing = _pattern()
        db = _mock_db(existing)

        update_behavior_pattern(db, uuid.uuid4(), Decimal("100.00"),
                                location_country="GB")

        locs = existing.typical_locations
        assert "GB" in locs

    def test_no_location_does_not_error(self):
        existing = _pattern()
        db = _mock_db(existing)

        # Should not raise
        update_behavior_pattern(db, uuid.uuid4(), Decimal("100.00"))

    def test_last_updated_refreshed(self):
        old_time = datetime(2020, 1, 1, tzinfo=timezone.utc)
        existing = _pattern(last_updated=old_time)
        db = _mock_db(existing)

        update_behavior_pattern(db, uuid.uuid4(), Decimal("100.00"))

        assert existing.last_updated > old_time

    def test_commit_false_does_not_commit(self):
        db = _mock_db()
        update_behavior_pattern(db, uuid.uuid4(), Decimal("100.00"), commit=False)
        db.commit.assert_not_called()

    def test_commit_true_commits(self):
        existing = _pattern()
        db = _mock_db(existing)
        update_behavior_pattern(db, uuid.uuid4(), Decimal("100.00"), commit=True)
        db.commit.assert_called_once()


# ============================================================================
# PatternAnomalyRule integration
# ============================================================================

class TestPatternAnomalyRuleIntegration:

    def test_amount_above_ema_max_scores_25(self):
        from app.services.fraud_service import PatternAnomalyRule
        from app.schemas.fraud import FraudRuleInput

        db = MagicMock()
        p = _pattern(avg="100.00", max_amt="500.00", freq=10)
        db.query.return_value.filter.return_value.first.return_value = p

        result = PatternAnomalyRule().evaluate(db, FraudRuleInput(
            user_id=uuid.uuid4(), transaction_amount=600.0
        ))
        assert result is not None
        assert result.score_delta == 25

    def test_amount_below_max_scores_zero(self):
        from app.services.fraud_service import PatternAnomalyRule
        from app.schemas.fraud import FraudRuleInput

        db = MagicMock()
        p = _pattern(max_amt="500.00")
        db.query.return_value.filter.return_value.first.return_value = p

        result = PatternAnomalyRule().evaluate(db, FraudRuleInput(
            user_id=uuid.uuid4(), transaction_amount=400.0
        ))
        assert result is None

    def test_no_baseline_returns_none(self):
        from app.services.fraud_service import PatternAnomalyRule
        from app.schemas.fraud import FraudRuleInput

        db = MagicMock()
        db.query.return_value.filter.return_value.first.return_value = None

        result = PatternAnomalyRule().evaluate(db, FraudRuleInput(
            user_id=uuid.uuid4(), transaction_amount=999.0
        ))
        assert result is None


# ============================================================================
# transaction_service hook placement
# ============================================================================

class TestTransactionServiceHook:
    """
    Verifies that update_behavior_pattern is called ONLY when a transaction
    reaches 'completed', and NOT during creation or on failure.
    """

    def _patched_process(self, makes_it_to_completed: bool):
        from app.services import transaction_service
        from decimal import Decimal

        user_id = uuid.uuid4()
        txn_id = uuid.uuid4()

        txn = MagicMock()
        txn.id = txn_id
        txn.user_id = user_id
        txn.status = "pending"
        txn.fraud_check_status = "approved"
        txn.transaction_type = "transfer"
        txn.recipient_account = "ACC123"
        txn.amount = Decimal("250.00")
        txn.location_country = "GB"
        txn.location_city = "London"
        txn.device_fingerprint = "fp-test"

        db = MagicMock()
        db.query.return_value.filter.return_value.first.return_value = txn

        with (
            patch.object(transaction_service, "update_behavior_pattern") as mock_ubp,
            patch.object(transaction_service, "_build_audit_log", return_value=MagicMock()),
            patch.object(transaction_service, "_transition") as mock_tr,
            patch.object(transaction_service.TransactionResponse, "model_validate",
                         return_value=MagicMock()),
        ):
            if not makes_it_to_completed:
                # Simulate processing failure
                def fail_transition(t, status):
                    if status == "completed":
                        raise ValueError("payment rail error")
                    t.status = status
                mock_tr.side_effect = fail_transition
            else:
                def succeed_transition(t, status):
                    t.status = status
                mock_tr.side_effect = succeed_transition

            try:
                transaction_service.process_transaction(
                    db, transaction_id=txn_id, user_id=user_id
                )
            except Exception:
                pass

        return mock_ubp

    def test_baseline_updated_on_completed(self):
        """process_transaction completing → update_behavior_pattern called."""
        mock_ubp = self._patched_process(makes_it_to_completed=True)
        mock_ubp.assert_called_once()
        kwargs = mock_ubp.call_args.kwargs
        assert kwargs.get("commit") is False

    def test_baseline_not_updated_on_failure(self):
        """process_transaction failing → update_behavior_pattern NOT called."""
        mock_ubp = self._patched_process(makes_it_to_completed=False)
        mock_ubp.assert_not_called()

    def test_baseline_not_updated_at_create_time(self):
        """
        create_transaction must NOT call update_behavior_pattern —
        pending transactions are not trusted signals.
        """
        from app.services import transaction_service
        from app.schemas.transaction import TransactionCreate

        user_id = uuid.uuid4()
        db = MagicMock()
        txn = MagicMock()
        txn.id = uuid.uuid4()
        txn.status = "pending"
        txn.fraud_check_status = "approved"
        txn.user_id = user_id
        txn.transaction_type = "transfer"
        txn.amount = Decimal("250.00")
        txn.currency = "USD"
        txn.recipient_account = "ACC123"
        txn.recipient_name = "Bob"
        txn.description = None
        txn.risk_score = 10
        txn.created_at = datetime.now(timezone.utc)
        txn.processed_at = None
        txn.completed_at = None

        data = TransactionCreate(
            transaction_type="transfer",
            amount=Decimal("250.00"),
            recipient_account="ACC123",
        )

        with (
            patch.object(transaction_service, "FraudService") as mock_fs,
            patch.object(transaction_service, "Transaction", return_value=txn),
            patch.object(transaction_service, "update_behavior_pattern") as mock_ubp,
            patch.object(transaction_service, "_build_audit_log", return_value=MagicMock()),
            patch.object(transaction_service.TransactionResponse, "model_validate",
                         return_value=MagicMock()),
        ):
            mock_result = MagicMock()
            mock_result.action = "allow"
            mock_result.score = 5
            mock_fs.return_value.evaluate.return_value = (mock_result, None)

            try:
                transaction_service.create_transaction(db, user_id=user_id, data=data)
            except Exception:
                pass

        mock_ubp.assert_not_called()
