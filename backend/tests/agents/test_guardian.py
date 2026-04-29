"""Exhaustive tests for GuardianAgent — math-based risk checks, no LLM."""

import pytest

from app.brokers.base import MarginInfo
from app.agents.base import AgentContext, AgentOutput, BaseAgent
from app.agents.guardian import GuardianAgent


# ---------------------------------------------------------------------------
# Guardian config used across all tests
# ---------------------------------------------------------------------------

GUARDIAN_CONFIG = {
    "max_loss_day": 50000,
    "max_capital_pct": 80,
    "max_trades_day": 50,
    "min_confidence": 0.6,
    "max_position_concentration_pct": 30,
}


# ---------------------------------------------------------------------------
# Helper — build an AgentContext with controlled values
# ---------------------------------------------------------------------------


def make_context(
    daily_pnl: float,
    confidence: float,
    available_cash: float,
    used_margin: float,
) -> AgentContext:
    """Create an AgentContext with the key risk inputs controlled.

    daily_pnl is stored as a list of dicts with a "pnl" key under
    recent_decisions so GuardianAgent can sum them.
    """
    total_margin = available_cash + used_margin
    margins = MarginInfo(
        available_cash=available_cash,
        used_margin=used_margin,
        total_margin=total_margin,
        broker_name="zerodha",
        raw={},
    )
    return AgentContext(
        account_name="test_account",
        symbol="NIFTY",
        market_state={},
        positions=[],
        margins=margins,
        recent_decisions=[{"pnl": daily_pnl}],
        memory_recall=[],
        signals={"confidence": confidence},
        debate_result=None,
        guardian_verdict=None,
        config=GUARDIAN_CONFIG,
    )


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_guardian_allows_valid_trade():
    """confidence=0.8, no limits hit → action=ALLOW, position_size > 0."""
    guardian = GuardianAgent(config=GUARDIAN_CONFIG, account_name="test_account")
    context = make_context(
        daily_pnl=0.0,
        confidence=0.8,
        available_cash=200000.0,
        used_margin=100000.0,
    )
    result = guardian.run(context)

    assert result.action == "ALLOW"
    assert result.data.get("position_size", 0) > 0


def test_guardian_blocks_daily_loss_exceeded():
    """daily_pnl=-60000 with max_loss_day=50000 → action=BLOCK, 'daily_loss' in reason."""
    guardian = GuardianAgent(config=GUARDIAN_CONFIG, account_name="test_account")
    context = make_context(
        daily_pnl=-60000.0,
        confidence=0.85,
        available_cash=200000.0,
        used_margin=100000.0,
    )
    result = guardian.run(context)

    assert result.action == "BLOCK"
    assert "daily_loss" in result.data.get("reason", "")


def test_guardian_blocks_capital_limit():
    """available=100000, used=450000 (82% usage), max_capital_pct=80 → BLOCK, 'capital' in reason."""
    guardian = GuardianAgent(config=GUARDIAN_CONFIG, account_name="test_account")
    # total = 550000, used = 450000 → 81.8% > 80%
    context = make_context(
        daily_pnl=0.0,
        confidence=0.85,
        available_cash=100000.0,
        used_margin=450000.0,
    )
    result = guardian.run(context)

    assert result.action == "BLOCK"
    assert "capital" in result.data.get("reason", "")


def test_guardian_blocks_low_confidence():
    """confidence=0.4 < min_confidence=0.6 → BLOCK, 'confidence' in reason."""
    guardian = GuardianAgent(config=GUARDIAN_CONFIG, account_name="test_account")
    context = make_context(
        daily_pnl=0.0,
        confidence=0.4,
        available_cash=200000.0,
        used_margin=100000.0,
    )
    result = guardian.run(context)

    assert result.action == "BLOCK"
    assert "confidence" in result.data.get("reason", "")


def test_guardian_position_sizing_low_confidence():
    """confidence=0.65 (range 0.6-0.7) → position_size=1."""
    guardian = GuardianAgent(config=GUARDIAN_CONFIG, account_name="test_account")
    context = make_context(
        daily_pnl=0.0,
        confidence=0.65,
        available_cash=200000.0,
        used_margin=100000.0,
    )
    result = guardian.run(context)

    assert result.action == "ALLOW"
    assert result.data.get("position_size") == 1


def test_guardian_position_sizing_medium_confidence():
    """confidence=0.75 (range 0.7-0.8) → position_size=2."""
    guardian = GuardianAgent(config=GUARDIAN_CONFIG, account_name="test_account")
    context = make_context(
        daily_pnl=0.0,
        confidence=0.75,
        available_cash=200000.0,
        used_margin=100000.0,
    )
    result = guardian.run(context)

    assert result.action == "ALLOW"
    assert result.data.get("position_size") == 2


def test_guardian_position_sizing_high_confidence():
    """confidence=0.85 (range 0.8-0.9) → position_size=3."""
    guardian = GuardianAgent(config=GUARDIAN_CONFIG, account_name="test_account")
    context = make_context(
        daily_pnl=0.0,
        confidence=0.85,
        available_cash=200000.0,
        used_margin=100000.0,
    )
    result = guardian.run(context)

    assert result.action == "ALLOW"
    assert result.data.get("position_size") == 3


def test_guardian_position_sizing_very_high_confidence():
    """confidence=0.95 (>= 0.9) → position_size=5."""
    guardian = GuardianAgent(config=GUARDIAN_CONFIG, account_name="test_account")
    context = make_context(
        daily_pnl=0.0,
        confidence=0.95,
        available_cash=200000.0,
        used_margin=100000.0,
    )
    result = guardian.run(context)

    assert result.action == "ALLOW"
    assert result.data.get("position_size") == 5


def test_guardian_no_llm_used():
    """GuardianAgent never uses an LLM — llm_tier_used must be None."""
    guardian = GuardianAgent(config=GUARDIAN_CONFIG, account_name="test_account")
    context = make_context(
        daily_pnl=0.0,
        confidence=0.8,
        available_cash=200000.0,
        used_margin=100000.0,
    )
    result = guardian.run(context)

    assert result.llm_tier_used is None


def test_guardian_is_base_agent():
    """GuardianAgent must be a subclass of BaseAgent."""
    guardian = GuardianAgent(config=GUARDIAN_CONFIG, account_name="test_account")
    assert isinstance(guardian, BaseAgent)
