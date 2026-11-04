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
        market_state={"ltp": 100.0},
        positions=[],
        margins=margins,
        recent_decisions=[{"pnl": daily_pnl}],
        memory_recall=[],
        signals={"signal": "BUY", "confidence": confidence, "stoploss": 95.0},
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



# ---------------------------------------------------------------------------
# Limits that were configured but not enforced, and the exit rule
# ---------------------------------------------------------------------------


def guarded(**overrides):
    config = {**GUARDIAN_CONFIG, **overrides}
    return GuardianAgent(config=config, account_name="test_account")


def entry_context(**changes):
    context = make_context(daily_pnl=0.0, confidence=0.8, available_cash=200000.0, used_margin=100000.0)
    for name, value in changes.items():
        setattr(context, name, value)
    return context


def position(symbol="NIFTY", quantity=3):
    from app.brokers.base import Position

    return Position(
        symbol=symbol, exchange="NSE", segment="CASH", quantity=quantity, average_price=100.0,
        last_price=100.0, pnl=0.0, product="MIS", broker_name="paper",
    )


def test_exit_is_allowed_even_when_every_limit_is_breached():
    context = make_context(daily_pnl=-10_000_000.0, confidence=0.1, available_cash=0.0, used_margin=300000.0)
    context.signals = {"signal": "EXIT", "confidence": 0.1}
    result = guarded().run(context)
    assert result.action == "ALLOW" and result.data["exit"] is True


def test_unknown_signal_is_blocked():
    context = entry_context(signals={"signal": "HOLD", "confidence": 0.9, "stoploss": 95.0})
    assert guarded().run(context).data["reason"] == "unknown_signal"


def test_max_trades_blocks_when_reached_and_counts_entries_only():
    rows = [{"action": "executed", "signal": "BUY", "pnl": 0.0}, {"action": "executed", "signal": "EXIT", "pnl": 5.0}]
    context = entry_context(recent_decisions=rows)
    assert guarded(max_trades_day=1).run(context).data["reason"] == "max_trades_reached"
    assert guarded(max_trades_day=2).run(context).action == "ALLOW"


def test_existing_position_blocks_a_new_entry_in_either_direction():
    for quantity in (3, -3):
        context = entry_context(positions=[position(quantity=quantity)])
        assert guarded().run(context).data["reason"] == "position_exists"


def test_position_in_another_symbol_does_not_block():
    context = entry_context(positions=[position(symbol="RELIANCE")])
    assert guarded().run(context).action == "ALLOW"


@pytest.mark.parametrize(
    "signal,stop,reason",
    [
        ("BUY", None, "no_stoploss"),
        ("BUY", 0, "no_stoploss"),
        ("BUY", "tight", "no_stoploss"),
        ("BUY", float("nan"), "no_stoploss"),
        ("BUY", 100.0, "invalid_stoploss"),
        ("BUY", 105.0, "invalid_stoploss"),
        ("SELL", 95.0, "invalid_stoploss"),
    ],
)
def test_entry_needs_a_stop_on_the_losing_side(signal, stop, reason):
    context = entry_context(signals={"signal": signal, "confidence": 0.8, "stoploss": stop})
    assert guarded().run(context).data["reason"] == reason


def test_short_entry_with_stop_above_price_is_allowed():
    context = entry_context(signals={"signal": "SELL", "confidence": 0.8, "stoploss": 105.0})
    assert guarded().run(context).action == "ALLOW"


def test_entry_without_a_price_is_blocked():
    context = entry_context(market_state={"ltp": 0})
    assert guarded().run(context).data["reason"] == "invalid_stoploss"


def test_concentration_blocks_a_position_that_is_too_large():
    # 3 lots at 100 against 300,000 total capital is 0.1%
    assert guarded(max_position_concentration_pct=0.05).run(entry_context()).data["reason"] == "concentration_exceeded"
    assert guarded(max_position_concentration_pct=0.5).run(entry_context()).action == "ALLOW"


def test_guardian_blocks_entry_when_halted_with_reason_kill_switch():
    context = entry_context(halted=True)
    result = guarded().run(context)
    assert result.action == "BLOCK" and result.data["reason"] == "kill_switch"


def test_guardian_allows_exit_when_halted():
    context = entry_context(halted=True, signals={"signal": "EXIT", "confidence": 0.5})
    assert guarded().run(context).action == "ALLOW"


# ---------------------------------------------------------------------------
# Cooldown after a stop-loss exit
# ---------------------------------------------------------------------------

from datetime import datetime, timedelta, timezone

NOW = datetime(2026, 11, 4, 6, 0, tzinfo=timezone.utc)


def stopped_out(symbol="NIFTY", minutes_ago=10, reason="stop_loss"):
    return {
        "action": "executed", "signal": "EXIT", "symbol": symbol, "pnl": -33.0,
        "exit_reason": reason, "timestamp": (NOW - timedelta(minutes=minutes_ago)).isoformat(),
    }


def test_cooldown_blocks_reentry_within_the_window():
    context = entry_context(recent_decisions=[stopped_out(minutes_ago=10)], now=NOW)
    assert guarded().run(context).data["reason"] == "cooldown"


def test_cooldown_expires():
    context = entry_context(recent_decisions=[stopped_out(minutes_ago=31)], now=NOW)
    assert guarded().run(context).action == "ALLOW"


def test_cooldown_is_per_symbol():
    context = entry_context(recent_decisions=[stopped_out(symbol="RELIANCE")], now=NOW)
    assert guarded().run(context).action == "ALLOW"


def test_a_target_exit_does_not_cool_down():
    context = entry_context(recent_decisions=[stopped_out(reason="target")], now=NOW)
    assert guarded().run(context).action == "ALLOW"


def test_cooldown_never_blocks_an_exit():
    context = entry_context(
        recent_decisions=[stopped_out()], now=NOW, signals={"signal": "EXIT", "confidence": 0.5}
    )
    assert guarded().run(context).action == "ALLOW"


def test_cooldown_length_is_configurable_and_zero_disables_it():
    context = entry_context(recent_decisions=[stopped_out(minutes_ago=10)], now=NOW)
    assert guarded(cooldown_minutes=5).run(context).action == "ALLOW"
    assert guarded(cooldown_minutes=0).run(context).action == "ALLOW"


def test_an_unreadable_timestamp_does_not_crash_or_block():
    row = {**stopped_out(), "timestamp": "not a time"}
    assert guarded().run(entry_context(recent_decisions=[row], now=NOW)).action == "ALLOW"
