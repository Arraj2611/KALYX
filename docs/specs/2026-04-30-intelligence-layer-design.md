# Intelligence Layer — Design Spec

**Date:** 2026-04-30
**Sub-project:** 3 of N
**Status:** Draft
**Depends on:** SP1 (Broker Abstraction) ✅, SP2 (Agent Framework) ✅

---

## 1. Purpose

Give KALYX agents real intelligence beyond price data. Aggregate multi-source data (Polymarket odds, news, sentiment, geopolitical events, MCP servers, market data), detect cross-market signal convergence, score signals by composite quality, feed everything into AnalystAgent context.

### What This Sub-project Delivers

- `DataSource` ABC + `DataSourceRegistry` (vendor abstraction with fallback chain)
- 6 data sources: yfinance, Polymarket (read-only), Groww MCP wrapper, Zerodha MCP wrapper, GDELT, news scraper (trafilatura)
- `FinBertSentiment` — financial sentiment classifier
- `CorrelationEngine` + `DomainAdapter` (per-market signal collectors)
- `compute_isq()` composite scoring (port WorldMonitor `signal-quality.ts`)
- `IntelligenceContext` + `IntelligenceContextBuilder`
- AnalystAgent + JudgeAgent enhanced to consume IntelligenceContext
- Per-symbol Redis cache with TTL

### What This Sub-project Does NOT Deliver

- Polymarket trading (read-only here, trading in SP4)
- Master Orchestrator / cross-pod (SP5)
- Memory Mesh (SP5)
- pgvector semantic search (deferred)
- 3-tier caching beyond Redis (deferred — premature)
- Additional broker adapters (SP4)
- Frontend dashboard (SP6)

### Patterns Adopted from Open Source

- **TradingAgents** `dataflows/interface.py` — VENDOR_METHODS + route_to_vendor with fallback chain
- **WorldMonitor** `correlation-engine/` — DomainAdapter, SignalEvidence, ConvergenceCard, cluster→score→trend pipeline (algorithm port, not code; AGPL)
- **WorldMonitor** `signal-quality.ts` — 4-dim composite scoring with weight profiles (algorithm port)
- **LLM Council** — multi-source aggregation with anonymized synthesis (already in SP2)

### Libraries Used

| Library | License | Purpose |
|---------|---------|---------|
| `py-clob-client` | MIT | Polymarket data |
| `yfinance` | Apache-2.0 | Global market OHLCV/news |
| `trafilatura` | Apache-2.0 | News article extraction |
| `gdelt-doc-api` | MIT | Geopolitical events |
| `transformers` + `ProsusAI/finbert` | Apache-2.0 | Financial sentiment |

All MIT/Apache/BSD. No GPL/AGPL pollution.

---

## 2. Architecture

### 2.1 Component Diagram

```
┌────────────────────────────────────────────────────────────────────┐
│                       INTELLIGENCE LAYER                            │
│                                                                      │
│  ┌──────────────────────────────────────────────────────────────┐  │
│  │                  DATA SOURCE REGISTRY                          │  │
│  │                                                                │  │
│  │  yfinance  Polymarket  GrowwMCP  ZerodhaMCP  GDELT  Trafil.  │  │
│  │     │          │          │          │         │       │      │  │
│  │     └──────────┴──────────┴──────────┴─────────┴───────┘      │  │
│  │              route_to_vendor() — fallback chain                │  │
│  └──────────────────────────────────────────────────────────────┘  │
│                              │                                       │
│              ┌───────────────┼───────────────┐                      │
│              ▼               ▼               ▼                       │
│      CORRELATION       COMPOSITE        SENTIMENT                   │
│       ENGINE           SCORING          ENGINE                      │
│      (DomainAdapter)   (compute_isq)    (FinBERT)                   │
│              │               │               │                       │
│              └───────────────┼───────────────┘                      │
│                              ▼                                       │
│                  IntelligenceContext (output)                        │
└────────────────────────────────────────────────────────────────────┘
                              │
                              ▼
                    AnalystAgent / JudgeAgent
                    (enriched signal generation)
```

### 2.2 File Structure

```
backend/app/intelligence/
├── __init__.py
├── base.py                       # DataSource ABC
├── registry.py                   # DataSourceRegistry, route_to_vendor
├── context.py                    # IntelligenceContext + Builder
├── sources/
│   ├── __init__.py
│   ├── yfinance_source.py
│   ├── polymarket_source.py
│   ├── mcp_groww_source.py
│   ├── mcp_zerodha_source.py
│   ├── gdelt_source.py
│   └── news_scraper_source.py
├── correlation/
│   ├── __init__.py
│   ├── types.py                  # SignalEvidence, ConvergenceCard
│   ├── adapters.py               # DomainAdapter ABC + 4 concrete
│   └── engine.py                 # CorrelationEngine
├── scoring/
│   ├── __init__.py
│   ├── composite.py              # compute_isq()
│   └── weights.py                # WEIGHT_PROFILES
└── sentiment/
    ├── __init__.py
    └── finbert.py                # FinBertSentiment
```

---

## 3. Data Source Registry

### 3.1 Base Interface

```python
# intelligence/base.py
from abc import ABC, abstractmethod
from typing import Any

class DataSource(ABC):
    """Abstract data source. Each broker MCP/SDK/scraper implements this."""

    @property
    @abstractmethod
    def name(self) -> str: ...

    @property
    @abstractmethod
    def capabilities(self) -> list[str]: ...

    @abstractmethod
    def supports(self, method: str) -> bool: ...

    @abstractmethod
    async def fetch(self, method: str, **kwargs) -> Any: ...


class RateLimitError(Exception):
    """Source rate-limited. Triggers fallback to next vendor."""
    pass


class SourceUnavailableError(Exception):
    """Source unreachable. Triggers fallback."""
    pass
```

### 3.2 Registry

```python
# intelligence/registry.py

TOOLS_CATEGORIES = {
    "ohlcv":        {"tools": ["get_ohlcv", "get_ltp"]},
    "quotes":       {"tools": ["get_quotes", "get_market_depth"]},
    "news":         {"tools": ["get_news", "get_global_news", "scrape_article"]},
    "odds":         {"tools": ["get_polymarket_odds", "get_event_probability"]},
    "fundamentals": {"tools": ["get_fundamentals", "get_balance_sheet", "get_cashflow"]},
    "geopolitical": {"tools": ["get_gdelt_events"]},
    "screener":     {"tools": ["screen_technical", "screen_fundamental"]},
    "options":      {"tools": ["get_option_chain", "get_greeks", "get_oi"]},
}


class DataSourceRegistry:
    def __init__(self, config: dict):
        self._sources: dict[str, DataSource] = {}
        self._vendor_config: dict[str, list[str]] = {}  # category → [primary, fallback...]
        self._load_config(config)

    def register(self, source: DataSource) -> None:
        self._sources[source.name] = source

    def get_source(self, name: str) -> DataSource:
        if name not in self._sources:
            raise KeyError(f"Source '{name}' not registered")
        return self._sources[name]

    def get_category_for_method(self, method: str) -> str:
        for cat, info in TOOLS_CATEGORIES.items():
            if method in info["tools"]:
                return cat
        raise ValueError(f"Unknown method: {method}")

    def get_vendor_chain(self, method: str) -> list[str]:
        category = self.get_category_for_method(method)
        return self._vendor_config.get(category, [])

    async def fetch(self, method: str, **kwargs) -> Any:
        """Try primary, fall back on rate limit / unavailable."""
        chain = self.get_vendor_chain(method)
        last_error = None
        for vendor_name in chain:
            if vendor_name not in self._sources:
                continue
            source = self._sources[vendor_name]
            if not source.supports(method):
                continue
            try:
                return await source.fetch(method, **kwargs)
            except (RateLimitError, SourceUnavailableError) as e:
                last_error = e
                continue
        if last_error:
            raise last_error
        raise RuntimeError(f"No vendor available for '{method}'")
```

### 3.3 Configuration

```yaml
# config/data_sources.yaml
data_vendors:
  ohlcv: zerodha_mcp,groww_mcp,yfinance
  quotes: groww_mcp,zerodha_mcp
  news: trafilatura,gdelt
  odds: polymarket
  geopolitical: gdelt
  screener: groww_mcp
  fundamentals: yfinance,groww_mcp
  options: groww_mcp

source_credentials_env:
  polymarket_funder: POLYMARKET_FUNDER_ADDRESS
  polymarket_pk: POLYMARKET_PRIVATE_KEY
  polymarket_chain: POLYMARKET_CHAIN_ID
```

---

## 4. Data Sources

### 4.1 YFinanceSource

```python
class YFinanceSource(DataSource):
    name = "yfinance"
    capabilities = ["get_ohlcv", "get_news", "get_fundamentals", "get_balance_sheet"]

    async def fetch(self, method: str, **kwargs):
        # Wrap yfinance.Ticker calls. yfinance is sync — wrap in asyncio.to_thread()
```

### 4.2 PolymarketSource (READ-ONLY in SP3)

```python
class PolymarketSource(DataSource):
    name = "polymarket"
    capabilities = ["get_polymarket_odds", "get_event_probability"]

    def __init__(self, host: str = "https://clob.polymarket.com"):
        self._host = host
        # py-clob-client allows read-only mode without private key

    async def fetch(self, method: str, **kwargs):
        # GET /markets, /price, /events from CLOB API
```

Trading deferred to SP4 (needs wallet wiring).

### 4.3 GrowwMCPSource / ZerodhaMCPSource

Wraps existing MCP server tools. Uses MCP client to call MCP tools.

```python
class GrowwMCPSource(DataSource):
    name = "groww_mcp"
    capabilities = ["get_ltp", "get_quotes", "get_oi", "get_option_chain",
                    "screen_technical", "screen_fundamental"]

    async def fetch(self, method: str, **kwargs):
        # Map method to MCP tool name, invoke via MCP client
        # e.g. method="get_ltp" → tool="get_ltp"
        # e.g. method="screen_technical" → tool="fetch_technical_screener"
```

### 4.4 GdeltSource

```python
class GdeltSource(DataSource):
    name = "gdelt"
    capabilities = ["get_gdelt_events", "get_news", "get_global_news"]
    # Wrap gdelt-doc-api
```

### 4.5 NewsScraperSource (trafilatura)

```python
class NewsScraperSource(DataSource):
    name = "trafilatura"
    capabilities = ["scrape_article"]

    async def fetch(self, method: str, url: str = "", **kwargs):
        # Use trafilatura.fetch_url + extract
        # Returns {"title", "text", "author", "date"}
```

---

## 5. Correlation Engine

### 5.1 Types (port WorldMonitor)

```python
# intelligence/correlation/types.py

@dataclass
class SignalEvidence:
    type: str              # "vix_spike", "news_polarity_shift", "polymarket_swing"
    source: str            # data source name
    severity: float        # 0-100
    timestamp: datetime
    label: str
    market: str            # affected market
    raw: dict | None = None


@dataclass
class ConvergenceCard:
    id: str
    domain: str            # "equity" | "crypto" | "forex" | "cross_market"
    title: str
    score: float           # 0-100 composite
    signals: list[SignalEvidence]
    markets: list[str]
    trend: str             # "escalating" | "stable" | "de-escalating"
    timestamp: datetime
    assessment: str | None = None
```

### 5.2 DomainAdapter ABC

```python
# intelligence/correlation/adapters.py

class DomainAdapter(ABC):
    domain: str
    weights: dict[str, float]    # signal_type → weight
    threshold: float
    time_window_hours: int

    @abstractmethod
    async def collect_signals(self, ctx: "IntelligenceContext") -> list[SignalEvidence]: ...

    @abstractmethod
    def generate_title(self, cluster: list[SignalEvidence]) -> str: ...
```

### 5.3 Concrete Adapters

```python
class EquityDomainAdapter(DomainAdapter):
    """Detects: VIX spikes, OI buildups, sector rotation, sentiment shifts."""
    domain = "equity"
    weights = {"vix_spike": 0.4, "oi_buildup": 0.3, "news_polarity": 0.2, "rsi_extreme": 0.1}
    threshold = 60.0
    time_window_hours = 24


class CryptoDomainAdapter(DomainAdapter):
    """Detects: BTC dominance shifts, funding rate divergence, on-chain spikes."""
    domain = "crypto"
    weights = {"funding_divergence": 0.35, "dominance_shift": 0.3, "volume_spike": 0.2, "polymarket_swing": 0.15}
    threshold = 60.0
    time_window_hours = 12


class ForexDomainAdapter(DomainAdapter):
    """Detects: rate-cut prediction shifts, DXY moves, correlation breaks."""
    domain = "forex"
    weights = {"polymarket_rate_swing": 0.4, "dxy_move": 0.3, "correlation_break": 0.2, "news_polarity": 0.1}
    threshold = 55.0
    time_window_hours = 12


class CrossMarketAdapter(DomainAdapter):
    """KEY: detects convergence across asset classes.
    Example: VIX spike + BTC dump + safe-haven forex move + war prediction up
    = systemic risk → reduce exposure across all accounts."""
    domain = "cross_market"
    weights = {"equity_vix": 0.25, "crypto_dump": 0.25, "forex_safe_haven": 0.20,
               "geopolitical_severity": 0.15, "polymarket_war_odds": 0.15}
    threshold = 70.0
    time_window_hours = 6
```

### 5.4 CorrelationEngine

```python
# intelligence/correlation/engine.py

# Dedupe TTLs per signal type (port WorldMonitor)
DEDUPE_TTLS = {
    "default": timedelta(minutes=30),
    "silent_divergence": timedelta(hours=6),
    "explained_market_move": timedelta(hours=6),
    "polymarket_swing": timedelta(hours=2),
    "news_spike": timedelta(minutes=30),
}


class CorrelationEngine:
    def __init__(self):
        self._adapters: list[DomainAdapter] = []
        self._previous_clusters: dict[str, list] = {}
        self._dedupe_seen: dict[str, datetime] = {}

    def register_adapter(self, adapter: DomainAdapter) -> None: ...

    async def run(self, ctx: "IntelligenceContext") -> list[ConvergenceCard]:
        """Pipeline: collect → cluster → score → filter → trend → dedupe."""
        all_cards = []
        for adapter in self._adapters:
            signals = await adapter.collect_signals(ctx)
            clusters = self._cluster(signals, adapter)
            scored = self._score_clusters(clusters, adapter)
            filtered = [c for c in scored if c.score >= adapter.threshold]
            with_trend = self._apply_trends(filtered, adapter)
            cards = [self._to_card(c, adapter) for c in with_trend]
            cards = self._dedupe(cards)
            self._previous_clusters[adapter.domain] = with_trend
            all_cards.extend(cards)
        return sorted(all_cards, key=lambda c: c.score, reverse=True)

    def _cluster(self, signals, adapter): ...    # group by market within time_window
    def _score_clusters(self, clusters, adapter): ...  # weighted by adapter.weights
    def _apply_trends(self, cards, adapter): ...  # compare vs _previous_clusters
    def _dedupe(self, cards): ...  # TTL-based dedupe
    def _to_card(self, cluster, adapter) -> ConvergenceCard: ...
```

---

## 6. Composite Scoring

### 6.1 SignalQuality + WEIGHT_PROFILES

```python
# intelligence/scoring/composite.py

@dataclass
class SignalQuality:
    confidence: float       # 0-1, how reliable
    intensity: float        # 0-1, how strong
    expectation_gap: float  # 0-1, how unexpected
    timeliness: float       # 0-1, how fresh
    composite: float        # 0-1, weighted sum
    tier: str               # "strong" | "notable" | "weak" | "noise"


WEIGHT_PROFILES = {
    "default":   (0.35, 0.30, 0.20, 0.15),
    "risk":      (0.45, 0.25, 0.20, 0.10),
    "macro":     (0.25, 0.40, 0.20, 0.15),
    "short_term":(0.30, 0.25, 0.20, 0.25),
}


def compute_isq(
    source_count: int,
    is_alert: bool,
    source_tier: int | None,
    intensity_value: float,    # 0-1
    expectation_gap_value: float,  # 0-1
    velocity_level: str,       # "spike" | "elevated" | "normal"
    velocity_trend: str | None, # "rising" | None
    profile: str = "default",
) -> SignalQuality:
    w_conf, w_int, w_gap, w_time = WEIGHT_PROFILES[profile]

    # confidence
    conf_base = 1.0 if source_count >= 3 else 0.7 if source_count == 2 else 0.4
    conf = min(1.0, conf_base + (0.2 if is_alert else 0) + (0.1 if source_tier and source_tier <= 2 else 0))

    # timeliness
    time = {"spike": 1.0, "elevated": 0.6}.get(velocity_level, 0.2)
    if velocity_trend == "rising":
        time = min(1.0, time + 0.2)

    composite = w_conf * conf + w_int * intensity_value + w_gap * expectation_gap_value + w_time * time

    tier = (
        "strong" if composite >= 0.75
        else "notable" if composite >= 0.50
        else "weak" if composite >= 0.25
        else "noise"
    )

    return SignalQuality(
        confidence=conf, intensity=intensity_value,
        expectation_gap=expectation_gap_value, timeliness=time,
        composite=composite, tier=tier,
    )
```

### 6.2 Profile Selection

| Agent | Profile | Why |
|-------|---------|-----|
| AnalystAgent | `default` | Balanced |
| GuardianAgent | `risk` | Confidence-weighted (avoid false positives) |
| StrategistAgent | `macro` | Intensity-weighted (find big moves) |
| Cross-market signals | `short_term` | Timeliness-weighted (act fast) |

---

## 7. Sentiment Engine

### 7.1 FinBertSentiment

```python
# intelligence/sentiment/finbert.py

class FinBertSentiment:
    def __init__(self, model_name: str = "ProsusAI/finbert"):
        self._model_name = model_name
        self._pipeline = None

    def _ensure_loaded(self):
        if self._pipeline is None:
            from transformers import pipeline
            self._pipeline = pipeline("sentiment-analysis", model=self._model_name)

    def score(self, text: str) -> dict:
        """Returns {"label": str, "score": float, "polarity": -1..+1}."""
        self._ensure_loaded()
        result = self._pipeline(text[:512])[0]
        polarity_map = {"positive": 1, "negative": -1, "neutral": 0}
        polarity = polarity_map.get(result["label"], 0) * result["score"]
        return {"label": result["label"], "score": result["score"], "polarity": polarity}

    def score_batch(self, texts: list[str]) -> list[dict]:
        self._ensure_loaded()
        truncated = [t[:512] for t in texts]
        return [
            {
                "label": r["label"], "score": r["score"],
                "polarity": {"positive": 1, "negative": -1, "neutral": 0}.get(r["label"], 0) * r["score"],
            }
            for r in self._pipeline(truncated)
        ]

    def aggregate_polarity(self, scores: list[dict]) -> float:
        """Weighted average polarity. Used for news aggregation."""
        if not scores:
            return 0.0
        return sum(s["polarity"] for s in scores) / len(scores)
```

Model loaded **once per pod** (~400MB RAM). Batched scoring for news efficiency.

---

## 8. IntelligenceContext + Builder

### 8.1 IntelligenceContext

```python
# intelligence/context.py

@dataclass
class IntelligenceContext:
    symbol: str
    market_state: dict

    # Cross-signal
    convergence_cards: list[ConvergenceCard]
    cross_market_signals: list[SignalEvidence]

    # Composite
    composite_score: SignalQuality | None

    # News + sentiment
    relevant_news: list[dict]            # [{title, url, polarity, label, score}]
    aggregated_sentiment: float          # weighted polarity -1..+1

    # Polymarket
    polymarket_odds: dict[str, float]

    # Geopolitical
    geopolitical_events: list[dict]

    # Attribution
    sources_used: list[str]
    fetch_latency_ms: dict[str, float]
    built_at: datetime
```

### 8.2 IntelligenceContextBuilder

```python
class IntelligenceContextBuilder:
    def __init__(
        self,
        registry: DataSourceRegistry,
        correlation_engine: CorrelationEngine,
        sentiment: FinBertSentiment,
        redis_client,
        cache_ttl_seconds: int = 60,
    ):
        ...

    async def build(self, symbol: str, account_name: str) -> IntelligenceContext:
        # 1. Check Redis cache
        cached = await self._get_cached(symbol, account_name)
        if cached:
            return cached

        # 2. Parallel fetch from registry
        tasks = {
            "ohlcv": self._safe_fetch("get_ohlcv", symbol=symbol),
            "news": self._safe_fetch("get_news", symbol=symbol),
            "polymarket": self._safe_fetch("get_polymarket_odds"),
            "geopolitical": self._safe_fetch("get_gdelt_events"),
        }
        results = await asyncio.gather(*tasks.values(), return_exceptions=True)

        # 3. Score news through FinBERT
        news = results[1] if not isinstance(results[1], Exception) else []
        news_scored = self._score_news(news)
        sentiment_avg = self._sentiment.aggregate_polarity(news_scored)

        # 4. Run correlation engine
        partial_ctx = IntelligenceContext(...)  # with what we have
        cards = await self._correlation_engine.run(partial_ctx)

        # 5. Compute composite quality score
        score = compute_isq(...)

        # 6. Assemble + cache
        ctx = IntelligenceContext(...)
        await self._cache(symbol, account_name, ctx)
        return ctx

    async def _safe_fetch(self, method, **kwargs):
        """Fetch with timeout, return None on failure."""

    def _score_news(self, news_items): ...
```

Cache uses JSON serialization (not pickle) for safety + cross-language compatibility.

---

## 9. AnalystAgent + JudgeAgent Wiring

### 9.1 AnalystAgent Update

```python
class AnalystAgent(BaseAgent):
    def __init__(self, llm_router, prompts_dir, account_name, intelligence_builder=None):
        self._intelligence_builder = intelligence_builder
        super().__init__(...)

    async def run(self, context: AgentContext) -> AgentOutput:
        intel = None
        if self._intelligence_builder:
            try:
                intel = await self._intelligence_builder.build(
                    symbol=context.symbol, account_name=context.account_name,
                )
            except Exception as e:
                logger.warning(f"Intelligence build failed: {e}")

        prompt = self._build_prompt(context, intel)
        ...

    def _build_prompt(self, context, intel: IntelligenceContext | None):
        sections = [...existing...]
        if intel:
            if intel.convergence_cards:
                sections.append("## Convergence Signals\n" + "\n".join(
                    f"- [{c.score:.0f}] {c.title} ({c.trend})" for c in intel.convergence_cards[:3]
                ))
            if intel.polymarket_odds:
                sections.append("## Polymarket Odds\n" + "\n".join(
                    f"- {k}: {v:.0%}" for k, v in intel.polymarket_odds.items()
                ))
            sections.append(f"## News Sentiment\nAggregated polarity: {intel.aggregated_sentiment:+.2f}")
            if intel.composite_score:
                sections.append(f"## Signal Quality\nTier: {intel.composite_score.tier} (composite {intel.composite_score.composite:.2f})")
        ...
```

### 9.2 JudgeAgent Update

Similar pattern — JudgeAgent receives IntelligenceContext for richer debate evaluation.

### 9.3 Pod Wiring

```python
class AgentPod:
    def __init__(self, ..., intelligence_builder=None):
        ...
        self.analyst = AnalystAgent(
            llm_router=self.llm_router,
            prompts_dir=prompts_dir,
            account_name=account_name,
            intelligence_builder=intelligence_builder,
        )
        ...
```

---

## 10. Caching

```
Redis key: intel:{account_name}:{symbol}
TTL: 60s default (configurable per market)
Value: JSON-serialized IntelligenceContext
```

JSON serialization (not pickle) — safer, language-agnostic, debuggable. Datetimes → ISO strings, dataclasses → dicts.

Per-symbol cache shared across pod's eval cycles. Each symbol independent cache.

Per-market TTL config:
```yaml
# accounts.yaml
agents:
  intelligence:
    enabled: true
    cache_ttl_seconds: 60        # default
    cache_ttl_overrides:
      crypto: 30                 # crypto moves faster
      forex: 90
```

---

## 11. Failure Handling

- Source down → registry skips, tries next vendor
- All vendors down for method → method returns None/empty in IntelligenceContext
- Correlation/sentiment partial failure → context built with available data
- Builder full failure → AnalystAgent runs without intel (degrades gracefully)
- FinBERT model load failure on pod start → log error, sentiment unavailable, continue
- Redis unavailable → no cache, every fetch is fresh

---

## 12. Migration Plan

| File | Change |
|------|--------|
| `app/intelligence/` | NEW package |
| `app/agents/analyst.py` | Accept `intelligence_builder=None` param |
| `app/agents/debate.py` | JudgeAgent same pattern |
| `app/agents/pod.py` | Inject `intelligence_builder` |
| `app/main.py` | Init registry + builder on startup |
| `config/data_sources.yaml` | NEW |
| `config/accounts.yaml` | Add `intelligence:` per account |
| `requirements.txt` | Add libraries |
| `prompts/defaults/analyst.md` | Update to expect intelligence sections |

---

## 13. Tech Stack

| Component | Library | License |
|-----------|---------|---------|
| Polymarket | `py-clob-client` | MIT |
| Market data | `yfinance` | Apache-2.0 |
| News scrape | `trafilatura` | Apache-2.0 |
| Geopolitical | `gdelt-doc-api` | MIT |
| Sentiment | `transformers` + `ProsusAI/finbert` | Apache-2.0 |
| ML runtime | `torch` (CPU) | BSD |
| Existing MCPs | Groww/Zerodha MCP | already connected |
| Cache | Redis (existing) | — |
| HTTP client | `httpx` (existing) | — |

---

## 14. Testing Strategy

1. **DataSource unit tests** — each source mocked HTTP/MCP, verify method routing
2. **Registry routing** — primary tries first, rate-limit triggers fallback, exhausts chain
3. **DomainAdapter tests** — synthetic SignalEvidence input → expected clusters
4. **CorrelationEngine** — full pipeline test with mock adapters
5. **Composite scoring** — exhaustive math (port WorldMonitor test cases): all weight profiles, edge cases (0/1 sources, missing fields)
6. **FinBERT** — mocked transformers pipeline, verify polarity mapping for positive/negative/neutral
7. **IntelligenceContextBuilder** — integration with all sources mocked, verify cache hit/miss
8. **AnalystAgent regression** — existing tests pass with `intelligence_builder=None`
9. **AnalystAgent enrichment** — new tests with mock IntelligenceContext, verify prompt sections appear
10. **End-to-end pod test** — run cycle with mocked intelligence, verify decision flows correctly

---

## 15. Success Criteria

1. `DataSourceRegistry` routes methods to correct vendor with fallback chain
2. All 6 data sources (yfinance, Polymarket, Groww MCP, Zerodha MCP, GDELT, trafilatura) implement `DataSource` interface and pass conformance tests
3. Polymarket source returns market odds for at least 5 known event markets (read-only)
4. `CorrelationEngine` produces `ConvergenceCard` outputs from synthetic signals across 4 domains
5. `compute_isq()` produces tier outputs matching WorldMonitor test cases for all 4 weight profiles
6. `FinBertSentiment` scores text in <100ms (CPU) and aggregates polarity correctly
7. `IntelligenceContextBuilder` builds context in <5s for typical symbol with all sources online
8. Redis cache (JSON-serialized) hits skip fetches; cache misses trigger full build
9. AnalystAgent prompts include intelligence sections when builder provided
10. AnalystAgent works unchanged when `intelligence_builder=None` (no SP2 regression)
11. All existing tests pass (no regression in 165 SP1+SP2 tests)
12. End-to-end pod cycle works with full intelligence context and PaperAdapter
