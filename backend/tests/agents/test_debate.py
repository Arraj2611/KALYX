"""Tests for DebateAgent (bull/bear) and JudgeAgent."""

import json
import pytest
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

from app.brokers.base import MarginInfo
from app.agents.base import AgentContext
from app.agents.debate import DebateAgent, JudgeAgent


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def make_margin() -> MarginInfo:
    return MarginInfo(
        available_cash=50000.0,
        used_margin=10000.0,
        total_margin=60000.0,
        broker_name="zerodha",
        raw={},
    )


ARGUE_RESPONSE = json.dumps({
    "argument": "Strong bullish case based on RSI",
    "conviction": 0.8,
    "key_factors": ["RSI oversold", "volume spike"],
})

JUDGE_RESPONSE = json.dumps({
    "proceed": True,
    "adjusted_confidence": 0.7,
    "reasoning": "Bullish case stronger but risks noted",
    "stronger_argument": "A",
})

JUDGE_REJECT_RESPONSE = json.dumps({
    "proceed": False,
    "adjusted_confidence": 0.2,
    "reasoning": "Both arguments weak, high-risk setup",
    "stronger_argument": "B",
})


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def mock_llm_router():
    router = MagicMock()
    router.generate_with_model = AsyncMock(return_value=ARGUE_RESPONSE)
    router.generate = AsyncMock(return_value=JUDGE_RESPONSE)
    return router


@pytest.fixture
def prompts_dir(tmp_path):
    defaults_dir = tmp_path / "defaults"
    defaults_dir.mkdir()
    (defaults_dir / "bullish.md").write_text("You are a bullish advocate.")
    (defaults_dir / "bearish.md").write_text("You are a bearish advocate.")
    (defaults_dir / "judge.md").write_text("You are an impartial judge.")
    return str(tmp_path)


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
        signals={"signal": "BUY", "confidence": 0.75, "reasoning": "RSI oversold"},
        debate_result=None,
        guardian_verdict=None,
        config={"debate": {"anonymize": True, "max_rounds": 1}},
    )


@pytest.fixture
def bullish(mock_llm_router, prompts_dir):
    return DebateAgent(
        side="bullish",
        llm_router=mock_llm_router,
        prompts_dir=prompts_dir,
        account_name="zerodha_main",
    )


@pytest.fixture
def bearish(mock_llm_router, prompts_dir):
    return DebateAgent(
        side="bearish",
        llm_router=mock_llm_router,
        prompts_dir=prompts_dir,
        account_name="zerodha_main",
    )


@pytest.fixture
def judge(mock_llm_router, prompts_dir):
    return JudgeAgent(
        llm_router=mock_llm_router,
        prompts_dir=prompts_dir,
        account_name="zerodha_main",
    )


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_bullish_argues_for(bullish, context):
    """DebateAgent(side='bullish') returns action=ARGUE with argument key."""
    output = await bullish.run(context)

    assert output.action == "ARGUE"
    assert "argument" in output.data


@pytest.mark.asyncio
async def test_bearish_argues_against(bearish, context):
    """DebateAgent(side='bearish') returns action=ARGUE with argument key."""
    output = await bearish.run(context)

    assert output.action == "ARGUE"
    assert "argument" in output.data


@pytest.mark.asyncio
async def test_debate_uses_named_model(bullish, context, mock_llm_router):
    """DebateAgent calls generate_with_model with model_name matching its side."""
    await bullish.run(context)

    mock_llm_router.generate_with_model.assert_called_once()
    call_kwargs = mock_llm_router.generate_with_model.call_args
    # model_name should be "bullish"
    model_name = call_kwargs.kwargs.get("model_name") or call_kwargs.args[2]
    assert model_name == "bullish"


@pytest.mark.asyncio
async def test_judge_evaluates(judge, context, mock_llm_router):
    """JudgeAgent returns action=JUDGE with proceed key when debate_result present."""
    context.debate_result = {
        "bullish": {"argument": "Bull case: RSI oversold strongly"},
        "bearish": {"argument": "Bear case: trend is downward"},
    }

    output = await judge.run(context)

    assert output.action == "JUDGE"
    assert "proceed" in output.data


@pytest.mark.asyncio
async def test_judge_anonymizes_arguments(judge, context, mock_llm_router):
    """Judge prompt uses 'Argument A'/'Argument B' labels, not 'bullish'/'bearish'."""
    context.debate_result = {
        "bullish": {"argument": "Bull case here"},
        "bearish": {"argument": "Bear case here"},
    }

    await judge.run(context)

    mock_llm_router.generate.assert_called_once()
    call_kwargs = mock_llm_router.generate.call_args
    prompt_text = call_kwargs.kwargs["prompt"]

    assert "bullish" not in prompt_text.lower() or "Argument" in prompt_text
    # The labels must appear
    assert "Argument A" in prompt_text
    assert "Argument B" in prompt_text
    # The raw side labels must NOT appear
    assert "bullish" not in prompt_text
    assert "bearish" not in prompt_text


@pytest.mark.asyncio
async def test_judge_reject(judge, context, mock_llm_router):
    """JudgeAgent returns proceed=False when LLM responds with proceed=false."""
    mock_llm_router.generate.return_value = JUDGE_REJECT_RESPONSE

    context.debate_result = {
        "bullish": {"argument": "Bull case here"},
        "bearish": {"argument": "Bear case here"},
    }

    output = await judge.run(context)

    assert output.data["proceed"] is False
