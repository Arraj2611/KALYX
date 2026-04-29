"""
Zerodha WebSocket client for live market data.
"""
import logging
import asyncio
import json
from typing import Callable, Optional, Dict, Any
from kiteconnect import KiteTicker

from app.auth.service import AuthService
from app.data.redis_client import get_redis

logger = logging.getLogger(__name__)


class ZerodhaWebSocketClient:
    """WebSocket client for Zerodha live ticks."""
    
    def __init__(self):
        self.auth_service = AuthService()
        self.kws: Optional[KiteTicker] = None
        self.is_connected = False
        self.subscribed_instruments: set = set()
        self.callbacks: Dict[str, Callable] = {}
    
    async def connect(self):
        """Connect to Zerodha WebSocket."""
        try:
            kite = self.auth_service.get_kite_client()
            if not kite:
                raise RuntimeError("Kite client not initialized. Please login first.")
            
            api_key = self.auth_service.api_key
            redis = get_redis()
            access_token_enc = await redis.get("zerodha:access_token")
            if not access_token_enc:
                raise RuntimeError("Access token not found. Please login first.")
            
            access_token = self.auth_service._decrypt_token(access_token_enc)
            
            # Initialize KiteTicker
            self.kws = KiteTicker(api_key, access_token)
            
            # Set callbacks
            self.kws.on_ticks = self._on_ticks
            self.kws.on_connect = self._on_connect
            self.kws.on_close = self._on_close
            self.kws.on_error = self._on_error
            self.kws.on_reconnect = self._on_reconnect
            
            # Connect
            self.kws.connect(threaded=True)
            self.is_connected = True
            logger.info("WebSocket connected to Zerodha")
            
        except Exception as e:
            logger.error(f"WebSocket connection failed: {e}", exc_info=True)
            raise
    
    def _on_ticks(self, ws, ticks):
        """Handle incoming ticks."""
        try:
            import asyncio
            redis = get_redis()
            
            for tick in ticks:
                instrument_token = tick.get("instrument_token")
                tradingsymbol = tick.get("tradingsymbol", "")
                
                # Cache tick in Redis (async)
                tick_key = f"tick:{instrument_token}"
                tick_data = {
                    "instrument_token": instrument_token,
                    "tradingsymbol": tradingsymbol,
                    "last_price": tick.get("last_price"),
                    "ohlc": tick.get("ohlc", {}),
                    "depth": tick.get("depth", {}),
                    "timestamp": tick.get("timestamp"),
                }
                # Use asyncio to run async Redis operations
                asyncio.create_task(redis.setex(tick_key, 60, json.dumps(tick_data)))
                
                # Store in tick stream for OHLC generation
                stream_key = f"tick_stream:{instrument_token}"
                asyncio.create_task(redis.lpush(stream_key, json.dumps(tick_data)))
                asyncio.create_task(redis.ltrim(stream_key, 0, 1000))
                asyncio.create_task(redis.expire(stream_key, 3600))
                
                # Call registered callbacks
                if "on_tick" in self.callbacks:
                    self.callbacks["on_tick"](tick)
            
        except Exception as e:
            logger.error(f"Error processing ticks: {e}", exc_info=True)
    
    def _on_connect(self, ws, response):
        """Handle WebSocket connect."""
        logger.info("WebSocket connected")
        self.is_connected = True
    
    def _on_close(self, ws, code, reason):
        """Handle WebSocket close."""
        logger.warning(f"WebSocket closed: {code} - {reason}")
        self.is_connected = False
    
    def _on_error(self, ws, code, reason):
        """Handle WebSocket error."""
        logger.error(f"WebSocket error: {code} - {reason}")
        self.is_connected = False
    
    def _on_reconnect(self, ws, attempts_count):
        """Handle WebSocket reconnect."""
        logger.info(f"WebSocket reconnecting... Attempt {attempts_count}")
        self.is_connected = True
    
    def subscribe(self, instrument_tokens: list):
        """Subscribe to instrument tokens."""
        if not self.kws or not self.is_connected:
            raise RuntimeError("WebSocket not connected")
        
        try:
            self.kws.subscribe(instrument_tokens)
            self.subscribed_instruments.update(instrument_tokens)
            logger.info(f"Subscribed to {len(instrument_tokens)} instruments")
        except Exception as e:
            logger.error(f"Subscription failed: {e}", exc_info=True)
            raise
    
    def unsubscribe(self, instrument_tokens: list):
        """Unsubscribe from instrument tokens."""
        if not self.kws or not self.is_connected:
            raise RuntimeError("WebSocket not connected")
        
        try:
            self.kws.unsubscribe(instrument_tokens)
            self.subscribed_instruments.difference_update(instrument_tokens)
            logger.info(f"Unsubscribed from {len(instrument_tokens)} instruments")
        except Exception as e:
            logger.error(f"Unsubscription failed: {e}", exc_info=True)
            raise
    
    def set_callback(self, event: str, callback: Callable):
        """Set callback for WebSocket events."""
        self.callbacks[event] = callback
    
    async def disconnect(self):
        """Disconnect WebSocket."""
        if self.kws:
            try:
                self.kws.close()
                self.is_connected = False
                logger.info("WebSocket disconnected")
            except Exception as e:
                logger.error(f"WebSocket disconnect error: {e}", exc_info=True)

