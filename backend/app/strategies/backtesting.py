"""
Backtesting engine for strategies.
"""
import logging
import pandas as pd
from typing import Dict, Any, List, Optional
from datetime import datetime, timedelta
from sqlalchemy.orm import Session

from app.strategies.base import BaseStrategy, StrategyInput, StrategyOutput, Signal
from app.data.indicators import calculate_indicators
from app.data import models

logger = logging.getLogger(__name__)


class BacktestEngine:
    """Engine for backtesting trading strategies."""
    
    def __init__(self, db: Session):
        self.db = db
    
    def run_backtest(
        self,
        strategy: BaseStrategy,
        ohlcv_data: pd.DataFrame,
        initial_capital: float = 100000.0,
        config: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """
        Run backtest on historical data.
        
        Args:
            strategy: Strategy instance to backtest
            ohlcv_data: DataFrame with columns: timestamp, open, high, low, close, volume
            initial_capital: Starting capital
            config: Additional backtest configuration
            
        Returns:
            Dictionary with backtest results
        """
        try:
            # Calculate indicators
            indicators_dict = {}
            required_indicators = strategy.get_required_indicators()
            
            # Calculate all indicators for the entire dataset
            for i in range(len(ohlcv_data)):
                window_data = ohlcv_data.iloc[:i+1]
                if len(window_data) > 0:
                    indicators = calculate_indicators(window_data)
                    indicators_dict[i] = indicators
            
            # Initialize backtest state
            capital = initial_capital
            positions = []
            trades = []
            equity_curve = [initial_capital]
            
            # Run strategy on each bar
            for i in range(len(ohlcv_data)):
                row = ohlcv_data.iloc[i]
                current_price = row["close"]
                
                # Prepare strategy input
                live_tick = {
                    "last_price": current_price,
                    "timestamp": row.get("timestamp", ""),
                    "volume": row.get("volume", 0)
                }
                
                indicators = indicators_dict.get(i, {})
                
                strategy_input = StrategyInput(
                    live_tick=live_tick,
                    indicators=indicators,
                    positions=positions.copy(),
                    cash=capital,
                    margin_available=capital * 0.8  # Assume 80% margin available
                )
                
                # Execute strategy
                output = strategy.execute(strategy_input)
                
                # Process signal
                if output.signal == Signal.BUY:
                    # Open long position
                    if output.quantity and output.quantity > 0:
                        position = {
                            "type": "LONG",
                            "entry_price": current_price,
                            "quantity": output.quantity,
                            "target": output.target,
                            "stoploss": output.stoploss,
                            "entry_time": row.get("timestamp", "")
                        }
                        positions.append(position)
                        capital -= current_price * output.quantity * 0.1  # Assume 10% margin
                
                elif output.signal == Signal.SELL:
                    # Open short position
                    if output.quantity and output.quantity > 0:
                        position = {
                            "type": "SHORT",
                            "entry_price": current_price,
                            "quantity": output.quantity,
                            "target": output.target,
                            "stoploss": output.stoploss,
                            "entry_time": row.get("timestamp", "")
                        }
                        positions.append(position)
                        capital -= current_price * output.quantity * 0.1
                
                elif output.signal == Signal.EXIT:
                    # Close all positions
                    for pos in positions:
                        pnl = self._calculate_pnl(pos, current_price)
                        trades.append({
                            "entry_price": pos["entry_price"],
                            "exit_price": current_price,
                            "quantity": pos["quantity"],
                            "pnl": pnl,
                            "entry_time": pos["entry_time"],
                            "exit_time": row.get("timestamp", "")
                        })
                        capital += pos["entry_price"] * pos["quantity"] * 0.1 + pnl
                    positions = []
                
                # Check stoploss and target for open positions
                positions_to_close = []
                for pos in positions:
                    pnl = self._calculate_pnl(pos, current_price)
                    
                    # Check stoploss
                    if pos["stoploss"]:
                        if pos["type"] == "LONG" and current_price <= pos["stoploss"]:
                            positions_to_close.append((pos, current_price, "STOPLOSS"))
                        elif pos["type"] == "SHORT" and current_price >= pos["stoploss"]:
                            positions_to_close.append((pos, current_price, "STOPLOSS"))
                    
                    # Check target
                    if pos["target"]:
                        if pos["type"] == "LONG" and current_price >= pos["target"]:
                            positions_to_close.append((pos, current_price, "TARGET"))
                        elif pos["type"] == "SHORT" and current_price <= pos["target"]:
                            positions_to_close.append((pos, current_price, "TARGET"))
                
                # Close positions
                for pos, exit_price, reason in positions_to_close:
                    pnl = self._calculate_pnl(pos, exit_price)
                    trades.append({
                        "entry_price": pos["entry_price"],
                        "exit_price": exit_price,
                        "quantity": pos["quantity"],
                        "pnl": pnl,
                        "entry_time": pos["entry_time"],
                        "exit_time": row.get("timestamp", ""),
                        "exit_reason": reason
                    })
                    capital += pos["entry_price"] * pos["quantity"] * 0.1 + pnl
                    positions.remove(pos)
                
                # Update equity curve
                current_equity = capital
                for pos in positions:
                    unrealized_pnl = self._calculate_pnl(pos, current_price)
                    current_equity += unrealized_pnl
                equity_curve.append(current_equity)
            
            # Close remaining positions at end
            for pos in positions:
                final_price = ohlcv_data.iloc[-1]["close"]
                pnl = self._calculate_pnl(pos, final_price)
                trades.append({
                    "entry_price": pos["entry_price"],
                    "exit_price": final_price,
                    "quantity": pos["quantity"],
                    "pnl": pnl,
                    "entry_time": pos["entry_time"],
                    "exit_time": ohlcv_data.iloc[-1].get("timestamp", ""),
                    "exit_reason": "END_OF_DATA"
                })
                capital += pos["entry_price"] * pos["quantity"] * 0.1 + pnl
            
            # Calculate metrics
            metrics = self._calculate_metrics(trades, equity_curve, initial_capital)
            
            return {
                "total_trades": len(trades),
                "winning_trades": metrics["winning_trades"],
                "losing_trades": metrics["losing_trades"],
                "win_rate": metrics["win_rate"],
                "total_pnl": metrics["total_pnl"],
                "max_drawdown": metrics["max_drawdown"],
                "sharpe_ratio": metrics["sharpe_ratio"],
                "equity_curve": equity_curve,
                "trades": trades,
                "final_capital": capital
            }
            
        except Exception as e:
            logger.error(f"Backtest failed: {e}", exc_info=True)
            raise
    
    def _calculate_pnl(self, position: Dict, current_price: float) -> float:
        """Calculate P&L for a position."""
        if position["type"] == "LONG":
            return (current_price - position["entry_price"]) * position["quantity"]
        else:  # SHORT
            return (position["entry_price"] - current_price) * position["quantity"]
    
    def _calculate_metrics(
        self,
        trades: List[Dict],
        equity_curve: List[float],
        initial_capital: float
    ) -> Dict[str, Any]:
        """Calculate backtest metrics."""
        if not trades:
            return {
                "winning_trades": 0,
                "losing_trades": 0,
                "win_rate": 0.0,
                "total_pnl": 0.0,
                "max_drawdown": 0.0,
                "sharpe_ratio": 0.0
            }
        
        winning_trades = sum(1 for t in trades if t["pnl"] > 0)
        losing_trades = sum(1 for t in trades if t["pnl"] < 0)
        win_rate = (winning_trades / len(trades)) * 100 if trades else 0.0
        total_pnl = sum(t["pnl"] for t in trades)
        
        # Calculate max drawdown
        peak = initial_capital
        max_drawdown = 0.0
        for equity in equity_curve:
            if equity > peak:
                peak = equity
            drawdown = (peak - equity) / peak * 100
            if drawdown > max_drawdown:
                max_drawdown = drawdown
        
        # Calculate Sharpe ratio (simplified)
        returns = [equity_curve[i] / equity_curve[i-1] - 1 for i in range(1, len(equity_curve)) if equity_curve[i-1] > 0]
        if returns:
            avg_return = sum(returns) / len(returns)
            std_return = (sum((r - avg_return) ** 2 for r in returns) / len(returns)) ** 0.5
            sharpe_ratio = (avg_return / std_return * (252 ** 0.5)) if std_return > 0 else 0.0
        else:
            sharpe_ratio = 0.0
        
        return {
            "winning_trades": winning_trades,
            "losing_trades": losing_trades,
            "win_rate": round(win_rate, 2),
            "total_pnl": round(total_pnl, 2),
            "max_drawdown": round(max_drawdown, 2),
            "sharpe_ratio": round(sharpe_ratio, 2)
        }

