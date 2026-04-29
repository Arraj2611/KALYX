"""
Base strategy interface and abstract class.
"""
from abc import ABC, abstractmethod
from typing import Dict, Any, Optional, Tuple
from enum import Enum


class Signal(Enum):
    """Trading signal types."""
    BUY = "BUY"
    SELL = "SELL"
    EXIT = "EXIT"
    HOLD = "HOLD"


class StrategyInput:
    """Input data for strategy execution."""
    
    def __init__(
        self,
        live_tick: Dict[str, Any],
        indicators: Dict[str, Any],
        positions: list,
        cash: float,
        margin_available: float
    ):
        self.live_tick = live_tick
        self.indicators = indicators
        self.positions = positions
        self.cash = cash
        self.margin_available = margin_available


class StrategyOutput:
    """Output from strategy execution."""
    
    def __init__(
        self,
        signal: Signal,
        target: Optional[float] = None,
        stoploss: Optional[float] = None,
        quantity: Optional[int] = None,
        reason: Optional[str] = None
    ):
        self.signal = signal
        self.target = target
        self.stoploss = stoploss
        self.quantity = quantity
        self.reason = reason


class BaseStrategy(ABC):
    """Base class for all trading strategies."""
    
    def __init__(self, config: Dict[str, Any]):
        """
        Initialize strategy with configuration.
        
        Args:
            config: Strategy-specific configuration dictionary
        """
        self.config = config
        self.name = config.get("name", self.__class__.__name__)
        self.is_active = False
    
    @abstractmethod
    def execute(self, input_data: StrategyInput) -> StrategyOutput:
        """
        Execute strategy logic.
        
        Args:
            input_data: StrategyInput containing market data, indicators, positions, etc.
            
        Returns:
            StrategyOutput with signal, target, stoploss, quantity
        """
        pass
    
    @abstractmethod
    def get_required_indicators(self) -> list[str]:
        """
        Get list of required technical indicators.
        
        Returns:
            List of indicator names (e.g., ["SMA_20", "RSI", "MACD"])
        """
        pass
    
    def validate_config(self) -> bool:
        """
        Validate strategy configuration.
        
        Returns:
            True if config is valid, raises ValueError otherwise
        """
        return True
    
    def on_activate(self):
        """Called when strategy is activated."""
        self.is_active = True
    
    def on_deactivate(self):
        """Called when strategy is deactivated."""
        self.is_active = False

