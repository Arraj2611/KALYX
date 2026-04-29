"""
Built-in trading strategies.
"""
from typing import Dict, Any
from app.strategies.base import BaseStrategy, StrategyInput, StrategyOutput, Signal


class MeanReversionStrategy(BaseStrategy):
    """Simple mean reversion strategy."""
    
    def get_required_indicators(self) -> list[str]:
        return ["SMA_20", "RSI"]
    
    def execute(self, input_data: StrategyInput) -> StrategyOutput:
        """Execute mean reversion logic."""
        tick = input_data.live_tick
        indicators = input_data.indicators
        
        current_price = tick.get("last_price", 0)
        sma_20 = indicators.get("SMA_20", current_price)
        rsi = indicators.get("RSI", 50)
        
        # Mean reversion: buy when price is below SMA and RSI is oversold
        if current_price < sma_20 * 0.98 and rsi < 30:
            return StrategyOutput(
                signal=Signal.BUY,
                target=sma_20,
                stoploss=current_price * 0.95,
                quantity=self.config.get("quantity", 1),
                reason="Price below SMA, RSI oversold"
            )
        
        # Sell when price is above SMA and RSI is overbought
        if current_price > sma_20 * 1.02 and rsi > 70:
            return StrategyOutput(
                signal=Signal.SELL,
                target=sma_20,
                stoploss=current_price * 1.05,
                quantity=self.config.get("quantity", 1),
                reason="Price above SMA, RSI overbought"
            )
        
        return StrategyOutput(signal=Signal.HOLD)


class MomentumStrategy(BaseStrategy):
    """Simple momentum strategy."""
    
    def get_required_indicators(self) -> list[str]:
        return ["SMA_20", "SMA_50", "MACD"]
    
    def execute(self, input_data: StrategyInput) -> StrategyOutput:
        """Execute momentum logic."""
        tick = input_data.live_tick
        indicators = input_data.indicators
        
        current_price = tick.get("last_price", 0)
        sma_20 = indicators.get("SMA_20", current_price)
        sma_50 = indicators.get("SMA_50", current_price)
        macd = indicators.get("MACD", {})
        macd_line = macd.get("macd", 0)
        signal_line = macd.get("signal", 0)
        
        # Momentum: buy when SMA20 > SMA50 and MACD crosses above signal
        if sma_20 > sma_50 and macd_line > signal_line:
            return StrategyOutput(
                signal=Signal.BUY,
                target=current_price * 1.05,
                stoploss=current_price * 0.97,
                quantity=self.config.get("quantity", 1),
                reason="Uptrend with MACD bullish crossover"
            )
        
        # Sell when SMA20 < SMA50 and MACD crosses below signal
        if sma_20 < sma_50 and macd_line < signal_line:
            return StrategyOutput(
                signal=Signal.SELL,
                target=current_price * 0.95,
                stoploss=current_price * 1.03,
                quantity=self.config.get("quantity", 1),
                reason="Downtrend with MACD bearish crossover"
            )
        
        return StrategyOutput(signal=Signal.HOLD)

