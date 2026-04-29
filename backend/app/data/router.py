"""
Data API router.
"""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from typing import List, Optional
from datetime import datetime

from app.data.database import get_db_session
from app.data import models

router = APIRouter()


@router.get("/market-data")
async def get_market_data(
    instrument_token: Optional[int] = None,
    tradingsymbol: Optional[str] = None,
    start_date: Optional[datetime] = None,
    end_date: Optional[datetime] = None,
    interval: Optional[str] = None,
    db: Session = Depends(get_db_session)
):
    """Get historical market data."""
    query = db.query(models.MarketData)
    
    if instrument_token:
        query = query.filter(models.MarketData.instrument_token == instrument_token)
    if tradingsymbol:
        query = query.filter(models.MarketData.tradingsymbol == tradingsymbol)
    if start_date:
        query = query.filter(models.MarketData.timestamp >= start_date)
    if end_date:
        query = query.filter(models.MarketData.timestamp <= end_date)
    if interval:
        query = query.filter(models.MarketData.interval == interval)
    
    data = query.order_by(models.MarketData.timestamp).all()
    return [{
        "timestamp": d.timestamp.isoformat(),
        "open": d.open,
        "high": d.high,
        "low": d.low,
        "close": d.close,
        "volume": d.volume,
        "interval": d.interval
    } for d in data]


@router.get("/logs")
async def get_logs(
    level: Optional[str] = None,
    limit: int = 100,
    db: Session = Depends(get_db_session)
):
    """Get system logs."""
    query = db.query(models.SystemLog)
    
    if level:
        query = query.filter(models.SystemLog.level == level.upper())
    
    logs = query.order_by(models.SystemLog.created_at.desc()).limit(limit).all()
    return [{
        "id": log.id,
        "level": log.level,
        "logger": log.logger,
        "message": log.message,
        "module": log.module,
        "function": log.function,
        "line": log.line,
        "extra": log.extra,
        "timestamp": log.created_at.isoformat()
    } for log in logs]

