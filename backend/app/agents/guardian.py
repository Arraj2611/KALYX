"""
GuardianAgent — math-based risk checks, no LLM.

Evaluates each potential trade against hard risk limits before execution.
Checks run in a fixed order: daily loss → capital usage → confidence.
Any failure is an immediate BLOCK. All errors are also BLOCKs (fail-safe).

Position sizing is confidence-tiered:
  0.6–0.7  → 1 lot
  0.7–0.8  → 2 lots
  0.8–0.9  → 3 lots
  0.9+     → 5 lots
"""

from __future__ import annotations

import time
from typing import Any

from app.agents.base import AgentContext, AgentOutput, BaseAgent


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

            # All checks passed — compute position size and allow
            position_size = self._compute_position_size(confidence)
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
