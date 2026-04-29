"""
OHLC generation from tick data.
"""
import json
import logging
from typing import List, Dict, Any
from datetime import datetime, timedelta
from collections import defaultdict

from app.data.redis_client import get_redis

logger = logging.getLogger(__name__)


class OHLCGenerator:
    """Generate OHLC candles from tick data."""
    
    def __init__(self, interval: str = "1min"):
        """
        Initialize OHLC generator.
        
        Args:
            interval: Time interval (1min, 5min, 15min, 1hour)
        """
        self.interval = interval
        self.interval_seconds = self._parse_interval(interval)
    
    def _parse_interval(self, interval: str) -> int:
        """Parse interval string to seconds."""
        if interval == "1min":
            return 60
        elif interval == "5min":
            return 300
        elif interval == "15min":
            return 900
        elif interval == "1hour":
            return 3600
        else:
            raise ValueError(f"Unsupported interval: {interval}")
    
    async def generate_from_ticks(
        self,
        instrument_token: int,
        start_time: datetime,
        end_time: datetime
    ) -> List[Dict[str, Any]]:
        """Generate OHLC candles from stored ticks."""
        try:
            redis = get_redis()
            stream_key = f"tick_stream:{instrument_token}"
            
            # Get ticks from Redis
            ticks_data = await redis.lrange(stream_key, 0, -1)
            ticks = [json.loads(t) for t in ticks_data]
            
            if not ticks:
                return []
            
            # Filter ticks by time range
            filtered_ticks = [
                t for t in ticks
                if start_time <= datetime.fromisoformat(t.get("timestamp", "")) <= end_time
            ]
            
            if not filtered_ticks:
                return []
            
            # Group ticks by interval
            candles = self._group_ticks_to_candles(filtered_ticks)
            
            return candles
            
        except Exception as e:
            logger.error(f"Failed to generate OHLC: {e}", exc_info=True)
            return []
    
    def _group_ticks_to_candles(self, ticks: List[Dict]) -> List[Dict[str, Any]]:
        """Group ticks into OHLC candles."""
        if not ticks:
            return []
        
        # Sort ticks by timestamp
        ticks.sort(key=lambda x: x.get("timestamp", ""))
        
        candles = []
        current_candle = None
        current_candle_start = None
        
        for tick in ticks:
            tick_time = datetime.fromisoformat(tick.get("timestamp", ""))
            last_price = tick.get("last_price", 0)
            
            # Determine candle start time (rounded to interval)
            candle_start = self._round_to_interval(tick_time)
            
            # New candle needed
            if current_candle is None or candle_start != current_candle_start:
                # Save previous candle
                if current_candle:
                    candles.append(current_candle)
                
                # Start new candle
                current_candle = {
                    "timestamp": candle_start.isoformat(),
                    "open": last_price,
                    "high": last_price,
                    "low": last_price,
                    "close": last_price,
                    "volume": 0
                }
                current_candle_start = candle_start
            
            # Update current candle
            current_candle["high"] = max(current_candle["high"], last_price)
            current_candle["low"] = min(current_candle["low"], last_price)
            current_candle["close"] = last_price
            current_candle["volume"] += tick.get("volume", 0)
        
        # Add last candle
        if current_candle:
            candles.append(current_candle)
        
        return candles
    
    def _round_to_interval(self, dt: datetime) -> datetime:
        """Round datetime to interval boundary."""
        if self.interval_seconds == 60:
            # Round to minute
            return dt.replace(second=0, microsecond=0)
        elif self.interval_seconds == 300:
            # Round to 5 minutes
            minute = (dt.minute // 5) * 5
            return dt.replace(minute=minute, second=0, microsecond=0)
        elif self.interval_seconds == 900:
            # Round to 15 minutes
            minute = (dt.minute // 15) * 15
            return dt.replace(minute=minute, second=0, microsecond=0)
        elif self.interval_seconds == 3600:
            # Round to hour
            return dt.replace(minute=0, second=0, microsecond=0)
        else:
            return dt

