"""ExecutorAgent — places orders via BrokerAdapter, logs via DecisionLogger.

No LLM involved. Reads the AgentContext produced by the analyst/guardian/debate
pipeline, builds a UnifiedOrder, submits it, and persists a full decision log
entry for the learning system.

Orders are MARKET orders without a price: the model's entry_price is a guess, and a
broker either ignores it or fills at the real market. An EXIT closes the whole open
position on the opposite side; it never opens a new one.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

from app.agents.base import AgentContext, AgentOutput, BaseAgent
from app.brokers.base import Position, TradeContext, UnifiedOrder
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
            action="EXECUTE" on success, "FAILED" on any exception, and "SKIP" when an
            EXIT finds nothing to close. EXECUTE data: order_id, status, broker, side,
            quantity, fill_price, decision_id, and realised_pnl for exits.
        """
        signals = context.signals
        market_state = context.market_state
        guardian_verdict = context.guardian_verdict or {}
        debate_result = context.debate_result or {}

        confidence: float = signals.get("confidence", 0.0)
        signal: str = signals.get("signal", "BUY")
        reasoning: str = debate_result.get("reasoning") or signals.get("reasoning", "")
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

        held: Position | None = None
        if signal == "EXIT":
            held = next((p for p in context.positions if p.symbol == context.symbol and p.quantity != 0), None)
            if held is None:
                await self._decision_logger.log_decision(
                    account_name=self.account_name,
                    symbol=context.symbol,
                    signal="EXIT",
                    action=DecisionAction.SKIPPED,
                    confidence=confidence,
                    reasoning=f"Nothing to exit in {context.symbol}. {reasoning}".strip(),
                    market_state=market_state,
                    skip_reason="no_position_to_exit",
                    context=trade_ctx,
                )
                return AgentOutput(
                    agent_name=self.name,
                    action="SKIP",
                    data={"reason": "no_position_to_exit"},
                    reasoning="No open position to exit.",
                    confidence=confidence,
                    llm_tier_used=None,
                )
            side = "SELL" if held.quantity > 0 else "BUY"
            quantity = abs(int(held.quantity))
            held_quantity, held_average = held.quantity, held.average_price  # before the order can change them
        else:
            side = signal
            quantity = int(guardian_verdict.get("position_size", 1))

        order = UnifiedOrder(
            symbol=context.symbol,
            exchange=market_state.get("exchange", "NSE"),
            segment=market_state.get("segment", "CASH"),
            transaction_type=side,
            quantity=quantity,
            order_type="MARKET",
            product=market_state.get("product", "MIS"),
            price=None,
            context=trade_ctx,
        )

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
                signal=signal,
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

        fill_price = self._fill_price(result, market_state)
        data: dict[str, Any] = {
            "order_id": result.broker_order_id,
            "status": result.status,
            "broker": result.broker_name,
            "side": side,
            "quantity": quantity,
            "fill_price": fill_price,
        }
        logged_state = market_state
        if held is not None:
            data["realised_pnl"] = (fill_price - held_average) * held_quantity
            logged_state = {
                **market_state,
                "realised_pnl": data["realised_pnl"],
                "exit_reason": signals.get("exit_reason", "signal"),
            }

        data["decision_id"] = await self._decision_logger.log_decision(
            account_name=self.account_name,
            symbol=context.symbol,
            signal=signal,
            action=DecisionAction.EXECUTED,
            confidence=confidence,
            reasoning=reasoning,
            market_state=logged_state,
            context=trade_ctx,
        )

        return AgentOutput(
            agent_name=self.name,
            action="EXECUTE",
            data=data,
            reasoning=reasoning,
            confidence=confidence,
            llm_tier_used=None,
        )

    @staticmethod
    def _fill_price(result: Any, market_state: dict) -> float:
        """The broker's fill price when it reports one, else the last price seen."""
        raw = getattr(result, "raw_response", None)
        reported = raw.get("fill_price") if isinstance(raw, dict) else None
        try:
            return float(reported) if reported else float(market_state.get("ltp") or 0.0)
        except (TypeError, ValueError):
            return float(market_state.get("ltp") or 0.0)
