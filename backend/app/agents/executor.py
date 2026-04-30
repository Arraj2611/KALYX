"""ExecutorAgent — places orders via BrokerAdapter, logs via DecisionLogger.

No LLM involved. Reads the AgentContext produced by the analyst/guardian/debate
pipeline, builds a UnifiedOrder, submits it, and persists a full decision log
entry for the learning system.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

from app.agents.base import AgentContext, AgentOutput, BaseAgent
from app.brokers.base import TradeContext, UnifiedOrder
from app.decisions.models import DecisionAction

logger = logging.getLogger(__name__)


class ExecutorAgent(BaseAgent):
    """Executes approved orders via the broker adapter and logs every decision.

    Receives the fully-evaluated AgentContext (signals + guardian_verdict +
    debate_result) and translates it into a UnifiedOrder.  On success it logs
    DecisionAction.EXECUTED; on any exception it logs FAILED and returns a
    FAILED output so the caller can react without crashing.

    Args:
        adapter: A BrokerAdapter implementation (real or paper).
        decision_logger: A DecisionLogger instance.
        account_name: Identifies the trading account in logs and DB.
    """

    def __init__(
        self,
        adapter: Any,
        decision_logger: Any,
        account_name: str,
    ) -> None:
        self._adapter = adapter
        self._decision_logger = decision_logger
        super().__init__(
            name="executor",
            role="order_executor",
            llm_tier="none",
            account_name=account_name,
            llm_router=None,
            prompts_dir="",
        )

    # ------------------------------------------------------------------
    # BaseAgent interface
    # ------------------------------------------------------------------

    async def run(self, context: AgentContext) -> AgentOutput:  # type: ignore[override]
        """Build a UnifiedOrder from context and submit it to the broker.

        Returns
        -------
        AgentOutput
            action="EXECUTE" on success, action="FAILED" on any exception.
        """
        signals = context.signals
        market_state = context.market_state
        guardian_verdict = context.guardian_verdict or {}
        debate_result = context.debate_result or {}

        # ------------------------------------------------------------------
        # Extract fields
        # ------------------------------------------------------------------
        confidence: float = signals.get("confidence", 0.0)
        signal_reasoning: str = signals.get("reasoning", "")
        reasoning: str = debate_result.get("reasoning") or signal_reasoning

        quantity: int = int(guardian_verdict.get("position_size", 1))
        strategy_id: str = str(context.config.get("strategy_id", 0))

        trade_ctx = TradeContext(
            strategy_id=strategy_id,
            account_name=self.account_name,
            signals=signals,
            market_state=market_state,
            reasoning=reasoning,
            confidence=confidence,
            timestamp=datetime.now(timezone.utc),
        )

        order = UnifiedOrder(
            symbol=context.symbol,
            exchange=market_state.get("exchange", "NSE"),
            segment=market_state.get("segment", "CASH"),
            transaction_type=signals.get("signal", "BUY"),
            quantity=quantity,
            order_type="MARKET",
            product=market_state.get("product", "MIS"),
            price=signals.get("entry_price"),
            context=trade_ctx,
        )

        # ------------------------------------------------------------------
        # Place order
        # ------------------------------------------------------------------
        try:
            result = await self._adapter.place_order(order)
        except Exception as exc:  # noqa: BLE001
            logger.error(
                "ExecutorAgent: order placement failed for %s — %s",
                context.symbol,
                exc,
            )
            await self._decision_logger.log_decision(
                account_name=self.account_name,
                symbol=context.symbol,
                signal=signals.get("signal", "UNKNOWN"),
                action=DecisionAction.FAILED,
                confidence=confidence,
                reasoning=f"Order placement failed: {exc}",
                market_state=market_state,
                context=trade_ctx,
            )
            return AgentOutput(
                agent_name=self.name,
                action="FAILED",
                data={"error": str(exc)},
                reasoning=f"Order placement failed: {exc}",
                confidence=confidence,
                llm_tier_used=None,
            )

        # ------------------------------------------------------------------
        # Log success and return
        # ------------------------------------------------------------------
        await self._decision_logger.log_decision(
            account_name=self.account_name,
            symbol=context.symbol,
            signal=signals.get("signal", "UNKNOWN"),
            action=DecisionAction.EXECUTED,
            confidence=confidence,
            reasoning=reasoning,
            market_state=market_state,
            context=trade_ctx,
        )

        return AgentOutput(
            agent_name=self.name,
            action="EXECUTE",
            data={
                "order_id": result.broker_order_id,
                "status": result.status,
                "broker": result.broker_name,
            },
            reasoning=reasoning,
            confidence=confidence,
            llm_tier_used=None,
        )
