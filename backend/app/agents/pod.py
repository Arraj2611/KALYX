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
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from app.agents.base import AgentContext
from app.agents.llm_router import LLMRouter
from app.agents.analyst import AnalystAgent
from app.agents.debate import DebateAgent, JudgeAgent
from app.agents.guardian import GuardianAgent
from app.agents.executor import ExecutorAgent
from app.agents.memory import MemoryAgent
from app.agents.strategist import StrategistAgent
from app.agents.streams import AgentStreamPublisher
from app.decisions.models import DecisionAction
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
        if self._eval_task:
            self._eval_task.cancel()
            try:
                await self._eval_task
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
        """Spawn the background task that calls run_cycle on a fixed interval."""
        self._eval_task = asyncio.create_task(self._eval_loop())

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

    async def run_cycle(self) -> None:
        """Evaluate all watched symbols once.

        Fetches positions and margins from the broker, then dispatches
        ``_evaluate_symbol`` for every symbol in the watch list.
        Errors per-symbol are caught and logged without aborting the rest.
        """
        agent_cfg = self.config.get("agents", {})
        watched = agent_cfg.get("watched_symbols", [])
        if not watched:
            return

        try:
            positions = await self.adapter.get_positions()
            margins = await self.adapter.get_margins()
        except Exception as exc:  # noqa: BLE001
            logger.error(
                "[%s] Failed to get positions/margins: %s", self.account_name, exc
            )
            return

        for symbol in watched:
            try:
                await self._evaluate_symbol(symbol, positions, margins, agent_cfg)
            except Exception as exc:  # noqa: BLE001
                logger.error(
                    "[%s] Failed evaluating %s: %s",
                    self.account_name,
                    symbol,
                    exc,
                    exc_info=True,
                )

    # ------------------------------------------------------------------
    # Per-symbol evaluation
    # ------------------------------------------------------------------

    async def _evaluate_symbol(
        self,
        symbol: str,
        positions: list,
        margins: Any,
        agent_cfg: dict,
    ) -> None:
        """Run the full analyst → debate → guardian → executor pipeline for one symbol."""

        # ---- Fetch LTP (best-effort) ------------------------------------
        market_state: dict = {"ltp": 0, "symbol": symbol}
        try:
            ltp_map = await self.adapter.get_ltp([symbol])
            market_state["ltp"] = ltp_map.get(symbol, 0)
        except Exception:  # noqa: BLE001
            pass

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
            recent_decisions=[],
            memory_recall=memory_recall,
            signals={},
            debate_result=None,
            guardian_verdict=None,
            config=agent_cfg,
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
            return

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
                return

            # Propagate judge's adjusted confidence
            context.signals["confidence"] = judge_output.confidence

        # ---- 3. Guardian ------------------------------------------------
        guardian_output = await self.guardian.run(context)
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
            return

        # ---- 4. Execute --------------------------------------------------
        executor_output = await self.executor.run(context)

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
        }
