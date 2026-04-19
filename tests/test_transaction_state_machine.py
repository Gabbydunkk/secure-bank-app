import pytest

from app.services.transaction_service import TransactionStateError, _transition


class DummyTransaction:
    def __init__(self, status: str):
        self.status = status


def test_transition_pending_to_processing():
    txn = DummyTransaction("pending")
    _transition(txn, "processing")
    assert txn.status == "processing"


def test_transition_rejects_invalid_edge():
    txn = DummyTransaction("completed")
    with pytest.raises(TransactionStateError):
        _transition(txn, "processing")
