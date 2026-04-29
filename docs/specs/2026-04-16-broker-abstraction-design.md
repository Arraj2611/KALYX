# Broker Abstraction Layer — Design Spec

**Date:** 2026-04-16
**Sub-project:** 1 of N (foundation layer)
**Status:** Draft

---

## 1. Purpose

Decouple KALYX from any single broker. Enable simultaneous multi-broker, multi-market, multi-asset trading through a unified interface. This is the foundation for the autonomous multi-market trading platform.

### What This Sub-project Delivers

- `BrokerAdapter` abstract interface
- `ZerodhaAdapter` (refactor existing Kite Connect code)
- `GrowwAdapter` (new)
- `PaperAdapter` (simulation mode — no real orders)
- `AccountManager` (multi-account registry + routing)
- `DecisionLog` model (every decision logged)
- `TradeContext` on every order (learning system foundation)
- Per-account structured log files
- Telegram alerting on failures

### What This Sub-project Does NOT Deliver (Planned for Future Sub-projects)

- AI agents with bull/bear debate pattern (sub-project 2)
- Memory agent with hindsight reflections + vector search (sub-project 2)
- LangGraph orchestration for agent coordination (sub-project 2)
- Cross-signal correlation engine across markets (sub-project 3)
- Multi-dimensional composite scoring (sub-project 3)
- Multi-source data aggregation: news, sentiment, macro, geopolitical (sub-project 3)
- Binance / IBKR adapters (built when those brokers are needed)
- Cross-account portfolio optimizer (sub-project 3)
- Frontend multi-broker dashboard (sub-project 4)

### Reference: Patterns Adopted from Open Source

- **TradingAgents** (54k stars): bull/bear debate, memory reflections, two-tier LLM, LangGraph, structured data flows
- **WorldMonitor** (3.7k commits): cross-signal correlation, composite scoring, multi-source aggregation, local-first AI, 3-tier caching

---

## 2. Architecture

### 2.1 Component Diagram

```
                    ┌──────────────┐
                    │ AccountManager│
                    │              │
                    │ registers &  │
                    │ routes to    │
                    │ adapters     │
                    └──────┬───────┘
                           │
              ┌────────────┼────────────┐
              ▼            ▼            ▼
       ┌────────────┐┌────────────┐┌────────────┐
       │ Zerodha    ││ Groww      ││ Paper      │
       │ Adapter    ││ Adapter    ││ Adapter    │
       │            ││            ││            │
       │ KiteConnect││ GrowwAPI   ││ Simulated  │
       │ KiteTicker ││ GrowwFeed  ││ fills      │
       └────────────┘└────────────┘└────────────┘
              │            │            │
              ▼            ▼            ▼
       ┌─────────────────────────────────────┐
       │         Unified Data Models         │
       │  UnifiedOrder, Position, MarginInfo  │
       │  OrderResult, Quote, Instrument      │
       └─────────────────────────────────────┘
              │
              ▼
       ┌─────────────────────────────────────┐
       │          Decision Log               │
       │  Every signal, every outcome        │
       │  EXECUTED / SKIPPED / BLOCKED /      │
       │  REJECTED / FAILED                   │
       └─────────────────────────────────────┘
```

### 2.2 File Structure

```
backend/app/
├── brokers/
│   ├── __init__.py
│   ├── base.py              # BrokerAdapter ABC + data models
│   ├── account_manager.py   # Multi-account registry
│   ├── zerodha/
│   │   ├── __init__.py
│   │   ├── adapter.py       # ZerodhaAdapter(BrokerAdapter)
│   │   ├── feed.py          # KiteTicker wrapper
│   │   └── auth.py          # Zerodha-specific auth (refactored from app/auth/)
│   ├── groww/
│   │   ├── __init__.py
│   │   ├── adapter.py       # GrowwAdapter(BrokerAdapter)
│   │   ├── feed.py          # GrowwFeed NATS wrapper
│   │   └── auth.py          # Groww TOTP auth
│   └── paper/
│       ├── __init__.py
│       └── adapter.py       # PaperAdapter(BrokerAdapter) — simulation
├── decisions/
│   ├── __init__.py
│   ├── models.py            # Decision, DecisionAction, TradeContext DB models
│   ├── logger.py            # DecisionLogger service
│   └── router.py            # API endpoints for decision history
├── alerts/
│   ├── __init__.py
│   └── telegram.py          # Telegram bot alerting
├── auth/                    # DEPRECATED — auth moves into brokers/<name>/auth.py
├── execution/               # Refactored to use BrokerAdapter instead of direct Kite calls
├── risk/                    # Refactored to use BrokerAdapter.get_margins()
└── ...
```

---

## 3. Core Interface

### 3.1 BrokerAdapter (ABC)

```python
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Callable

TickCallback = Callable[[dict], None]


class BrokerAdapter(ABC):
    """Abstract broker interface. Every broker implements this."""

    # ── Auth ──────────────────────────────────────────
    @abstractmethod
    async def login(self, credentials: dict) -> "AuthResult": ...

    @abstractmethod
    async def logout(self) -> None: ...

    @abstractmethod
    async def get_auth_status(self) -> "AuthStatus": ...

    # ── Orders ────────────────────────────────────────
    @abstractmethod
    async def place_order(self, order: "UnifiedOrder") -> "OrderResult": ...

    @abstractmethod
    async def modify_order(self, order_id: str, changes: dict) -> "OrderResult": ...

    @abstractmethod
    async def cancel_order(self, order_id: str, segment: str) -> str: ...

    @abstractmethod
    async def get_order_status(self, order_id: str) -> "OrderStatus": ...

    @abstractmethod
    async def get_orders(self) -> list["OrderStatus"]: ...

    # ── Portfolio ─────────────────────────────────────
    @abstractmethod
    async def get_positions(self) -> list["Position"]: ...

    @abstractmethod
    async def get_holdings(self) -> list["Holding"]: ...

    @abstractmethod
    async def get_margins(self) -> "MarginInfo": ...

    # ── Market Data ───────────────────────────────────
    @abstractmethod
    async def get_ltp(self, symbols: list[str]) -> dict[str, float]: ...

    @abstractmethod
    async def get_quote(self, symbol: str, exchange: str, segment: str) -> "Quote": ...

    @abstractmethod
    async def get_instruments(self, exchange: str | None = None) -> list["Instrument"]: ...

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
    def rate_limits(self) -> "RateLimitConfig": ...

    @property
    @abstractmethod
    def is_connected(self) -> bool: ...
```

### 3.2 Unified Data Models

```python
@dataclass
class UnifiedOrder:
    symbol: str
    exchange: str
    segment: str                          # CASH, FNO, COMMODITY, SPOT, FUTURES
    transaction_type: str                 # BUY, SELL
    quantity: int
    order_type: str                       # MARKET, LIMIT, SL, SL_M
    product: str                          # CNC, MIS, NRML
    price: float | None = None
    trigger_price: float | None = None
    context: "TradeContext | None" = None  # learning system

@dataclass
class TradeContext:
    strategy_id: int
    account_name: str
    signals: dict                         # what signals fired
    market_state: dict                    # snapshot at decision time
    reasoning: str                        # AI/strategy reasoning
    confidence: float                     # 0.0 - 1.0
    timestamp: datetime = field(default_factory=datetime.utcnow)

@dataclass
class OrderResult:
    broker_order_id: str
    status: str
    broker_name: str
    raw_response: dict

@dataclass
class OrderStatus:
    broker_order_id: str
    symbol: str
    status: str                           # PENDING, OPEN, COMPLETE, CANCELLED, REJECTED
    quantity: int
    filled_quantity: int
    average_price: float | None
    order_type: str
    transaction_type: str
    broker_name: str

@dataclass
class Position:
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
    symbol: str
    isin: str | None
    quantity: int
    average_price: float
    last_price: float
    pnl: float
    broker_name: str

@dataclass
class MarginInfo:
    available_cash: float
    used_margin: float
    total_margin: float
    broker_name: str
    raw: dict                             # broker-specific full margin breakdown

@dataclass
class Quote:
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
    oi: int | None = None                 # open interest (F&O)
    broker_name: str = ""

@dataclass
class Instrument:
    symbol: str
    exchange: str
    segment: str
    instrument_type: str                  # EQ, CE, PE, FUT
    lot_size: int
    tick_size: float
    expiry: datetime | None = None
    strike: float | None = None
    broker_name: str = ""

@dataclass
class AuthResult:
    success: bool
    user_id: str
    broker_name: str
    message: str

@dataclass
class AuthStatus:
    is_valid: bool
    user_id: str | None
    broker_name: str
    expires_at: datetime | None

@dataclass
class RateLimitConfig:
    orders_per_second: int
    orders_per_minute: int
    data_requests_per_second: int
    max_ws_subscriptions: int
```

---

## 4. Account Manager

Registers multiple broker accounts, routes operations to the right adapter.

```python
class AccountManager:
    """Registry for multiple broker accounts."""

    def register(self, account_name: str, adapter: BrokerAdapter, config: dict) -> None
    def get_adapter(self, account_name: str) -> BrokerAdapter
    def get_all_adapters(self) -> dict[str, BrokerAdapter]
    def get_adapters_by_broker(self, broker_name: str) -> list[BrokerAdapter]

    # Cross-account queries
    async def get_all_positions(self) -> dict[str, list[Position]]
    async def get_all_margins(self) -> dict[str, MarginInfo]
    async def get_total_exposure(self) -> float
```

### 4.1 Account Configuration

```yaml
# config/accounts.yaml
accounts:
  zerodha_fno:
    broker: zerodha
    segments: [FNO]
    mode: paper          # paper | live
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

Secrets stay in `.env` (local) or GitHub Actions secrets (CI/CD). YAML references env var names, never actual values.

---

## 5. Paper Adapter

Simulates broker behavior without real orders. Used for testing strategies before live deployment.

```python
class PaperAdapter(BrokerAdapter):
    """Simulated broker for paper trading."""

    def __init__(self, config: dict):
        self.capital = config.get("initial_capital", 1000000)
        self.slippage_pct = config.get("slippage_pct", 0.05)
        self.positions: list[Position] = []
        self.orders: list[OrderStatus] = []
        self.order_counter = 0

    async def place_order(self, order: UnifiedOrder) -> OrderResult:
        # Simulate fill with slippage
        # Deduct margin
        # Update positions
        # Log as if real
        ...

    async def get_positions(self) -> list[Position]:
        return self.positions

    async def get_margins(self) -> MarginInfo:
        # Calculate from capital - used margin
        ...
```

Paper adapter uses real market data (via MCP or another broker's data feed) but simulates order fills locally. Applies configurable slippage. Tracks P&L as if real.

---

## 6. Decision Log

### 6.1 DB Model

```python
class DecisionAction(str, Enum):
    EXECUTED = "executed"
    SKIPPED = "skipped"
    BLOCKED = "blocked"
    REJECTED = "rejected"
    FAILED = "failed"

class DecisionLog(Base):
    __tablename__ = "decision_log"

    id = Column(Integer, primary_key=True, index=True)
    timestamp = Column(DateTime(timezone=True), server_default=func.now(), index=True)
    account_name = Column(String, index=True)

    # What was evaluated
    symbol = Column(String, index=True)
    signal = Column(String)               # BUY, SELL, EXIT, HOLD
    strategy_id = Column(Integer, ForeignKey("strategies.id"), nullable=True)
    confidence = Column(Float)

    # Market snapshot
    market_state = Column(JSON)

    # Decision
    action = Column(String, index=True)   # DecisionAction value
    reasoning = Column(Text)

    # Skip/block reason
    skip_reason = Column(String, nullable=True)

    # Trade link
    trade_id = Column(Integer, ForeignKey("trades.id"), nullable=True)

    # Hindsight (filled later)
    outcome_if_taken = Column(Float, nullable=True)
    outcome_actual = Column(Float, nullable=True)
    was_correct = Column(Boolean, nullable=True)

    # Context blob
    trade_context = Column(JSON, nullable=True)
```

### 6.2 DecisionLogger Service

```python
class DecisionLogger:
    """Logs every decision to DB + structured log file."""

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
        context: TradeContext | None = None,
    ) -> int:
        # 1. Write to PostgreSQL
        # 2. Write to per-account log file (JSON structured)
        # 3. If action is FAILED or REJECTED, trigger Telegram alert
        ...

    async def fill_hindsight(self, decision_id: int, outcome_if_taken: float, outcome_actual: float) -> None:
        # Called by Memory Agent post-session
        ...
```

---

## 7. Structured Log Files

### 7.1 Directory Layout

```
logs/
├── system/
│   ├── kalyx-YYYY-MM-DD.log
│   ├── kalyx-error-YYYY-MM-DD.log
│   └── kalyx-audit-YYYY-MM-DD.log
├── accounts/
│   ├── zerodha_fno/
│   │   ├── decisions-YYYY-MM-DD.log
│   │   ├── trades-YYYY-MM-DD.log
│   │   ├── agent-YYYY-MM-DD.log
│   │   └── ws-YYYY-MM-DD.log
│   ├── groww_equity/
│   │   └── ...
│   └── paper_test/
│       └── ...
├── orchestrator/
│   ├── cross-account-YYYY-MM-DD.log
│   └── memory-mesh-YYYY-MM-DD.log
└── performance/
    ├── latency-YYYY-MM-DD.log
    └── health-YYYY-MM-DD.log
```

### 7.2 Format

All logs use JSON structured format via `python-json-logger`:

```json
{
  "ts": "2026-04-16T10:30:05.123Z",
  "level": "INFO",
  "account": "zerodha_fno",
  "event": "decision",
  "symbol": "NIFTY25APR24500CE",
  "signal": "BUY",
  "action": "BLOCKED",
  "reason": "guardian:daily_loss_80pct",
  "confidence": 0.72,
  "ltp": 150.5,
  "latency_ms": 3.2
}
```

### 7.3 Retention

| Log type | Hot (local) | Archive |
|----------|-------------|---------|
| Decisions | 90 days | Compressed, indefinite |
| Trades | 90 days | Compressed, indefinite |
| Errors | 180 days | Compressed, indefinite |
| WebSocket | 30 days | Delete |
| Performance | 30 days | Delete |

---

## 8. Telegram Alerting

### 8.1 Alert Triggers

| Event | Severity | Alert |
|-------|----------|-------|
| Broker API down after 3 retries | CRITICAL | Immediate |
| Circuit breaker activated | CRITICAL | Immediate |
| Order rejected by broker | WARNING | Batched (every 5 min) |
| Daily loss limit > 80% | WARNING | Immediate |
| Pod crashed and restarted | CRITICAL | Immediate |
| Auth token expired | WARNING | Immediate |
| Strategy P&L milestone (±₹10K) | INFO | Immediate |
| Daily summary | INFO | Scheduled (EOD) |

### 8.2 Retry + Pause Logic

```
Broker API call fails
  → Retry 1 (immediate)
  → Retry 2 (2 second backoff)
  → Retry 3 (4 second backoff)
  → All failed:
      1. Pause account pod
      2. Cancel any pending orders for safety
      3. Send Telegram: "⚠️ [zerodha_fno] API DOWN — pod paused after 3 retries. Error: {msg}"
      4. Log to error log
      5. Pod stays paused until manual restart or API health check passes
```

---

## 9. Error Handling & Resilience

### 9.1 Per-Adapter Error Handling

Each adapter wraps broker SDK calls with:
- Retry with exponential backoff (3 attempts)
- Per-broker rate limiter (token bucket in Redis)
- Timeout per call (configurable, default 10s)
- All exceptions caught, logged, and translated to unified error types

### 9.2 Unified Error Types

```python
class BrokerError(Exception):
    """Base broker error."""
    broker_name: str
    original_error: Exception

class AuthenticationError(BrokerError): ...
class OrderRejectedError(BrokerError): ...
class RateLimitError(BrokerError): ...
class InsufficientMarginError(BrokerError): ...
class BrokerUnavailableError(BrokerError): ...
class InvalidSymbolError(BrokerError): ...
```

---

## 10. Migration Plan

### What Changes in Existing Code

| File | Change |
|------|--------|
| `app/auth/service.py` | Refactored into `brokers/zerodha/auth.py` |
| `app/auth/websocket_client.py` | Refactored into `brokers/zerodha/feed.py` |
| `app/execution/service.py` | Uses `AccountManager.get_adapter()` instead of `AuthService.get_kite_client()` |
| `app/risk/service.py` | Uses `adapter.get_margins()` instead of `kite.margins()` |
| `app/config.py` | Zerodha-specific settings stay but load from accounts.yaml |
| `app/data/models.py` | `User.zerodha_user_id` → `User.broker_accounts` (JSON), add DecisionLog model |
| `app/main.py` | Startup initializes AccountManager, registers adapters from config |
| `requirements.txt` | Add `growwapi`, `python-telegram-bot` |

### What Stays Unchanged

- Strategy engine (`strategies/`) — unchanged, still emits signals
- Data layer (`data/database.py`, `data/redis_client.py`) — unchanged
- AI agents (`agents/`) — unchanged for now
- Frontend — unchanged for now (still shows single broker view)

---

## 11. Tech Stack (This Sub-project)

| Component | Technology |
|-----------|-----------|
| Language | Python 3.10+ |
| Async runtime | asyncio + uvloop |
| Broker SDK (Zerodha) | kiteconnect 4.2.0 |
| Broker SDK (Groww) | growwapi (latest) |
| Rate limiting | Token bucket in Redis |
| Database | PostgreSQL 15 (existing) |
| Cache | Redis 7 (existing) |
| Logging | python-json-logger (existing) |
| Alerting | python-telegram-bot |
| Config | YAML (accounts) + .env (secrets) |
| Containerization | Docker Compose (existing) |

---

## 12. Deployment

- **Target:** VPS/cloud server (24/7 uptime)
- **Process model:** One Python process per account pod (future sub-project). For this sub-project, single process with AccountManager.
- **Secrets:** `.env` locally, GitHub Actions secrets for CI/CD
- **Docker Compose:** Add Telegram bot service config, update existing services

---

## 13. Testing Strategy

1. **Unit tests:** Each adapter method tested with mocked broker SDK responses
2. **Integration tests:** PaperAdapter end-to-end (place order → fill → position update → P&L)
3. **Adapter conformance test suite:** Generic test class that runs against ANY BrokerAdapter implementation — ensures all adapters behave identically for the same inputs
4. **Decision log tests:** Verify every code path produces a DecisionLog entry
5. **Telegram alert tests:** Mock Telegram API, verify alerts fire for each trigger

---

## 14. Success Criteria

1. `ZerodhaAdapter` passes all existing test scenarios (refactor, not rewrite behavior)
2. `GrowwAdapter` can authenticate (TOTP), place/cancel orders, fetch positions/margins, subscribe to live ticks
3. `PaperAdapter` simulates order fills with configurable slippage, tracks P&L
4. `AccountManager` registers multiple adapters, routes correctly
5. Every signal evaluation produces a `DecisionLog` entry (DB + log file)
6. Telegram alerts fire on API failure, circuit breaker, and daily summary
7. Existing execution/risk services work through adapter interface without regression
8. Per-account log files written in JSON structured format with daily rotation
9. Adapter conformance test suite passes for all three adapters (Zerodha, Groww, Paper)
10. All accounts start in `paper` mode by default — explicit switch to `live` required
