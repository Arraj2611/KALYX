"""Tests for BaseAgent ABC, AgentContext dataclass, and AgentOutput dataclass."""

import time
import pytest
from pathlib import Path

from app.brokers.base import Position, MarginInfo
from app.agents.base import AgentContext, AgentOutput, BaseAgent


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def make_position() -> Position:
    return Position(
        symbol="RELIANCE",
        exchange="NSE",
        segment="EQ",
        quantity=10,
        average_price=2500.0,
        last_price=2550.0,
        pnl=500.0,
        product="CNC",
        broker_name="zerodha",
    )


def make_margin() -> MarginInfo:
    return MarginInfo(
        available_cash=50000.0,
        used_margin=15000.0,
        total_margin=65000.0,
        broker_name="zerodha",
        raw={"equity": {"available": {"cash": 50000.0}}},
    )


# ---------------------------------------------------------------------------
# AgentContext tests
# ---------------------------------------------------------------------------


def test_agent_context_creation():
    """Create AgentContext with all fields and verify each one."""
    position = make_position()
    margins = make_margin()

    context = AgentContext(
        account_name="zerodha_main",
        symbol="RELIANCE",
        market_state={"vix": 14.2, "trend": "bullish"},
        positions=[position],
        margins=margins,
        recent_decisions=[{"action": "BUY", "symbol": "INFY", "ts": "2026-04-29"}],
        memory_recall=[{"pattern": "breakout", "confidence": 0.9}],
        signals={"rsi": 72.5, "macd_cross": True},
        debate_result=None,
        guardian_verdict=None,
        config={"max_position_size": 50000, "risk_pct": 0.02},
    )

    assert context.account_name == "zerodha_main"
    assert context.symbol == "RELIANCE"
    assert context.market_state == {"vix": 14.2, "trend": "bullish"}
    assert context.positions == [position]
    assert context.margins is margins
    assert len(context.recent_decisions) == 1
    assert context.recent_decisions[0]["action"] == "BUY"
    assert len(context.memory_recall) == 1
    assert context.memory_recall[0]["pattern"] == "breakout"
    assert context.signals == {"rsi": 72.5, "macd_cross": True}
    assert context.debate_result is None
    assert context.guardian_verdict is None
    assert context.config["max_position_size"] == 50000


# ---------------------------------------------------------------------------
# AgentOutput tests
# ---------------------------------------------------------------------------


def test_agent_output_creation():
    """Create AgentOutput with all fields and verify each one."""
    output = AgentOutput(
        agent_name="analyst",
        action="BUY",
        data={"symbol": "RELIANCE", "qty": 10},
        reasoning="RSI oversold, strong support at 2480",
        confidence=0.87,
        llm_tier_used="tier1",
        latency_ms=342.5,
    )

    assert output.agent_name == "analyst"
    assert output.action == "BUY"
    assert output.data == {"symbol": "RELIANCE", "qty": 10}
    assert output.reasoning == "RSI oversold, strong support at 2480"
    assert output.confidence == 0.87
    assert output.llm_tier_used == "tier1"
    assert output.latency_ms == 342.5


def test_agent_output_defaults():
    """AgentOutput without llm_tier_used and latency_ms uses correct defaults."""
    output = AgentOutput(
        agent_name="guardian",
        action="HOLD",
        data={},
        reasoning="No strong signal detected",
        confidence=0.5,
    )

    assert output.llm_tier_used is None
    assert output.latency_ms == 0.0


# ---------------------------------------------------------------------------
# BaseAgent ABC tests
# ---------------------------------------------------------------------------


def test_base_agent_is_abstract():
    """Instantiating BaseAgent directly raises TypeError."""
    with pytest.raises(TypeError):
        BaseAgent(
            name="test",
            role="analyst",
            llm_tier="tier1",
            account_name="zerodha_main",
            llm_router=None,
            prompts_dir="/tmp",
        )


def test_base_agent_prompt_loading(tmp_path):
    """Concrete subclass loads system_prompt from {prompts_dir}/defaults/{name}.md."""
    defaults_dir = tmp_path / "defaults"
    defaults_dir.mkdir()
    prompt_file = defaults_dir / "analyst.md"
    prompt_file.write_text("You are an analyst agent. Analyse the market carefully.")

    class ConcreteAgent(BaseAgent):
        def run(self, context: AgentContext) -> AgentOutput:
            return AgentOutput(
                agent_name=self.name,
                action="HOLD",
                data={},
                reasoning="test",
                confidence=0.5,
            )

    agent = ConcreteAgent(
        name="analyst",
        role="analyst",
        llm_tier="tier1",
        account_name="zerodha_main",
        llm_router=None,
        prompts_dir=str(tmp_path),
    )

    assert "analyst agent" in agent.system_prompt
    assert "Analyse the market carefully" in agent.system_prompt


def test_base_agent_prompt_fallback(tmp_path):
    """When account-specific dir is missing, falls back to defaults/ prompt."""
    defaults_dir = tmp_path / "defaults"
    defaults_dir.mkdir()
    prompt_file = defaults_dir / "risk_guard.md"
    prompt_file.write_text("You are the risk guardian. Protect capital at all costs.")

    # No account-specific directory created — should fall back

    class ConcreteAgent(BaseAgent):
        def run(self, context: AgentContext) -> AgentOutput:
            return AgentOutput(
                agent_name=self.name,
                action="HOLD",
                data={},
                reasoning="test",
                confidence=0.5,
            )

    agent = ConcreteAgent(
        name="risk_guard",
        role="guardian",
        llm_tier="tier1",
        account_name="zerodha_main",
        llm_router=None,
        prompts_dir=str(tmp_path),
    )

    assert "risk guardian" in agent.system_prompt
    assert "Protect capital" in agent.system_prompt


def test_base_agent_reload_prompt(tmp_path):
    """reload_prompt() picks up a modified prompt file."""
    defaults_dir = tmp_path / "defaults"
    defaults_dir.mkdir()
    prompt_file = defaults_dir / "analyst.md"
    prompt_file.write_text("Version 1 of the analyst prompt.")

    class ConcreteAgent(BaseAgent):
        def run(self, context: AgentContext) -> AgentOutput:
            return AgentOutput(
                agent_name=self.name,
                action="HOLD",
                data={},
                reasoning="test",
                confidence=0.5,
            )

    agent = ConcreteAgent(
        name="analyst",
        role="analyst",
        llm_tier="tier1",
        account_name="zerodha_main",
        llm_router=None,
        prompts_dir=str(tmp_path),
    )

    assert "Version 1" in agent.system_prompt

    # Overwrite the file with a new version
    prompt_file.write_text("Version 2 of the analyst prompt.")

    agent.reload_prompt()

    assert "Version 2" in agent.system_prompt
    assert "Version 1" not in agent.system_prompt
