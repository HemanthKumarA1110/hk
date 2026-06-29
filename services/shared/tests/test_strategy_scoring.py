import pytest

from trading_shared.strategies.scoring import score_confirmations
from trading_shared.strategies.types import Confirmation


def test_score_confirmations_all_pass():
    confirmations = [
        Confirmation("a", True, 10),
        Confirmation("b", True, 10),
    ]
    assert score_confirmations(confirmations) == 100.0


def test_score_confirmations_partial():
    confirmations = [
        Confirmation("a", True, 10),
        Confirmation("b", False, 10),
    ]
    assert score_confirmations(confirmations) == 50.0
