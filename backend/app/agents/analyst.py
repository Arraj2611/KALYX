"""AnalystAgent — reads market data + memory + intelligence, emits signals."""
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
    """LLM-backed analyst. Optionally enriched via IntelligenceContextBuilder."""

    def __init__(
        self,
        llm_router: Any,
        prompts_dir: str,
        account_name: str,
        intelligence_builder: Any | None = None,
    ) -> None:
        self._intelligence_builder = intelligence_builder
        super().__init__(
            name="analyst",
            role="market_analyst",
            llm_tier="quick",
            account_name=account_name,
            llm_router=llm_router,
            prompts_dir=prompts_dir,
        )

    async def run(self, context: AgentContext) -> AgentOutput:
        start = time.perf_counter()

        intel = await self._build_intelligence(context)
        prompt = self._build_prompt(context, intel)
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

    async def _build_intelligence(self, context: AgentContext) -> Any | None:
        if self._intelligence_builder is None:
            return None
        try:
            return await self._intelligence_builder.build(
                symbol=context.symbol,
                account_name=context.account_name,
            )
        except Exception as exc:
            logger.warning(f"Intelligence build failed: {exc}")
            return None

    def _build_prompt(self, context: AgentContext, intel: Any | None) -> str:
        sections: list[str] = []

        sections.append(f"## Symbol\n{context.symbol}")
        sections.append("## Market State\n" + json.dumps(context.market_state, indent=2))

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

        # Intelligence enrichment
        if intel is not None:
            cards = getattr(intel, "convergence_cards", []) or []
            if cards:
                lines = [
                    f"- [{c.score:.0f}] {c.title} ({c.trend})"
                    for c in cards[:5]
                ]
                sections.append("## Convergence Signals\n" + "\n".join(lines))

            odds = getattr(intel, "polymarket_odds", {}) or {}
            if odds:
                lines = [f"- {k}: {v:.0%}" for k, v in list(odds.items())[:10]]
                sections.append("## Polymarket Odds\n" + "\n".join(lines))

            polarity = getattr(intel, "aggregated_sentiment", 0.0) or 0.0
            sections.append(f"## News Sentiment\nAggregated polarity: {polarity:+.2f}")

            score = getattr(intel, "composite_score", None)
            if score is not None:
                sections.append(
                    f"## Signal Quality\nTier: {score.tier} (composite {score.composite:.2f})"
                )

        sections.append(
            "## Task\n"
            "Analyse the market state, intelligence signals, and learnings above. "
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

    def _parse_response(self, raw: str) -> dict[str, Any]:
        try:
            text = raw.strip()
            fence_match = re.search(r"```(?:json)?\s*([\s\S]*?)```", text)
            if fence_match:
                text = fence_match.group(1).strip()

            parsed = json.loads(text)

            signal = str(parsed.get("signal", "HOLD")).upper()
            if signal not in _VALID_SIGNALS:
                logger.warning(
                    "AnalystAgent received unknown signal '%s', defaulting to HOLD",
                    signal,
                )
                signal = "HOLD"
            parsed["signal"] = signal
            parsed["confidence"] = float(parsed.get("confidence", 0.0))
            return parsed

        except Exception as exc:
            logger.warning(
                "AnalystAgent failed to parse LLM response: %s — using safe default",
                exc,
            )
            return dict(_SAFE_DEFAULT)
