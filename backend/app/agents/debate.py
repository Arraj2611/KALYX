"""DebateAgent (bull/bear) and JudgeAgent — LLM Council debate system.

DebateAgent uses named models per side (LLM Council pattern) so each
advocate genuinely runs a distinct Ollama model if registered. Falls
back to the standard quick-tier when the named model is not registered.

JudgeAgent shuffles and anonymises the two arguments (random A/B order)
before asking the deep-tier LLM to adjudicate. Anonymisation prevents
the judge from being biased by knowing which side is which.
"""

from __future__ import annotations

import json
import logging
import random
import re
import time
from typing import Any

from app.agents.base import AgentContext, AgentOutput, BaseAgent

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------


def _strip_fences(text: str) -> str:
    """Remove markdown ```json ... ``` or ``` ... ``` code fences."""
    fence_match = re.search(r"```(?:json)?\s*([\s\S]*?)```", text)
    if fence_match:
        return fence_match.group(1).strip()
    return text.strip()


# ---------------------------------------------------------------------------
# DebateAgent
# ---------------------------------------------------------------------------


class DebateAgent(BaseAgent):
    """Argues one side of a trade debate.

    ``side`` must be ``"bullish"`` or ``"bearish"``. The agent attempts to use
    a named Ollama model registered as ``side`` via
    :meth:`~app.agents.llm_router.LLMRouter.register_model`. If the named model
    is not registered it falls back to the quick tier via :meth:`~BaseAgent.think`.

    Returns an :class:`~app.agents.base.AgentOutput` with
    ``action="ARGUE"`` and ``data`` containing at minimum an ``"argument"`` key.
    """

    def __init__(
        self,
        side: str,
        llm_router: Any,
        prompts_dir: str,
        account_name: str,
    ) -> None:
        self.side = side
        super().__init__(
            name=side,
            role=f"{side}_advocate",
            llm_tier="quick",
            account_name=account_name,
            llm_router=llm_router,
            prompts_dir=prompts_dir,
        )

    # ------------------------------------------------------------------
    # Core interface
    # ------------------------------------------------------------------

    async def run(self, context: AgentContext) -> AgentOutput:
        """Build a one-sided argument and return it as AgentOutput.

        Tries ``generate_with_model`` using the side name as the model alias.
        On :exc:`KeyError` (named model not registered) falls back to the
        standard :meth:`~BaseAgent.think` quick-tier call.
        """
        start = time.perf_counter()

        prompt = self._build_prompt(context)

        try:
            raw = await self.llm_router.generate_with_model(
                prompt,
                self.system_prompt,
                model_name=self.side,
            )
        except KeyError:
            logger.debug(
                "DebateAgent(%s): named model not registered, falling back to quick tier",
                self.side,
            )
            raw = await self.think(prompt, tier="quick")

        data = self._parse(raw)

        return self._timed_output(
            start,
            agent_name=self.name,
            action="ARGUE",
            data=data,
            reasoning=data.get("argument", ""),
            confidence=float(data.get("conviction", 0.5)),
            llm_tier_used="named_model",
        )

    # ------------------------------------------------------------------
    # Prompt construction
    # ------------------------------------------------------------------

    def _build_prompt(self, context: AgentContext) -> str:
        """Build a side-specific debate prompt from context."""
        direction = "FOR" if self.side == "bullish" else "AGAINST"
        signal = context.signals.get("signal", "?")
        confidence = context.signals.get("confidence", "?")
        original_reasoning = context.signals.get("reasoning", "No reasoning provided.")

        return (
            f"## Symbol: {context.symbol}\n"
            f"## Signal: {signal} (confidence: {confidence})\n"
            f"## Market State:\n{json.dumps(context.market_state, indent=2)}\n\n"
            f"## Original Reasoning:\n{original_reasoning}\n\n"
            f"Your job: argue {direction} taking this trade.\n"
            "Respond ONLY with the JSON format specified in your system prompt."
        )

    # ------------------------------------------------------------------
    # Response parsing
    # ------------------------------------------------------------------

    def _parse(self, raw: str) -> dict[str, Any]:
        """Parse JSON response, stripping fences. Returns safe default on failure."""
        try:
            return json.loads(_strip_fences(raw))
        except Exception as exc:
            logger.warning(
                "DebateAgent(%s) failed to parse LLM response: %s — using fallback",
                self.side,
                exc,
            )
            return {
                "argument": f"No valid argument produced by {self.side} advocate.",
                "conviction": 0.0,
            }


# ---------------------------------------------------------------------------
# JudgeAgent
# ---------------------------------------------------------------------------


class JudgeAgent(BaseAgent):
    """Adjudicates anonymised bull/bear arguments.

    Shuffles the two arguments into random A/B order before building the
    prompt so the LLM cannot be influenced by knowing which side is which.
    Uses the deep tier for thorough analysis.

    Returns an :class:`~app.agents.base.AgentOutput` with
    ``action="JUDGE"`` and ``data`` containing at minimum ``"proceed"`` and
    ``"adjusted_confidence"`` keys.
    """

    def __init__(
        self,
        llm_router: Any,
        prompts_dir: str,
        account_name: str,
    ) -> None:
        super().__init__(
            name="judge",
            role="impartial_judge",
            llm_tier="deep",
            account_name=account_name,
            llm_router=llm_router,
            prompts_dir=prompts_dir,
        )

    # ------------------------------------------------------------------
    # Core interface
    # ------------------------------------------------------------------

    async def run(self, context: AgentContext) -> AgentOutput:
        """Evaluate debate arguments and return a proceed/reject verdict.

        If no ``debate_result`` is present on ``context`` (e.g. debate was
        skipped) a permissive pass-through is returned with the original
        signal confidence.
        """
        start = time.perf_counter()

        if not context.debate_result:
            default_confidence = float(context.signals.get("confidence", 0.5))
            return self._timed_output(
                start,
                agent_name=self.name,
                action="JUDGE",
                data={
                    "proceed": True,
                    "adjusted_confidence": default_confidence,
                    "reasoning": "No debate — passing through original signal.",
                    "stronger_argument": None,
                },
                reasoning="No debate — passing through original signal.",
                confidence=default_confidence,
                llm_tier_used="deep",
            )

        bull = context.debate_result.get("bullish", {})
        bear = context.debate_result.get("bearish", {})

        prompt = self._anonymize_and_build_prompt(bull, bear, context)
        raw = await self.think(prompt, tier="deep")
        data = self._parse(raw)

        return self._timed_output(
            start,
            agent_name=self.name,
            action="JUDGE",
            data=data,
            reasoning=data.get("reasoning", ""),
            confidence=float(data.get("adjusted_confidence", 0.5)),
            llm_tier_used="deep",
        )

    # ------------------------------------------------------------------
    # Anonymisation
    # ------------------------------------------------------------------

    def _anonymize_and_build_prompt(
        self,
        bull: dict,
        bear: dict,
        context: AgentContext,
    ) -> str:
        """Shuffle and label arguments as A/B, then build the judge prompt.

        When ``config.debate.anonymize`` is True (default) the order is
        randomised so the judge cannot infer which is bullish/bearish from
        position alone.
        """
        bull_text = bull.get("argument", str(bull))
        bear_text = bear.get("argument", str(bear))

        args = [("A", bull_text), ("B", bear_text)]

        if context.config.get("debate", {}).get("anonymize", True):
            random.shuffle(args)

        signal = context.signals.get("signal", "?")
        confidence = context.signals.get("confidence", "?")

        return (
            f"## Symbol: {context.symbol}\n"
            f"## Original Signal: {signal} (confidence: {confidence})\n\n"
            f"## Argument {args[0][0]}:\n{args[0][1]}\n\n"
            f"## Argument {args[1][0]}:\n{args[1][1]}\n\n"
            "Evaluate both arguments and decide.\n"
            "Respond ONLY with the JSON format specified in your system prompt."
        )

    # ------------------------------------------------------------------
    # Response parsing
    # ------------------------------------------------------------------

    def _parse(self, raw: str) -> dict[str, Any]:
        """Parse JSON response, stripping fences. Returns safe default on failure."""
        try:
            return json.loads(_strip_fences(raw))
        except Exception as exc:
            logger.warning(
                "JudgeAgent failed to parse LLM response: %s — using safe default",
                exc,
            )
            return {
                "proceed": False,
                "adjusted_confidence": 0.0,
                "reasoning": "parse_failure",
                "stronger_argument": None,
            }
