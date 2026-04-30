"""AnalystAgent — reads market data + memory, emits BUY/SELL/HOLD signals via LLM.

Builds a structured prompt from the current market state, past memory
learnings, and recent decisions, then calls the quick-tier LLM to produce
a JSON signal. Handles markdown-wrapped JSON (```json blocks) and falls
back to a safe HOLD/0.0 default on any parse failure so the eval cycle
never crashes on a malformed LLM response.
"""

from __future__ import annotations

import json
import logging
import re
import time
from typing import Any

from app.agents.base import AgentContext, AgentOutput, BaseAgent

logger = logging.getLogger(__name__)

_VALID_SIGNALS = {"BUY", "SELL", "HOLD", "EXIT"}

_SAFE_DEFAULT: dict[str, Any] = {
    "signal": "HOLD",
    "confidence": 0.0,
    "reasoning": "parse_failure",
    "entry_price": None,
    "stoploss": None,
    "target": None,
}


class AnalystAgent(BaseAgent):
    """LLM-backed analyst that emits directional trading signals.

    Uses the quick tier for low-latency signal generation. The structured
    JSON response is validated and parsed; any failure produces a safe HOLD
    so downstream agents are never given garbage data.
    """

    def __init__(
        self,
        llm_router: Any,
        prompts_dir: str,
        account_name: str,
    ) -> None:
        super().__init__(
            name="analyst",
            role="market_analyst",
            llm_tier="quick",
            account_name=account_name,
            llm_router=llm_router,
            prompts_dir=prompts_dir,
        )

    # ------------------------------------------------------------------
    # Core interface
    # ------------------------------------------------------------------

    async def run(self, context: AgentContext) -> AgentOutput:
        """Analyse market state and emit a BUY/SELL/HOLD signal.

        Steps:
        1. Build a structured prompt from market_state, memory_recall, and
           recent_decisions.
        2. Call the quick-tier LLM via ``think()``.
        3. Parse the JSON response, stripping markdown code fences if present.
        4. Validate the signal value; default to HOLD on any error.
        5. Return an AgentOutput with action="SIGNAL".
        """
        start = time.perf_counter()

        prompt = self._build_prompt(context)
        raw_response = await self.think(prompt, tier="quick")
        parsed = self._parse_response(raw_response)

        return self._timed_output(
            start,
            agent_name=self.name,
            action="SIGNAL",
            data=parsed,
            reasoning=parsed.get("reasoning", ""),
            confidence=parsed.get("confidence", 0.0),
            llm_tier_used=self.llm_tier,
        )

    # ------------------------------------------------------------------
    # Prompt construction
    # ------------------------------------------------------------------

    def _build_prompt(self, context: AgentContext) -> str:
        """Build the analyst prompt from context sections."""
        sections: list[str] = []

        sections.append(f"## Symbol\n{context.symbol}")

        sections.append(
            "## Market State\n" + json.dumps(context.market_state, indent=2)
        )

        if context.memory_recall:
            learnings = "\n".join(
                f"- {item.get('learning', json.dumps(item))}"
                for item in context.memory_recall
            )
            sections.append(f"## Past Learnings\n{learnings}")
        else:
            sections.append("## Past Learnings\nNone available.")

        if context.recent_decisions:
            decisions = "\n".join(
                f"- {json.dumps(d)}" for d in context.recent_decisions
            )
            sections.append(f"## Recent Decisions\n{decisions}")
        else:
            sections.append("## Recent Decisions\nNone.")

        sections.append(
            "## Task\n"
            "Analyse the market state and learnings above. "
            "Respond with a single JSON object containing these fields:\n"
            "  signal       : 'BUY' | 'SELL' | 'HOLD' | 'EXIT'\n"
            "  confidence   : float 0.0–1.0\n"
            "  reasoning    : string (concise explanation)\n"
            "  entry_price  : float or null\n"
            "  stoploss     : float or null\n"
            "  target       : float or null\n"
            "Return ONLY the JSON object — no extra text."
        )

        return "\n\n".join(sections)

    # ------------------------------------------------------------------
    # Response parsing
    # ------------------------------------------------------------------

    def _parse_response(self, raw: str) -> dict[str, Any]:
        """Parse the LLM response into a signal dict.

        Strips markdown code fences (```json ... ``` or ``` ... ```) before
        attempting JSON parse. Validates the signal value and falls back to
        the safe HOLD default on any error.
        """
        try:
            text = raw.strip()

            # Strip markdown code fences if present
            fence_match = re.search(r"```(?:json)?\s*([\s\S]*?)```", text)
            if fence_match:
                text = fence_match.group(1).strip()

            parsed = json.loads(text)

            # Validate signal
            signal = str(parsed.get("signal", "HOLD")).upper()
            if signal not in _VALID_SIGNALS:
                logger.warning(
                    "AnalystAgent received unknown signal '%s', defaulting to HOLD",
                    signal,
                )
                signal = "HOLD"
            parsed["signal"] = signal

            # Ensure confidence is a float
            parsed["confidence"] = float(parsed.get("confidence", 0.0))

            return parsed

        except Exception as exc:
            logger.warning(
                "AnalystAgent failed to parse LLM response: %s — using safe default",
                exc,
            )
            return dict(_SAFE_DEFAULT)
