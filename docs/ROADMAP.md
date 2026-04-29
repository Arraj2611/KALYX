# KALYX Roadmap

Autonomous multi-market AI trading platform. Each sub-project is self-contained: spec → plan → build → test → ship.

---

## Sub-project 1: Broker Abstraction Layer ✅ COMPLETE
**Branch:** `feat/broker-abstraction` | **Tests:** 104 | **Status:** Done

- BrokerAdapter ABC + unified data models
- ZerodhaAdapter, GrowwAdapter, PaperAdapter
- AccountManager (multi-account registry)
- DecisionLog (every decision logged — taken or not)
- Telegram alerting with retry
- Per-account structured logging
- Conformance test suite

---

## Sub-project 2: AI Agent Framework
**Status:** Not started | **Depends on:** Sub-project 1

Core agent infrastructure. Each account gets its own agent pod.

- Per-account agents: Analyst, Guardian, Executor, Strategist, Memory
- Bull/bear debate pattern before every trade signal (from TradingAgents)
- Two-tier LLM: Ollama (fast/real-time) + Cloud API (deep analysis)
- LangGraph orchestration for agent coordination
- Memory Agent per account with hindsight reflections
- Memory Mesh — Orchestrator queries across all account memories
- Structured data flows per domain (market, sentiment, fundamentals)
- Agent communication via Redis Streams

**Reference repos:**
- `TradingAgents` — debate pattern, memory reflections, LangGraph, two-tier LLM
- `WorldMonitor` — cross-signal correlation, local-first AI

---

## Sub-project 3: Intelligence Layer
**Status:** Not started | **Depends on:** Sub-project 2

Multi-source data aggregation + cross-market intelligence.

- Cross-signal correlation engine (VIX + BTC + Gold + Forex convergence detection)
- Multi-dimensional composite scoring (technical, momentum, sentiment, fundamental, risk)
- Polymarket integration as signal source (prediction market odds → trading signals)
- News/sentiment feeds
- Geopolitical signal integration (WorldMonitor patterns)
- 3-tier caching: in-memory → Redis → PostgreSQL
- pgvector for semantic search over trade journals
- MCP server integration (Zerodha MCP, Groww MCP, Binance MCP)

---

## Sub-project 4: Additional Broker Adapters
**Status:** Not started | **Depends on:** Sub-project 1

Add brokers as needed. Each adapter ~1 day to build.

- **Binance** — crypto primary. Official Rust + Go SDKs. Free API. 3+ MCP servers.
- **IBKR** — forex + multi-asset. TWS API. 4+ MCP servers. Community Rust crate.
- **Polymarket** — prediction markets. Polygon blockchain. Direct trading on event outcomes.
- **OANDA** — forex backup (simpler than IBKR, no true WebSocket)
- **CoinDCX** — Indian crypto backup
- **Angel One / Upstox / Fyers** — Indian equity alternatives (if needed)

---

## Sub-project 5: Autonomous Operations
**Status:** Not started | **Depends on:** Sub-projects 2 + 3

Full 24/7 unattended operation.

- Master Orchestrator (cross-account coordination, capital allocation)
- Portfolio Optimizer (cross-broker rebalancing, correlation monitoring)
- Self-healing: auto-restart crashed pods, auto-reconnect feeds
- Confidence-based position sizing (new strategy = tiny, proven = full)
- Strategy auto-creation: AI creates strategies from market patterns
- Strategy auto-retirement: kill underperformers automatically
- Circuit breaker enhancements: cross-account, correlation-aware
- VPS/cloud deployment with systemd/supervisor
- Prometheus + Grafana monitoring
- Daily/weekly Telegram summaries

---

## Sub-project 6: Frontend Multi-Broker Dashboard
**Status:** Not started | **Depends on:** Sub-projects 1 + 2

- Multi-account view (all brokers on one dashboard)
- Per-account P&L, positions, orders
- Decision log viewer with hindsight analysis
- Strategy performance comparison
- Cross-account portfolio view
- Agent activity feed (what agents are thinking/doing)
- Alert history

---

## Future Considerations

- **Rust migration** of hot paths (tick processing, risk checks) via PyO3
- **TimescaleDB** for tick-level time-series storage
- **Temporal.io** for durable multi-step workflows (replaces APScheduler)
- **gRPC** service boundaries when splitting into microservices
- Mobile alerts (beyond Telegram)
