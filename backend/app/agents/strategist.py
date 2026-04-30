"""StrategistAgent — overnight optimization loop (autoresearch pattern).

Iterates over a list of strategies, asks the deep-tier LLM to suggest a
single parameter change per strategy, evaluates whether to keep the change
via Sharpe ratio comparison, and logs every experiment as a decision so the
learning system has a full audit trail.
"""

from __future__ import annotations

import json
import logging
import re
import time
from typing import Any, Optional

from app.agents.base import AgentContext, AgentOutput, BaseAgent
from app.decisions.models import DecisionAction

logger = logging.getLogger(__name__)

_SUGGESTION_FALLBACK: dict[str, Any] = {
    "parameter_name": "unknown",
    "current_value": None,
    "suggested_value": None,
    "reasoning": "parse_failure",
    "expected_improvement": "N/A",
}


class StrategistAgent(BaseAgent):
    """LLM-backed strategy optimizer that runs an overnight autoresearch loop.

    For each strategy it:
    1. Pulls relevant memory context.
    2. Asks the deep-tier LLM to suggest ONE parameter change.
    3. Evaluates the suggestion via ``_should_keep()`` (Sharpe delta).
    4. Logs the experiment outcome as a decision entry.

    Constructor Args
    ----------------
    llm_router      : LLM router (deep tier used for suggestions).
    memory          : MemoryAgent instance for context retrieval.
    decision_logger : DecisionLogger for persisting experiment results.
    prompts_dir     : Root directory for prompt markdown files.
    account_name    : Account scope for all DB queries.
    config          : Optional runtime config dict.
                      Keys: experiment_duration_min, max_experiments_per_night.
    """

    def __init__(
        self,
        llm_router: Any,
        memory: Any,
        decision_logger: Any,
        prompts_dir: str,
        account_name: str,
        config: Optional[dict] = None,
    ) -> None:
        self._memory = memory
        self._decision_logger = decision_logger
        self._config = config or {}
        super().__init__(
            name="strategist",
            role="strategy_optimizer",
            llm_tier="deep",
            account_name=account_name,
            llm_router=llm_router,
            prompts_dir=prompts_dir,
        )

    # ------------------------------------------------------------------
    # Core interface
    # ------------------------------------------------------------------

    async def run(self, context: AgentContext) -> AgentOutput:
        """Default run — generate a suggestion for the strategy in context.config.

        Returns an AgentOutput with action='OPTIMIZE' and the suggestion dict.
        """
        start = time.perf_counter()

        suggestion = await self.suggest_improvement(
            strategy_name="default",
            strategy_config=context.config,
            performance={"win_rate": 0, "sharpe": 0},
        )

        return self._timed_output(
            start,
            agent_name=self.name,
            action="OPTIMIZE",
            data=suggestion,
            reasoning=suggestion.get("reasoning", ""),
            confidence=1.0,
            llm_tier_used=self.llm_tier,
        )

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def suggest_improvement(
        self,
        strategy_name: str,
        strategy_config: dict,
        performance: dict,
    ) -> dict:
        """Ask the deep-tier LLM to suggest ONE parameter change.

        Pulls memory context to inform the suggestion, builds a structured
        prompt, calls the LLM, and returns the parsed suggestion dict.

        Returns a fallback dict on any parse failure.
        """
        memory_context = await self._memory.recall(
            symbol=None,
            strategy_id=None,
            market_state={},
        )

        prompt = self._build_suggestion_prompt(
            strategy_name=strategy_name,
            strategy_config=strategy_config,
            performance=performance,
            memory_context=memory_context,
        )

        raw = await self.think(prompt, tier="deep")
        return self._parse(raw)

    async def overnight_optimization(
        self, strategies: list[dict]
    ) -> list[dict]:
        """Run the autoresearch loop across all provided strategies.

        Iterates up to ``max_experiments_per_night`` strategies, generates a
        suggestion for each, evaluates keep/discard via Sharpe delta, and
        logs every experiment as a decision entry.

        Args:
            strategies: List of dicts with keys:
                name        : str — strategy identifier
                config      : dict — current parameters
                performance : dict — baseline metrics (must include 'sharpe')

        Returns:
            List of result dicts: {"strategy", "suggestion", "kept"}
        """
        max_experiments = self._config.get("max_experiments_per_night", 10)
        results: list[dict] = []

        for i, strategy in enumerate(strategies[:max_experiments]):
            name = strategy.get("name", f"strategy_{i}")
            config = strategy.get("config", {})
            performance = strategy.get("performance", {})

            suggestion = await self.suggest_improvement(
                strategy_name=name,
                strategy_config=config,
                performance=performance,
            )

            # Placeholder: real backtest comparison comes in a later task.
            # For now kept=False so no strategy is silently auto-applied.
            kept = False

            action = DecisionAction.EXECUTED if kept else DecisionAction.SKIPPED
            reasoning_text = (
                f"Kept: {suggestion}" if kept else f"Suggested: {suggestion}"
            )

            await self._decision_logger.log_decision(
                account_name=self.account_name,
                symbol="STRATEGY_OPT",
                signal="OPTIMIZE",
                action=action,
                confidence=1.0,
                reasoning=reasoning_text,
                market_state={"experiment": i, "strategy": name},
            )

            results.append({"strategy": name, "suggestion": suggestion, "kept": kept})

        return results

    # ------------------------------------------------------------------
    # Decision helpers
    # ------------------------------------------------------------------

    def _should_keep(self, baseline: dict, modified: dict) -> bool:
        """Return True if modified Sharpe ratio is strictly better than baseline."""
        return modified.get("sharpe", 0) > baseline.get("sharpe", 0)

    # ------------------------------------------------------------------
    # Prompt construction
    # ------------------------------------------------------------------

    def _build_suggestion_prompt(
        self,
        strategy_name: str,
        strategy_config: dict,
        performance: dict,
        memory_context: list[dict],
    ) -> str:
        """Build a structured prompt for the deep-tier LLM."""
        sections: list[str] = []

        sections.append(f"## Strategy\n{strategy_name}")
        sections.append(
            "## Current Config\n" + json.dumps(strategy_config, indent=2)
        )
        sections.append(
            "## Performance\n" + json.dumps(performance, indent=2)
        )

        if memory_context:
            learnings = "\n".join(
                f"- {item.get('learning', json.dumps(item))}"
                for item in memory_context
            )
            sections.append(f"## Past Learnings\n{learnings}")
        else:
            sections.append("## Past Learnings\nNone available.")

        sections.append(
            "Suggest ONE parameter change. "
            "Respond with a single JSON object containing:\n"
            "  parameter_name      : string\n"
            "  current_value       : current value\n"
            "  suggested_value     : new value to test\n"
            "  reasoning           : string (why this change)\n"
            "  expected_improvement: string (what metric improves and by how much)\n"
            "Return ONLY the JSON object — no extra text."
        )

        return "\n\n".join(sections)

    # ------------------------------------------------------------------
    # Response parsing
    # ------------------------------------------------------------------

    def _parse(self, raw: str) -> dict:
        """Parse suggestion JSON from an LLM response.

        Strips markdown code fences before decoding. Returns a fallback dict
        on any parse error so the optimization loop is never interrupted.
        """
        try:
            text = raw.strip()

            fence_match = re.search(r"```(?:json)?\s*([\s\S]*?)```", text)
            if fence_match:
                text = fence_match.group(1).strip()

            return json.loads(text)

        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "StrategistAgent._parse failed: %s — using fallback", exc
            )
            return dict(_SUGGESTION_FALLBACK)
