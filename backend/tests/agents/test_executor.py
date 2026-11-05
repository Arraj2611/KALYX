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


# ---------------------------------------------------------------------------
# Market price, fills, and exits
# ---------------------------------------------------------------------------


def held(quantity, average_price=100.0):
    from app.brokers.base import Position

    return Position(
        symbol="NIFTY25APR24500CE", exchange="NSE", segment="FNO", quantity=quantity,
        average_price=average_price, last_price=average_price, pnl=0.0, product="MIS", broker_name="paper",
    )


def order_sent(mock_adapter):
    call = mock_adapter.place_order.call_args
    return call.args[0] if call.args else call.kwargs["order"]


def logged(mock_decision_logger):
    return mock_decision_logger.log_decision.call_args.kwargs


@pytest.mark.asyncio
async def test_market_order_does_not_carry_the_models_price_guess(executor, context, mock_adapter):
    context.signals["entry_price"] = 123.0
    await executor.run(context)
    assert order_sent(mock_adapter).price is None


@pytest.mark.asyncio
async def test_entry_reports_fill_price_side_quantity_and_decision_id(executor, context, mock_adapter):
    mock_adapter.place_order.return_value = OrderResult("PAPER-001", "COMPLETE", "paper", {"fill_price": 151.0})
    output = await executor.run(context)
    assert output.data["fill_price"] == 151.0 and output.data["side"] == "BUY"
    assert output.data["quantity"] == 50 and output.data["decision_id"] == 1


@pytest.mark.asyncio
async def test_fill_price_falls_back_to_the_last_price(executor, context):
    assert (await executor.run(context)).data["fill_price"] == 150.0


@pytest.mark.asyncio
async def test_exit_closes_a_long_with_the_position_quantity_and_reports_realised_pnl(
    executor, context, mock_adapter, mock_decision_logger
):
    context.signals["signal"] = "EXIT"
    context.guardian_verdict = {"exit": True}
    context.positions = [held(3)]
    mock_adapter.place_order.return_value = OrderResult("PAPER-002", "COMPLETE", "paper", {"fill_price": 105.0})

    output = await executor.run(context)

    order = order_sent(mock_adapter)
    assert (order.transaction_type, order.quantity) == ("SELL", 3)
    assert output.action == "EXECUTE" and output.data["realised_pnl"] == pytest.approx(15.0)
    assert logged(mock_decision_logger)["market_state"]["realised_pnl"] == pytest.approx(15.0)
    assert logged(mock_decision_logger)["signal"] == "EXIT"


@pytest.mark.asyncio
async def test_exit_closes_a_short_by_buying_back(executor, context, mock_adapter):
    context.signals["signal"] = "EXIT"
    context.positions = [held(-3)]
    mock_adapter.place_order.return_value = OrderResult("PAPER-002", "COMPLETE", "paper", {"fill_price": 95.0})

    output = await executor.run(context)

    order = order_sent(mock_adapter)
    assert (order.transaction_type, order.quantity) == ("BUY", 3)
    assert output.data["realised_pnl"] == pytest.approx(15.0)


@pytest.mark.asyncio
async def test_exit_with_no_position_places_nothing_and_logs_a_skip(executor, context, mock_adapter, mock_decision_logger):
    context.signals["signal"] = "EXIT"

    output = await executor.run(context)

    mock_adapter.place_order.assert_not_called()
    assert output.action == "SKIP"
    assert logged(mock_decision_logger)["action"] == DecisionAction.SKIPPED
    assert logged(mock_decision_logger)["skip_reason"] == "no_position_to_exit"


@pytest.mark.asyncio
async def test_exit_pnl_uses_the_position_as_it_was_before_the_order(executor, context, mock_adapter):
    """An adapter may flatten the very object it handed out; P&L must not read it afterwards."""
    position = held(3)

    async def fill_and_flatten(order):
        position.quantity, position.average_price = 0, 0.0
        return OrderResult("PAPER-002", "COMPLETE", "paper", {"fill_price": 105.0})

    mock_adapter.place_order = fill_and_flatten
    context.signals["signal"] = "EXIT"
    context.positions = [position]

    assert (await executor.run(context)).data["realised_pnl"] == pytest.approx(15.0)


@pytest.mark.asyncio
async def test_exit_records_why_it_happened(executor, context, mock_adapter, mock_decision_logger):
    context.signals.update({"signal": "EXIT", "exit_reason": "stop_loss"})
    context.positions = [held(3)]
    mock_adapter.place_order.return_value = OrderResult("PAPER-002", "COMPLETE", "paper", {"fill_price": 95.0})

    await executor.run(context)

    assert logged(mock_decision_logger)["market_state"]["exit_reason"] == "stop_loss"


@pytest.mark.asyncio
async def test_exit_without_a_stated_reason_is_a_signal_exit(executor, context, mock_adapter, mock_decision_logger):
    context.signals["signal"] = "EXIT"
    context.positions = [held(3)]

    await executor.run(context)

    assert logged(mock_decision_logger)["market_state"]["exit_reason"] == "signal"
