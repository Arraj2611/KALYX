"""MemoryAgent — recall past decisions, fill hindsight, generate LLM reflections.

Queries DecisionLog for historical context, calls fill_hindsight when trades
close, and produces structured reflections (patterns, learnings, tags) via
the deep-tier LLM. End-of-session review tallies decisions that still need
hindsight analysis.
"""

from __future__ import annotations

import json
import logging
import re
import time
from datetime import date
from typing import Any, Optional

from app.agents.base import AgentContext, AgentOutput, BaseAgent
from app.decisions.models import DecisionAction, DecisionLog

logger = logging.getLogger(__name__)

_REFLECTION_FALLBACK: dict[str, Any] = {
    "reflection": "",
    "learning": "",
    "tags": [],
    "pattern": "",
}


class MemoryAgent(BaseAgent):
    """Recall past decisions and generate LLM-backed reflections after trades close.

    Constructor Args
    ----------------
    llm_router      : LLM router (deep tier used for reflections).
    db              : Active SQLAlchemy session.
    decision_logger : DecisionLogger instance for fill_hindsight and log_decision.
    prompts_dir     : Root directory for prompt markdown files.
    account_name    : Account scope for all DB queries.
    """

    def __init__(
        self,
        llm_router: Any,
        db: Any,
        decision_logger: Any,
        prompts_dir: str,
        account_name: str,
    ) -> None:
        self._db = db
        self._decision_logger = decision_logger
        super().__init__(
            name="memory",
            role="trade_memory",
            llm_tier="deep",
            account_name=account_name,
            llm_router=llm_router,
            prompts_dir=prompts_dir,
        )

    # ------------------------------------------------------------------
    # Core interface
    # ------------------------------------------------------------------

    async def run(self, context: AgentContext) -> AgentOutput:
        """Default run — recall past decisions for the current symbol.

        Returns an AgentOutput with action='RECALL' and a list of matching
        historical decisions so downstream agents can use memory context.
        """
        start = time.perf_counter()

        results = await self.recall(
            symbol=context.symbol,
            strategy_id=None,
            market_state=context.market_state,
        )

        return self._timed_output(
            start,
            agent_name=self.name,
            action="RECALL",
            data={"recall_count": len(results), "recalls": results},
            reasoning=f"Retrieved {len(results)} past decisions for {context.symbol}",
            confidence=1.0,
            llm_tier_used=None,
        )

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def recall(
        self,
        symbol: Optional[str],
        strategy_id: Optional[int],
        market_state: dict,
        limit: int = 10,
    ) -> list[dict]:
        """Query DecisionLog for historical decisions with hindsight filled.

        Filters by account_name (always), symbol (if provided), and
        strategy_id (if provided). Returns only rows where was_correct is
        not NULL — i.e. decisions that have been evaluated in hindsight.

        Returns an empty list on any error so the eval cycle is never blocked.
        """
        try:
            query = self._db.query(DecisionLog).filter(
                DecisionLog.account_name == self.account_name,
                DecisionLog.was_correct.isnot(None),
            )

            if symbol:
                query = query.filter(DecisionLog.symbol == symbol)

            if strategy_id is not None:
                query = query.filter(DecisionLog.strategy_id == strategy_id)

            rows = (
                query.order_by(DecisionLog.timestamp.desc())
                .limit(limit)
                .all()
            )

            return [
                {
                    "symbol": row.symbol,
                    "signal": row.signal,
                    "action": row.action,
                    "confidence": row.confidence,
                    "reasoning": row.reasoning,
                    "was_correct": row.was_correct,
                    "outcome_actual": row.outcome_actual,
                    "timestamp": str(row.timestamp),
                }
                for row in rows
            ]

        except Exception as exc:  # noqa: BLE001
            logger.warning("MemoryAgent.recall failed: %s", exc)
            return []

    async def store_outcome(
        self,
        decision_id: int,
        entry_price: float,
        exit_price: float,
        pnl: float,
    ) -> None:
        """Fill hindsight for a closed trade and generate an LLM reflection.

        Steps
        -----
        1. Query DecisionLog by id.
        2. If not found, log a warning and return early.
        3. Call decision_logger.fill_hindsight with the realised P&L.
        4. Build a reflection prompt and call think() on the deep tier.
        5. Parse the JSON reflection.
        6. Log a new REFLECTION decision (signal='REFLECTION', action=SKIPPED)
           capturing the learning and linking it back to the original decision.
        """
        entry: Optional[Any] = (
            self._db.query(DecisionLog)
            .filter(DecisionLog.id == decision_id)
            .first()
        )

        if entry is None:
            logger.warning(
                "MemoryAgent.store_outcome: decision_id=%d not found", decision_id
            )
            return

        # Determine outcome_if_taken based on whether trade was executed
        executed = str(entry.action).lower() == "executed"
        outcome_actual = pnl if executed else 0.0

        await self._decision_logger.fill_hindsight(
            decision_id,
            outcome_if_taken=pnl,
            outcome_actual=outcome_actual,
        )

        # Generate reflection via deep LLM
        market_state = entry.market_state or {}
        prompt = (
            f"## Trade Outcome\n"
            f"Symbol: {entry.symbol}\n"
            f"Action: {entry.action}\n"
            f"Entry price: {entry_price}\n"
            f"Exit price: {exit_price}\n"
            f"P&L: {pnl}\n\n"
            f"## Original Reasoning\n{entry.reasoning}\n\n"
            f"## Market State at Decision\n{json.dumps(market_state, indent=2)}\n\n"
            "## Task\n"
            "Reflect on this trade outcome. Respond with a single JSON object:\n"
            "  reflection : string (what happened and why)\n"
            "  learning   : string (actionable rule for future trades)\n"
            "  tags       : list of strings (signal types, conditions)\n"
            "  pattern    : string (short machine-readable pattern name)\n"
            "Return ONLY the JSON object."
        )

        raw = await self.think(prompt, tier="deep")
        reflection = self._parse_reflection(raw)

        # Log the reflection as a new decision entry
        await self._decision_logger.log_decision(
            account_name=self.account_name,
            symbol=entry.symbol,
            signal="REFLECTION",
            action=DecisionAction.SKIPPED,
            confidence=1.0,
            reasoning=reflection.get("learning", ""),
            market_state={"reflection_for": decision_id, "pnl": pnl},
        )

    async def end_of_session_review(self) -> dict:
        """Summarise today's decisions awaiting hindsight.

        Counts all decisions for this account where was_correct is still NULL
        (not yet reviewed), and also counts decisions that were SKIPPED or
        BLOCKED (already analysed without execution).

        Returns a dict with total_decisions, reviewed count, and today's date.
        Returns {"error": str(e)} on any DB failure.
        """
        try:
            today = date.today()

            pending = (
                self._db.query(DecisionLog)
                .filter(
                    DecisionLog.account_name == self.account_name,
                    DecisionLog.was_correct.is_(None),
                )
                .all()
            )

            reviewed = [
                d
                for d in pending
                if str(d.action).lower()
                in (DecisionAction.SKIPPED.value, DecisionAction.BLOCKED.value)
            ]

            return {
                "total_decisions": len(pending),
                "reviewed": len(reviewed),
                "date": today.isoformat(),
            }

        except Exception as exc:  # noqa: BLE001
            return {"error": str(exc)}

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _parse_reflection(self, raw: str) -> dict[str, Any]:
        """Parse reflection JSON from LLM response.

        Strips markdown code fences (```json ... ``` or ``` ... ```) before
        attempting JSON decode. Returns a fallback dict on any parse error.
        """
        try:
            text = raw.strip()

            fence_match = re.search(r"```(?:json)?\s*([\s\S]*?)```", text)
            if fence_match:
                text = fence_match.group(1).strip()

            return json.loads(text)

        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "MemoryAgent._parse_reflection failed: %s — using fallback", exc
            )
            return dict(_REFLECTION_FALLBACK)
