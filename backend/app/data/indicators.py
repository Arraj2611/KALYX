"""
Technical indicators calculation.
"""
import pandas as pd
import numpy as np
from typing import Dict, Any, List


def calculate_sma(data: pd.Series, period: int) -> pd.Series:
    """Calculate Simple Moving Average."""
    return data.rolling(window=period).mean()


def calculate_ema(data: pd.Series, period: int) -> pd.Series:
    """Calculate Exponential Moving Average."""
    return data.ewm(span=period, adjust=False).mean()


def calculate_rsi(data: pd.Series, period: int = 14) -> pd.Series:
    """Calculate Relative Strength Index."""
    delta = data.diff()
    gain = (delta.where(delta > 0, 0)).rolling(window=period).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(window=period).mean()
    rs = gain / loss
    rsi = 100 - (100 / (1 + rs))
    return rsi


def calculate_macd(data: pd.Series, fast: int = 12, slow: int = 26, signal: int = 9) -> Dict[str, pd.Series]:
    """Calculate MACD."""
    ema_fast = calculate_ema(data, fast)
    ema_slow = calculate_ema(data, slow)
    macd_line = ema_fast - ema_slow
    signal_line = calculate_ema(macd_line, signal)
    histogram = macd_line - signal_line
    
    return {
        "macd": macd_line,
        "signal": signal_line,
        "histogram": histogram
    }


def calculate_bollinger_bands(data: pd.Series, period: int = 20, std_dev: int = 2) -> Dict[str, pd.Series]:
    """Calculate Bollinger Bands."""
    sma = calculate_sma(data, period)
    std = data.rolling(window=period).std()
    upper = sma + (std * std_dev)
    lower = sma - (std * std_dev)
    
    return {
        "upper": upper,
        "middle": sma,
        "lower": lower
    }


def calculate_indicators(ohlcv_df: pd.DataFrame) -> Dict[str, Any]:
    """
    Calculate all technical indicators for a DataFrame.
    
    Args:
        ohlcv_df: DataFrame with columns: open, high, low, close, volume
        
    Returns:
        Dictionary of calculated indicators
    """
    close = ohlcv_df["close"]
    
    indicators = {
        "SMA_20": calculate_sma(close, 20).iloc[-1] if len(close) >= 20 else None,
        "SMA_50": calculate_sma(close, 50).iloc[-1] if len(close) >= 50 else None,
        "EMA_12": calculate_ema(close, 12).iloc[-1] if len(close) >= 12 else None,
        "EMA_26": calculate_ema(close, 26).iloc[-1] if len(close) >= 26 else None,
        "RSI": calculate_rsi(close, 14).iloc[-1] if len(close) >= 14 else None,
    }
    
    # MACD
    if len(close) >= 26:
        macd = calculate_macd(close)
        indicators["MACD"] = {
            "macd": macd["macd"].iloc[-1],
            "signal": macd["signal"].iloc[-1],
            "histogram": macd["histogram"].iloc[-1]
        }
    
    # Bollinger Bands
    if len(close) >= 20:
        bb = calculate_bollinger_bands(close)
        indicators["BB"] = {
            "upper": bb["upper"].iloc[-1],
            "middle": bb["middle"].iloc[-1],
            "lower": bb["lower"].iloc[-1]
        }
    
    return indicators

