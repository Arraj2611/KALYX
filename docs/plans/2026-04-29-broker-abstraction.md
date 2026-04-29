# Broker Abstraction Layer Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Decouple KALYX from Zerodha, introduce unified broker interface with Zerodha + Groww + Paper adapters, decision logging, and Telegram alerting.

**Architecture:** Protocol-based ABC (`BrokerAdapter`) with unified dataclasses. Each broker gets own adapter translating to/from SDK. `AccountManager` registers multiple adapters. `DecisionLogger` writes every decision to DB + log files. `PaperAdapter` simulates fills for safe testing.

**Tech Stack:** Python 3.10+, asyncio, kiteconnect 4.2.0, growwapi, python-telegram-bot, PostgreSQL 15, Redis 7, python-json-logger, PyYAML

---

## File Map

### New Files

| File | Responsibility |
|------|---------------|
| `backend/app/brokers/__init__.py` | Package init, exports BrokerAdapter + models |
| `backend/app/brokers/base.py` | BrokerAdapter ABC + all unified dataclasses + error types |
| `backend/app/brokers/account_manager.py` | Multi-account registry + cross-account queries |
| `backend/app/brokers/zerodha/__init__.py` | Package init |
| `backend/app/brokers/zerodha/adapter.py` | ZerodhaAdapter(BrokerAdapter) |
| `backend/app/brokers/zerodha/feed.py` | KiteTicker wrapper (refactored from auth/websocket_client.py) |
| `backend/app/brokers/zerodha/auth.py` | Zerodha auth (refactored from auth/service.py) |
| `backend/app/brokers/groww/__init__.py` | Package init |
| `backend/app/brokers/groww/adapter.py` | GrowwAdapter(BrokerAdapter) |
| `backend/app/brokers/groww/feed.py` | GrowwFeed NATS wrapper |
| `backend/app/brokers/groww/auth.py` | Groww TOTP auth |
| `backend/app/brokers/paper/__init__.py` | Package init |
| `backend/app/brokers/paper/adapter.py` | PaperAdapter(BrokerAdapter) — simulation |
| `backend/app/decisions/__init__.py` | Package init |
| `backend/app/decisions/models.py` | DecisionLog SQLAlchemy model + DecisionAction enum |
| `backend/app/decisions/logger.py` | DecisionLogger service (DB + file + Telegram) |
| `backend/app/decisions/router.py` | FastAPI endpoints for decision history |
| `backend/app/alerts/__init__.py` | Package init |
| `backend/app/alerts/telegram.py` | Telegram alerting service |
| `backend/config/accounts.yaml` | Multi-account configuration |
| `backend/tests/brokers/__init__.py` | Test package |
| `backend/tests/brokers/test_base.py` | Tests for dataclasses and error types |
| `backend/tests/brokers/test_paper.py` | PaperAdapter tests |
| `backend/tests/brokers/test_zerodha.py` | ZerodhaAdapter tests (mocked SDK) |
| `backend/tests/brokers/test_groww.py` | GrowwAdapter tests (mocked SDK) |
| `backend/tests/brokers/test_account_manager.py` | AccountManager tests |
| `backend/tests/brokers/test_conformance.py` | Generic conformance suite for any adapter |
| `backend/tests/decisions/__init__.py` | Test package |
| `backend/tests/decisions/test_logger.py` | DecisionLogger tests |
| `backend/tests/decisions/test_models.py` | DecisionLog model tests |
| `backend/tests/alerts/__init__.py` | Test package |
| `backend/tests/alerts/test_telegram.py` | Telegram alert tests |

### Modified Files

| File | Change |
|------|--------|
| `backend/app/execution/service.py` | Use adapter via AccountManager instead of AuthService.get_kite_client() |
| `backend/app/execution/router.py` | Add `account_name` param to order endpoints |
| `backend/app/risk/service.py` | Use adapter.get_margins() instead of kite.margins() |
| `backend/app/risk/router.py` | Add `account_name` param |
| `backend/app/data/models.py` | User.zerodha_user_id → User.broker_accounts (JSON) |
| `backend/app/main.py` | Initialize AccountManager on startup from accounts.yaml |
| `backend/app/config.py` | Add TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID, ACCOUNTS_CONFIG_PATH |
| `backend/requirements.txt` | Add growwapi, python-telegram-bot, pyyaml, uvloop |

---

## Task 1: Base Interface + Unified Data Models

**Files:**
- Create: `backend/app/brokers/__init__.py`
- Create: `backend/app/brokers/base.py`
- Create: `backend/tests/brokers/__init__.py`
- Create: `backend/tests/brokers/test_base.py`

- [ ] **Step 1: Create test file for dataclasses and error types**

```python
# backend/tests/brokers/test_base.py
"""Tests for broker base interface and unified data models."""
import pytest
from datetime import datetime


def test_unified_order_creation():
    from app.brokers.base import UnifiedOrder, TradeContext

    ctx = TradeContext(
        strategy_id=1,
        account_name="paper_test",
        signals={"rsi_oversold": True},
        market_state={"ltp": 150.5, "volume": 10000},
        reasoning="RSI below 30 on 15m",
        confidence=0.75,
    )
    order = UnifiedOrder(
        symbol="NIFTY25APR24500CE",
        exchange="NFO",
        segment="FNO",
        transaction_type="BUY",
        quantity=50,
        order_type="MARKET",
        product="MIS",
        context=ctx,
    )
    assert order.symbol == "NIFTY25APR24500CE"
    assert order.context.confidence == 0.75
    assert order.context.account_name == "paper_test"
    assert order.price is None
    assert order.trigger_price is None


def test_unified_order_with_limit_price():
    from app.brokers.base import UnifiedOrder

    order = UnifiedOrder(
        symbol="RELIANCE",
        exchange="NSE",
        segment="CASH",
        transaction_type="BUY",
        quantity=1,
        order_type="LIMIT",
        product="CNC",
        price=2500.0,
        trigger_price=2490.0,
    )
    assert order.price == 2500.0
    assert order.trigger_price == 2490.0


def test_position_dataclass():
    from app.brokers.base import Position

    pos = Position(
        symbol="NIFTY25APR24500CE",
        exchange="NFO",
        segment="FNO",
        quantity=50,
        average_price=150.0,
        last_price=160.0,
        pnl=500.0,
        product="MIS",
        broker_name="zerodha",
    )
    assert pos.pnl == 500.0
    assert pos.broker_name == "zerodha"


def test_margin_info_dataclass():
    from app.brokers.base import MarginInfo

    margin = MarginInfo(
        available_cash=500000.0,
        used_margin=200000.0,
        total_margin=700000.0,
        broker_name="groww",
        raw={"equity": {"available": 500000}},
    )
    assert margin.total_margin == 700000.0
    assert margin.raw["equity"]["available"] == 500000


def test_order_result_dataclass():
    from app.brokers.base import OrderResult

    result = OrderResult(
        broker_order_id="ORD123456",
        status="PENDING",
        broker_name="zerodha",
        raw_response={"order_id": "ORD123456"},
    )
    assert result.broker_order_id == "ORD123456"


def test_auth_result_dataclass():
    from app.brokers.base import AuthResult

    auth = AuthResult(
        success=True,
        user_id="AB1234",
        broker_name="zerodha",
        message="Login successful",
    )
    assert auth.success is True


def test_rate_limit_config():
    from app.brokers.base import RateLimitConfig

    config = RateLimitConfig(
        orders_per_second=10,
        orders_per_minute=250,
        data_requests_per_second=10,
        max_ws_subscriptions=1000,
    )
    assert config.orders_per_second == 10


def test_broker_error_hierarchy():
    from app.brokers.base import (
        BrokerError,
        AuthenticationError,
        OrderRejectedError,
        RateLimitError,
        InsufficientMarginError,
        BrokerUnavailableError,
        InvalidSymbolError,
    )

    err = AuthenticationError("zerodha", ValueError("token expired"), "Token expired")
    assert isinstance(err, BrokerError)
    assert err.broker_name == "zerodha"
    assert str(err) == "Token expired"

    err2 = OrderRejectedError("groww", RuntimeError("qty"), "Invalid quantity")
    assert isinstance(err2, BrokerError)
    assert err2.broker_name == "groww"


def test_quote_dataclass():
    from app.brokers.base import Quote

    q = Quote(
        symbol="NIFTY",
        exchange="NSE",
        ltp=22500.0,
        open=22400.0,
        high=22600.0,
        low=22350.0,
        close=22450.0,
        volume=1000000,
        oi=5000000,
        broker_name="zerodha",
    )
    assert q.oi == 5000000
    assert q.bid is None


def test_instrument_dataclass():
    from app.brokers.base import Instrument

    inst = Instrument(
        symbol="NIFTY25APR24500CE",
        exchange="NFO",
        segment="FNO",
        instrument_type="CE",
        lot_size=50,
        tick_size=0.05,
        expiry=datetime(2025, 4, 24),
        strike=24500.0,
        broker_name="zerodha",
    )
    assert inst.lot_size == 50
    assert inst.strike == 24500.0


def test_broker_adapter_is_abstract():
    from app.brokers.base import BrokerAdapter

    with pytest.raises(TypeError):
        BrokerAdapter()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd backend && python -m pytest tests/brokers/test_base.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.brokers'`

- [ ] **Step 3: Create brokers package init**

```python
# backend/app/brokers/__init__.py
"""Broker abstraction layer for multi-broker trading."""
from app.brokers.base import (
    BrokerAdapter,
    UnifiedOrder,
    TradeContext,
    OrderResult,
    OrderStatus,
    Position,
    Holding,
    MarginInfo,
    Quote,
    Instrument,
    AuthResult,
    AuthStatus,
    RateLimitConfig,
    BrokerError,
    AuthenticationError,
    OrderRejectedError,
    RateLimitError,
    InsufficientMarginError,
    BrokerUnavailableError,
    InvalidSymbolError,
)

__all__ = [
    "BrokerAdapter",
    "UnifiedOrder",
    "TradeContext",
    "OrderResult",
    "OrderStatus",
    "Position",
    "Holding",
    "MarginInfo",
    "Quote",
    "Instrument",
    "AuthResult",
    "AuthStatus",
    "RateLimitConfig",
    "BrokerError",
    "AuthenticationError",
    "OrderRejectedError",
    "RateLimitError",
    "InsufficientMarginError",
    "BrokerUnavailableError",
    "InvalidSymbolError",
]
```

- [ ] **Step 4: Create base.py with ABC + all dataclasses + error types**

```python
# backend/app/brokers/base.py
"""
Broker abstraction layer — core interface and unified data models.
Every broker adapter implements BrokerAdapter ABC.
All broker-specific responses are translated into these unified models.
"""
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Callable, Any


TickCallback = Callable[[dict], None]


# ── Error Types ───────────────────────────────────────────────


class BrokerError(Exception):
    """Base error for all broker operations."""

    def __init__(self, broker_name: str, original_error: Exception, message: str = ""):
        self.broker_name = broker_name
        self.original_error = original_error
        super().__init__(message or str(original_error))


class AuthenticationError(BrokerError):
    """Authentication failed or token expired."""
    pass


class OrderRejectedError(BrokerError):
    """Broker rejected the order."""
    pass


class RateLimitError(BrokerError):
    """Rate limit exceeded."""
    pass


class InsufficientMarginError(BrokerError):
    """Not enough margin to place order."""
    pass


class BrokerUnavailableError(BrokerError):
    """Broker API is unreachable."""
    pass


class InvalidSymbolError(BrokerError):
    """Symbol not found or invalid for this broker."""
    pass


# ── Unified Data Models ──────────────────────────────────────


@dataclass
class TradeContext:
    """Context attached to every order for the learning system."""
    strategy_id: int
    account_name: str
    signals: dict
    market_state: dict
    reasoning: str
    confidence: float
    timestamp: datetime = field(default_factory=datetime.utcnow)


@dataclass
class UnifiedOrder:
    """Broker-agnostic order representation."""
    symbol: str
    exchange: str
    segment: str
    transaction_type: str
    quantity: int
    order_type: str
    product: str
    price: float | None = None
    trigger_price: float | None = None
    context: TradeContext | None = None


@dataclass
class OrderResult:
    """Result from placing an order."""
    broker_order_id: str
    status: str
    broker_name: str
    raw_response: dict


@dataclass
class OrderStatus:
    """Current status of an order."""
    broker_order_id: str
    symbol: str
    status: str
    quantity: int
    filled_quantity: int
    average_price: float | None
    order_type: str
    transaction_type: str
    broker_name: str


@dataclass
class Position:
    """Current open position."""
    symbol: str
    exchange: str
    segment: str
    quantity: int
    average_price: float
    last_price: float
    pnl: float
    product: str
    broker_name: str


@dataclass
class Holding:
    """Long-term holding (delivery)."""
    symbol: str
    isin: str | None
    quantity: int
    average_price: float
    last_price: float
    pnl: float
    broker_name: str


@dataclass
class MarginInfo:
    """Account margin information."""
    available_cash: float
    used_margin: float
    total_margin: float
    broker_name: str
    raw: dict


@dataclass
class Quote:
    """Market quote for an instrument."""
    symbol: str
    exchange: str
    ltp: float
    open: float
    high: float
    low: float
    close: float
    volume: int
    bid: float | None = None
    ask: float | None = None
    oi: int | None = None
    broker_name: str = ""


@dataclass
class Instrument:
    """Tradeable instrument metadata."""
    symbol: str
    exchange: str
    segment: str
    instrument_type: str
    lot_size: int
    tick_size: float
    expiry: datetime | None = None
    strike: float | None = None
    broker_name: str = ""


@dataclass
class AuthResult:
    """Result from login attempt."""
    success: bool
    user_id: str
    broker_name: str
    message: str


@dataclass
class AuthStatus:
    """Current authentication status."""
    is_valid: bool
    user_id: str | None
    broker_name: str
    expires_at: datetime | None


@dataclass
class RateLimitConfig:
    """Broker-specific rate limit configuration."""
    orders_per_second: int
    orders_per_minute: int
    data_requests_per_second: int
    max_ws_subscriptions: int


# ── Abstract Broker Interface ─────────────────────────────────


class BrokerAdapter(ABC):
    """Abstract broker interface. Every broker implements this."""

    # ── Auth ──────────────────────────────────────────
    @abstractmethod
    async def login(self, credentials: dict) -> AuthResult: ...

    @abstractmethod
    async def logout(self) -> None: ...

    @abstractmethod
    async def get_auth_status(self) -> AuthStatus: ...

    # ── Orders ────────────────────────────────────────
    @abstractmethod
    async def place_order(self, order: UnifiedOrder) -> OrderResult: ...

    @abstractmethod
    async def modify_order(self, order_id: str, changes: dict) -> OrderResult: ...

    @abstractmethod
    async def cancel_order(self, order_id: str, segment: str) -> str: ...

    @abstractmethod
    async def get_order_status(self, order_id: str) -> OrderStatus: ...

    @abstractmethod
    async def get_orders(self) -> list[OrderStatus]: ...

    # ── Portfolio ─────────────────────────────────────
    @abstractmethod
    async def get_positions(self) -> list[Position]: ...

    @abstractmethod
    async def get_holdings(self) -> list[Holding]: ...

    @abstractmethod
    async def get_margins(self) -> MarginInfo: ...

    # ── Market Data ───────────────────────────────────
    @abstractmethod
    async def get_ltp(self, symbols: list[str]) -> dict[str, float]: ...

    @abstractmethod
    async def get_quote(self, symbol: str, exchange: str, segment: str) -> Quote: ...

    @abstractmethod
    async def get_instruments(self, exchange: str | None = None) -> list[Instrument]: ...

    # ── Live Feed ─────────────────────────────────────
    @abstractmethod
    async def subscribe_ticks(self, symbols: list[str], callback: TickCallback) -> None: ...

    @abstractmethod
    async def unsubscribe_ticks(self, symbols: list[str]) -> None: ...

    @abstractmethod
    async def disconnect_feed(self) -> None: ...

    # ── Metadata ──────────────────────────────────────
    @property
    @abstractmethod
    def name(self) -> str: ...

    @property
    @abstractmethod
    def supported_segments(self) -> list[str]: ...

    @property
    @abstractmethod
    def rate_limits(self) -> RateLimitConfig: ...

    @property
    @abstractmethod
    def is_connected(self) -> bool: ...
```

- [ ] **Step 5: Create tests/__init__.py files**

```python
# backend/tests/__init__.py
# (create if not exists)

# backend/tests/brokers/__init__.py
"""Tests for broker abstraction layer."""
```

- [ ] **Step 6: Run tests to verify they pass**

Run: `cd backend && python -m pytest tests/brokers/test_base.py -v`
Expected: All 11 tests PASS

- [ ] **Step 7: Commit**

```bash
git add backend/app/brokers/__init__.py backend/app/brokers/base.py backend/tests/brokers/__init__.py backend/tests/brokers/test_base.py
git commit -m "feat(brokers): add BrokerAdapter ABC, unified data models, error types

Foundation for multi-broker abstraction. Defines:
- BrokerAdapter abstract interface (auth, orders, portfolio, market data, feed)
- 11 unified dataclasses (UnifiedOrder, Position, MarginInfo, etc.)
- TradeContext for learning system
- 6 typed broker errors
- Full test coverage for all models and error hierarchy

Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>"
```

---

## Task 2: PaperAdapter (Simulation)

**Files:**
- Create: `backend/app/brokers/paper/__init__.py`
- Create: `backend/app/brokers/paper/adapter.py`
- Create: `backend/tests/brokers/test_paper.py`

- [ ] **Step 1: Write PaperAdapter tests**

```python
# backend/tests/brokers/test_paper.py
"""Tests for paper trading adapter."""
import pytest
import asyncio
from app.brokers.base import (
    BrokerAdapter,
    UnifiedOrder,
    TradeContext,
    Position,
    MarginInfo,
    OrderResult,
    OrderStatus,
)


@pytest.fixture
def paper_adapter():
    from app.brokers.paper.adapter import PaperAdapter

    return PaperAdapter(config={"initial_capital": 1000000, "slippage_pct": 0.05})


@pytest.fixture
def sample_order():
    return UnifiedOrder(
        symbol="NIFTY25APR24500CE",
        exchange="NFO",
        segment="FNO",
        transaction_type="BUY",
        quantity=50,
        order_type="MARKET",
        product="MIS",
        price=150.0,
        context=TradeContext(
            strategy_id=1,
            account_name="paper_test",
            signals={"rsi": 28},
            market_state={"ltp": 150.0},
            reasoning="RSI oversold",
            confidence=0.8,
        ),
    )


def test_paper_adapter_is_broker_adapter(paper_adapter):
    assert isinstance(paper_adapter, BrokerAdapter)


def test_paper_adapter_name(paper_adapter):
    assert paper_adapter.name == "paper"


def test_paper_adapter_supported_segments(paper_adapter):
    assert "CASH" in paper_adapter.supported_segments
    assert "FNO" in paper_adapter.supported_segments


def test_paper_adapter_rate_limits(paper_adapter):
    rl = paper_adapter.rate_limits
    assert rl.orders_per_second > 0
    assert rl.max_ws_subscriptions > 0


@pytest.mark.asyncio
async def test_paper_login(paper_adapter):
    result = await paper_adapter.login({"mode": "paper"})
    assert result.success is True
    assert result.broker_name == "paper"


@pytest.mark.asyncio
async def test_paper_place_order(paper_adapter, sample_order):
    await paper_adapter.login({"mode": "paper"})
    result = await paper_adapter.place_order(sample_order)
    assert isinstance(result, OrderResult)
    assert result.broker_name == "paper"
    assert result.status == "COMPLETE"
    assert result.broker_order_id.startswith("PAPER-")


@pytest.mark.asyncio
async def test_paper_positions_after_buy(paper_adapter, sample_order):
    await paper_adapter.login({"mode": "paper"})
    await paper_adapter.place_order(sample_order)
    positions = await paper_adapter.get_positions()
    assert len(positions) == 1
    assert positions[0].symbol == "NIFTY25APR24500CE"
    assert positions[0].quantity == 50
    assert positions[0].broker_name == "paper"


@pytest.mark.asyncio
async def test_paper_margin_deducted(paper_adapter, sample_order):
    await paper_adapter.login({"mode": "paper"})
    margin_before = await paper_adapter.get_margins()
    await paper_adapter.place_order(sample_order)
    margin_after = await paper_adapter.get_margins()
    assert margin_after.used_margin > margin_before.used_margin
    assert margin_after.available_cash < margin_before.available_cash


@pytest.mark.asyncio
async def test_paper_cancel_order(paper_adapter, sample_order):
    await paper_adapter.login({"mode": "paper"})
    result = await paper_adapter.place_order(sample_order)
    # Paper fills immediately, cancel returns the id but position stays
    cancelled_id = await paper_adapter.cancel_order(result.broker_order_id, "FNO")
    assert cancelled_id == result.broker_order_id


@pytest.mark.asyncio
async def test_paper_get_orders(paper_adapter, sample_order):
    await paper_adapter.login({"mode": "paper"})
    await paper_adapter.place_order(sample_order)
    orders = await paper_adapter.get_orders()
    assert len(orders) == 1
    assert orders[0].status == "COMPLETE"


@pytest.mark.asyncio
async def test_paper_slippage_applied(paper_adapter):
    """Buy orders should fill at slightly higher price (slippage)."""
    await paper_adapter.login({"mode": "paper"})
    order = UnifiedOrder(
        symbol="RELIANCE",
        exchange="NSE",
        segment="CASH",
        transaction_type="BUY",
        quantity=1,
        order_type="LIMIT",
        product="CNC",
        price=2500.0,
    )
    await paper_adapter.place_order(order)
    positions = await paper_adapter.get_positions()
    # 0.05% slippage on buy = 2500 * 1.0005 = 2501.25
    assert positions[0].average_price == pytest.approx(2501.25, abs=0.01)


@pytest.mark.asyncio
async def test_paper_sell_slippage(paper_adapter):
    """Sell orders should fill at slightly lower price (slippage)."""
    await paper_adapter.login({"mode": "paper"})
    # First buy
    buy = UnifiedOrder(
        symbol="TCS", exchange="NSE", segment="CASH",
        transaction_type="BUY", quantity=10, order_type="LIMIT",
        product="CNC", price=4000.0,
    )
    await paper_adapter.place_order(buy)
    # Then sell
    sell = UnifiedOrder(
        symbol="TCS", exchange="NSE", segment="CASH",
        transaction_type="SELL", quantity=10, order_type="LIMIT",
        product="CNC", price=4100.0,
    )
    await paper_adapter.place_order(sell)
    positions = await paper_adapter.get_positions()
    # Position should be closed (qty 0 filtered out)
    tcs_positions = [p for p in positions if p.symbol == "TCS"]
    assert len(tcs_positions) == 0


@pytest.mark.asyncio
async def test_paper_get_margins_initial(paper_adapter):
    await paper_adapter.login({"mode": "paper"})
    margin = await paper_adapter.get_margins()
    assert margin.available_cash == 1000000.0
    assert margin.used_margin == 0.0
    assert margin.total_margin == 1000000.0
    assert margin.broker_name == "paper"


@pytest.mark.asyncio
async def test_paper_holdings_empty(paper_adapter):
    await paper_adapter.login({"mode": "paper"})
    holdings = await paper_adapter.get_holdings()
    assert holdings == []


@pytest.mark.asyncio
async def test_paper_auth_status(paper_adapter):
    status = await paper_adapter.get_auth_status()
    assert status.is_valid is False
    await paper_adapter.login({"mode": "paper"})
    status = await paper_adapter.get_auth_status()
    assert status.is_valid is True
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd backend && python -m pytest tests/brokers/test_paper.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.brokers.paper'`

- [ ] **Step 3: Implement PaperAdapter**

```python
# backend/app/brokers/paper/__init__.py
"""Paper trading adapter for simulation."""
from app.brokers.paper.adapter import PaperAdapter

__all__ = ["PaperAdapter"]
```

```python
# backend/app/brokers/paper/adapter.py
"""
Paper trading adapter — simulates broker behavior without real orders.
Uses configurable slippage. Tracks positions and P&L in memory.
"""
import logging
from datetime import datetime
from typing import Callable

from app.brokers.base import (
    BrokerAdapter,
    UnifiedOrder,
    OrderResult,
    OrderStatus,
    Position,
    Holding,
    MarginInfo,
    Quote,
    Instrument,
    AuthResult,
    AuthStatus,
    RateLimitConfig,
    TickCallback,
)

logger = logging.getLogger(__name__)


class PaperAdapter(BrokerAdapter):
    """Simulated broker for paper trading. No real orders placed."""

    def __init__(self, config: dict | None = None):
        config = config or {}
        self._capital = float(config.get("initial_capital", 1000000))
        self._slippage_pct = float(config.get("slippage_pct", 0.05)) / 100  # convert to decimal
        self._positions: dict[str, Position] = {}  # symbol -> Position
        self._orders: list[OrderStatus] = []
        self._order_counter = 0
        self._used_margin = 0.0
        self._logged_in = False
        self._tick_callbacks: dict[str, TickCallback] = {}

    # ── Auth ──────────────────────────────────────────

    async def login(self, credentials: dict) -> AuthResult:
        self._logged_in = True
        logger.info("Paper adapter logged in")
        return AuthResult(
            success=True,
            user_id="PAPER_USER",
            broker_name="paper",
            message="Paper trading mode active",
        )

    async def logout(self) -> None:
        self._logged_in = False
        logger.info("Paper adapter logged out")

    async def get_auth_status(self) -> AuthStatus:
        return AuthStatus(
            is_valid=self._logged_in,
            user_id="PAPER_USER" if self._logged_in else None,
            broker_name="paper",
            expires_at=None,
        )

    # ── Orders ────────────────────────────────────────

    async def place_order(self, order: UnifiedOrder) -> OrderResult:
        self._order_counter += 1
        order_id = f"PAPER-{self._order_counter:06d}"

        # Calculate fill price with slippage
        base_price = order.price if order.price else 0.0
        if order.transaction_type == "BUY":
            fill_price = base_price * (1 + self._slippage_pct)
        else:
            fill_price = base_price * (1 - self._slippage_pct)

        # Update positions
        key = order.symbol
        if key in self._positions:
            existing = self._positions[key]
            if order.transaction_type == "BUY":
                total_qty = existing.quantity + order.quantity
                if total_qty > 0:
                    new_avg = (
                        (existing.average_price * existing.quantity)
                        + (fill_price * order.quantity)
                    ) / total_qty
                else:
                    new_avg = 0.0
                self._positions[key] = Position(
                    symbol=order.symbol,
                    exchange=order.exchange,
                    segment=order.segment,
                    quantity=total_qty,
                    average_price=round(new_avg, 2),
                    last_price=fill_price,
                    pnl=round((fill_price - new_avg) * total_qty, 2),
                    product=order.product,
                    broker_name="paper",
                )
            else:  # SELL
                new_qty = existing.quantity - order.quantity
                self._positions[key] = Position(
                    symbol=order.symbol,
                    exchange=order.exchange,
                    segment=order.segment,
                    quantity=new_qty,
                    average_price=existing.average_price,
                    last_price=fill_price,
                    pnl=round(
                        (fill_price - existing.average_price) * order.quantity, 2
                    ),
                    product=order.product,
                    broker_name="paper",
                )
        else:
            self._positions[key] = Position(
                symbol=order.symbol,
                exchange=order.exchange,
                segment=order.segment,
                quantity=order.quantity if order.transaction_type == "BUY" else -order.quantity,
                average_price=round(fill_price, 2),
                last_price=fill_price,
                pnl=0.0,
                product=order.product,
                broker_name="paper",
            )

        # Update margin
        order_value = fill_price * order.quantity
        if order.transaction_type == "BUY":
            self._used_margin += order_value
        else:
            self._used_margin = max(0, self._used_margin - order_value)

        # Record order
        order_status = OrderStatus(
            broker_order_id=order_id,
            symbol=order.symbol,
            status="COMPLETE",
            quantity=order.quantity,
            filled_quantity=order.quantity,
            average_price=round(fill_price, 2),
            order_type=order.order_type,
            transaction_type=order.transaction_type,
            broker_name="paper",
        )
        self._orders.append(order_status)

        logger.info(
            f"Paper order filled: {order_id} {order.transaction_type} "
            f"{order.quantity}x {order.symbol} @ {fill_price:.2f}"
        )

        return OrderResult(
            broker_order_id=order_id,
            status="COMPLETE",
            broker_name="paper",
            raw_response={
                "order_id": order_id,
                "fill_price": round(fill_price, 2),
                "slippage_pct": self._slippage_pct * 100,
            },
        )

    async def modify_order(self, order_id: str, changes: dict) -> OrderResult:
        # Paper orders fill immediately, modification is a no-op
        return OrderResult(
            broker_order_id=order_id,
            status="COMPLETE",
            broker_name="paper",
            raw_response={"message": "Paper orders fill immediately, cannot modify"},
        )

    async def cancel_order(self, order_id: str, segment: str) -> str:
        logger.info(f"Paper cancel order: {order_id}")
        return order_id

    async def get_order_status(self, order_id: str) -> OrderStatus:
        for order in self._orders:
            if order.broker_order_id == order_id:
                return order
        return OrderStatus(
            broker_order_id=order_id,
            symbol="",
            status="NOT_FOUND",
            quantity=0,
            filled_quantity=0,
            average_price=None,
            order_type="",
            transaction_type="",
            broker_name="paper",
        )

    async def get_orders(self) -> list[OrderStatus]:
        return list(self._orders)

    # ── Portfolio ─────────────────────────────────────

    async def get_positions(self) -> list[Position]:
        return [p for p in self._positions.values() if p.quantity != 0]

    async def get_holdings(self) -> list[Holding]:
        return []

    async def get_margins(self) -> MarginInfo:
        available = self._capital - self._used_margin
        return MarginInfo(
            available_cash=round(available, 2),
            used_margin=round(self._used_margin, 2),
            total_margin=round(self._capital, 2),
            broker_name="paper",
            raw={"initial_capital": self._capital, "slippage_pct": self._slippage_pct * 100},
        )

    # ── Market Data ───────────────────────────────────

    async def get_ltp(self, symbols: list[str]) -> dict[str, float]:
        # Paper adapter returns last known prices from positions
        result = {}
        for sym in symbols:
            if sym in self._positions:
                result[sym] = self._positions[sym].last_price
            else:
                result[sym] = 0.0
        return result

    async def get_quote(self, symbol: str, exchange: str, segment: str) -> Quote:
        lp = 0.0
        if symbol in self._positions:
            lp = self._positions[symbol].last_price
        return Quote(
            symbol=symbol, exchange=exchange,
            ltp=lp, open=lp, high=lp, low=lp, close=lp,
            volume=0, broker_name="paper",
        )

    async def get_instruments(self, exchange: str | None = None) -> list[Instrument]:
        return []

    # ── Live Feed ─────────────────────────────────────

    async def subscribe_ticks(self, symbols: list[str], callback: TickCallback) -> None:
        for sym in symbols:
            self._tick_callbacks[sym] = callback
        logger.info(f"Paper subscribed to {len(symbols)} symbols")

    async def unsubscribe_ticks(self, symbols: list[str]) -> None:
        for sym in symbols:
            self._tick_callbacks.pop(sym, None)

    async def disconnect_feed(self) -> None:
        self._tick_callbacks.clear()

    # ── Metadata ──────────────────────────────────────

    @property
    def name(self) -> str:
        return "paper"

    @property
    def supported_segments(self) -> list[str]:
        return ["CASH", "FNO", "COMMODITY", "SPOT", "FUTURES"]

    @property
    def rate_limits(self) -> RateLimitConfig:
        return RateLimitConfig(
            orders_per_second=1000,
            orders_per_minute=60000,
            data_requests_per_second=1000,
            max_ws_subscriptions=100000,
        )

    @property
    def is_connected(self) -> bool:
        return self._logged_in
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd backend && python -m pytest tests/brokers/test_paper.py -v`
Expected: All 16 tests PASS

- [ ] **Step 5: Commit**

```bash
git add backend/app/brokers/paper/ backend/tests/brokers/test_paper.py
git commit -m "feat(brokers): add PaperAdapter for simulated trading

Implements BrokerAdapter with in-memory order fills, configurable
slippage, position tracking, and margin accounting. Immediate fills
simulate market behavior for safe strategy testing.

Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>"
```

---

## Task 3: Adapter Conformance Test Suite

**Files:**
- Create: `backend/tests/brokers/test_conformance.py`

This generic test class runs against ANY BrokerAdapter implementation. Ensures all adapters behave identically for same inputs.

- [ ] **Step 1: Write conformance test suite**

```python
# backend/tests/brokers/test_conformance.py
"""
Conformance test suite for BrokerAdapter implementations.
Parameterized to run against every adapter. Ensures uniform behavior.
"""
import pytest
import asyncio
from app.brokers.base import (
    BrokerAdapter,
    UnifiedOrder,
    OrderResult,
    OrderStatus,
    Position,
    Holding,
    MarginInfo,
    AuthResult,
    AuthStatus,
    RateLimitConfig,
)


def make_paper_adapter():
    from app.brokers.paper.adapter import PaperAdapter
    return PaperAdapter(config={"initial_capital": 500000, "slippage_pct": 0.0})


# Add more adapters here as they're built:
# def make_zerodha_adapter(): ...
# def make_groww_adapter(): ...

ADAPTER_FACTORIES = [
    pytest.param(make_paper_adapter, id="paper"),
]


@pytest.fixture(params=ADAPTER_FACTORIES)
def adapter(request) -> BrokerAdapter:
    return request.param()


@pytest.mark.asyncio
async def test_conformance_is_broker_adapter(adapter):
    assert isinstance(adapter, BrokerAdapter)


@pytest.mark.asyncio
async def test_conformance_name_is_string(adapter):
    assert isinstance(adapter.name, str)
    assert len(adapter.name) > 0


@pytest.mark.asyncio
async def test_conformance_segments_is_list(adapter):
    segs = adapter.supported_segments
    assert isinstance(segs, list)
    assert len(segs) > 0
    assert all(isinstance(s, str) for s in segs)


@pytest.mark.asyncio
async def test_conformance_rate_limits(adapter):
    rl = adapter.rate_limits
    assert isinstance(rl, RateLimitConfig)
    assert rl.orders_per_second > 0


@pytest.mark.asyncio
async def test_conformance_login_returns_auth_result(adapter):
    result = await adapter.login({})
    assert isinstance(result, AuthResult)
    assert isinstance(result.success, bool)
    assert result.broker_name == adapter.name


@pytest.mark.asyncio
async def test_conformance_auth_status_after_login(adapter):
    await adapter.login({})
    status = await adapter.get_auth_status()
    assert isinstance(status, AuthStatus)
    assert status.is_valid is True
    assert status.broker_name == adapter.name


@pytest.mark.asyncio
async def test_conformance_place_order_returns_order_result(adapter):
    await adapter.login({})
    order = UnifiedOrder(
        symbol="TEST",
        exchange="NSE",
        segment="CASH",
        transaction_type="BUY",
        quantity=1,
        order_type="LIMIT",
        product="CNC",
        price=100.0,
    )
    result = await adapter.place_order(order)
    assert isinstance(result, OrderResult)
    assert result.broker_name == adapter.name
    assert isinstance(result.broker_order_id, str)
    assert len(result.broker_order_id) > 0


@pytest.mark.asyncio
async def test_conformance_get_orders_returns_list(adapter):
    await adapter.login({})
    orders = await adapter.get_orders()
    assert isinstance(orders, list)
    for o in orders:
        assert isinstance(o, OrderStatus)


@pytest.mark.asyncio
async def test_conformance_get_positions_returns_list(adapter):
    await adapter.login({})
    positions = await adapter.get_positions()
    assert isinstance(positions, list)
    for p in positions:
        assert isinstance(p, Position)


@pytest.mark.asyncio
async def test_conformance_get_holdings_returns_list(adapter):
    await adapter.login({})
    holdings = await adapter.get_holdings()
    assert isinstance(holdings, list)
    for h in holdings:
        assert isinstance(h, Holding)


@pytest.mark.asyncio
async def test_conformance_get_margins_returns_margin_info(adapter):
    await adapter.login({})
    margin = await adapter.get_margins()
    assert isinstance(margin, MarginInfo)
    assert margin.broker_name == adapter.name
    assert margin.total_margin >= 0


@pytest.mark.asyncio
async def test_conformance_get_ltp_returns_dict(adapter):
    await adapter.login({})
    ltp = await adapter.get_ltp(["TEST"])
    assert isinstance(ltp, dict)


@pytest.mark.asyncio
async def test_conformance_logout(adapter):
    await adapter.login({})
    await adapter.logout()
    status = await adapter.get_auth_status()
    assert status.is_valid is False
```

- [ ] **Step 2: Run conformance tests**

Run: `cd backend && python -m pytest tests/brokers/test_conformance.py -v`
Expected: All 13 tests PASS (for paper adapter)

- [ ] **Step 3: Commit**

```bash
git add backend/tests/brokers/test_conformance.py
git commit -m "test(brokers): add adapter conformance test suite

Generic parameterized tests that run against any BrokerAdapter.
Ensures all adapters return correct types and behave uniformly.
New adapters just add a factory to ADAPTER_FACTORIES.

Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>"
```

---

## Task 4: AccountManager

**Files:**
- Create: `backend/app/brokers/account_manager.py`
- Create: `backend/tests/brokers/test_account_manager.py`
- Create: `backend/config/accounts.yaml`

- [ ] **Step 1: Write AccountManager tests**

```python
# backend/tests/brokers/test_account_manager.py
"""Tests for AccountManager multi-account registry."""
import pytest
from app.brokers.base import BrokerAdapter, Position, MarginInfo
from app.brokers.paper.adapter import PaperAdapter


@pytest.fixture
def manager():
    from app.brokers.account_manager import AccountManager
    return AccountManager()


@pytest.fixture
def two_accounts(manager):
    paper1 = PaperAdapter(config={"initial_capital": 500000, "slippage_pct": 0})
    paper2 = PaperAdapter(config={"initial_capital": 300000, "slippage_pct": 0})
    manager.register("account_a", paper1, {"broker": "paper"})
    manager.register("account_b", paper2, {"broker": "paper"})
    return manager


def test_register_and_get(manager):
    adapter = PaperAdapter()
    manager.register("test_account", adapter, {"broker": "paper"})
    retrieved = manager.get_adapter("test_account")
    assert retrieved is adapter


def test_get_nonexistent_raises(manager):
    with pytest.raises(KeyError):
        manager.get_adapter("nonexistent")


def test_get_all_adapters(two_accounts):
    all_adapters = two_accounts.get_all_adapters()
    assert len(all_adapters) == 2
    assert "account_a" in all_adapters
    assert "account_b" in all_adapters


def test_get_adapters_by_broker(two_accounts):
    paper_adapters = two_accounts.get_adapters_by_broker("paper")
    assert len(paper_adapters) == 2


def test_get_adapters_by_broker_empty(two_accounts):
    result = two_accounts.get_adapters_by_broker("zerodha")
    assert len(result) == 0


def test_duplicate_registration_raises(manager):
    adapter = PaperAdapter()
    manager.register("dup", adapter, {"broker": "paper"})
    with pytest.raises(ValueError):
        manager.register("dup", adapter, {"broker": "paper"})


@pytest.mark.asyncio
async def test_get_all_positions(two_accounts):
    from app.brokers.base import UnifiedOrder
    # Login both
    for name in ["account_a", "account_b"]:
        await two_accounts.get_adapter(name).login({})

    # Place order on account_a
    order = UnifiedOrder(
        symbol="TEST", exchange="NSE", segment="CASH",
        transaction_type="BUY", quantity=10, order_type="LIMIT",
        product="CNC", price=100.0,
    )
    await two_accounts.get_adapter("account_a").place_order(order)

    all_pos = await two_accounts.get_all_positions()
    assert "account_a" in all_pos
    assert "account_b" in all_pos
    assert len(all_pos["account_a"]) == 1
    assert len(all_pos["account_b"]) == 0


@pytest.mark.asyncio
async def test_get_all_margins(two_accounts):
    for name in ["account_a", "account_b"]:
        await two_accounts.get_adapter(name).login({})

    all_margins = await two_accounts.get_all_margins()
    assert all_margins["account_a"].total_margin == 500000
    assert all_margins["account_b"].total_margin == 300000


@pytest.mark.asyncio
async def test_get_total_exposure(two_accounts):
    for name in ["account_a", "account_b"]:
        await two_accounts.get_adapter(name).login({})

    exposure = await two_accounts.get_total_exposure()
    assert exposure == 0.0  # No orders placed
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd backend && python -m pytest tests/brokers/test_account_manager.py -v`
Expected: FAIL — `ModuleNotFoundError`

- [ ] **Step 3: Implement AccountManager**

```python
# backend/app/brokers/account_manager.py
"""
Multi-account registry. Routes operations to correct broker adapter.
"""
import logging
from typing import Any

from app.brokers.base import BrokerAdapter, Position, MarginInfo

logger = logging.getLogger(__name__)


class AccountManager:
    """Registry for multiple broker accounts."""

    def __init__(self):
        self._adapters: dict[str, BrokerAdapter] = {}
        self._configs: dict[str, dict] = {}

    def register(self, account_name: str, adapter: BrokerAdapter, config: dict) -> None:
        """Register a broker adapter under a unique account name."""
        if account_name in self._adapters:
            raise ValueError(f"Account '{account_name}' already registered")
        self._adapters[account_name] = adapter
        self._configs[account_name] = config
        logger.info(f"Registered account: {account_name} (broker={adapter.name})")

    def get_adapter(self, account_name: str) -> BrokerAdapter:
        """Get adapter by account name. Raises KeyError if not found."""
        if account_name not in self._adapters:
            raise KeyError(f"Account '{account_name}' not registered")
        return self._adapters[account_name]

    def get_all_adapters(self) -> dict[str, BrokerAdapter]:
        """Get all registered adapters."""
        return dict(self._adapters)

    def get_adapters_by_broker(self, broker_name: str) -> list[BrokerAdapter]:
        """Get all adapters for a specific broker type."""
        return [a for a in self._adapters.values() if a.name == broker_name]

    def get_account_names(self) -> list[str]:
        """Get all registered account names."""
        return list(self._adapters.keys())

    # ── Cross-account queries ─────────────────────────

    async def get_all_positions(self) -> dict[str, list[Position]]:
        """Get positions across all accounts."""
        result = {}
        for name, adapter in self._adapters.items():
            try:
                result[name] = await adapter.get_positions()
            except Exception as e:
                logger.error(f"Failed to get positions for {name}: {e}")
                result[name] = []
        return result

    async def get_all_margins(self) -> dict[str, MarginInfo]:
        """Get margins across all accounts."""
        result = {}
        for name, adapter in self._adapters.items():
            try:
                result[name] = await adapter.get_margins()
            except Exception as e:
                logger.error(f"Failed to get margins for {name}: {e}")
        return result

    async def get_total_exposure(self) -> float:
        """Get total used margin across all accounts."""
        margins = await self.get_all_margins()
        return sum(m.used_margin for m in margins.values())
```

- [ ] **Step 4: Create accounts.yaml**

```yaml
# backend/config/accounts.yaml
# Account configuration — secrets referenced by env var names, never stored here.
accounts:
  zerodha_fno:
    broker: zerodha
    segments: [FNO]
    mode: paper
    credentials_env:
      api_key: ZERODHA_API_KEY
      api_secret: ZERODHA_API_SECRET

  groww_equity:
    broker: groww
    segments: [CASH]
    mode: paper
    credentials_env:
      api_key: GROWW_API_KEY
      totp_secret: GROWW_TOTP_SECRET

  paper_test:
    broker: paper
    segments: [CASH, FNO]
    mode: paper
    config:
      initial_capital: 1000000
      slippage_pct: 0.05
```

- [ ] **Step 5: Run tests**

Run: `cd backend && python -m pytest tests/brokers/test_account_manager.py -v`
Expected: All 9 tests PASS

- [ ] **Step 6: Commit**

```bash
git add backend/app/brokers/account_manager.py backend/tests/brokers/test_account_manager.py backend/config/accounts.yaml
git commit -m "feat(brokers): add AccountManager multi-account registry

Registers multiple BrokerAdapter instances by account name.
Cross-account queries for positions, margins, total exposure.
Includes accounts.yaml config template.

Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>"
```

---

## Task 5: Telegram Alerting

**Files:**
- Create: `backend/app/alerts/__init__.py`
- Create: `backend/app/alerts/telegram.py`
- Create: `backend/tests/alerts/__init__.py`
- Create: `backend/tests/alerts/test_telegram.py`
- Modify: `backend/app/config.py`

- [ ] **Step 1: Write Telegram alert tests**

```python
# backend/tests/alerts/__init__.py
"""Tests for alerting services."""

# backend/tests/alerts/test_telegram.py
"""Tests for Telegram alerting service."""
import pytest
from unittest.mock import AsyncMock, patch, MagicMock


@pytest.fixture
def alert_service():
    from app.alerts.telegram import TelegramAlertService
    return TelegramAlertService(bot_token="fake_token", chat_id="fake_chat_id")


@pytest.mark.asyncio
async def test_send_critical_alert(alert_service):
    with patch.object(alert_service, "_send_message", new_callable=AsyncMock) as mock_send:
        await alert_service.send_critical("zerodha_fno", "API DOWN after 3 retries")
        mock_send.assert_called_once()
        msg = mock_send.call_args[0][0]
        assert "CRITICAL" in msg
        assert "zerodha_fno" in msg
        assert "API DOWN" in msg


@pytest.mark.asyncio
async def test_send_warning_alert(alert_service):
    with patch.object(alert_service, "_send_message", new_callable=AsyncMock) as mock_send:
        await alert_service.send_warning("groww_equity", "Daily loss 80% reached")
        mock_send.assert_called_once()
        msg = mock_send.call_args[0][0]
        assert "WARNING" in msg


@pytest.mark.asyncio
async def test_send_info_alert(alert_service):
    with patch.object(alert_service, "_send_message", new_callable=AsyncMock) as mock_send:
        await alert_service.send_info("paper_test", "Strategy hit +₹10K milestone")
        mock_send.assert_called_once()


@pytest.mark.asyncio
async def test_send_daily_summary(alert_service):
    with patch.object(alert_service, "_send_message", new_callable=AsyncMock) as mock_send:
        summary = {
            "total_pnl": 5000.0,
            "trades_executed": 12,
            "decisions_logged": 450,
            "accounts_active": 3,
        }
        await alert_service.send_daily_summary(summary)
        mock_send.assert_called_once()
        msg = mock_send.call_args[0][0]
        assert "5000" in msg or "5,000" in msg


@pytest.mark.asyncio
async def test_disabled_when_no_token():
    from app.alerts.telegram import TelegramAlertService
    service = TelegramAlertService(bot_token="", chat_id="")
    # Should not raise, just log warning
    await service.send_critical("test", "test message")


@pytest.mark.asyncio
async def test_retry_on_failure(alert_service):
    call_count = 0

    async def failing_send(msg):
        nonlocal call_count
        call_count += 1
        if call_count < 3:
            raise Exception("Network error")

    with patch.object(alert_service, "_send_message", side_effect=failing_send):
        await alert_service.send_critical("test", "important message")
        assert call_count == 3  # retried twice after first failure
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd backend && python -m pytest tests/alerts/test_telegram.py -v`
Expected: FAIL

- [ ] **Step 3: Add config settings**

Add to `backend/app/config.py` after the `LLM_MODEL` field:

```python
    # Telegram Alerting
    TELEGRAM_BOT_TOKEN: Optional[str] = Field(default=None, description="Telegram bot token")
    TELEGRAM_CHAT_ID: Optional[str] = Field(default=None, description="Telegram chat ID")
    
    # Account Configuration
    ACCOUNTS_CONFIG_PATH: str = Field(
        default="config/accounts.yaml",
        description="Path to accounts YAML configuration"
    )
```

- [ ] **Step 4: Implement TelegramAlertService**

```python
# backend/app/alerts/__init__.py
"""Alerting services."""
from app.alerts.telegram import TelegramAlertService

__all__ = ["TelegramAlertService"]
```

```python
# backend/app/alerts/telegram.py
"""
Telegram alerting service for KALYX.
Sends critical, warning, and info alerts to configured Telegram chat.
Retry logic: 3 attempts with exponential backoff.
"""
import logging
import asyncio
from datetime import datetime

logger = logging.getLogger(__name__)


class TelegramAlertService:
    """Sends alerts to Telegram. Disabled gracefully if no token configured."""

    def __init__(self, bot_token: str, chat_id: str):
        self._bot_token = bot_token
        self._chat_id = chat_id
        self._enabled = bool(bot_token and chat_id)
        if not self._enabled:
            logger.warning("Telegram alerting disabled — no bot_token or chat_id")

    async def _send_message(self, text: str) -> None:
        """Send message to Telegram. Raises on failure."""
        if not self._enabled:
            return

        import httpx

        url = f"https://api.telegram.org/bot{self._bot_token}/sendMessage"
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.post(url, json={
                "chat_id": self._chat_id,
                "text": text,
                "parse_mode": "HTML",
            })
            resp.raise_for_status()

    async def _send_with_retry(self, text: str, max_retries: int = 3) -> None:
        """Send message with retry logic."""
        for attempt in range(max_retries):
            try:
                await self._send_message(text)
                return
            except Exception as e:
                if attempt < max_retries - 1:
                    wait = 2 ** attempt
                    logger.warning(f"Telegram send failed (attempt {attempt + 1}), retrying in {wait}s: {e}")
                    await asyncio.sleep(wait)
                else:
                    logger.error(f"Telegram send failed after {max_retries} attempts: {e}")

    async def send_critical(self, account_name: str, message: str) -> None:
        """Send critical alert — immediate."""
        ts = datetime.utcnow().strftime("%H:%M:%S UTC")
        text = f"🔴 <b>CRITICAL</b> [{account_name}] {ts}\n{message}"
        await self._send_with_retry(text)

    async def send_warning(self, account_name: str, message: str) -> None:
        """Send warning alert."""
        ts = datetime.utcnow().strftime("%H:%M:%S UTC")
        text = f"🟡 <b>WARNING</b> [{account_name}] {ts}\n{message}"
        await self._send_with_retry(text)

    async def send_info(self, account_name: str, message: str) -> None:
        """Send info alert."""
        ts = datetime.utcnow().strftime("%H:%M:%S UTC")
        text = f"🟢 <b>INFO</b> [{account_name}] {ts}\n{message}"
        await self._send_with_retry(text)

    async def send_daily_summary(self, summary: dict) -> None:
        """Send end-of-day summary."""
        pnl = summary.get("total_pnl", 0)
        trades = summary.get("trades_executed", 0)
        decisions = summary.get("decisions_logged", 0)
        accounts = summary.get("accounts_active", 0)
        emoji = "📈" if pnl >= 0 else "📉"
        text = (
            f"{emoji} <b>KALYX Daily Summary</b>\n"
            f"P&L: ₹{pnl:,.2f}\n"
            f"Trades: {trades}\n"
            f"Decisions logged: {decisions}\n"
            f"Active accounts: {accounts}"
        )
        await self._send_with_retry(text)
```

- [ ] **Step 5: Run tests**

Run: `cd backend && python -m pytest tests/alerts/test_telegram.py -v`
Expected: All 6 tests PASS

- [ ] **Step 6: Commit**

```bash
git add backend/app/alerts/ backend/tests/alerts/ backend/app/config.py
git commit -m "feat(alerts): add Telegram alerting with retry logic

Critical/warning/info alerts + daily summary. 3 retries with
exponential backoff. Graceful disable if no token configured.
Adds TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID, ACCOUNTS_CONFIG_PATH
to config.

Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>"
```

---

## Task 6: Decision Log Model + Logger Service

**Files:**
- Create: `backend/app/decisions/__init__.py`
- Create: `backend/app/decisions/models.py`
- Create: `backend/app/decisions/logger.py`
- Create: `backend/tests/decisions/__init__.py`
- Create: `backend/tests/decisions/test_models.py`
- Create: `backend/tests/decisions/test_logger.py`

- [ ] **Step 1: Write DecisionLog model tests**

```python
# backend/tests/decisions/__init__.py
"""Tests for decision logging."""

# backend/tests/decisions/test_models.py
"""Tests for DecisionLog SQLAlchemy model."""
import pytest
from app.decisions.models import DecisionAction


def test_decision_action_values():
    assert DecisionAction.EXECUTED == "executed"
    assert DecisionAction.SKIPPED == "skipped"
    assert DecisionAction.BLOCKED == "blocked"
    assert DecisionAction.REJECTED == "rejected"
    assert DecisionAction.FAILED == "failed"


def test_decision_action_is_string():
    assert isinstance(DecisionAction.EXECUTED, str)
    assert DecisionAction.EXECUTED == "executed"


def test_decision_log_model_columns():
    from app.decisions.models import DecisionLog
    columns = {c.name for c in DecisionLog.__table__.columns}
    expected = {
        "id", "timestamp", "account_name", "symbol", "signal",
        "strategy_id", "confidence", "market_state", "action",
        "reasoning", "skip_reason", "trade_id",
        "outcome_if_taken", "outcome_actual", "was_correct",
        "trade_context",
    }
    assert expected.issubset(columns)
```

- [ ] **Step 2: Write DecisionLogger tests**

```python
# backend/tests/decisions/test_logger.py
"""Tests for DecisionLogger service."""
import pytest
import tempfile
import os
from unittest.mock import AsyncMock, MagicMock, patch
from app.decisions.models import DecisionAction


@pytest.fixture
def tmp_log_dir():
    with tempfile.TemporaryDirectory() as d:
        yield d


@pytest.fixture
def mock_db():
    db = MagicMock()
    db.add = MagicMock()
    db.commit = MagicMock()
    db.refresh = MagicMock()
    return db


@pytest.fixture
def decision_logger(mock_db, tmp_log_dir):
    from app.decisions.logger import DecisionLogger
    return DecisionLogger(
        db=mock_db,
        log_base_dir=tmp_log_dir,
        alert_service=None,
    )


@pytest.mark.asyncio
async def test_log_executed_decision(decision_logger, mock_db):
    decision_id = await decision_logger.log_decision(
        account_name="paper_test",
        symbol="NIFTY25APR24500CE",
        signal="BUY",
        action=DecisionAction.EXECUTED,
        confidence=0.85,
        reasoning="RSI oversold + MACD bullish",
        market_state={"ltp": 150.0, "rsi": 28},
        strategy_id=1,
        trade_id=42,
    )
    mock_db.add.assert_called_once()
    mock_db.commit.assert_called_once()


@pytest.mark.asyncio
async def test_log_skipped_decision(decision_logger, mock_db):
    await decision_logger.log_decision(
        account_name="paper_test",
        symbol="RELIANCE",
        signal="HOLD",
        action=DecisionAction.SKIPPED,
        confidence=0.3,
        reasoning="No signal",
        market_state={"ltp": 2500.0},
        skip_reason="no_signal",
    )
    mock_db.add.assert_called_once()


@pytest.mark.asyncio
async def test_log_blocked_decision(decision_logger, mock_db):
    await decision_logger.log_decision(
        account_name="zerodha_fno",
        symbol="BANKNIFTY",
        signal="BUY",
        action=DecisionAction.BLOCKED,
        confidence=0.9,
        reasoning="Strong signal",
        market_state={"ltp": 52000},
        skip_reason="guardian:daily_loss_80pct",
    )
    mock_db.add.assert_called_once()


@pytest.mark.asyncio
async def test_log_writes_to_file(decision_logger, tmp_log_dir):
    await decision_logger.log_decision(
        account_name="paper_test",
        symbol="TEST",
        signal="BUY",
        action=DecisionAction.EXECUTED,
        confidence=0.7,
        reasoning="test",
        market_state={},
    )
    # Check log file created
    account_dir = os.path.join(tmp_log_dir, "accounts", "paper_test")
    assert os.path.isdir(account_dir)
    log_files = os.listdir(account_dir)
    assert any(f.startswith("decisions-") for f in log_files)


@pytest.mark.asyncio
async def test_fill_hindsight(decision_logger, mock_db):
    mock_db.query = MagicMock()
    mock_entry = MagicMock()
    mock_db.query.return_value.filter.return_value.first.return_value = mock_entry

    await decision_logger.fill_hindsight(
        decision_id=1,
        outcome_if_taken=5000.0,
        outcome_actual=0.0,
    )
    assert mock_entry.outcome_if_taken == 5000.0
    assert mock_entry.outcome_actual == 0.0
    assert mock_entry.was_correct is False
    mock_db.commit.assert_called_once()
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `cd backend && python -m pytest tests/decisions/ -v`
Expected: FAIL

- [ ] **Step 4: Implement DecisionLog model**

```python
# backend/app/decisions/__init__.py
"""Decision logging — every signal, every outcome."""
from app.decisions.models import DecisionLog, DecisionAction

__all__ = ["DecisionLog", "DecisionAction"]
```

```python
# backend/app/decisions/models.py
"""
DecisionLog SQLAlchemy model.
Stores every trading decision — executed, skipped, blocked, rejected, failed.
"""
from enum import Enum as PyEnum
from sqlalchemy import (
    Column, Integer, String, Float, DateTime, Boolean, JSON, Text, ForeignKey,
)
from sqlalchemy.sql import func

from app.data.database import Base


class DecisionAction(str, PyEnum):
    """Decision outcome types."""
    EXECUTED = "executed"
    SKIPPED = "skipped"
    BLOCKED = "blocked"
    REJECTED = "rejected"
    FAILED = "failed"


class DecisionLog(Base):
    """Every trading decision is logged here — taken or not."""
    __tablename__ = "decision_log"

    id = Column(Integer, primary_key=True, index=True)
    timestamp = Column(DateTime(timezone=True), server_default=func.now(), index=True)
    account_name = Column(String, index=True)

    # What was evaluated
    symbol = Column(String, index=True)
    signal = Column(String)
    strategy_id = Column(Integer, ForeignKey("strategies.id"), nullable=True)
    confidence = Column(Float)

    # Market snapshot
    market_state = Column(JSON)

    # Decision
    action = Column(String, index=True)
    reasoning = Column(Text)

    # Skip/block reason
    skip_reason = Column(String, nullable=True)

    # Trade link
    trade_id = Column(Integer, ForeignKey("trades.id"), nullable=True)

    # Hindsight (filled later by Memory Agent)
    outcome_if_taken = Column(Float, nullable=True)
    outcome_actual = Column(Float, nullable=True)
    was_correct = Column(Boolean, nullable=True)

    # Full context blob
    trade_context = Column(JSON, nullable=True)
```

- [ ] **Step 5: Implement DecisionLogger service**

```python
# backend/app/decisions/logger.py
"""
DecisionLogger — writes every decision to DB + structured log file.
Triggers Telegram alerts on failures.
"""
import os
import json
import logging
from datetime import datetime, date
from typing import Any
from sqlalchemy.orm import Session

from app.decisions.models import DecisionLog, DecisionAction

logger = logging.getLogger(__name__)


class DecisionLogger:
    """Logs every trading decision to PostgreSQL and per-account log files."""

    def __init__(self, db: Session, log_base_dir: str = "logs", alert_service: Any = None):
        self._db = db
        self._log_base_dir = log_base_dir
        self._alert_service = alert_service

    async def log_decision(
        self,
        account_name: str,
        symbol: str,
        signal: str,
        action: DecisionAction,
        confidence: float,
        reasoning: str,
        market_state: dict,
        strategy_id: int | None = None,
        skip_reason: str | None = None,
        trade_id: int | None = None,
        context: Any = None,
    ) -> int:
        """Log decision to DB + file. Returns decision ID."""

        # 1. Write to PostgreSQL
        entry = DecisionLog(
            account_name=account_name,
            symbol=symbol,
            signal=signal,
            strategy_id=strategy_id,
            confidence=confidence,
            market_state=market_state,
            action=action.value if isinstance(action, DecisionAction) else action,
            reasoning=reasoning,
            skip_reason=skip_reason,
            trade_id=trade_id,
            trade_context=self._serialize_context(context),
        )
        self._db.add(entry)
        self._db.commit()
        self._db.refresh(entry)

        # 2. Write to per-account log file
        self._write_log_file(account_name, entry)

        # 3. Alert on failure/rejection
        if action in (DecisionAction.FAILED, DecisionAction.REJECTED) and self._alert_service:
            try:
                await self._alert_service.send_warning(
                    account_name,
                    f"Decision {action.value}: {symbol} {signal} — {reasoning}",
                )
            except Exception as e:
                logger.error(f"Failed to send alert: {e}")

        return entry.id

    async def fill_hindsight(
        self,
        decision_id: int,
        outcome_if_taken: float,
        outcome_actual: float,
    ) -> None:
        """Fill in hindsight data for a past decision."""
        entry = self._db.query(DecisionLog).filter(DecisionLog.id == decision_id).first()
        if entry:
            entry.outcome_if_taken = outcome_if_taken
            entry.outcome_actual = outcome_actual
            entry.was_correct = (
                (outcome_actual >= 0 and entry.action == DecisionAction.EXECUTED.value)
                or (outcome_if_taken <= 0 and entry.action != DecisionAction.EXECUTED.value)
            )
            self._db.commit()

    def _write_log_file(self, account_name: str, entry: DecisionLog) -> None:
        """Write JSON log line to per-account decisions log file."""
        account_dir = os.path.join(self._log_base_dir, "accounts", account_name)
        os.makedirs(account_dir, exist_ok=True)

        today = date.today().isoformat()
        log_path = os.path.join(account_dir, f"decisions-{today}.log")

        log_data = {
            "ts": datetime.utcnow().isoformat() + "Z",
            "level": "INFO",
            "account": account_name,
            "event": "decision",
            "symbol": entry.symbol,
            "signal": entry.signal,
            "action": entry.action,
            "confidence": entry.confidence,
            "reasoning": entry.reasoning,
            "skip_reason": entry.skip_reason,
            "strategy_id": entry.strategy_id,
            "trade_id": entry.trade_id,
        }

        try:
            with open(log_path, "a") as f:
                f.write(json.dumps(log_data) + "\n")
        except Exception as e:
            logger.error(f"Failed to write decision log file: {e}")

    def _serialize_context(self, context: Any) -> dict | None:
        """Serialize TradeContext to dict for JSON storage."""
        if context is None:
            return None
        if hasattr(context, "__dict__"):
            data = {}
            for k, v in context.__dict__.items():
                if isinstance(v, datetime):
                    data[k] = v.isoformat()
                else:
                    data[k] = v
            return data
        return None
```

- [ ] **Step 6: Run tests**

Run: `cd backend && python -m pytest tests/decisions/ -v`
Expected: All 7 tests PASS

- [ ] **Step 7: Commit**

```bash
git add backend/app/decisions/ backend/tests/decisions/
git commit -m "feat(decisions): add DecisionLog model + DecisionLogger service

Every trading decision logged to PostgreSQL + per-account JSON log files.
Captures: executed, skipped, blocked, rejected, failed decisions with
full market state, reasoning, and confidence. Hindsight fill for
post-session analysis. Telegram alerts on failures.

Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>"
```

---

## Task 7: ZerodhaAdapter (Refactor Existing Code)

**Files:**
- Create: `backend/app/brokers/zerodha/__init__.py`
- Create: `backend/app/brokers/zerodha/adapter.py`
- Create: `backend/app/brokers/zerodha/auth.py`
- Create: `backend/app/brokers/zerodha/feed.py`
- Create: `backend/tests/brokers/test_zerodha.py`

- [ ] **Step 1: Write ZerodhaAdapter tests (mocked KiteConnect)**

```python
# backend/tests/brokers/test_zerodha.py
"""Tests for ZerodhaAdapter with mocked KiteConnect SDK."""
import pytest
from unittest.mock import MagicMock, AsyncMock, patch
from app.brokers.base import (
    BrokerAdapter, UnifiedOrder, OrderResult, Position, MarginInfo, AuthResult,
)


@pytest.fixture
def mock_kite():
    kite = MagicMock()
    kite.generate_session.return_value = {
        "access_token": "test_access_token",
        "public_token": "test_public_token",
        "user_id": "AB1234",
    }
    kite.profile.return_value = {"user_id": "AB1234"}
    kite.place_order.return_value = {"order_id": "ZRD123456"}
    kite.positions.return_value = {
        "net": [
            {
                "tradingsymbol": "NIFTY25APR24500CE",
                "exchange": "NFO",
                "quantity": 50,
                "average_price": 150.0,
                "last_price": 160.0,
                "pnl": 500.0,
                "product": "MIS",
            }
        ]
    }
    kite.margins.return_value = {
        "equity": {"available": {"cash": 500000.0}, "utilised": {"debits": 200000.0}}
    }
    kite.instruments.return_value = [
        {
            "tradingsymbol": "NIFTY25APR24500CE",
            "instrument_token": 12345,
            "exchange": "NFO",
            "segment": "NFO-OPT",
            "instrument_type": "CE",
            "lot_size": 50,
            "tick_size": 0.05,
            "expiry": "2025-04-24",
            "strike": 24500.0,
        }
    ]
    return kite


@pytest.fixture
def zerodha_adapter(mock_kite):
    with patch("app.brokers.zerodha.auth.KiteConnect", return_value=mock_kite):
        from app.brokers.zerodha.adapter import ZerodhaAdapter
        adapter = ZerodhaAdapter(api_key="test_key", api_secret="test_secret")
        adapter._kite = mock_kite
        adapter._logged_in = True
        return adapter


def test_zerodha_is_broker_adapter(zerodha_adapter):
    assert isinstance(zerodha_adapter, BrokerAdapter)


def test_zerodha_name(zerodha_adapter):
    assert zerodha_adapter.name == "zerodha"


def test_zerodha_segments(zerodha_adapter):
    assert "CASH" in zerodha_adapter.supported_segments
    assert "FNO" in zerodha_adapter.supported_segments


@pytest.mark.asyncio
async def test_zerodha_place_order(zerodha_adapter, mock_kite):
    order = UnifiedOrder(
        symbol="NIFTY25APR24500CE", exchange="NFO", segment="FNO",
        transaction_type="BUY", quantity=50, order_type="MARKET", product="MIS",
    )
    result = await zerodha_adapter.place_order(order)
    assert isinstance(result, OrderResult)
    assert result.broker_name == "zerodha"
    mock_kite.place_order.assert_called_once()


@pytest.mark.asyncio
async def test_zerodha_get_positions(zerodha_adapter):
    positions = await zerodha_adapter.get_positions()
    assert len(positions) == 1
    assert isinstance(positions[0], Position)
    assert positions[0].symbol == "NIFTY25APR24500CE"
    assert positions[0].broker_name == "zerodha"


@pytest.mark.asyncio
async def test_zerodha_get_margins(zerodha_adapter):
    margin = await zerodha_adapter.get_margins()
    assert isinstance(margin, MarginInfo)
    assert margin.broker_name == "zerodha"
    assert margin.available_cash == 500000.0


@pytest.mark.asyncio
async def test_zerodha_cancel_order(zerodha_adapter, mock_kite):
    mock_kite.cancel_order.return_value = None
    result = await zerodha_adapter.cancel_order("ZRD123", "FNO")
    assert result == "ZRD123"
    mock_kite.cancel_order.assert_called_once()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd backend && python -m pytest tests/brokers/test_zerodha.py -v`
Expected: FAIL

- [ ] **Step 3: Implement ZerodhaAdapter auth module**

```python
# backend/app/brokers/zerodha/__init__.py
"""Zerodha Kite Connect broker adapter."""
from app.brokers.zerodha.adapter import ZerodhaAdapter

__all__ = ["ZerodhaAdapter"]
```

```python
# backend/app/brokers/zerodha/auth.py
"""
Zerodha authentication — refactored from app/auth/service.py.
Handles token encryption, Redis storage, session management.
"""
import logging
import base64
import hashlib
from typing import Optional
from datetime import datetime
from kiteconnect import KiteConnect
from cryptography.fernet import Fernet

from app.config import settings
from app.data.redis_client import get_redis

logger = logging.getLogger(__name__)


class ZerodhaAuth:
    """Manages Zerodha authentication and token lifecycle."""

    def __init__(self, api_key: str, api_secret: str):
        self.api_key = api_key
        self.api_secret = api_secret
        self.kite: Optional[KiteConnect] = None
        self._encryption_key = self._get_encryption_key()

    def _get_encryption_key(self) -> bytes:
        if settings.ENCRYPTION_KEY:
            return base64.urlsafe_b64decode(settings.ENCRYPTION_KEY.encode())
        key = hashlib.sha256(settings.SECRET_KEY.encode()).digest()
        return base64.urlsafe_b64encode(key)[:32]

    def _encrypt_token(self, token: str) -> str:
        f = Fernet(self._encryption_key)
        return f.encrypt(token.encode()).decode()

    def _decrypt_token(self, encrypted_token: str) -> str:
        f = Fernet(self._encryption_key)
        return f.decrypt(encrypted_token.encode()).decode()

    async def login(self, request_token: str) -> dict:
        """Generate session from request token, store encrypted in Redis."""
        kite = KiteConnect(api_key=self.api_key)
        data = kite.generate_session(request_token, api_secret=self.api_secret)

        access_token = data["access_token"]
        public_token = data.get("public_token", "")
        user_id = data.get("user_id", "")

        redis = get_redis()
        await redis.setex("zerodha:access_token", 86400, self._encrypt_token(access_token))
        await redis.setex("zerodha:public_token", 86400, self._encrypt_token(public_token))
        await redis.setex("zerodha:user_id", 86400, user_id)
        await redis.set("zerodha:login_time", datetime.utcnow().isoformat())

        self.kite = KiteConnect(api_key=self.api_key)
        self.kite.set_access_token(access_token)

        return {"access_token": access_token, "user_id": user_id}

    async def get_access_token(self) -> Optional[str]:
        """Get decrypted access token from Redis."""
        redis = get_redis()
        enc = await redis.get("zerodha:access_token")
        if enc:
            return self._decrypt_token(enc)
        return None

    def get_kite_client(self) -> Optional[KiteConnect]:
        """Get or initialize KiteConnect client."""
        if self.kite:
            return self.kite
        try:
            redis = get_redis()
            enc = redis.get("zerodha:access_token")
            if enc:
                token = self._decrypt_token(enc)
                self.kite = KiteConnect(api_key=self.api_key)
                self.kite.set_access_token(token)
                return self.kite
        except Exception as e:
            logger.error(f"Failed to init Kite client: {e}")
        return None

    async def logout(self) -> None:
        redis = get_redis()
        for key in ["zerodha:access_token", "zerodha:public_token", "zerodha:user_id", "zerodha:login_time"]:
            await redis.delete(key)
        self.kite = None
```

- [ ] **Step 4: Implement ZerodhaAdapter**

```python
# backend/app/brokers/zerodha/adapter.py
"""
ZerodhaAdapter — BrokerAdapter implementation for Zerodha Kite Connect.
Refactored from app/auth/service.py, app/execution/service.py, app/auth/websocket_client.py.
"""
import logging
import asyncio
from datetime import datetime
from typing import Optional

from app.brokers.base import (
    BrokerAdapter,
    UnifiedOrder,
    OrderResult,
    OrderStatus,
    Position,
    Holding,
    MarginInfo,
    Quote,
    Instrument,
    AuthResult,
    AuthStatus,
    RateLimitConfig,
    TickCallback,
    BrokerError,
    BrokerUnavailableError,
    OrderRejectedError,
)

logger = logging.getLogger(__name__)


class ZerodhaAdapter(BrokerAdapter):
    """Zerodha Kite Connect adapter."""

    def __init__(self, api_key: str, api_secret: str):
        self._api_key = api_key
        self._api_secret = api_secret
        self._kite = None  # KiteConnect instance
        self._logged_in = False
        self._rate_limit_delay = 0.1  # 100ms between orders

    def _get_kite(self):
        if not self._kite:
            raise BrokerUnavailableError("zerodha", RuntimeError("Not logged in"), "Kite client not initialized")
        return self._kite

    # ── Auth ──────────────────────────────────────────

    async def login(self, credentials: dict) -> AuthResult:
        from kiteconnect import KiteConnect
        try:
            request_token = credentials.get("request_token", "")
            kite = KiteConnect(api_key=self._api_key)
            data = kite.generate_session(request_token, api_secret=self._api_secret)
            kite.set_access_token(data["access_token"])
            self._kite = kite
            self._logged_in = True
            user_id = data.get("user_id", "")
            logger.info(f"Zerodha login successful. User: {user_id}")
            return AuthResult(success=True, user_id=user_id, broker_name="zerodha", message="Login successful")
        except Exception as e:
            logger.error(f"Zerodha login failed: {e}")
            return AuthResult(success=False, user_id="", broker_name="zerodha", message=str(e))

    async def logout(self) -> None:
        self._kite = None
        self._logged_in = False

    async def get_auth_status(self) -> AuthStatus:
        if not self._logged_in or not self._kite:
            return AuthStatus(is_valid=False, user_id=None, broker_name="zerodha", expires_at=None)
        try:
            profile = self._kite.profile()
            return AuthStatus(
                is_valid=True, user_id=profile.get("user_id"),
                broker_name="zerodha", expires_at=None,
            )
        except Exception:
            return AuthStatus(is_valid=False, user_id=None, broker_name="zerodha", expires_at=None)

    # ── Orders ────────────────────────────────────────

    async def place_order(self, order: UnifiedOrder) -> OrderResult:
        kite = self._get_kite()
        params = {
            "tradingsymbol": order.symbol,
            "exchange": order.exchange,
            "transaction_type": order.transaction_type,
            "quantity": order.quantity,
            "order_type": order.order_type,
            "product": order.product,
        }
        if order.price is not None:
            params["price"] = order.price
        if order.trigger_price is not None:
            params["trigger_price"] = order.trigger_price

        try:
            response = kite.place_order(**params)
            order_id = response if isinstance(response, str) else response.get("order_id", str(response))
            return OrderResult(
                broker_order_id=str(order_id), status="PENDING",
                broker_name="zerodha", raw_response={"order_id": order_id},
            )
        except Exception as e:
            raise OrderRejectedError("zerodha", e, str(e))

    async def modify_order(self, order_id: str, changes: dict) -> OrderResult:
        kite = self._get_kite()
        try:
            kite.modify_order(order_id=order_id, **changes)
            return OrderResult(broker_order_id=order_id, status="MODIFIED", broker_name="zerodha", raw_response=changes)
        except Exception as e:
            raise OrderRejectedError("zerodha", e, str(e))

    async def cancel_order(self, order_id: str, segment: str) -> str:
        kite = self._get_kite()
        kite.cancel_order(variety="regular", order_id=order_id)
        return order_id

    async def get_order_status(self, order_id: str) -> OrderStatus:
        kite = self._get_kite()
        orders = kite.orders()
        for o in orders:
            if str(o.get("order_id")) == order_id:
                return OrderStatus(
                    broker_order_id=order_id, symbol=o.get("tradingsymbol", ""),
                    status=o.get("status", ""), quantity=o.get("quantity", 0),
                    filled_quantity=o.get("filled_quantity", 0),
                    average_price=o.get("average_price"), order_type=o.get("order_type", ""),
                    transaction_type=o.get("transaction_type", ""), broker_name="zerodha",
                )
        return OrderStatus(
            broker_order_id=order_id, symbol="", status="NOT_FOUND",
            quantity=0, filled_quantity=0, average_price=None,
            order_type="", transaction_type="", broker_name="zerodha",
        )

    async def get_orders(self) -> list[OrderStatus]:
        kite = self._get_kite()
        orders = kite.orders()
        return [
            OrderStatus(
                broker_order_id=str(o.get("order_id", "")), symbol=o.get("tradingsymbol", ""),
                status=o.get("status", ""), quantity=o.get("quantity", 0),
                filled_quantity=o.get("filled_quantity", 0), average_price=o.get("average_price"),
                order_type=o.get("order_type", ""), transaction_type=o.get("transaction_type", ""),
                broker_name="zerodha",
            )
            for o in orders
        ]

    # ── Portfolio ─────────────────────────────────────

    async def get_positions(self) -> list[Position]:
        kite = self._get_kite()
        positions = kite.positions()
        net = positions.get("net", [])
        return [
            Position(
                symbol=p.get("tradingsymbol", ""), exchange=p.get("exchange", ""),
                segment="FNO" if p.get("exchange") == "NFO" else "CASH",
                quantity=p.get("quantity", 0), average_price=p.get("average_price", 0),
                last_price=p.get("last_price", 0), pnl=p.get("pnl", 0),
                product=p.get("product", ""), broker_name="zerodha",
            )
            for p in net if p.get("quantity", 0) != 0
        ]

    async def get_holdings(self) -> list[Holding]:
        kite = self._get_kite()
        try:
            holdings = kite.holdings()
            return [
                Holding(
                    symbol=h.get("tradingsymbol", ""), isin=h.get("isin"),
                    quantity=h.get("quantity", 0), average_price=h.get("average_price", 0),
                    last_price=h.get("last_price", 0), pnl=h.get("pnl", 0),
                    broker_name="zerodha",
                )
                for h in holdings
            ]
        except Exception:
            return []

    async def get_margins(self) -> MarginInfo:
        kite = self._get_kite()
        margins = kite.margins()
        equity = margins.get("equity", {})
        available = equity.get("available", {}).get("cash", 0.0)
        used = equity.get("utilised", {}).get("debits", 0.0)
        return MarginInfo(
            available_cash=available, used_margin=used, total_margin=available + used,
            broker_name="zerodha", raw=margins,
        )

    # ── Market Data ───────────────────────────────────

    async def get_ltp(self, symbols: list[str]) -> dict[str, float]:
        kite = self._get_kite()
        formatted = [f"NFO:{s}" if "CE" in s or "PE" in s or "FUT" in s else f"NSE:{s}" for s in symbols]
        data = kite.ltp(formatted)
        return {k.split(":")[-1]: v.get("last_price", 0) for k, v in data.items()}

    async def get_quote(self, symbol: str, exchange: str, segment: str) -> Quote:
        kite = self._get_kite()
        key = f"{exchange}:{symbol}"
        data = kite.quote([key])
        q = data.get(key, {})
        ohlc = q.get("ohlc", {})
        return Quote(
            symbol=symbol, exchange=exchange, ltp=q.get("last_price", 0),
            open=ohlc.get("open", 0), high=ohlc.get("high", 0),
            low=ohlc.get("low", 0), close=ohlc.get("close", 0),
            volume=q.get("volume", 0), bid=q.get("depth", {}).get("buy", [{}])[0].get("price"),
            ask=q.get("depth", {}).get("sell", [{}])[0].get("price"),
            oi=q.get("oi"), broker_name="zerodha",
        )

    async def get_instruments(self, exchange: str | None = None) -> list[Instrument]:
        kite = self._get_kite()
        instruments = kite.instruments(exchange) if exchange else kite.instruments()
        return [
            Instrument(
                symbol=i.get("tradingsymbol", ""), exchange=i.get("exchange", ""),
                segment=i.get("segment", ""), instrument_type=i.get("instrument_type", "EQ"),
                lot_size=i.get("lot_size", 1), tick_size=i.get("tick_size", 0.05),
                expiry=i.get("expiry"), strike=i.get("strike"),
                broker_name="zerodha",
            )
            for i in instruments
        ]

    # ── Live Feed ─────────────────────────────────────

    async def subscribe_ticks(self, symbols: list[str], callback: TickCallback) -> None:
        logger.info(f"Zerodha tick subscription: {len(symbols)} symbols (stub — use feed.py for full impl)")

    async def unsubscribe_ticks(self, symbols: list[str]) -> None:
        pass

    async def disconnect_feed(self) -> None:
        pass

    # ── Metadata ──────────────────────────────────────

    @property
    def name(self) -> str:
        return "zerodha"

    @property
    def supported_segments(self) -> list[str]:
        return ["CASH", "FNO", "COMMODITY"]

    @property
    def rate_limits(self) -> RateLimitConfig:
        return RateLimitConfig(
            orders_per_second=10, orders_per_minute=400,
            data_requests_per_second=10, max_ws_subscriptions=3000,
        )

    @property
    def is_connected(self) -> bool:
        return self._logged_in
```

- [ ] **Step 5: Create feed.py stub** (full KiteTicker integration kept separate)

```python
# backend/app/brokers/zerodha/feed.py
"""
Zerodha WebSocket feed — refactored from app/auth/websocket_client.py.
Full implementation uses KiteTicker. This is the adapter wrapper.
"""
import logging
from typing import Callable, Optional
from app.brokers.base import TickCallback

logger = logging.getLogger(__name__)


class ZerodhaFeed:
    """Wraps KiteTicker for live market data."""

    def __init__(self, api_key: str, access_token: str):
        self._api_key = api_key
        self._access_token = access_token
        self._kws = None
        self._connected = False
        self._callbacks: dict[str, TickCallback] = {}

    async def connect(self) -> None:
        from kiteconnect import KiteTicker
        self._kws = KiteTicker(self._api_key, self._access_token)
        self._kws.on_ticks = self._on_ticks
        self._kws.on_connect = self._on_connect
        self._kws.on_close = self._on_close
        self._kws.connect(threaded=True)
        self._connected = True
        logger.info("Zerodha WebSocket connected")

    def _on_ticks(self, ws, ticks):
        for tick in ticks:
            token = str(tick.get("instrument_token", ""))
            if token in self._callbacks:
                self._callbacks[token](tick)

    def _on_connect(self, ws, response):
        self._connected = True

    def _on_close(self, ws, code, reason):
        self._connected = False

    def subscribe(self, instrument_tokens: list[int], callback: TickCallback) -> None:
        if self._kws:
            self._kws.subscribe(instrument_tokens)
            for token in instrument_tokens:
                self._callbacks[str(token)] = callback

    def unsubscribe(self, instrument_tokens: list[int]) -> None:
        if self._kws:
            self._kws.unsubscribe(instrument_tokens)
            for token in instrument_tokens:
                self._callbacks.pop(str(token), None)

    async def disconnect(self) -> None:
        if self._kws:
            self._kws.close()
            self._connected = False
```

- [ ] **Step 6: Run tests**

Run: `cd backend && python -m pytest tests/brokers/test_zerodha.py -v`
Expected: All 7 tests PASS

- [ ] **Step 7: Add ZerodhaAdapter to conformance suite**

Add to `backend/tests/brokers/test_conformance.py`:

```python
def make_zerodha_adapter():
    from unittest.mock import MagicMock, patch
    mock_kite = MagicMock()
    mock_kite.generate_session.return_value = {"access_token": "t", "user_id": "U"}
    mock_kite.profile.return_value = {"user_id": "U"}
    mock_kite.place_order.return_value = {"order_id": "Z1"}
    mock_kite.positions.return_value = {"net": []}
    mock_kite.margins.return_value = {"equity": {"available": {"cash": 100000}, "utilised": {"debits": 0}}}
    mock_kite.orders.return_value = []
    mock_kite.holdings.return_value = []
    mock_kite.ltp.return_value = {}
    with patch("app.brokers.zerodha.adapter.BrokerUnavailableError"):
        pass
    from app.brokers.zerodha.adapter import ZerodhaAdapter
    adapter = ZerodhaAdapter(api_key="k", api_secret="s")
    adapter._kite = mock_kite
    adapter._logged_in = True
    return adapter


ADAPTER_FACTORIES = [
    pytest.param(make_paper_adapter, id="paper"),
    pytest.param(make_zerodha_adapter, id="zerodha"),
]
```

- [ ] **Step 8: Run conformance tests**

Run: `cd backend && python -m pytest tests/brokers/test_conformance.py -v`
Expected: All tests PASS for both paper and zerodha

- [ ] **Step 9: Commit**

```bash
git add backend/app/brokers/zerodha/ backend/tests/brokers/test_zerodha.py backend/tests/brokers/test_conformance.py
git commit -m "feat(brokers): add ZerodhaAdapter refactored from existing Kite code

Implements BrokerAdapter for Zerodha Kite Connect. Auth, orders,
positions, margins, market data, instruments all translated to
unified models. Feed module wraps KiteTicker. Passes conformance
test suite.

Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>"
```

---

## Task 8: GrowwAdapter

**Files:**
- Create: `backend/app/brokers/groww/__init__.py`
- Create: `backend/app/brokers/groww/adapter.py`
- Create: `backend/app/brokers/groww/auth.py`
- Create: `backend/app/brokers/groww/feed.py`
- Create: `backend/tests/brokers/test_groww.py`

- [ ] **Step 1: Write GrowwAdapter tests (mocked growwapi SDK)**

```python
# backend/tests/brokers/test_groww.py
"""Tests for GrowwAdapter with mocked growwapi SDK."""
import pytest
from unittest.mock import MagicMock, patch
from app.brokers.base import (
    BrokerAdapter, UnifiedOrder, OrderResult, Position, MarginInfo,
)


@pytest.fixture
def mock_groww():
    g = MagicMock()
    g.place_order.return_value = {"groww_order_id": "GRW123", "order_status": "OPEN"}
    g.get_positions_for_user.return_value = [
        {
            "trading_symbol": "RELIANCE", "segment": "CASH", "exchange": "NSE",
            "quantity": 10, "net_price": 2500.0, "credit_price": 2500.0,
            "debit_price": 0.0, "product": "CNC", "realised_pnl": 0,
        }
    ]
    g.get_available_margin_details.return_value = {
        "clear_cash": 400000.0, "net_margin_used": 100000.0,
    }
    g.cancel_order.return_value = {"groww_order_id": "GRW123", "order_status": "CANCELLED"}
    g.get_order_list.return_value = {"order_list": []}
    g.get_holdings_for_user.return_value = []
    g.get_ltp.return_value = {"NSE_RELIANCE": 2550.0}
    g.get_all_instruments.return_value = MagicMock()  # DataFrame mock
    return g


@pytest.fixture
def groww_adapter(mock_groww):
    with patch("app.brokers.groww.adapter.GrowwAPI", return_value=mock_groww):
        from app.brokers.groww.adapter import GrowwAdapter
        adapter = GrowwAdapter()
        adapter._client = mock_groww
        adapter._logged_in = True
        return adapter


def test_groww_is_broker_adapter(groww_adapter):
    assert isinstance(groww_adapter, BrokerAdapter)


def test_groww_name(groww_adapter):
    assert groww_adapter.name == "groww"


@pytest.mark.asyncio
async def test_groww_place_order(groww_adapter, mock_groww):
    order = UnifiedOrder(
        symbol="RELIANCE", exchange="NSE", segment="CASH",
        transaction_type="BUY", quantity=1, order_type="LIMIT",
        product="CNC", price=2500.0,
    )
    result = await groww_adapter.place_order(order)
    assert isinstance(result, OrderResult)
    assert result.broker_name == "groww"
    assert result.broker_order_id == "GRW123"


@pytest.mark.asyncio
async def test_groww_get_positions(groww_adapter):
    positions = await groww_adapter.get_positions()
    assert len(positions) >= 1
    assert positions[0].broker_name == "groww"


@pytest.mark.asyncio
async def test_groww_get_margins(groww_adapter):
    margin = await groww_adapter.get_margins()
    assert isinstance(margin, MarginInfo)
    assert margin.broker_name == "groww"
    assert margin.available_cash == 400000.0


@pytest.mark.asyncio
async def test_groww_cancel_order(groww_adapter):
    result = await groww_adapter.cancel_order("GRW123", "CASH")
    assert result == "GRW123"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd backend && python -m pytest tests/brokers/test_groww.py -v`
Expected: FAIL

- [ ] **Step 3: Implement Groww auth module**

```python
# backend/app/brokers/groww/__init__.py
"""Groww broker adapter."""
from app.brokers.groww.adapter import GrowwAdapter

__all__ = ["GrowwAdapter"]
```

```python
# backend/app/brokers/groww/auth.py
"""Groww TOTP authentication."""
import logging
from typing import Optional

logger = logging.getLogger(__name__)


class GrowwAuth:
    """Handles Groww API authentication via TOTP."""

    def __init__(self, api_key: str, totp_secret: str):
        self.api_key = api_key
        self.totp_secret = totp_secret

    def get_access_token(self) -> str:
        """Generate access token using TOTP."""
        import pyotp
        from growwapi import GrowwAPI

        totp_gen = pyotp.TOTP(self.totp_secret)
        totp = totp_gen.now()
        access_token = GrowwAPI.get_access_token(api_key=self.api_key, totp=totp)
        return access_token
```

- [ ] **Step 4: Implement GrowwAdapter**

```python
# backend/app/brokers/groww/adapter.py
"""
GrowwAdapter — BrokerAdapter implementation for Groww Trading API.
Uses growwapi Python SDK with TOTP authentication.
"""
import logging
from datetime import datetime
from typing import Optional

from app.brokers.base import (
    BrokerAdapter, UnifiedOrder, OrderResult, OrderStatus,
    Position, Holding, MarginInfo, Quote, Instrument,
    AuthResult, AuthStatus, RateLimitConfig, TickCallback,
    OrderRejectedError, BrokerUnavailableError,
)

logger = logging.getLogger(__name__)

# Lazy import — growwapi may not be installed
GrowwAPI = None


def _ensure_groww_sdk():
    global GrowwAPI
    if GrowwAPI is None:
        from growwapi import GrowwAPI as _G
        GrowwAPI = _G


class GrowwAdapter(BrokerAdapter):
    """Groww Trading API adapter."""

    def __init__(self):
        self._client = None
        self._logged_in = False
        self._user_id = ""

    def _get_client(self):
        if not self._client:
            raise BrokerUnavailableError("groww", RuntimeError("Not logged in"), "Groww client not initialized")
        return self._client

    # ── Auth ──────────────────────────────────────────

    async def login(self, credentials: dict) -> AuthResult:
        _ensure_groww_sdk()
        try:
            api_key = credentials.get("api_key", "")
            totp_secret = credentials.get("totp_secret", "")
            if totp_secret:
                import pyotp
                totp = pyotp.TOTP(totp_secret).now()
                token = GrowwAPI.get_access_token(api_key=api_key, totp=totp)
            else:
                secret = credentials.get("secret", "")
                token = GrowwAPI.get_access_token(api_key=api_key, secret=secret)

            self._client = GrowwAPI(token)
            self._logged_in = True
            self._user_id = "GROWW_USER"
            logger.info("Groww login successful")
            return AuthResult(success=True, user_id=self._user_id, broker_name="groww", message="Login successful")
        except Exception as e:
            logger.error(f"Groww login failed: {e}")
            return AuthResult(success=False, user_id="", broker_name="groww", message=str(e))

    async def logout(self) -> None:
        self._client = None
        self._logged_in = False

    async def get_auth_status(self) -> AuthStatus:
        return AuthStatus(
            is_valid=self._logged_in, user_id=self._user_id if self._logged_in else None,
            broker_name="groww", expires_at=None,
        )

    # ── Orders ────────────────────────────────────────

    async def place_order(self, order: UnifiedOrder) -> OrderResult:
        client = self._get_client()
        try:
            segment_map = {"CASH": "CASH", "FNO": "FNO", "COMMODITY": "COMMODITY"}
            response = client.place_order(
                trading_symbol=order.symbol,
                quantity=order.quantity,
                validity="DAY",
                exchange=order.exchange,
                segment=segment_map.get(order.segment, order.segment),
                product=order.product,
                order_type=order.order_type,
                transaction_type=order.transaction_type,
                price=order.price,
                trigger_price=order.trigger_price,
            )
            order_id = response.get("groww_order_id", "")
            return OrderResult(
                broker_order_id=order_id, status=response.get("order_status", "OPEN"),
                broker_name="groww", raw_response=response,
            )
        except Exception as e:
            raise OrderRejectedError("groww", e, str(e))

    async def modify_order(self, order_id: str, changes: dict) -> OrderResult:
        client = self._get_client()
        response = client.modify_order(groww_order_id=order_id, **changes)
        return OrderResult(
            broker_order_id=order_id, status=response.get("order_status", ""),
            broker_name="groww", raw_response=response,
        )

    async def cancel_order(self, order_id: str, segment: str) -> str:
        client = self._get_client()
        client.cancel_order(segment=segment, groww_order_id=order_id)
        return order_id

    async def get_order_status(self, order_id: str) -> OrderStatus:
        client = self._get_client()
        response = client.get_order_status(groww_order_id=order_id, segment="CASH")
        return OrderStatus(
            broker_order_id=order_id, symbol="",
            status=response.get("order_status", ""), quantity=0,
            filled_quantity=response.get("filled_quantity", 0),
            average_price=None, order_type="", transaction_type="",
            broker_name="groww",
        )

    async def get_orders(self) -> list[OrderStatus]:
        client = self._get_client()
        response = client.get_order_list()
        orders = response.get("order_list", [])
        return [
            OrderStatus(
                broker_order_id=o.get("groww_order_id", ""), symbol=o.get("trading_symbol", ""),
                status=o.get("order_status", ""), quantity=o.get("quantity", 0),
                filled_quantity=o.get("filled_quantity", 0), average_price=o.get("average_fill_price"),
                order_type=o.get("order_type", ""), transaction_type=o.get("transaction_type", ""),
                broker_name="groww",
            )
            for o in orders
        ]

    # ── Portfolio ─────────────────────────────────────

    async def get_positions(self) -> list[Position]:
        client = self._get_client()
        positions = client.get_positions_for_user()
        return [
            Position(
                symbol=p.get("trading_symbol", ""), exchange=p.get("exchange", "NSE"),
                segment=p.get("segment", "CASH"), quantity=p.get("quantity", 0),
                average_price=p.get("net_price", 0), last_price=p.get("credit_price", 0),
                pnl=p.get("realised_pnl", 0), product=p.get("product", "CNC"),
                broker_name="groww",
            )
            for p in positions if p.get("quantity", 0) != 0
        ]

    async def get_holdings(self) -> list[Holding]:
        client = self._get_client()
        holdings = client.get_holdings_for_user()
        return [
            Holding(
                symbol=h.get("trading_symbol", ""), isin=h.get("isin"),
                quantity=h.get("quantity", 0), average_price=h.get("average_price", 0),
                last_price=0, pnl=0, broker_name="groww",
            )
            for h in holdings
        ]

    async def get_margins(self) -> MarginInfo:
        client = self._get_client()
        data = client.get_available_margin_details()
        available = data.get("clear_cash", 0)
        used = data.get("net_margin_used", 0)
        return MarginInfo(
            available_cash=available, used_margin=used, total_margin=available + used,
            broker_name="groww", raw=data,
        )

    # ── Market Data ───────────────────────────────────

    async def get_ltp(self, symbols: list[str]) -> dict[str, float]:
        client = self._get_client()
        formatted = tuple(f"NSE_{s}" for s in symbols)
        data = client.get_ltp(segment="CASH", exchange_trading_symbols=formatted)
        return {k.split("_", 1)[-1]: v for k, v in data.items()}

    async def get_quote(self, symbol: str, exchange: str, segment: str) -> Quote:
        client = self._get_client()
        data = client.get_quote(exchange=exchange, segment=segment, trading_symbol=symbol)
        return Quote(
            symbol=symbol, exchange=exchange, ltp=data.get("ltp", 0),
            open=data.get("open", 0), high=data.get("high", 0),
            low=data.get("low", 0), close=data.get("close", 0),
            volume=data.get("volume", 0), oi=data.get("oi"),
            broker_name="groww",
        )

    async def get_instruments(self, exchange: str | None = None) -> list[Instrument]:
        client = self._get_client()
        df = client.get_all_instruments()
        instruments = []
        for _, row in df.iterrows():
            if exchange and row.get("exchange") != exchange:
                continue
            instruments.append(Instrument(
                symbol=row.get("trading_symbol", ""), exchange=row.get("exchange", ""),
                segment=row.get("segment", ""), instrument_type=row.get("instrument_type", "EQ"),
                lot_size=int(row.get("lot_size", 1)), tick_size=float(row.get("tick_size", 0.05)),
                broker_name="groww",
            ))
        return instruments

    # ── Live Feed ─────────────────────────────────────

    async def subscribe_ticks(self, symbols: list[str], callback: TickCallback) -> None:
        logger.info(f"Groww tick subscription: {len(symbols)} symbols (stub — use feed.py)")

    async def unsubscribe_ticks(self, symbols: list[str]) -> None:
        pass

    async def disconnect_feed(self) -> None:
        pass

    # ── Metadata ──────────────────────────────────────

    @property
    def name(self) -> str:
        return "groww"

    @property
    def supported_segments(self) -> list[str]:
        return ["CASH", "FNO", "COMMODITY"]

    @property
    def rate_limits(self) -> RateLimitConfig:
        return RateLimitConfig(
            orders_per_second=10, orders_per_minute=250,
            data_requests_per_second=10, max_ws_subscriptions=1000,
        )

    @property
    def is_connected(self) -> bool:
        return self._logged_in
```

- [ ] **Step 5: Create feed.py stub**

```python
# backend/app/brokers/groww/feed.py
"""Groww WebSocket feed — NATS-based. Stub for now."""
import logging
from app.brokers.base import TickCallback

logger = logging.getLogger(__name__)


class GrowwFeed:
    """Wraps GrowwFeed NATS WebSocket for live market data."""

    def __init__(self, access_token: str):
        self._access_token = access_token
        self._connected = False

    async def connect(self) -> None:
        logger.info("Groww feed connect (stub)")
        self._connected = True

    async def disconnect(self) -> None:
        self._connected = False
```

- [ ] **Step 6: Run tests**

Run: `cd backend && python -m pytest tests/brokers/test_groww.py -v`
Expected: All 6 tests PASS

- [ ] **Step 7: Commit**

```bash
git add backend/app/brokers/groww/ backend/tests/brokers/test_groww.py
git commit -m "feat(brokers): add GrowwAdapter for Groww Trading API

Implements BrokerAdapter for Groww. TOTP auth, order CRUD,
positions, holdings, margins, LTP, quotes, instruments.
Translates growwapi responses to unified models.
Feed stub for NATS WebSocket (full impl in future task).

Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>"
```

---

## Task 9: Refactor Existing Services to Use Adapters

**Files:**
- Modify: `backend/app/execution/service.py`
- Modify: `backend/app/execution/router.py`
- Modify: `backend/app/risk/service.py`
- Modify: `backend/app/risk/router.py`
- Modify: `backend/app/data/models.py`
- Modify: `backend/app/main.py`
- Modify: `backend/requirements.txt`

- [ ] **Step 1: Update requirements.txt**

Add these lines to `backend/requirements.txt`:

```
# Groww
growwapi>=1.5.0
pyotp>=2.9.0

# Alerting
python-telegram-bot>=20.0
httpx>=0.25.2

# Config
pyyaml>=6.0.1

# Async performance
uvloop>=0.19.0
```

- [ ] **Step 2: Update User model in data/models.py**

Replace `zerodha_user_id` column:

```python
    # Replace: zerodha_user_id = Column(String, unique=True, index=True)
    # With:
    broker_accounts = Column(JSON, default={})  # {"zerodha": "AB1234", "groww": "GRW5678"}
```

- [ ] **Step 3: Refactor ExecutionService**

Update `backend/app/execution/service.py` to accept adapter instead of creating AuthService:

Replace the `__init__` and `place_order` methods:

```python
class ExecutionService:
    """Service for executing trades via broker adapters."""

    def __init__(self, db: Session, adapter: BrokerAdapter):
        self.db = db
        self.adapter = adapter
```

Replace all `kite = self.auth_service.get_kite_client()` calls with `self.adapter` method calls:
- `kite.place_order(**params)` → `await self.adapter.place_order(unified_order)`
- `kite.cancel_order(...)` → `await self.adapter.cancel_order(...)`
- `kite.positions()` → `await self.adapter.get_positions()`

- [ ] **Step 4: Refactor ExecutionRouter to pass adapter**

Update `backend/app/execution/router.py` — add `account_name` query param:

```python
from app.brokers.account_manager import AccountManager

# Global account manager (set during app startup)
_account_manager: AccountManager | None = None

def set_account_manager(manager: AccountManager):
    global _account_manager
    _account_manager = manager

@router.post("/order")
async def place_order(
    order: OrderRequest,
    account_name: str = "paper_test",
    db: Session = Depends(get_db_session),
):
    adapter = _account_manager.get_adapter(account_name)
    service = ExecutionService(db, adapter)
    # ... rest unchanged
```

- [ ] **Step 5: Refactor RiskService**

Update `backend/app/risk/service.py`:

```python
class RiskService:
    def __init__(self, db: Session, adapter: BrokerAdapter):
        self.db = db
        self.adapter = adapter
```

Replace `kite.margins()` with `await self.adapter.get_margins()`.

- [ ] **Step 6: Update main.py startup**

Add AccountManager initialization to `backend/app/main.py` lifespan:

```python
import yaml
from app.brokers.account_manager import AccountManager
from app.brokers.paper.adapter import PaperAdapter

account_manager = AccountManager()

@asynccontextmanager
async def lifespan(app: FastAPI):
    # ... existing init ...

    # Initialize account manager
    config_path = settings.ACCOUNTS_CONFIG_PATH
    if os.path.exists(config_path):
        with open(config_path) as f:
            config = yaml.safe_load(f)
        for name, acct in config.get("accounts", {}).items():
            broker = acct.get("broker")
            if broker == "paper":
                adapter = PaperAdapter(config=acct.get("config", {}))
                account_manager.register(name, adapter, acct)
            # zerodha and groww registered on login
    else:
        # Default paper account
        account_manager.register("paper_test", PaperAdapter(), {"broker": "paper"})

    logger.info(f"AccountManager initialized with {len(account_manager.get_account_names())} accounts")

    # Set account manager on routers
    from app.execution.router import set_account_manager
    set_account_manager(account_manager)

    yield
    # ... existing shutdown ...
```

- [ ] **Step 7: Run existing tests to check for regressions**

Run: `cd backend && python -m pytest tests/ -v`
Expected: All tests PASS (existing + new)

- [ ] **Step 8: Commit**

```bash
git add backend/app/execution/ backend/app/risk/ backend/app/data/models.py backend/app/main.py backend/requirements.txt
git commit -m "refactor: wire existing services through BrokerAdapter interface

ExecutionService and RiskService now accept BrokerAdapter instead of
calling KiteConnect directly. AccountManager initialized on startup
from accounts.yaml. Execution router accepts account_name param.
User model updated: zerodha_user_id → broker_accounts JSON.

Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>"
```

---

## Task 10: Structured Logging Setup + Decision Router

**Files:**
- Modify: `backend/app/utils/logging.py`
- Create: `backend/app/decisions/router.py`

- [ ] **Step 1: Add per-account file logging**

Update `backend/app/utils/logging.py` to add file handlers:

```python
import os
from logging.handlers import TimedRotatingFileHandler


def setup_account_logger(account_name: str, log_base_dir: str = "logs") -> None:
    """Set up per-account log files with daily rotation."""
    account_dir = os.path.join(log_base_dir, "accounts", account_name)
    os.makedirs(account_dir, exist_ok=True)

    log_types = ["decisions", "trades", "agent", "ws"]
    for log_type in log_types:
        logger_name = f"kalyx.{account_name}.{log_type}"
        log_logger = logging.getLogger(logger_name)
        log_logger.setLevel(logging.INFO)

        handler = TimedRotatingFileHandler(
            filename=os.path.join(account_dir, f"{log_type}.log"),
            when="midnight",
            interval=1,
            backupCount=90,
            encoding="utf-8",
        )
        handler.setFormatter(JSONFormatter())
        handler.suffix = "%Y-%m-%d"
        log_logger.addHandler(handler)
```

- [ ] **Step 2: Create decision history API endpoints**

```python
# backend/app/decisions/router.py
"""API endpoints for decision log history."""
from fastapi import APIRouter, Depends, Query
from typing import Optional
from sqlalchemy.orm import Session
from datetime import date

from app.data.database import get_db_session
from app.decisions.models import DecisionLog

router = APIRouter()


@router.get("/")
async def get_decisions(
    account_name: Optional[str] = None,
    symbol: Optional[str] = None,
    action: Optional[str] = None,
    date_from: Optional[date] = None,
    limit: int = Query(default=100, le=1000),
    db: Session = Depends(get_db_session),
):
    """Query decision log with filters."""
    query = db.query(DecisionLog).order_by(DecisionLog.timestamp.desc())

    if account_name:
        query = query.filter(DecisionLog.account_name == account_name)
    if symbol:
        query = query.filter(DecisionLog.symbol == symbol)
    if action:
        query = query.filter(DecisionLog.action == action)
    if date_from:
        query = query.filter(DecisionLog.timestamp >= date_from)

    decisions = query.limit(limit).all()
    return [
        {
            "id": d.id,
            "timestamp": d.timestamp.isoformat() if d.timestamp else None,
            "account_name": d.account_name,
            "symbol": d.symbol,
            "signal": d.signal,
            "action": d.action,
            "confidence": d.confidence,
            "reasoning": d.reasoning,
            "skip_reason": d.skip_reason,
            "was_correct": d.was_correct,
        }
        for d in decisions
    ]


@router.get("/stats")
async def get_decision_stats(
    account_name: Optional[str] = None,
    db: Session = Depends(get_db_session),
):
    """Get decision statistics."""
    from sqlalchemy import func

    query = db.query(
        DecisionLog.action,
        func.count(DecisionLog.id).label("count"),
    ).group_by(DecisionLog.action)

    if account_name:
        query = query.filter(DecisionLog.account_name == account_name)

    results = query.all()
    return {action: count for action, count in results}
```

- [ ] **Step 3: Register decisions router in main.py**

Add to `backend/app/main.py`:

```python
from app.decisions.router import router as decisions_router

app.include_router(decisions_router, prefix="/api/decisions", tags=["Decisions"])
```

- [ ] **Step 4: Commit**

```bash
git add backend/app/utils/logging.py backend/app/decisions/router.py backend/app/main.py
git commit -m "feat: add per-account structured logging + decision history API

TimedRotatingFileHandler per account with daily rotation and 90-day
retention. Decision history API with filtering by account, symbol,
action, date. Stats endpoint for decision action distribution.

Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>"
```

---

## Final Verification

- [ ] **Run full test suite**

```bash
cd backend && python -m pytest tests/ -v --tb=short
```

Expected: All tests PASS across all modules.

- [ ] **Verify conformance for all adapters**

```bash
cd backend && python -m pytest tests/brokers/test_conformance.py -v
```

Expected: Paper + Zerodha adapters pass all conformance tests.

- [ ] **Final commit — tag the milestone**

```bash
git tag -a v0.2.0-broker-abstraction -m "Sub-project 1: Broker abstraction layer complete"
```
