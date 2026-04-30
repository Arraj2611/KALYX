"""Tests for MemoryAgent — recall, hindsight, reflection."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.agents.base import AgentContext, BaseAgent
from app.agents.memory import MemoryAgent
from app.brokers.base import MarginInfo


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def mock_llm_router():
    router = MagicMock()
    router.generate = AsyncMock(
        return_value=json.dumps(
            {
                "reflection": "RSI signal worked in low VIX environment",
                "learning": "When VIX < 15, RSI oversold is a strong buy signal",
                "tags": ["rsi", "nifty", "low_vix"],
                "pattern": "rsi_oversold_low_vix",
            }
        )
    )
    return router


@pytest.fixture
def mock_db():
    db = MagicMock()
    db.query = MagicMock()
    db.add = MagicMock()
    db.commit = MagicMock()
    return db


@pytest.fixture
def mock_decision_logger():
    dl = MagicMock()
    dl.fill_hindsight = AsyncMock()
    dl.log_decision = AsyncMock(return_value=1)
    return dl


@pytest.fixture
def memory_agent(tmp_path, mock_llm_router, mock_db, mock_decision_logger):
    defaults_dir = tmp_path / "defaults"
    defaults_dir.mkdir()
    (defaults_dir / "memory.md").write_text("Analyze trade outcomes.")
    return MemoryAgent(
        llm_router=mock_llm_router,
        db=mock_db,
        decision_logger=mock_decision_logger,
        prompts_dir=str(tmp_path),
        account_name="test_account",
    )


def _make_mock_entry():
    entry = MagicMock()
    entry.reasoning = "RSI oversold"
    entry.market_state = {"ltp": 150, "vix": 12}
    entry.action = "executed"
    entry.symbol = "NIFTY"
    return entry


def _make_agent_context():
    return AgentContext(
        account_name="test_account",
        symbol="NIFTY",
        market_state={"ltp": 150, "vix": 12},
        positions=[],
        margins=MarginInfo(
            available_cash=100000.0,
            used_margin=0.0,
            total_margin=100000.0,
            broker_name="test",
            raw={},
        ),
        recent_decisions=[],
        memory_recall=[],
        signals={},
        debate_result=None,
        guardian_verdict=None,
        config={},
    )


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_memory_recall_returns_list(memory_agent, mock_db):
    """recall() returns a list even when DB query returns empty."""
    # Set up query chain to return []
    mock_db.query.return_value.filter.return_value.order_by.return_value.limit.return_value.all.return_value = (
        []
    )

    result = await memory_agent.recall(
        symbol="NIFTY", strategy_id=None, market_state={}
    )

    assert isinstance(result, list)


@pytest.mark.asyncio
async def test_memory_store_outcome(memory_agent, mock_db, mock_decision_logger):
    """store_outcome() calls decision_logger.fill_hindsight exactly once."""
    mock_entry = _make_mock_entry()
    mock_db.query.return_value.filter.return_value.first.return_value = mock_entry

    await memory_agent.store_outcome(
        decision_id=1, entry_price=150, exit_price=160, pnl=5000
    )

    mock_decision_logger.fill_hindsight.assert_called_once()


@pytest.mark.asyncio
async def test_memory_generates_reflection(
    memory_agent, mock_db, mock_llm_router, mock_decision_logger
):
    """store_outcome() calls llm_router.generate exactly once to produce a reflection."""
    mock_entry = _make_mock_entry()
    mock_db.query.return_value.filter.return_value.first.return_value = mock_entry

    await memory_agent.store_outcome(
        decision_id=1, entry_price=150, exit_price=160, pnl=5000
    )

    mock_llm_router.generate.assert_called_once()


def test_memory_is_base_agent(memory_agent):
    """MemoryAgent must be a subclass of BaseAgent with llm_tier=='deep'."""
    assert isinstance(memory_agent, BaseAgent)
    assert memory_agent.llm_tier == "deep"
