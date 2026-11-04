"""
BaseAgent ABC, AgentContext, and AgentOutput.

Foundation for the KALYX agent framework. Every agent in the eval cycle
(analyst, risk guardian, debater, executor) subclasses BaseAgent and
receives shared state via AgentContext, then returns an AgentOutput.
"""

from __future__ import annotations

import abc
import time
from datetime import datetime
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

from app.brokers.base import MarginInfo, Position


# ---------------------------------------------------------------------------
# AgentContext — shared state passed to every agent in the eval cycle
# ---------------------------------------------------------------------------


@dataclass
class AgentContext:
    """All state an agent needs to produce a decision.

    Constructed once per eval cycle and passed immutably to each agent.
    Carries market data, portfolio state, prior decisions, memory retrievals,
    upstream signals, and any results already produced earlier in the cycle.
    """

    account_name: str
    symbol: str
    market_state: dict
    positions: list[Position]
    margins: MarginInfo
    recent_decisions: list[dict]
    memory_recall: list[dict]
    signals: dict
    debate_result: dict | None
    guardian_verdict: dict | None
    config: dict
    halted: bool = False  # kill switch on: no new positions
    now: datetime | None = None  # the pod's clock; None means the real time


# ---------------------------------------------------------------------------
# AgentOutput — what every agent returns
# ---------------------------------------------------------------------------


@dataclass
class AgentOutput:
    """Structured output from a single agent invocation.

    Captures not just the action but the full decision trail — reasoning,
    confidence, which LLM tier was used, and how long it took.
    All fields feed directly into the learning system's decision log.
    """

    agent_name: str
    action: str
    data: dict
    reasoning: str
    confidence: float
    llm_tier_used: str | None = None
    latency_ms: float = 0.0


# ---------------------------------------------------------------------------
# BaseAgent — abstract base class all KALYX agents must subclass
# ---------------------------------------------------------------------------


class BaseAgent(abc.ABC):
    """Abstract base for all KALYX agents.

    Handles prompt loading (with account-specific overrides), LLM routing,
    and latency measurement. Subclasses only need to implement ``run()``.

    Prompt resolution order (first found wins):
      1. ``{prompts_dir}/{account_name}/{name}.md``
      2. ``{prompts_dir}/defaults/{name}.md``
      3. Inline fallback string (agent can still run, just without a tuned prompt)
    """

    def __init__(
        self,
        name: str,
        role: str,
        llm_tier: str,
        account_name: str,
        llm_router: Any,
        prompts_dir: str,
    ) -> None:
        self.name = name
        self.role = role
        self.llm_tier = llm_tier
        self.account_name = account_name
        self.llm_router = llm_router
        self.prompts_dir = prompts_dir
        self.system_prompt: str = self._load_prompt()

    # ------------------------------------------------------------------
    # Abstract interface
    # ------------------------------------------------------------------

    @abc.abstractmethod
    def run(self, context: AgentContext) -> AgentOutput:
        """Execute the agent's reasoning cycle and return a decision."""

    # ------------------------------------------------------------------
    # LLM interaction
    # ------------------------------------------------------------------

    async def think(self, prompt: str, tier: Optional[str] = None) -> str:
        """Send a prompt to the LLM router and return the response text.

        Uses the agent's default tier unless overridden.
        """
        chosen_tier = tier or self.llm_tier
        return await self.llm_router.generate(
            prompt=prompt,
            system_prompt=self.system_prompt,
            tier=chosen_tier,
        )

    # ------------------------------------------------------------------
    # Prompt management
    # ------------------------------------------------------------------

    def _load_prompt(self) -> str:
        """Load system prompt from disk with account-specific override support.

        Returns a fallback string if no prompt file is found so the agent
        can still operate (degraded, but not crashed).
        """
        base = Path(self.prompts_dir)

        # 1. Account-specific override
        account_path = base / self.account_name / f"{self.name}.md"
        if account_path.exists():
            return account_path.read_text(encoding="utf-8")

        # 2. Shared defaults
        default_path = base / "defaults" / f"{self.name}.md"
        if default_path.exists():
            return default_path.read_text(encoding="utf-8")

        # 3. Inline fallback
        return (
            f"You are the {self.name} agent with role: {self.role}. "
            "No prompt file was found — operate with caution."
        )

    def reload_prompt(self) -> None:
        """Re-read the prompt file from disk (picks up live edits)."""
        self.system_prompt = self._load_prompt()

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _timed_output(self, start: float, **kwargs: Any) -> AgentOutput:
        """Build an AgentOutput and inject the elapsed latency in ms.

        Args:
            start: ``time.perf_counter()`` value captured before the LLM call.
            **kwargs: All other AgentOutput fields.
        """
        latency_ms = (time.perf_counter() - start) * 1000.0
        return AgentOutput(
            latency_ms=latency_ms,
            **kwargs,
        )
