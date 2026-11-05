"""Regressions from the Phase 0 whole-branch review: each test pins one way money could have gone wrong."""

from types import SimpleNamespace

import pytest

from app.control.killswitch import KillSwitch
from app.execution.router import OrderRequest, _reduces_position
from tests.agents.test_core_cycle import positions, signal, stop_out, world  # noqa: F401  (fixtures)


@pytest.mark.asyncio
async def test_a_halt_during_analysis_stops_the_entry(world):
    original = world.pod.analyst.run

    async def halt_while_thinking(context):
        output = await original(context)
        KillSwitch(lambda: world.session).halt("paper_test", "halted mid-analysis", "pytest")
        return output

    world.pod.analyst.run = halt_while_thinking

    await world.pod.run_cycle()

    assert await positions(world) == []
    assert world.rows(action="blocked")[-1].skip_reason == "kill_switch"


@pytest.mark.asyncio
async def test_memory_reflection_runs_after_the_trade_lock_is_released(world):
    locked_during_memory = []
    original = world.pod.memory.store_outcome

    async def spy(**kwargs):
        locked_during_memory.append(world.pod._trade_lock.locked())
        return await original(**kwargs)

    world.pod.memory.store_outcome = spy

    await stop_out(world)

    assert locked_during_memory == [False]


@pytest.mark.asyncio
async def test_exit_with_an_unreadable_broker_does_not_sell_on_a_stale_view(world):
    await world.pod.run_cycle()
    world.ollama.responses["analyst"] = signal("EXIT", confidence=0.9, stoploss=None, target=None)
    original = world.pod.analyst.run

    async def broker_dies_after_analysis(context):
        output = await original(context)

        async def down():
            raise RuntimeError("429 from broker")

        world.adapter.get_positions = down
        return output

    world.pod.analyst.run = broker_dies_after_analysis

    await world.pod.run_cycle()

    assert world.rows(action="executed", signal="EXIT") == []
    assert world.rows(skip_reason="broker_state_unavailable")


@pytest.mark.asyncio
async def test_flatten_without_a_price_fills_nothing_at_zero_and_reports_what_is_left(world):
    await world.pod.run_cycle()
    world.market.prices["NIFTY"] = 0.0

    closed = await world.pod.flatten("feed is dead")

    assert closed == 0 and world.pod.last_flatten_remaining == ["NIFTY"]
    assert len(await positions(world)) == 1
    assert world.rows(action="executed", signal="EXIT") == []


@pytest.mark.asyncio
async def test_an_unknown_exchange_keeps_the_stop_monitor_on(world):
    world.pod.config["agents"]["market_gate"] = True
    world.pod.config["market"] = "MCX"

    assert world.pod._market_open() is True


@pytest.mark.asyncio
async def test_manual_order_helper_allows_only_orders_that_reduce_a_position(monkeypatch):
    held = SimpleNamespace(symbol="NIFTY", quantity=5)

    class Adapter:
        async def get_positions(self):
            return [held]

    monkeypatch.setattr("app.execution.router._get_adapter", lambda name: Adapter())

    def order(side, qty, symbol="NIFTY"):
        return OrderRequest(tradingsymbol=symbol, transaction_type=side, quantity=qty)

    assert await _reduces_position("a", order("SELL", 5)) is True
    assert await _reduces_position("a", order("SELL", 6)) is False  # would flip to short
    assert await _reduces_position("a", order("BUY", 1)) is False  # adds risk
    assert await _reduces_position("a", order("SELL", 1, symbol="TCS")) is False  # nothing held
