"""
AI agents API router.
"""
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import Optional, Dict, Any, TYPE_CHECKING

from app.agents.service import AgentService

if TYPE_CHECKING:
    from app.agents.pod import AgentPod

_pods: Dict[str, "AgentPod"] = {}


def set_pods(pods: Dict[str, "AgentPod"]):
    global _pods
    _pods = pods


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


@router.get("/pods")
async def get_pods_status():
    return {name: pod.get_status() for name, pod in _pods.items()}


@router.get("/pods/{account_name}")
async def get_pod_status(account_name: str):
    if account_name not in _pods:
        raise HTTPException(status_code=404, detail=f"Pod '{account_name}' not found")
    return _pods[account_name].get_status()


@router.post("/pods/{account_name}/start")
async def start_pod(account_name: str):
    if account_name not in _pods:
        raise HTTPException(status_code=404, detail=f"Pod '{account_name}' not found")
    pod = _pods[account_name]
    await pod.start()
    await pod.start_eval_loop()
    return {"status": "started", "account": account_name}


@router.post("/pods/{account_name}/stop")
async def stop_pod(account_name: str):
    if account_name not in _pods:
        raise HTTPException(status_code=404, detail=f"Pod '{account_name}' not found")
    await _pods[account_name].stop()
    return {"status": "stopped", "account": account_name}


@router.post("/pods/{account_name}/cycle")
async def run_single_cycle(account_name: str):
    if account_name not in _pods:
        raise HTTPException(status_code=404, detail=f"Pod '{account_name}' not found")
    await _pods[account_name].run_cycle()
    return {"status": "cycle_complete", "account": account_name}

