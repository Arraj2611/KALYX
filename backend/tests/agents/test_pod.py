"""Integration tests for AgentPod — per-account eval pipeline container."""

import json
import pytest
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

from app.brokers.paper.adapter import PaperAdapter
from app.agents.pod import AgentPod


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

BUY_RESPONSE = json.dumps({
    "signal": "BUY",
    "confidence": 0.8,
    "reasoning": "Strong breakout signal",
    "entry_price": 100.0,
    "stoploss": 90.0,
    "target": 120.0,
})

HOLD_RESPONSE = json.dumps({
    "signal": "HOLD",
    "confidence": 0.5,
    "reasoning": "No directional bias",
    "entry_price": None,
    "stoploss": None,
    "target": None,
})

LOW_CONFIDENCE_BUY_RESPONSE = json.dumps({
    "signal": "BUY",
    "confidence": 0.3,
    "reasoning": "Weak signal",
    "entry_price": 100.0,
    "stoploss": 90.0,
    "target": 120.0,
})


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def pod_config():
    return {
        "broker": "paper",
        "mode": "paper",
        "config": {"initial_capital": 1000000, "slippage_pct": 0},
        "agents": {
            "enabled": True,
            "eval_interval_seconds": 60,
            "watched_symbols": ["NIFTY"],
            "debate": {"enabled": False},
            "guardian": {
                "max_loss_day": 50000,
                "max_capital_pct": 80,
                "max_trades_day": 50,
                "min_confidence": 0.6,
                "max_position_concentration_pct": 30,
            },
            "llm": {
                "quick_model": "test-model",
                "deep_model": "test-model",
                "ollama_base_url": "http://localhost:11434",
            },
            "prompts_dir": "(set by test)",
            "memory": {"recall_limit": 10},
        },
    }


@pytest.fixture
def mock_llm_response():
    return BUY_RESPONSE


@pytest.fixture
def pod(pod_config, mock_llm_response, tmp_path):
    # Create prompt files required by agents
    defaults_dir = tmp_path / "defaults"
    defaults_dir.mkdir()
    for name in ("analyst", "bullish", "bearish", "judge", "memory", "strategist"):
        (defaults_dir / f"{name}.md").write_text(f"You are the {name} agent.")

    pod_config["agents"]["prompts_dir"] = str(tmp_path)

    adapter = PaperAdapter(pod_config["config"])

    p = AgentPod(
        account_name="paper_test",
        adapter=adapter,
        config=pod_config,
        db=MagicMock(),
        alert_service=MagicMock(),
    )

    # Override LLM calls so we never hit Ollama
    p.llm_router.generate = AsyncMock(return_value=mock_llm_response)
    p.llm_router.generate_with_model = AsyncMock(return_value=mock_llm_response)

    # Override memory.recall to avoid DB queries
    p.memory.recall = AsyncMock(return_value=[])

    return p


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_pod_creation(pod):
    """AgentPod initializes all required sub-agents."""
    assert pod.account_name == "paper_test"
    assert pod.analyst is not None
    assert pod.guardian is not None
    assert pod.executor is not None
    assert pod.memory is not None


@pytest.mark.asyncio
async def test_pod_start_stop(pod):
    """start() sets _running=True; stop() sets _running=False."""
    await pod.start()
    assert pod._running is True

    await pod.stop()
    assert pod._running is False


@pytest.mark.asyncio
async def test_pod_single_cycle_buy(pod):
    """A full eval cycle with a BUY signal completes without raising."""
    await pod.start()
    await pod.run_cycle()
    await pod.stop()
    # No assertion on position — guardian/executor may or may not place
    # depending on margin state, but the cycle must not raise.


@pytest.mark.asyncio
async def test_pod_single_cycle_hold(pod):
    """When LLM returns HOLD, the eval cycle skips execution — no positions created."""
    pod.llm_router.generate = AsyncMock(return_value=HOLD_RESPONSE)
    pod.llm_router.generate_with_model = AsyncMock(return_value=HOLD_RESPONSE)

    await pod.start()
    await pod.run_cycle()
    await pod.stop()

    positions = await pod.adapter.get_positions()
    assert positions == []


@pytest.mark.asyncio
async def test_pod_guardian_blocks_low_confidence(pod):
    """Guardian blocks trades with confidence below min_confidence (0.6)."""
    pod.llm_router.generate = AsyncMock(return_value=LOW_CONFIDENCE_BUY_RESPONSE)
    pod.llm_router.generate_with_model = AsyncMock(return_value=LOW_CONFIDENCE_BUY_RESPONSE)

    await pod.start()
    await pod.run_cycle()
    await pod.stop()

    positions = await pod.adapter.get_positions()
    assert positions == []
