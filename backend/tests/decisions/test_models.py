"""Tests for DecisionLog model and DecisionAction enum."""

import pytest
from sqlalchemy import inspect

from app.decisions.models import DecisionAction, DecisionLog


# ---------------------------------------------------------------------------
# DecisionAction enum tests
# ---------------------------------------------------------------------------


def test_decision_action_values():
    """DecisionAction enum members must map to expected string literals."""
    assert DecisionAction.EXECUTED == "executed"
    assert DecisionAction.SKIPPED == "skipped"
    assert DecisionAction.BLOCKED == "blocked"
    assert DecisionAction.REJECTED == "rejected"
    assert DecisionAction.FAILED == "failed"


def test_decision_action_is_string():
    """DecisionAction values must be instances of str (str-mixin enum)."""
    assert isinstance(DecisionAction.EXECUTED, str)
    assert isinstance(DecisionAction.SKIPPED, str)
    assert isinstance(DecisionAction.BLOCKED, str)
    assert isinstance(DecisionAction.REJECTED, str)
    assert isinstance(DecisionAction.FAILED, str)


# ---------------------------------------------------------------------------
# DecisionLog model column tests
# ---------------------------------------------------------------------------

REQUIRED_COLUMNS = [
    "id",
    "timestamp",
    "account_name",
    "symbol",
    "signal",
    "strategy_id",
    "confidence",
    "market_state",
    "action",
    "reasoning",
    "skip_reason",
    "trade_id",
    "outcome_if_taken",
    "outcome_actual",
    "was_correct",
    "trade_context",
]


def test_decision_log_model_columns():
    """DecisionLog must expose all required columns via SQLAlchemy mapper."""
    mapper = inspect(DecisionLog)
    column_names = {col.key for col in mapper.columns}
    for col in REQUIRED_COLUMNS:
        assert col in column_names, f"Missing column: {col}"
