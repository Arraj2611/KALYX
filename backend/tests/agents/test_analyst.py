"""Tests for AnalystAgent — market signal emission via LLM."""

import json
import pytest
from pathlib import Path
from unittest.mock import AsyncMock

from app.brokers.base import MarginInfo
from app.agents.base import AgentContext, AgentOutput, BaseAgent
from app.agents.analyst import AnalystAgent


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

BUY_RESPONSE = json.dumps({
    "signal": "BUY",
    "confidence": 0.75,
    "reasoning": "RSI oversold at 28",
    "entry_price": 150.0,
    "stoploss": 140.0,
    "target": 170.0,
})

HOLD_RESPONSE = json.dumps({
    "signal": "HOLD",
    "confidence": 0.5,
    "reasoning": "No clear directional bias",
    "entry_price": None,
    "stoploss": None,
    "target": None,
})


def make_margin() -> MarginInfo:
    return MarginInfo(
        available_cash=50000.0,
        used_margin=10000.0,
        total_margin=60000.0,
        broker_name="zerodha",
        raw={},
    )


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def mock_llm_router():
    router = AsyncMock()
    router.generate = AsyncMock(return_value=BUY_RESPONSE)
    return router


@pytest.fixture
def analyst(mock_llm_router, tmp_path):
    defaults_dir = tmp_path / "defaults"
    defaults_dir.mkdir()
    (defaults_dir / "analyst.md").write_text("You are a market analyst.")
    return AnalystAgent(
        llm_router=mock_llm_router,
        prompts_dir=str(tmp_path),
        account_name="zerodha_main",
    )


@pytest.fixture
def context():
    return AgentContext(
        account_name="zerodha_main",
        symbol="NIFTY",
        market_state={"ltp": 22500, "rsi": 28},
        positions=[],
        margins=make_margin(),
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
async def test_analyst_emits_buy_signal(analyst, context):
    """run() returns AgentOutput with action=SIGNAL and signal=BUY."""
    output = await analyst.run(context)

    assert output.action == "SIGNAL"
    assert output.data["signal"] == "BUY"
    assert output.confidence == 0.75


@pytest.mark.asyncio
async def test_analyst_includes_reasoning(analyst, context):
    """AgentOutput.reasoning contains the LLM's reasoning text."""
    output = await analyst.run(context)

    assert "RSI" in output.reasoning


@pytest.mark.asyncio
async def test_analyst_uses_quick_tier(analyst):
    """AnalystAgent is initialised with llm_tier='quick'."""
    assert analyst.llm_tier == "quick"


@pytest.mark.asyncio
async def test_analyst_handles_hold_signal(analyst, context, mock_llm_router):
    """When LLM returns HOLD, output signal is HOLD."""
    mock_llm_router.generate.return_value = HOLD_RESPONSE

    output = await analyst.run(context)

    assert output.data["signal"] == "HOLD"


@pytest.mark.asyncio
async def test_analyst_handles_malformed_json(analyst, context, mock_llm_router):
    """Malformed LLM response produces safe default: signal=HOLD, confidence=0.0."""
    mock_llm_router.generate.return_value = "not json"

    output = await analyst.run(context)

    assert output.data["signal"] == "HOLD"
    assert output.confidence == 0.0


@pytest.mark.asyncio
async def test_analyst_includes_memory_in_prompt(analyst, context, mock_llm_router):
    """Memory recall items are included in the prompt sent to generate()."""
    context.memory_recall = [{"learning": "RSI works below 30"}]

    await analyst.run(context)

    mock_llm_router.generate.assert_called_once()
    call_kwargs = mock_llm_router.generate.call_args
    # grab the user_prompt kwarg that BaseAgent.think passes
    user_prompt = call_kwargs.kwargs.get("user_prompt") or call_kwargs.args[0]
    assert "RSI works below 30" in user_prompt


def test_analyst_is_base_agent(analyst):
    """AnalystAgent is a subclass of BaseAgent."""
    assert isinstance(analyst, BaseAgent)
