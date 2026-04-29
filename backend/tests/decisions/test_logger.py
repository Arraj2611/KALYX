"""Tests for DecisionLogger service.

All DB interactions are mocked; file I/O uses a temp directory.
"""

import json
import os
import tempfile
from datetime import date
from unittest.mock import MagicMock, AsyncMock, patch

import pytest

from app.decisions.logger import DecisionLogger
from app.decisions.models import DecisionAction, DecisionLog


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def tmp_log_dir():
    """Temporary directory for per-account log files."""
    with tempfile.TemporaryDirectory() as d:
        yield d


@pytest.fixture
def mock_db():
    """Minimal mock of a SQLAlchemy Session."""
    db = MagicMock()
    db.add = MagicMock()
    db.commit = MagicMock()
    db.refresh = MagicMock()
    # query(...).filter(...).first() chain
    query_result = MagicMock()
    db.query.return_value.filter.return_value.first.return_value = query_result
    return db


# ---------------------------------------------------------------------------
# Helper: build a DecisionLogger with a fresh mock DB
# ---------------------------------------------------------------------------


def make_logger(mock_db, tmp_log_dir):
    return DecisionLogger(db=mock_db, log_base_dir=tmp_log_dir)


# ---------------------------------------------------------------------------
# Test: log_decision — EXECUTED path
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_log_executed_decision(mock_db, tmp_log_dir):
    """log_decision(action=EXECUTED) must call db.add and db.commit."""
    logger = make_logger(mock_db, tmp_log_dir)

    # db.refresh populates the id after commit
    def _set_id(entry):
        entry.id = 42

    mock_db.refresh.side_effect = _set_id

    decision_id = await logger.log_decision(
        account_name="paper_test",
        symbol="NIFTY25JANFUT",
        signal="LONG",
        action=DecisionAction.EXECUTED,
        confidence=0.85,
        reasoning="RSI oversold + volume spike",
        market_state={"rsi": 28, "vwap_delta": 0.3},
        strategy_id=1,
    )

    mock_db.add.assert_called_once()
    mock_db.commit.assert_called_once()
    assert decision_id == 42


# ---------------------------------------------------------------------------
# Test: log_decision — SKIPPED path
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_log_skipped_decision(mock_db, tmp_log_dir):
    """log_decision(action=SKIPPED) must call db.add and db.commit."""
    logger = make_logger(mock_db, tmp_log_dir)

    def _set_id(entry):
        entry.id = 7

    mock_db.refresh.side_effect = _set_id

    decision_id = await logger.log_decision(
        account_name="paper_test",
        symbol="NIFTY25JANFUT",
        signal="SHORT",
        action=DecisionAction.SKIPPED,
        confidence=0.45,
        reasoning="Confidence below threshold",
        market_state={"rsi": 55},
        skip_reason="confidence_too_low",
    )

    mock_db.add.assert_called_once()
    mock_db.commit.assert_called_once()
    assert decision_id == 7


# ---------------------------------------------------------------------------
# Test: log_decision — BLOCKED path (guardian)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_log_blocked_decision(mock_db, tmp_log_dir):
    """log_decision(action=BLOCKED) must persist the guardian skip_reason."""
    logger = make_logger(mock_db, tmp_log_dir)

    def _set_id(entry):
        entry.id = 99

    mock_db.refresh.side_effect = _set_id

    decision_id = await logger.log_decision(
        account_name="paper_test",
        symbol="BANKNIFTY25JANFUT",
        signal="LONG",
        action=DecisionAction.BLOCKED,
        confidence=0.9,
        reasoning="Guardian blocked: daily loss limit hit",
        market_state={"daily_loss_pct": 0.82},
        skip_reason="guardian:daily_loss_80pct",
    )

    mock_db.add.assert_called_once()
    mock_db.commit.assert_called_once()
    assert decision_id == 99

    # Verify the entry passed to db.add carries the skip_reason
    entry_arg: DecisionLog = mock_db.add.call_args[0][0]
    assert entry_arg.skip_reason == "guardian:daily_loss_80pct"
    assert entry_arg.action == DecisionAction.BLOCKED


# ---------------------------------------------------------------------------
# Test: log_decision writes JSON line to per-account log file
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_log_writes_to_file(mock_db, tmp_log_dir):
    """log_decision must create .../accounts/<account>/decisions-YYYY-MM-DD.log."""
    logger = make_logger(mock_db, tmp_log_dir)

    def _set_id(entry):
        entry.id = 5

    mock_db.refresh.side_effect = _set_id

    await logger.log_decision(
        account_name="paper_test",
        symbol="NIFTY25JANFUT",
        signal="LONG",
        action=DecisionAction.EXECUTED,
        confidence=0.75,
        reasoning="Breakout confirmed",
        market_state={"breakout": True},
    )

    today = date.today().strftime("%Y-%m-%d")
    log_path = os.path.join(
        tmp_log_dir, "accounts", "paper_test", f"decisions-{today}.log"
    )
    assert os.path.exists(log_path), f"Log file not found: {log_path}"

    with open(log_path) as f:
        line = f.readline().strip()
    data = json.loads(line)
    assert data["symbol"] == "NIFTY25JANFUT"
    assert data["action"] == "executed"
    assert data["account_name"] == "paper_test"


# ---------------------------------------------------------------------------
# Test: fill_hindsight updates outcome fields and computes was_correct
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_fill_hindsight(mock_db, tmp_log_dir):
    """fill_hindsight must set outcome fields and compute was_correct."""
    logger = make_logger(mock_db, tmp_log_dir)

    # Simulate an EXECUTED decision that was profitable
    fake_entry = DecisionLog()
    fake_entry.id = 10
    fake_entry.action = DecisionAction.EXECUTED
    fake_entry.outcome_if_taken = None
    fake_entry.outcome_actual = None
    fake_entry.was_correct = None

    mock_db.query.return_value.filter.return_value.first.return_value = fake_entry

    await logger.fill_hindsight(
        decision_id=10,
        outcome_if_taken=250.0,
        outcome_actual=230.0,
    )

    assert fake_entry.outcome_if_taken == 250.0
    assert fake_entry.outcome_actual == 230.0
    # EXECUTED + positive actual => was_correct = True
    assert fake_entry.was_correct is True
    mock_db.commit.assert_called_once()
