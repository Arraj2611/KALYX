"""Tests for StrategistAgent — overnight optimization loop."""

import json
import pytest
from pathlib import Path
from unittest.mock import AsyncMock

from app.agents.base import BaseAgent
from app.agents.strategist import StrategistAgent


# ---------------------------------------------------------------------------
# LLM response fixture value
# ---------------------------------------------------------------------------

IMPROVEMENT_RESPONSE = json.dumps({
    "parameter_name": "rsi_period",
    "current_value": 14,
    "suggested_value": 10,
    "reasoning": "Shorter RSI reacts faster to oversold conditions",
    "expected_improvement": "Win rate +5%",
})


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def mock_llm_router():
    router = AsyncMock()
    router.generate = AsyncMock(return_value=IMPROVEMENT_RESPONSE)
    return router


@pytest.fixture
def mock_memory():
    mem = AsyncMock()
    mem.recall = AsyncMock(return_value=[])
    return mem


@pytest.fixture
def mock_decision_logger():
    dl = AsyncMock()
    dl.log_decision = AsyncMock(return_value=1)
    return dl


@pytest.fixture
def strategist(mock_llm_router, mock_memory, mock_decision_logger, tmp_path):
    defaults_dir = tmp_path / "defaults"
    defaults_dir.mkdir()
    (defaults_dir / "strategist.md").write_text("Optimize strategies.")
    return StrategistAgent(
        llm_router=mock_llm_router,
        memory=mock_memory,
        decision_logger=mock_decision_logger,
        prompts_dir=str(tmp_path),
        account_name="paper_test",
        config={"experiment_duration_min": 1, "max_experiments_per_night": 3},
    )


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_strategist_suggests_change(strategist, mock_llm_router):
    """suggest_improvement returns the parsed LLM suggestion with correct fields."""
    result = await strategist.suggest_improvement(
        strategy_name="rsi_mean_reversion",
        strategy_config={"rsi_period": 14, "threshold": 30},
        performance={"win_rate": 0.45, "sharpe": 0.8},
    )

    assert result["parameter_name"] == "rsi_period"
    assert result["suggested_value"] == 10
    mock_llm_router.generate.assert_called_once()


def test_strategist_uses_deep_tier(strategist):
    """StrategistAgent is initialised with llm_tier='deep'."""
    assert strategist.llm_tier == "deep"


@pytest.mark.asyncio
async def test_strategist_keep_or_discard_logic(strategist):
    """_should_keep returns True when modified Sharpe > baseline, False otherwise."""
    assert strategist._should_keep(
        baseline={"sharpe": 0.8}, modified={"sharpe": 1.2}
    ) is True
    assert strategist._should_keep(
        baseline={"sharpe": 0.8}, modified={"sharpe": 0.5}
    ) is False


def test_strategist_is_base_agent(strategist):
    """StrategistAgent is a subclass of BaseAgent."""
    assert isinstance(strategist, BaseAgent)
