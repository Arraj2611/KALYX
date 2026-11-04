"""AgentPod — per-account container running the full eval pipeline.

Each AgentPod owns one of every agent type and orchestrates the complete
eval cycle: analyst → debate (optional) → guardian → executor. Lifecycle
is managed via start()/stop() with an optional background eval loop.

Pipeline flow per symbol
------------------------
1. Analyst emits a BUY/SELL/HOLD/EXIT signal.
2. If signal is HOLD: log and skip.
3. If debate is enabled: bullish + bearish advocates argue; judge decides.
4. Guardian runs math-based risk checks; BLOCK exits the cycle.
5. Executor places the order and logs the decision.

Before the symbols are analysed, every cycle checks open positions against their
stop-loss and target with no model involved. A closed trade is handed to the memory
agent, so hindsight and reflections reach the next cycle's recall.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from typing import Any
from zoneinfo import ZoneInfo

from app.agents.base import AgentContext
from app.agents.llm_router import LLMRouter
from app.agents.analyst import AnalystAgent
from app.agents.debate import DebateAgent, JudgeAgent
from app.agents.guardian import GuardianAgent, as_price
from app.agents.executor import ExecutorAgent
from app.agents.memory import MemoryAgent
from app.agents.strategist import StrategistAgent
from app.agents.streams import AgentStreamPublisher
from app.control.killswitch import KillSwitch
from app.markets.calendar import MarketCalendar
from app.decisions.models import DecisionAction, DecisionLog
from app.decisions.logger import DecisionLogger

logger = logging.getLogger(__name__)


class AgentPod:
    """Per-account container running the full agent eval pipeline.

    Constructor Args
    ----------------
    account_name     : Unique identifier for this trading account.
    adapter          : A BrokerAdapter implementation (real or paper).
    config           : Full account config dict.  Sub-keys:
                         config["agents"]["llm"]      — LLM routing config
                         config["agents"]["guardian"] — risk limits
                         config["agents"]["debate"]   — debate settings
                         config["agents"]["prompts_dir"]
    db               : SQLAlchemy session for DecisionLogger and MemoryAgent.
    alert_service    : Optional alert service (e.g. Telegram).
    stream_publisher : Optional AgentStreamPublisher for Redis Streams.
    """

    def __init__(
        self,
        account_name: str,
        adapter: Any,
        config: dict,
        db: Any,
        alert_service: Any = None,
        stream_publisher: Any = None,
        intelligence_builder: Any = None,
        clock: Any = None,
        calendar: MarketCalendar | None = None,
    ) -> None:
        self.account_name = account_name
        self.adapter = adapter
        self.config = config
        self._db = db
        self._alert_service = alert_service
        self._stream_publisher = stream_publisher
        self._intelligence_builder = intelligence_builder
        self._running = False
        self._eval_task: asyncio.Task | None = None
        # symbol -> {decision_id, side, stoploss, target} for positions this pod manages
        self._plans: dict[str, dict] = {}
        self._unmanaged: set[str] = set()
        self._no_price: set[str] = set()
        self._last_cycle: dict | None = None
        self._kill_switch = KillSwitch(lambda: self._db)
        self._clock = clock or (lambda: datetime.now(timezone.utc))
        self._calendar = calendar or MarketCalendar()
        # Serialises everything that places an order: the analysis cycle, the stop monitor and flatten.
        self._trade_lock = asyncio.Lock()
        self._monitor_task: asyncio.Task | None = None
        self._price_miss: dict[str, int] = {}
        self._price_alerted: set[str] = set()

        agent_cfg = config.get("agents", {})
        llm_cfg = agent_cfg.get("llm", {})
        prompts_dir = agent_cfg.get("prompts_dir", "prompts/defaults")

        # Build LLM router
        self.llm_router = LLMRouter(llm_cfg)

        # Register named debate models when debate is enabled
        debate_cfg = agent_cfg.get("debate", {})
        if debate_cfg.get("enabled"):
            self.llm_router.register_model(
                "bullish",
                debate_cfg.get("bullish_model", llm_cfg.get("quick_model", "")),
            )
            self.llm_router.register_model(
                "bearish",
                debate_cfg.get("bearish_model", llm_cfg.get("deep_model", "")),
            )
            self.llm_router.register_model(
                "judge",
                debate_cfg.get("judge_model", llm_cfg.get("deep_model", "")),
            )

        # Decision logger — wraps DB writes and optional alerts
        self._decision_logger = DecisionLogger(db=db, alert_service=alert_service)

        # Instantiate all agents
        self.analyst = AnalystAgent(
            self.llm_router, prompts_dir, account_name,
            intelligence_builder=intelligence_builder,
        )
        self.bullish = DebateAgent("bullish", self.llm_router, prompts_dir, account_name)
        self.bearish = DebateAgent("bearish", self.llm_router, prompts_dir, account_name)
        self.judge = JudgeAgent(self.llm_router, prompts_dir, account_name)
        self.guardian = GuardianAgent(
            agent_cfg.get("guardian", {}),
            account_name,
            self.llm_router,
            prompts_dir,
        )
        self.executor = ExecutorAgent(adapter, self._decision_logger, account_name)
        self.memory = MemoryAgent(
            self.llm_router, db, self._decision_logger, prompts_dir, account_name
        )
        self.strategist = StrategistAgent(
            self.llm_router,
            self.memory,
            self._decision_logger,
            prompts_dir,
            account_name,
            agent_cfg.get("strategist", {}),
        )

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def start(self) -> None:
        """Connect the broker (if not already) and mark the pod as running."""
        if not self.adapter.is_connected:
            try:
                await self.adapter.login({})
            except Exception as exc:  # noqa: BLE001
                logger.warning("[%s] Auto-login failed: %s", self.account_name, exc)
        self._running = True
        logger.info("[%s] Pod started", self.account_name)

    async def stop(self) -> None:
        """Stop the eval loop, run the end-of-session review, and mark as stopped."""
        self._running = False
        for task in (self._eval_task, self._monitor_task):
            if task:
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    pass
        try:
            summary = await self.memory.end_of_session_review()
            logger.info("[%s] Session review: %s", self.account_name, summary)
        except Exception as exc:  # noqa: BLE001
            logger.error("[%s] Session review failed: %s", self.account_name, exc)
        logger.info("[%s] Pod stopped", self.account_name)

    # ------------------------------------------------------------------
    # Background eval loop
    # ------------------------------------------------------------------

    async def start_eval_loop(self) -> None:
        """Spawn the analysis loop and the stop monitor."""
        self._eval_task = asyncio.create_task(self._eval_loop())
        self.start_monitor()

    def start_monitor(self) -> None:
        """Start only the stop monitor: it checks stops and targets every few seconds, with no model."""
        if self._monitor_task is None or self._monitor_task.done():
            self._monitor_task = asyncio.create_task(self._monitor_loop())

    async def _monitor_loop(self) -> None:
        interval = float(self.config.get("agents", {}).get("monitor_interval_seconds", 5))
        failures = 0
        while self._running:
            try:
                await self._monitor_tick()
                failures = 0
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # noqa: BLE001 - one bad tick must never end the loop
                failures += 1
                logger.error("[%s] Stop monitor tick failed (%d in a row): %s", self.account_name, failures, exc)
                if failures == 3:
                    await self._alert(f"Stop monitor has failed {failures} checks in a row: {exc}")
            await asyncio.sleep(interval)

    async def _monitor_tick(self) -> int:
        """One stop/target check against fresh broker state. Returns how many positions it closed."""
        agent_cfg = self.config.get("agents", {})
        if not self._market_open():
            return 0  # nothing can fill while the exchange is closed
        async with self._trade_lock:
            positions, margins = await self._broker_state()
            await self._recover_plans(positions)
            return await self._enforce_exits(positions, margins, agent_cfg)

    def _market_open(self) -> bool:
        """The gate: the account's exchange (config ``market``, default NSE) is in session."""
        if not self.config.get("agents", {}).get("market_gate", True):
            return True
        return self._calendar.is_open(self.config.get("market", "NSE"), self._clock())

    async def _alert(self, message: str) -> None:
        logger.error("[%s] %s", self.account_name, message)
        if self._alert_service:
            try:
                await self._alert_service.send_warning(self.account_name, message)
            except Exception:  # noqa: BLE001
                pass

    async def _eval_loop(self) -> None:
        """Internal loop: run_cycle, sleep interval, repeat while running."""
        interval = self.config.get("agents", {}).get("eval_interval_seconds", 300)
        while self._running:
            try:
                await self.run_cycle()
            except Exception as exc:  # noqa: BLE001
                logger.error(
                    "[%s] Eval cycle failed: %s",
                    self.account_name,
                    exc,
                    exc_info=True,
                )
                if self._alert_service:
                    try:
                        await self._alert_service.send_warning(
                            self.account_name, f"Eval cycle error: {exc}"
                        )
                    except Exception:  # noqa: BLE001
                        pass
            await asyncio.sleep(interval)

    # ------------------------------------------------------------------
    # Single eval cycle
    # ------------------------------------------------------------------

    async def run_cycle(self) -> dict:
        """Run one cycle and return ``{"evaluated", "errors", "closed"}``.

        Open positions are checked against their stop-loss and target first, with no model
        involved, so a failing LLM can never leave a stop unenforced. Each watched symbol then
        runs through ``_evaluate_symbol``. A symbol that raises is counted and logged without
        stopping the rest, and a cycle where everything failed raises an alert: errors used to
        vanish into the log, which let a dead pipeline look healthy.
        """
        agent_cfg = self.config.get("agents", {})
        watched = agent_cfg.get("watched_symbols", [])
        result = {"evaluated": 0, "errors": 0, "closed": 0, "skipped_halted": 0}
        if not watched:
            return result

        if not self._market_open():
            # Closed market: no price to trust, nothing can fill, and a model call would be wasted.
            result["skipped_closed"] = len(watched)
            await self._finish_cycle(result)
            return result

        async with self._trade_lock:
            try:
                positions, margins = await self._broker_state()
            except Exception as exc:  # noqa: BLE001
                logger.error("[%s] Failed to get positions/margins: %s", self.account_name, exc)
                result["errors"] += 1
                await self._finish_cycle(result)
                return result

            try:
                await self._recover_plans(positions)
                result["closed"] += await self._enforce_exits(positions, margins, agent_cfg)
            except Exception as exc:  # noqa: BLE001
                logger.error("[%s] Stop/target check failed: %s", self.account_name, exc, exc_info=True)
                result["errors"] += 1
            if result["closed"]:
                positions, margins = await self._refreshed(positions, margins)

        for symbol in watched:
            result["evaluated"] += 1
            try:
                outcome = await self._evaluate_symbol(symbol, positions, margins, agent_cfg)
            except Exception as exc:  # noqa: BLE001
                result["errors"] += 1
                logger.error(
                    "[%s] Failed evaluating %s: %s", self.account_name, symbol, exc, exc_info=True
                )
                continue
            if outcome == "halted":
                result["skipped_halted"] += 1
            elif outcome != "none":
                if outcome == "closed":
                    result["closed"] += 1
                positions, margins = await self._refreshed(positions, margins)

        await self._finish_cycle(result)
        return result

    async def _broker_state(self) -> tuple[list, Any]:
        return await self.adapter.get_positions(), await self.adapter.get_margins()

    async def _refreshed(self, positions: list, margins: Any) -> tuple[list, Any]:
        """Re-read the broker after an order; keep the old view if the read fails."""
        try:
            return await self._broker_state()
        except Exception as exc:  # noqa: BLE001
            logger.warning("[%s] Could not refresh broker state: %s", self.account_name, exc)
            return positions, margins

    async def _finish_cycle(self, result: dict) -> None:
        self._last_cycle = {**result, "at": datetime.now(timezone.utc).isoformat()}
        if result["errors"] and result["errors"] >= max(result["evaluated"], 1):
            message = (
                f"Eval cycle failed: {result['errors']} error(s) across "
                f"{result['evaluated']} symbol(s) evaluated"
            )
            await self._alert(message)

    # ------------------------------------------------------------------
    # Open positions: stop-loss, target, and learning from closed trades
    # ------------------------------------------------------------------

    async def _recover_plans(self, positions: list) -> None:
        """Rebuild stop/target plans for positions this pod did not open in this process.

        After a restart the broker still holds the position but the in-memory plan is gone. The
        entry decision's stored context carries the stop and target the model chose, so they are
        read back from DecisionLog. A position with no stop on record is left unmanaged and
        reported in ``get_status``.
        """
        for position in positions:
            symbol = position.symbol
            if position.quantity == 0 or symbol in self._plans:
                continue
            row = (
                self._db.query(DecisionLog)
                .filter(
                    DecisionLog.account_name == self.account_name,
                    DecisionLog.symbol == symbol,
                    DecisionLog.action == DecisionAction.EXECUTED.value,
                    DecisionLog.signal.in_(("BUY", "SELL")),
                    DecisionLog.outcome_actual.is_(None),
                )
                .order_by(DecisionLog.id.desc())
                .first()
            )
            signals = ((row.trade_context or {}).get("signals") or {}) if row is not None else {}
            stop = as_price(signals.get("stoploss"))
            if row is None or stop is None:
                if symbol not in self._unmanaged:
                    self._unmanaged.add(symbol)
                    logger.warning(
                        "[%s] %s is open with no stop-loss on record; it will not be managed",
                        self.account_name,
                        symbol,
                    )
                continue
            self._unmanaged.discard(symbol)
            self._plans[symbol] = {
                "decision_id": row.id,
                "side": row.signal,
                "stoploss": stop,
                "target": self._valid_target(row.signal, signals.get("target"), position.average_price),
            }

    @staticmethod
    def _valid_target(side: str, target: Any, fill: float) -> float | None:
        """A target on the wrong side of the entry would close the trade at once, so drop it."""
        price = as_price(target)
        if price is None or (side == "BUY" and price <= fill) or (side == "SELL" and price >= fill):
            return None
        return price

    async def _enforce_exits(self, positions: list, margins: Any, agent_cfg: dict) -> int:
        """Close every managed position whose stop-loss or target has been reached."""
        managed = [p for p in positions if p.quantity != 0 and p.symbol in self._plans]
        if not managed:
            return 0
        prices = await self.adapter.get_ltp([p.symbol for p in managed])
        closed = 0
        for position in managed:
            symbol = position.symbol
            ltp = float(prices.get(symbol) or 0.0)
            if ltp <= 0:
                misses = self._price_miss[symbol] = self._price_miss.get(symbol, 0) + 1
                logger.warning("[%s] No price for %s: cannot check its stop", self.account_name, symbol)
                if misses >= 3 and symbol not in self._price_alerted:
                    self._price_alerted.add(symbol)
                    await self._alert(
                        f"No price for open position {symbol} on {misses} checks in a row: its stop cannot be checked"
                    )
                continue
            self._price_miss.pop(symbol, None)
            self._price_alerted.discard(symbol)
            reason = self._exit_reason(position, self._plans[position.symbol], ltp)
            if reason and await self._close_position(position, positions, margins, agent_cfg, ltp, reason):
                closed += 1
        return closed

    @staticmethod
    def _exit_reason(position: Any, plan: dict, ltp: float) -> str | None:
        long = position.quantity > 0
        stop, target = plan["stoploss"], plan.get("target")
        if (long and ltp <= stop) or (not long and ltp >= stop):
            return "stop_loss"
        if target is not None and ((long and ltp >= target) or (not long and ltp <= target)):
            return "target"
        return None

    async def _close_position(
        self, position: Any, positions: list, margins: Any, agent_cfg: dict, ltp: float, reason: str
    ) -> bool:
        context = AgentContext(
            account_name=self.account_name,
            symbol=position.symbol,
            market_state={"ltp": ltp, "symbol": position.symbol},
            positions=positions,
            margins=margins,
            recent_decisions=[],
            memory_recall=[],
            signals={
                "signal": "EXIT",
                "confidence": 1.0,
                "reasoning": f"{reason}: price {ltp}, plan {self._plans.get(position.symbol)}",
            },
            debate_result=None,
            guardian_verdict={"exit": True},
            config=agent_cfg,
        )
        output = await self.executor.run(context)
        if output.action != "EXECUTE":
            logger.error(
                "[%s] Could not close %s on %s: %s", self.account_name, position.symbol, reason, output.reasoning
            )
            return False
        await self._record_close(position.symbol, position, output)
        return True

    async def flatten(self, reason: str) -> int:
        """Close every open position at market, whatever the stops say. Returns how many closed.

        Used by the kill-switch endpoint. Exits are never blocked by the switch or by risk limits.
        """
        agent_cfg = self.config.get("agents", {})
        async with self._trade_lock:
            positions, margins = await self._broker_state()
            open_positions = [p for p in positions if p.quantity != 0]
            prices = await self.adapter.get_ltp([p.symbol for p in open_positions]) if open_positions else {}
            closed = 0
            for position in open_positions:
                ltp = float(prices.get(position.symbol) or 0.0)
                if await self._close_position(position, positions, margins, agent_cfg, ltp, f"flatten ({reason})"):
                    closed += 1
            return closed

    async def _record_close(self, symbol: str, position: Any, output: Any) -> None:
        """Feed a closed trade to the memory agent: hindsight on the entry, then a reflection."""
        plan = self._plans.pop(symbol, None)
        if plan is None or position is None or not plan.get("decision_id"):
            logger.info("[%s] %s closed with no recorded entry; skipping memory", self.account_name, symbol)
            return
        try:
            await self.memory.store_outcome(
                decision_id=plan["decision_id"],
                entry_price=position.average_price,
                exit_price=output.data["fill_price"],
                pnl=output.data["realised_pnl"],
            )
        except Exception as exc:  # noqa: BLE001
            logger.error("[%s] Memory update failed for %s: %s", self.account_name, symbol, exc)

    def _open_plan(self, symbol: str, signal: str, signals: dict, output: Any) -> None:
        fill = output.data["fill_price"]
        self._plans[symbol] = {
            "decision_id": output.data.get("decision_id"),
            "side": signal,
            "stoploss": as_price(signals.get("stoploss")),
            "target": self._valid_target(signal, signals.get("target"), fill),
        }

    def _todays_decisions(self, positions: list) -> list[dict]:
        """Today's executed decisions plus open-position P&L, in the shape the guardian sums.

        Realised P&L is read from the EXIT decision's own record, so a trade opened yesterday and
        closed today counts today. Entries carry no P&L and only count as trades.
        """
        zone = ZoneInfo(self.config.get("timezone", "Asia/Kolkata"))
        day_start = datetime.now(zone).replace(hour=0, minute=0, second=0, microsecond=0)
        rows = (
            self._db.query(DecisionLog)
            .filter(
                DecisionLog.account_name == self.account_name,
                DecisionLog.action == DecisionAction.EXECUTED.value,
                DecisionLog.timestamp >= day_start.astimezone(timezone.utc),
            )
            .all()
        )
        decisions = [
            {
                "action": "executed",
                "signal": row.signal,
                "symbol": row.symbol,
                "pnl": float((row.market_state or {}).get("realised_pnl", 0.0)) if row.signal == "EXIT" else 0.0,
            }
            for row in rows
        ]
        decisions.append(
            {"action": "open_positions", "signal": "", "pnl": sum(float(p.pnl) for p in positions if p.quantity != 0)}
        )
        return decisions

    # ------------------------------------------------------------------
    # Per-symbol evaluation
    # ------------------------------------------------------------------

    async def _evaluate_symbol(
        self,
        symbol: str,
        positions: list,
        margins: Any,
        agent_cfg: dict,
    ) -> str:
        """Run the full analyst → debate → guardian → executor pipeline for one symbol.

        Returns "entered" or "closed" when an order was placed, "halted" when the kill switch
        skipped the symbol, otherwise "none".
        """
        halted = self._kill_switch.is_halted(self.account_name)
        if halted and not any(p.symbol == symbol and p.quantity != 0 for p in positions):
            return "halted"  # nothing open and no new risk allowed: do not spend a model call


        # ---- Fetch LTP: with no price there is nothing to analyse or trade ----
        market_state: dict = {"ltp": 0.0, "symbol": symbol}
        try:
            ltp_map = await self.adapter.get_ltp([symbol])
            market_state["ltp"] = float(ltp_map.get(symbol) or 0.0)
        except Exception as exc:  # noqa: BLE001
            logger.warning("[%s] Price fetch failed for %s: %s", self.account_name, symbol, exc)

        if market_state["ltp"] <= 0:
            if symbol not in self._no_price:
                self._no_price.add(symbol)  # log once per outage, not every cycle
                await self._decision_logger.log_decision(
                    account_name=self.account_name,
                    symbol=symbol,
                    signal="NONE",
                    action=DecisionAction.SKIPPED,
                    confidence=0.0,
                    reasoning="No price available, so no analysis or trade.",
                    market_state=market_state,
                    skip_reason="no_price",
                )
            return "none"
        self._no_price.discard(symbol)

        # ---- Memory recall -----------------------------------------------
        memory_recall = await self.memory.recall(
            symbol, strategy_id=None, market_state=market_state
        )

        # ---- Build shared context ----------------------------------------
        context = AgentContext(
            account_name=self.account_name,
            symbol=symbol,
            market_state=market_state,
            positions=positions,
            margins=margins,
            recent_decisions=self._todays_decisions(positions),
            memory_recall=memory_recall,
            signals={},
            debate_result=None,
            guardian_verdict=None,
            config=agent_cfg,
            halted=halted,
        )

        # ---- 1. Analyst --------------------------------------------------
        analyst_output = await self.analyst.run(context)
        context.signals = analyst_output.data
        signal = analyst_output.data.get("signal", "HOLD")

        if self._stream_publisher:
            await self._stream_publisher.publish_signal(
                self.account_name, analyst_output.data
            )

        if signal == "HOLD":
            await self._decision_logger.log_decision(
                account_name=self.account_name,
                symbol=symbol,
                signal="HOLD",
                action=DecisionAction.SKIPPED,
                confidence=analyst_output.confidence,
                reasoning=analyst_output.reasoning,
                market_state=market_state,
                skip_reason="no_signal",
            )
            return "none"

        # ---- 2. Debate (optional) ----------------------------------------
        debate_cfg = agent_cfg.get("debate", {})
        if debate_cfg.get("enabled") and not (
            debate_cfg.get("skip_for_exits") and signal == "EXIT"
        ):
            bull_output = await self.bullish.run(context)
            bear_output = await self.bearish.run(context)
            context.debate_result = {
                "bullish": bull_output.data,
                "bearish": bear_output.data,
            }
            judge_output = await self.judge.run(context)
            context.debate_result["verdict"] = judge_output.data
            context.debate_result["reasoning"] = judge_output.reasoning

            if judge_output.data.get("proceed") is False:
                await self._decision_logger.log_decision(
                    account_name=self.account_name,
                    symbol=symbol,
                    signal=signal,
                    action=DecisionAction.BLOCKED,
                    confidence=judge_output.confidence,
                    reasoning=judge_output.reasoning,
                    market_state=market_state,
                    skip_reason="judge_rejected",
                )
                return "none"

            # Propagate judge's adjusted confidence
            context.signals["confidence"] = judge_output.confidence

        # ---- 3 and 4. Guardian, then executor: under the trade lock, on a fresh broker view ----
        # The model took seconds; the stop monitor may have closed or opened something meanwhile.
        async with self._trade_lock:
            positions, margins = await self._refreshed(positions, margins)
            context.positions, context.margins = positions, margins
            context.recent_decisions = self._todays_decisions(positions)

            guardian_output = self.guardian.run(context)
            context.guardian_verdict = guardian_output.data

            if guardian_output.action == "BLOCK":
                await self._decision_logger.log_decision(
                    account_name=self.account_name,
                    symbol=symbol,
                    signal=signal,
                    action=DecisionAction.BLOCKED,
                    confidence=analyst_output.confidence,
                    reasoning=guardian_output.reasoning,
                    market_state=market_state,
                    skip_reason=guardian_output.data.get("reason", "guardian"),
                )
                return "none"

            executor_output = await self.executor.run(context)

            outcome = "none"
            if executor_output.action == "EXECUTE":
                if signal == "EXIT":
                    held = next((p for p in positions if p.symbol == symbol and p.quantity != 0), None)
                    await self._record_close(symbol, held, executor_output)
                    outcome = "closed"
                else:
                    self._open_plan(symbol, signal, context.signals, executor_output)
                    outcome = "entered"

        if self._stream_publisher:
            await self._stream_publisher.publish_decision(
                self.account_name,
                {
                    "symbol": symbol,
                    "signal": signal,
                    "action": executor_output.action,
                    "order_id": executor_output.data.get("order_id"),
                },
            )
        return outcome

    # ------------------------------------------------------------------
    # Status
    # ------------------------------------------------------------------

    def get_status(self) -> dict:
        """Return a lightweight status snapshot of the pod."""
        return {
            "account_name": self.account_name,
            "running": self._running,
            "broker": self.adapter.name,
            "connected": self.adapter.is_connected,
            "watched_symbols": self.config.get("agents", {}).get(
                "watched_symbols", []
            ),
            "last_cycle": self._last_cycle,
            "unmanaged_positions": sorted(self._unmanaged),
        }
