"""
AI agents service for market analysis, strategy critique, and trade explanation.
"""
import logging
from typing import Dict, Any, Optional
import asyncio

from app.config import settings
from app.agents.llm_providers import LLMProvider, get_llm_provider

logger = logging.getLogger(__name__)


class AgentService:
    """Service for AI agents."""
    
    def __init__(self):
        self.llm_provider = get_llm_provider()
    
    async def analyze_market(
        self,
        instrument_token: Optional[int] = None,
        tradingsymbol: Optional[str] = None,
        days: int = 7
    ) -> Dict[str, Any]:
        """Get market analysis from AI agent."""
        try:
            prompt = self._build_market_analysis_prompt(
                instrument_token=instrument_token,
                tradingsymbol=tradingsymbol,
                days=days
            )
            
            response = await self.llm_provider.generate(prompt)
            
            return {
                "analysis": response,
                "instrument_token": instrument_token,
                "tradingsymbol": tradingsymbol,
                "days": days
            }
            
        except Exception as e:
            logger.error(f"Market analysis failed: {e}", exc_info=True)
            raise
    
    async def critique_strategy(
        self,
        strategy_code: str,
        strategy_config: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Get strategy critique from AI agent."""
        try:
            prompt = self._build_strategy_critic_prompt(
                strategy_code=strategy_code,
                strategy_config=strategy_config
            )
            
            response = await self.llm_provider.generate(prompt)
            
            return {
                "critique": response,
                "suggestions": self._extract_suggestions(response)
            }
            
        except Exception as e:
            logger.error(f"Strategy critique failed: {e}", exc_info=True)
            raise
    
    async def explain_trade(
        self,
        trade_id: int,
        context: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """Get trade explanation from AI agent."""
        try:
            prompt = self._build_trade_explanation_prompt(
                trade_id=trade_id,
                context=context or {}
            )
            
            response = await self.llm_provider.generate(prompt)
            
            return {
                "explanation": response,
                "trade_id": trade_id
            }
            
        except Exception as e:
            logger.error(f"Trade explanation failed: {e}", exc_info=True)
            raise
    
    def _build_market_analysis_prompt(
        self,
        instrument_token: Optional[int],
        tradingsymbol: Optional[str],
        days: int
    ) -> str:
        """Build prompt for market analysis."""
        return f"""You are a professional market analyst for index options trading.

Analyze the market conditions for:
- Instrument: {tradingsymbol or f'Token: {instrument_token}'}
- Time period: Last {days} days

Provide:
1. Overall market sentiment (bullish/bearish/neutral)
2. Key technical levels (support/resistance)
3. Volatility assessment
4. Trading opportunities
5. Risk factors

Format your response as a structured analysis."""

    def _build_strategy_critic_prompt(
        self,
        strategy_code: str,
        strategy_config: Dict[str, Any]
    ) -> str:
        """Build prompt for strategy critique."""
        return f"""You are an expert algorithmic trading strategy reviewer.

Review the following trading strategy:

Strategy Code:
{strategy_code}

Configuration:
{strategy_config}

Provide:
1. Strengths of the strategy
2. Weaknesses and potential issues
3. Risk assessment
4. Suggested improvements
5. Market conditions where this strategy would work best

Format your response as a detailed critique with actionable suggestions."""

    def _build_trade_explanation_prompt(
        self,
        trade_id: int,
        context: Dict[str, Any]
    ) -> str:
        """Build prompt for trade explanation."""
        return f"""You are explaining a trade execution to a trader.

Trade ID: {trade_id}
Context: {context}

Explain:
1. Why this trade was taken
2. The strategy logic behind it
3. Risk-reward rationale
4. Expected outcome

Format your response as a clear, natural language explanation."""

    def _extract_suggestions(self, critique: str) -> list[str]:
        """Extract actionable suggestions from critique."""
        # Simple extraction - in production, use more sophisticated parsing
        suggestions = []
        lines = critique.split("\n")
        for line in lines:
            if any(keyword in line.lower() for keyword in ["suggest", "improve", "consider", "recommend"]):
                suggestions.append(line.strip())
        return suggestions[:5]  # Return top 5 suggestions

