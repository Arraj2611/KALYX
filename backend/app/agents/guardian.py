"""
GuardianAgent — math-based risk checks, no LLM.

Evaluates each potential trade against hard risk limits before execution.
Checks run in a fixed order: daily loss → capital usage → confidence → trades per day →
one position per symbol → stop-loss → concentration. An EXIT is always allowed.
Any failure is an immediate BLOCK. All errors are also BLOCKs (fail-safe).

Position sizing is confidence-tiered:
  0.6–0.7  → 1 lot
  0.7–0.8  → 2 lots
  0.8–0.9  → 3 lots
  0.9+     → 5 lots
"""

from __future__ import annotations

import math
import time
from typing import Any

from app.agents.base import AgentContext, AgentOutput, BaseAgent


def as_price(value: Any) -> float | None:
    """A positive finite number, or None for anything else (missing, zero, text, NaN)."""
    try:
        price = float(value)
    except (TypeError, ValueError):
        return None
    return price if math.isfinite(price) and price > 0 else None


class GuardianAgent(BaseAgent):
    """Math-only risk gate — never calls an LLM.

    All decisions are deterministic arithmetic on the AgentContext.
    ``llm_tier_used`` is always ``None`` in returned AgentOutput objects.
    """

    def __init__(
        self,
        config: dict[str, Any],
        account_name: str,
        llm_router: Any = None,
        prompts_dir: str = "",
    ) -> None:
        super().__init__(
            name="guardian",
            role="risk_guard",
            llm_tier="none",
            account_name=account_name,
            llm_router=llm_router,
            prompts_dir=prompts_dir,
        )
        # Risk parameters — fall back to safe defaults if a key is missing
        self.max_loss_day: float = float(config.get("max_loss_day", 50000))
        self.max_capital_pct: float = float(config.get("max_capital_pct", 80))
        self.max_trades_day: int = int(config.get("max_trades_day", 50))
        self.min_confidence: float = float(config.get("min_confidence", 0.6))
        self.max_position_concentration_pct: float = float(
            config.get("max_position_concentration_pct", 30)
        )

    # ------------------------------------------------------------------
    # Public interface
    # ------------------------------------------------------------------

    def run(self, context: AgentContext) -> AgentOutput:
        """Run all risk checks and return ALLOW or BLOCK.

        Checks are evaluated in this order:
          1. Daily loss limit
          2. Capital usage limit
          3. Minimum confidence threshold

        The first failing check returns a BLOCK immediately.
        Any unexpected exception also returns a BLOCK (fail-safe).
        """
        start = time.perf_counter()
        try:
            signal = str(context.signals.get("signal", "")).upper()
            if signal == "EXIT":
                # Closing a position only ever reduces risk, so no limit may stand in its way.
                return AgentOutput(
                    agent_name=self.name,
                    action="ALLOW",
                    data={"exit": True},
                    reasoning="Exit reduces risk; risk limits do not apply.",
                    confidence=float(context.signals.get("confidence", 0.0)),
                    llm_tier_used=None,
                    latency_ms=(time.perf_counter() - start) * 1000.0,
                )
            if signal not in ("BUY", "SELL"):
                return self._block(
                    start, reason="unknown_signal", reasoning=f"Cannot trade on signal '{signal}'."
                )

            # 1. Daily loss check
            daily_pnl = sum(
                d.get("pnl", 0.0) for d in context.recent_decisions
            )
            if daily_pnl < -self.max_loss_day:
                return self._block(
                    start,
                    reason="daily_loss_exceeded",
                    reasoning=(
                        f"Daily P&L of {daily_pnl:.2f} exceeds max allowed loss "
                        f"of -{self.max_loss_day:.2f}. Trading halted for today."
                    ),
                )

            # 2. Capital usage check
            total = context.margins.total_margin
            used = context.margins.used_margin
            if total > 0:
                usage_pct = (used / total) * 100.0
            else:
                usage_pct = 100.0  # no capital at all → block
            if usage_pct > self.max_capital_pct:
                return self._block(
                    start,
                    reason="capital_limit_exceeded",
                    reasoning=(
                        f"Capital usage {usage_pct:.1f}% exceeds max allowed "
                        f"{self.max_capital_pct:.0f}%. Reduce exposure before trading."
                    ),
                )

            # 3. Confidence check
            confidence: float = float(context.signals.get("confidence", 0.0))
            if confidence < self.min_confidence:
                return self._block(
                    start,
                    reason="low_confidence",
                    reasoning=(
                        f"Signal confidence {confidence:.2f} is below minimum "
                        f"threshold {self.min_confidence:.2f}. Trade skipped."
                    ),
                )

            position_size = self._compute_position_size(confidence)

            # 4. Trades per day (entries only; exits do not count)
            trades_today = sum(
                1
                for d in context.recent_decisions
                if str(d.get("action", "")).lower() == "executed"
                and d.get("signal") in ("BUY", "SELL")
            )
            if trades_today >= self.max_trades_day:
                return self._block(
                    start,
                    reason="max_trades_reached",
                    reasoning=f"{trades_today} trades today; limit is {self.max_trades_day}.",
                )

            # 5. One position per symbol: pyramiding or flipping must go through an EXIT first
            if any(p.symbol == context.symbol and p.quantity != 0 for p in context.positions):
                return self._block(
                    start,
                    reason="position_exists",
                    reasoning=f"Already holding {context.symbol}; close it before opening another.",
                )

            # 6. A stop-loss must exist and sit on the losing side of the current price
            ltp = as_price(context.market_state.get("ltp"))
            stop = as_price(context.signals.get("stoploss"))
            if stop is None:
                return self._block(
                    start, reason="no_stoploss", reasoning="Entry signal carries no usable stop-loss."
                )
            if ltp is None or (signal == "BUY" and stop >= ltp) or (signal == "SELL" and stop <= ltp):
                return self._block(
                    start,
                    reason="invalid_stoploss",
                    reasoning=f"Stop {stop} is on the wrong side of price {ltp} for a {signal}.",
                )

            # 7. Concentration: the new position's value against total capital
            if total > 0:
                concentration_pct = ltp * position_size / total * 100.0
                if concentration_pct > self.max_position_concentration_pct:
                    return self._block(
                        start,
                        reason="concentration_exceeded",
                        reasoning=(
                            f"Position would be {concentration_pct:.2f}% of capital; "
                            f"limit is {self.max_position_concentration_pct:.2f}%."
                        ),
                    )

            latency_ms = (time.perf_counter() - start) * 1000.0
            return AgentOutput(
                agent_name=self.name,
                action="ALLOW",
                data={
                    "position_size": position_size,
                    "daily_pnl": daily_pnl,
                    "capital_usage_pct": round(usage_pct, 2),
                    "confidence": confidence,
                },
                reasoning=(
                    f"All risk checks passed. Confidence {confidence:.2f} → "
                    f"position size {position_size} lot(s). "
                    f"Capital usage {usage_pct:.1f}%, daily P&L {daily_pnl:.2f}."
                ),
                confidence=confidence,
                llm_tier_used=None,
                latency_ms=latency_ms,
            )

        except Exception as exc:  # noqa: BLE001
            return self._block(
                start,
                reason="guardian_error",
                reasoning=f"Unexpected error during risk check: {exc}. Blocking as fail-safe.",
            )

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _compute_position_size(self, confidence: float) -> int:
        """Map confidence score to a position size in lots.

        Bands:
          [0.6, 0.7) → 1 lot
          [0.7, 0.8) → 2 lots
          [0.8, 0.9) → 3 lots
          [0.9, 1.0] → 5 lots
        """
        if confidence >= 0.9:
            return 5
        if confidence >= 0.8:
            return 3
        if confidence >= 0.7:
            return 2
        return 1  # [0.6, 0.7)

    def _block(
        self,
        start: float,
        reason: str,
        reasoning: str,
    ) -> AgentOutput:
        """Build a BLOCK AgentOutput with the given reason and reasoning."""
        latency_ms = (time.perf_counter() - start) * 1000.0
        return AgentOutput(
            agent_name=self.name,
            action="BLOCK",
            data={"reason": reason},
            reasoning=reasoning,
            confidence=0.0,
            llm_tier_used=None,
            latency_ms=latency_ms,
        )
