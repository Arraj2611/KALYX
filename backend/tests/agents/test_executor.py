"""Tests for ExecutorAgent — order placement + decision logging."""

import pytest
from unittest.mock import AsyncMock, MagicMock

from app.agents.base import AgentContext, AgentOutput
from app.agents.executor import ExecutorAgent
from app.brokers.base import MarginInfo, OrderResult, UnifiedOrder
from app.decisions.models import DecisionAction


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def mock_adapter():
    adapter = MagicMock()
    adapter.place_order = AsyncMock(
        return_value=OrderResult(
            broker_order_id="PAPER-001",
            status="COMPLETE",
            broker_name="paper",
            raw_response={},
        )
    )
    adapter.name = "paper"
    return adapter


@pytest.fixture
def mock_decision_logger():
    dl = MagicMock()
    dl.log_decision = AsyncMock(return_value=1)
    return dl


@pytest.fixture
def executor(mock_adapter, mock_decision_logger):
    return ExecutorAgent(
        adapter=mock_adapter,
        decision_logger=mock_decision_logger,
        account_name="paper_test",
    )


@pytest.fixture
def context():
    return AgentContext(
        account_name="paper_test",
        symbol="NIFTY25APR24500CE",
        market_state={"ltp": 150.0},
        positions=[],
        margins=MarginInfo(
            available_cash=100000.0,
            used_margin=50000.0,
            total_margin=150000.0,
            broker_name="paper",
            raw={},
        ),
        recent_decisions=[],
        memory_recall=[],
        signals={
            "signal": "BUY",
            "confidence": 0.8,
            "reasoning": "RSI oversold",
        },
        debate_result={"reasoning": "Debate favored buy"},
        guardian_verdict={"position_size": 50, "checks_passed": True},
        config={},
    )


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_executor_places_order(executor, context, mock_adapter):
    """output.action=='EXECUTE', data has order_id, adapter.place_order called once."""
    output = await executor.run(context)

    assert output.action == "EXECUTE"
    assert output.data.get("order_id") == "PAPER-001"
    mock_adapter.place_order.assert_called_once()


@pytest.mark.asyncio
async def test_executor_logs_decision(executor, context, mock_decision_logger):
    """decision_logger.log_decision called with EXECUTED action and correct symbol."""
    await executor.run(context)

    mock_decision_logger.log_decision.assert_called_once()
    call_kwargs = mock_decision_logger.log_decision.call_args
    # Support both positional and keyword-argument call styles
    kwargs = call_kwargs.kwargs if call_kwargs.kwargs else {}
    args = call_kwargs.args if call_kwargs.args else ()

    # Extract action and symbol regardless of how they were passed
    # Signature: log_decision(account_name, symbol, signal, action, confidence, reasoning, market_state, ...)
    if "action" in kwargs:
        assert kwargs["action"] == DecisionAction.EXECUTED
    else:
        assert args[3] == DecisionAction.EXECUTED  # 4th positional arg

    if "symbol" in kwargs:
        assert kwargs["symbol"] == "NIFTY25APR24500CE"
    else:
        assert args[1] == "NIFTY25APR24500CE"  # 2nd positional arg


@pytest.mark.asyncio
async def test_executor_creates_unified_order(executor, context, mock_adapter):
    """The order passed to adapter.place_order is a UnifiedOrder with correct fields."""
    await executor.run(context)

    call_args = mock_adapter.place_order.call_args
    order = call_args.args[0] if call_args.args else call_args.kwargs.get("order")

    assert isinstance(order, UnifiedOrder)
    assert order.symbol == "NIFTY25APR24500CE"
    assert order.quantity == 50
    assert order.context is not None
    assert order.context.confidence == 0.8


@pytest.mark.asyncio
async def test_executor_no_llm(executor):
    """ExecutorAgent must declare llm_tier='none' — no LLM dependency."""
    assert executor.llm_tier == "none"


@pytest.mark.asyncio
async def test_executor_handles_order_failure(executor, context, mock_adapter):
    """When place_order raises, output.action should be 'FAILED'."""
    mock_adapter.place_order = AsyncMock(side_effect=Exception("broker down"))

    output = await executor.run(context)

    assert output.action == "FAILED"
