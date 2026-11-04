"""No-mock eval cycles: real AgentPod, real LLMRouter, real PaperAdapter, real SQLAlchemy session.

Only the outside world is faked: Ollama is a local HTTP server and market prices come from FakeMarket.
Everything else, including the HTTP call, JSON parsing, risk gate, orders, DecisionLog rows and the
memory loop, runs for real. Earlier tests replaced the LLM router with an AsyncMock, which hid a
TypeError in BaseAgent.think and an await on a sync guardian, and one test asserted nothing.
"""

import asyncio
import json
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import app.data.models  # noqa: F401  (registers the tables DecisionLog points at)
from app.agents.pod import AgentPod
from app.brokers.paper.adapter import PaperAdapter
from app.control.killswitch import KillSwitch
from app.data.database import Base
from app.decisions.models import DecisionLog

AGENTS = ("analyst", "bullish", "bearish", "judge", "memory", "strategist")
REFLECTION = json.dumps(
    {"reflection": "Breakout failed.", "learning": "Cut failed breakouts fast.", "tags": ["breakout"], "pattern": "failed_breakout"}
)


def signal(kind="BUY", confidence=0.8, stoploss=90.0, target=120.0, entry=99.5):
    return json.dumps(
        {"signal": kind, "confidence": confidence, "reasoning": f"{kind} setup", "entry_price": entry, "stoploss": stoploss, "target": target}
    )


class FakeOllama:
    """Serves POST /api/generate. The agent is told apart by its system prompt."""

    def __init__(self):
        self.responses = {"analyst": signal(), "memory": REFLECTION}
        self.calls = []
        self.status = 200
        outer = self

        class Handler(BaseHTTPRequestHandler):
            wbufsize = -1  # one TCP segment per response; split writes cost ~2s per call on Windows

            def do_POST(self):
                body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
                agent = next((a for a in AGENTS if f"You are the {a} agent." in body.get("system", "")), "unknown")
                outer.calls.append((agent, body))
                if outer.status != 200:
                    self.send_response(outer.status)
                    self.end_headers()
                    return
                payload = json.dumps({"response": outer.responses[agent]}).encode()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(payload)))
                self.end_headers()
                self.wfile.write(payload)

            def log_message(self, *args):
                pass

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    @property
    def url(self):
        return f"http://127.0.0.1:{self.server.server_address[1]}"

    def count(self, agent):
        return sum(1 for name, _ in self.calls if name == agent)

    def close(self):
        self.server.shutdown()
        self.server.server_close()


class FakeMarket:
    async def __call__(self, symbols):
        return {s: self.prices.get(s, 0.0) for s in symbols}

    def __init__(self, prices):
        self.prices = dict(prices)


def make_pod(tmp_path, ollama, adapter, session, alerts, guardian=None, llm=None, symbols=("NIFTY",)):
    defaults = tmp_path / "prompts" / "defaults"
    defaults.mkdir(parents=True, exist_ok=True)
    for name in AGENTS:
        (defaults / f"{name}.md").write_text(f"You are the {name} agent.")
    config = {
        "broker": "paper",
        "mode": "paper",
        "agents": {
            "enabled": True,
            "eval_interval_seconds": 60,
            "watched_symbols": list(symbols),
            "debate": {"enabled": False},
            "guardian": {
                "max_loss_day": 50_000,
                "max_capital_pct": 80,
                "max_trades_day": 50,
                "min_confidence": 0.6,
                "max_position_concentration_pct": 30,
                **(guardian or {}),
            },
            "llm": {"quick_model": "m", "deep_model": "m", "ollama_base_url": ollama.url, "max_retries": 1, **(llm or {})},
            "monitor_interval_seconds": 0.05,
            "prompts_dir": str(tmp_path / "prompts"),
            "memory": {"recall_limit": 10},
        },
    }
    return AgentPod(account_name="paper_test", adapter=adapter, config=config, db=session, alert_service=alerts)


@pytest.fixture
def world(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)  # DecisionLogger writes log files relative to the working directory
    ollama = FakeOllama()
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)()
    market = FakeMarket({"NIFTY": 100.0})
    adapter = PaperAdapter({"initial_capital": 1_000_000, "slippage_pct": 0}, price_source=market)
    alerts = MagicMock()
    alerts.send_warning = AsyncMock()
    ns = SimpleNamespace(ollama=ollama, session=session, market=market, adapter=adapter, alerts=alerts, tmp_path=tmp_path)
    ns.build = lambda **kw: make_pod(tmp_path, ollama, adapter, session, alerts, **kw)
    ns.pod = ns.build()
    ns.rows = lambda **kw: session.query(DecisionLog).filter_by(**kw).order_by(DecisionLog.id).all()
    yield ns
    ollama.close()
    session.close()


async def positions(world):
    return await world.adapter.get_positions()


@pytest.mark.asyncio
async def test_buy_cycle_opens_position_at_market_price_not_the_llm_guess(world):
    result = await world.pod.run_cycle()

    assert result["errors"] == 0
    (position,) = await positions(world)
    assert (position.symbol, position.quantity, position.average_price) == ("NIFTY", 3, 100.0)
    (executed,) = world.rows(action="executed")
    assert executed.symbol == "NIFTY" and executed.signal == "BUY"


@pytest.mark.asyncio
async def test_second_buy_signal_does_not_pyramid_the_position(world):
    await world.pod.run_cycle()
    await world.pod.run_cycle()

    (position,) = await positions(world)
    assert position.quantity == 3
    assert len(world.rows(action="executed")) == 1
    assert world.rows(action="blocked")[0].skip_reason == "position_exists"


@pytest.mark.asyncio
async def test_stop_loss_closes_position_and_memory_loop_records_the_loss(world):
    await world.pod.run_cycle()
    world.ollama.responses["analyst"] = signal("HOLD", confidence=0.5, stoploss=None, target=None)
    world.market.prices["NIFTY"] = 89.0

    result = await world.pod.run_cycle()

    assert result["closed"] == 1 and await positions(world) == []
    entry = world.rows(action="executed", signal="BUY")[0]
    assert entry.outcome_actual == pytest.approx(-33.0) and entry.was_correct is False
    assert len(world.rows(signal="REFLECTION")) == 1 and world.ollama.count("memory") == 1


@pytest.mark.asyncio
async def test_target_closes_position_with_profit(world):
    await world.pod.run_cycle()
    world.ollama.responses["analyst"] = signal("HOLD", confidence=0.5, stoploss=None, target=None)
    world.market.prices["NIFTY"] = 121.0

    await world.pod.run_cycle()

    assert await positions(world) == []
    entry = world.rows(action="executed", signal="BUY")[0]
    assert entry.outcome_actual == pytest.approx(63.0) and entry.was_correct is True


@pytest.mark.asyncio
async def test_exit_signal_closes_the_whole_position(world):
    await world.pod.run_cycle()
    world.ollama.responses["analyst"] = signal("EXIT", confidence=0.7, stoploss=None, target=None)
    world.market.prices["NIFTY"] = 105.0

    await world.pod.run_cycle()

    assert await positions(world) == []
    assert world.rows(action="executed", signal="BUY")[0].outcome_actual == pytest.approx(15.0)


@pytest.mark.asyncio
async def test_exit_with_nothing_open_places_no_order(world):
    world.ollama.responses["analyst"] = signal("EXIT", confidence=0.7, stoploss=None, target=None)

    await world.pod.run_cycle()

    assert await positions(world) == [] and world.rows(action="executed") == []
    assert world.rows(action="skipped")[0].skip_reason == "no_position_to_exit"


@pytest.mark.asyncio
async def test_exit_is_never_blocked_by_the_daily_loss_limit(world):
    pod = world.build(guardian={"max_loss_day": 10})
    await pod.run_cycle()
    world.ollama.responses["analyst"] = signal("EXIT", confidence=0.7, stoploss=None, target=None)
    world.market.prices["NIFTY"] = 95.0  # unrealised -15, past the limit but above the stop

    await pod.run_cycle()

    assert await positions(world) == []


@pytest.mark.asyncio
async def test_realised_loss_blocks_the_next_entry(world):
    pod = world.build(guardian={"max_loss_day": 20})
    await pod.run_cycle()
    world.ollama.responses["analyst"] = signal("HOLD", confidence=0.5, stoploss=None, target=None)
    world.market.prices["NIFTY"] = 89.0
    await pod.run_cycle()  # stopped out, realised -33
    world.ollama.responses["analyst"] = signal("BUY")
    world.market.prices["NIFTY"] = 100.0

    await pod.run_cycle()

    assert await positions(world) == []
    assert world.rows(action="blocked")[-1].skip_reason == "daily_loss_exceeded"


@pytest.mark.asyncio
async def test_max_trades_per_day_is_enforced(world):
    pod = world.build(guardian={"max_trades_day": 1})
    await pod.run_cycle()
    world.ollama.responses["analyst"] = signal("HOLD", confidence=0.5, stoploss=None, target=None)
    world.market.prices["NIFTY"] = 89.0
    await pod.run_cycle()
    world.ollama.responses["analyst"] = signal("BUY")
    world.market.prices["NIFTY"] = 100.0

    await pod.run_cycle()

    assert await positions(world) == []
    assert world.rows(action="blocked")[-1].skip_reason == "max_trades_reached"


@pytest.mark.asyncio
async def test_position_concentration_is_enforced(world):
    pod = world.build(guardian={"max_position_concentration_pct": 0.01})

    await pod.run_cycle()

    assert await positions(world) == []
    assert world.rows(action="blocked")[0].skip_reason == "concentration_exceeded"


@pytest.mark.asyncio
@pytest.mark.parametrize("stop,reason", [(None, "no_stoploss"), (110.0, "invalid_stoploss")])
async def test_entry_without_a_sane_stop_is_blocked(world, stop, reason):
    world.ollama.responses["analyst"] = signal("BUY", stoploss=stop)

    await world.pod.run_cycle()

    assert await positions(world) == []
    assert world.rows(action="blocked")[0].skip_reason == reason


@pytest.mark.asyncio
async def test_no_price_skips_the_symbol_without_calling_the_model(world):
    world.market.prices.clear()

    result = await world.pod.run_cycle()

    assert result["errors"] == 0 and world.ollama.count("analyst") == 0
    assert world.rows(action="skipped")[0].skip_reason == "no_price"


@pytest.mark.asyncio
async def test_failing_model_is_reported_not_swallowed(world):
    world.ollama.status = 500

    result = await world.pod.run_cycle()

    assert result["evaluated"] == 1 and result["errors"] == 1
    world.alerts.send_warning.assert_awaited()
    assert world.pod.get_status()["last_cycle"]["errors"] == 1


@pytest.mark.asyncio
async def test_restarted_pod_still_enforces_the_stop(world):
    await world.pod.run_cycle()
    restarted = world.build()  # new pod, same broker and database
    world.ollama.responses["analyst"] = signal("HOLD", confidence=0.5, stoploss=None, target=None)
    world.market.prices["NIFTY"] = 89.0

    result = await restarted.run_cycle()

    assert result["closed"] == 1 and await positions(world) == []


@pytest.mark.asyncio
async def test_short_position_is_stopped_out_when_price_rises(world):
    world.ollama.responses["analyst"] = signal("SELL", stoploss=110.0, target=80.0)
    await world.pod.run_cycle()
    (position,) = await positions(world)
    assert position.quantity == -3
    world.ollama.responses["analyst"] = signal("HOLD", confidence=0.5, stoploss=None, target=None)
    world.market.prices["NIFTY"] = 111.0

    result = await world.pod.run_cycle()

    assert result["closed"] == 1 and await positions(world) == []
    assert world.rows(action="executed", signal="SELL")[0].outcome_actual == pytest.approx(-33.0)


@pytest.mark.asyncio
async def test_short_position_takes_profit_at_its_target(world):
    world.ollama.responses["analyst"] = signal("SELL", stoploss=110.0, target=80.0)
    await world.pod.run_cycle()
    world.ollama.responses["analyst"] = signal("HOLD", confidence=0.5, stoploss=None, target=None)
    world.market.prices["NIFTY"] = 79.0

    await world.pod.run_cycle()

    assert await positions(world) == []
    entry = world.rows(action="executed", signal="SELL")[0]
    assert entry.outcome_actual == pytest.approx(63.0) and entry.was_correct is True


@pytest.mark.asyncio
async def test_target_on_the_wrong_side_of_the_entry_is_ignored(world):
    world.ollama.responses["analyst"] = signal("BUY", stoploss=90.0, target=95.0)  # target below the entry

    await world.pod.run_cycle()
    world.ollama.responses["analyst"] = signal("HOLD", confidence=0.5, stoploss=None, target=None)
    await world.pod.run_cycle()

    (position,) = await positions(world)
    assert position.quantity == 3


@pytest.mark.asyncio
async def test_halted_symbol_with_no_position_makes_no_model_call(world):
    KillSwitch(lambda: world.session).halt("all", "test", "pytest")

    result = await world.pod.run_cycle()

    assert world.ollama.count("analyst") == 0 and await positions(world) == []
    assert result["skipped_halted"] == 1 and result["errors"] == 0


@pytest.mark.asyncio
async def test_halt_blocks_new_entries_with_a_position_open(world):
    await world.pod.run_cycle()
    KillSwitch(lambda: world.session).halt("paper_test", "test", "pytest")

    await world.pod.run_cycle()

    assert world.rows(action="blocked")[-1].skip_reason == "kill_switch"


@pytest.mark.asyncio
async def test_halt_does_not_stop_the_stop_loss(world):
    await world.pod.run_cycle()
    KillSwitch(lambda: world.session).halt("all", "test", "pytest")
    world.ollama.responses["analyst"] = signal("HOLD", confidence=0.5, stoploss=None, target=None)
    world.market.prices["NIFTY"] = 89.0

    result = await world.pod.run_cycle()

    assert result["closed"] == 1 and await positions(world) == []


@pytest.mark.asyncio
async def test_flatten_closes_every_open_position(world):
    pod = world.build(symbols=("NIFTY", "RELIANCE"))
    world.market.prices["RELIANCE"] = 200.0  # the canned BUY has stop 90, so the price must sit above it
    await pod.run_cycle()
    assert len(await positions(world)) == 2

    closed = await pod.flatten("owner pressed the button")

    assert closed == 2 and await positions(world) == []
    assert len(world.rows(action="executed", signal="EXIT")) == 2


@pytest.mark.asyncio
async def test_flatten_with_nothing_open_closes_nothing(world):
    assert await world.pod.flatten("drill") == 0


async def wait_for(condition, timeout=3.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if await condition():
            return True
        await asyncio.sleep(0.02)
    return False


@pytest.mark.asyncio
async def test_monitor_closes_a_stopped_position_without_waiting_for_the_cycle(world):
    await world.pod.run_cycle()
    await world.pod.start()
    world.pod.start_monitor()
    world.market.prices["NIFTY"] = 89.0

    async def flat():
        return await positions(world) == []

    closed = await wait_for(flat)
    await world.pod.stop()

    assert closed
    assert len(world.rows(action="executed", signal="EXIT")) == 1
    assert world.ollama.count("analyst") == 1  # only the first cycle ever asked the model


@pytest.mark.asyncio
async def test_monitor_and_cycle_never_double_close(world):
    await world.pod.run_cycle()
    world.ollama.responses["analyst"] = signal("HOLD", confidence=0.5, stoploss=None, target=None)
    world.market.prices["NIFTY"] = 89.0

    await asyncio.gather(world.pod._monitor_tick(), world.pod.run_cycle(), world.pod._monitor_tick())

    assert await positions(world) == []  # a double close would leave a short behind
    assert len(world.rows(action="executed", signal="EXIT")) == 1


@pytest.mark.asyncio
async def test_monitor_survives_a_broker_error(world, monkeypatch):
    await world.pod.run_cycle()
    real = world.adapter.get_positions
    calls = {"n": 0}

    async def flaky():
        calls["n"] += 1
        if calls["n"] == 1:
            raise RuntimeError("broker hiccup")
        return await real()

    monkeypatch.setattr(world.adapter, "get_positions", flaky)
    world.market.prices["NIFTY"] = 89.0
    await world.pod.start()
    world.pod.start_monitor()

    async def flat():
        return await real() == []  # read through the real method so only the monitor sees the failure

    closed = await wait_for(flat)
    await world.pod.stop()

    assert closed and calls["n"] >= 2


@pytest.mark.asyncio
async def test_missing_price_alerts_once_after_three_checks_then_again_after_recovery(world):
    await world.pod.run_cycle()
    world.market.prices.clear()

    for _ in range(4):
        await world.pod._monitor_tick()
    assert world.alerts.send_warning.await_count == 1
    assert "NIFTY" in world.alerts.send_warning.await_args.args[1]

    world.market.prices["NIFTY"] = 100.0
    await world.pod._monitor_tick()
    world.market.prices.clear()
    for _ in range(3):
        await world.pod._monitor_tick()
    assert world.alerts.send_warning.await_count == 2


@pytest.mark.asyncio
async def test_eval_loop_starts_the_monitor_and_stop_cancels_it(world):
    await world.pod.start()
    await world.pod.start_eval_loop()
    assert world.pod._monitor_task is not None and not world.pod._monitor_task.done()

    await world.pod.stop()

    assert world.pod._monitor_task.done()
