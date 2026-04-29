"""
AI agents API router.
"""
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import Optional, Dict, Any

from app.agents.service import AgentService

router = APIRouter()


class MarketAnalysisRequest(BaseModel):
    """Market analysis request model."""
    instrument_token: Optional[int] = None
    tradingsymbol: Optional[str] = None
    days: int = 7


class StrategyCriticRequest(BaseModel):
    """Strategy critic request model."""
    strategy_code: str
    strategy_config: Dict[str, Any]


class TradeExplanationRequest(BaseModel):
    """Trade explanation request model."""
    trade_id: int
    context: Optional[Dict[str, Any]] = None


@router.post("/market-analysis")
async def get_market_analysis(request: MarketAnalysisRequest):
    """Get market analysis from AI agent."""
    service = AgentService()
    try:
        analysis = await service.analyze_market(
            instrument_token=request.instrument_token,
            tradingsymbol=request.tradingsymbol,
            days=request.days
        )
        return analysis
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/strategy-critic")
async def critique_strategy(request: StrategyCriticRequest):
    """Get strategy critique from AI agent."""
    service = AgentService()
    try:
        critique = await service.critique_strategy(
            strategy_code=request.strategy_code,
            strategy_config=request.strategy_config
        )
        return critique
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/trade-explanation")
async def explain_trade(request: TradeExplanationRequest):
    """Get trade explanation from AI agent."""
    service = AgentService()
    try:
        explanation = await service.explain_trade(
            trade_id=request.trade_id,
            context=request.context
        )
        return explanation
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

