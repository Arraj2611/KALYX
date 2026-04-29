"""
Database models for KALYX trading system.
"""
from sqlalchemy import Column, Integer, String, Float, DateTime, Boolean, JSON, Text, ForeignKey
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from datetime import datetime

from app.data.database import Base


class User(Base):
    """User model (single user system)."""
    __tablename__ = "users"
    
    id = Column(Integer, primary_key=True, index=True)
    broker_accounts = Column(JSON, default={})  # {"zerodha": "AB1234", "groww": "GRW5678"}
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())
    
    # Relationships
    trades = relationship("Trade", back_populates="user")
    strategies = relationship("Strategy", back_populates="user")


class Strategy(Base):
    """Strategy configuration model."""
    __tablename__ = "strategies"
    
    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"))
    name = Column(String, nullable=False, index=True)
    description = Column(Text)
    strategy_type = Column(String)  # e.g., "mean_reversion", "momentum"
    config = Column(JSON)  # Strategy-specific configuration
    code = Column(Text)  # Strategy code (Python)
    is_active = Column(Boolean, default=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())
    
    # Relationships
    user = relationship("User", back_populates="strategies")
    trades = relationship("Trade", back_populates="strategy")
    backtests = relationship("Backtest", back_populates="strategy")


class Trade(Base):
    """Trade execution model."""
    __tablename__ = "trades"
    
    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"))
    strategy_id = Column(Integer, ForeignKey("strategies.id"), nullable=True)
    
    # Trade details
    order_id = Column(String, unique=True, index=True)  # Zerodha order ID
    exchange_order_id = Column(String, index=True)
    tradingsymbol = Column(String, nullable=False, index=True)
    instrument_token = Column(Integer, index=True)
    exchange = Column(String, default="NFO")
    
    # Order details
    transaction_type = Column(String)  # BUY, SELL
    product = Column(String, default="MIS")  # MIS, NRML, CNC
    order_type = Column(String)  # MARKET, LIMIT, SL, SL-M
    quantity = Column(Integer)
    price = Column(Float)
    trigger_price = Column(Float, nullable=True)
    
    # Status
    status = Column(String, index=True)  # PENDING, OPEN, COMPLETE, CANCELLED, REJECTED
    filled_quantity = Column(Integer, default=0)
    average_price = Column(Float, nullable=True)
    
    # P&L
    entry_price = Column(Float, nullable=True)
    exit_price = Column(Float, nullable=True)
    pnl = Column(Float, default=0.0)
    pnl_percentage = Column(Float, default=0.0)
    
    # Timestamps
    order_timestamp = Column(DateTime(timezone=True))
    fill_timestamp = Column(DateTime(timezone=True), nullable=True)
    exit_timestamp = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())
    
    # Relationships
    user = relationship("User", back_populates="trades")
    strategy = relationship("Strategy", back_populates="trades")


class Backtest(Base):
    """Backtest results model."""
    __tablename__ = "backtests"
    
    id = Column(Integer, primary_key=True, index=True)
    strategy_id = Column(Integer, ForeignKey("strategies.id"))
    
    # Configuration
    start_date = Column(DateTime(timezone=True))
    end_date = Column(DateTime(timezone=True))
    initial_capital = Column(Float)
    config = Column(JSON)  # Backtest-specific config
    
    # Results
    total_trades = Column(Integer, default=0)
    winning_trades = Column(Integer, default=0)
    losing_trades = Column(Integer, default=0)
    win_rate = Column(Float, default=0.0)
    total_pnl = Column(Float, default=0.0)
    max_drawdown = Column(Float, default=0.0)
    sharpe_ratio = Column(Float, nullable=True)
    equity_curve = Column(JSON)  # List of equity values over time
    
    # Timestamps
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    
    # Relationships
    strategy = relationship("Strategy", back_populates="backtests")


class SystemLog(Base):
    """System log entries."""
    __tablename__ = "system_logs"
    
    id = Column(Integer, primary_key=True, index=True)
    level = Column(String, index=True)  # INFO, WARNING, ERROR, CRITICAL
    logger = Column(String, index=True)
    message = Column(Text)
    module = Column(String)
    function = Column(String)
    line = Column(Integer)
    extra = Column(JSON)  # Additional structured data
    created_at = Column(DateTime(timezone=True), server_default=func.now(), index=True)


class MarketData(Base):
    """Historical market data cache."""
    __tablename__ = "market_data"
    
    id = Column(Integer, primary_key=True, index=True)
    instrument_token = Column(Integer, index=True)
    tradingsymbol = Column(String, index=True)
    exchange = Column(String, default="NFO")
    
    # OHLCV data
    timestamp = Column(DateTime(timezone=True), index=True)
    open = Column(Float)
    high = Column(Float)
    low = Column(Float)
    close = Column(Float)
    volume = Column(Integer)
    interval = Column(String)  # 1min, 5min, 15min, 1hour, 1day
    
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    
    # Composite index for efficient queries
    __table_args__ = (
        {"postgresql_indexes": [
            {"name": "idx_market_data_token_time", "columns": ["instrument_token", "timestamp"]},
            {"name": "idx_market_data_symbol_time", "columns": ["tradingsymbol", "timestamp"]},
        ]},
    )

