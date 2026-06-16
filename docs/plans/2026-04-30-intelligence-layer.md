# Intelligence Layer Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build multi-source data intelligence layer feeding KALYX agents richer context — Polymarket odds, news, sentiment, geopolitical signals, MCP servers, market data — with cross-market correlation detection and composite quality scoring.

**Architecture:** Vendor-abstracted DataSourceRegistry routes method calls across 6 sources with rate-limit fallback. CorrelationEngine clusters signals per domain (equity/crypto/forex/cross-market) using DomainAdapters. compute_isq() scores signals on 4 dimensions (confidence/intensity/expectation_gap/timeliness). FinBERT classifies news sentiment. IntelligenceContextBuilder assembles everything into a single context object cached in Redis (JSON serialization).

**Tech Stack:** Python 3.10+, asyncio, py-clob-client, yfinance, trafilatura, gdelt-doc-api, transformers, ProsusAI/finbert, Redis (existing), httpx, pytest-asyncio

---

## File Map

### New Files

| File | Responsibility |
|------|---------------|
| `backend/app/intelligence/__init__.py` | Package init |
| `backend/app/intelligence/base.py` | DataSource ABC, error types (RateLimitError, SourceUnavailableError) |
| `backend/app/intelligence/registry.py` | DataSourceRegistry, TOOLS_CATEGORIES, route_to_vendor |
| `backend/app/intelligence/context.py` | IntelligenceContext dataclass + IntelligenceContextBuilder |
| `backend/app/intelligence/sources/__init__.py` | Sources package init |
| `backend/app/intelligence/sources/yfinance_source.py` | YFinanceSource |
| `backend/app/intelligence/sources/polymarket_source.py` | PolymarketSource (read-only) |
| `backend/app/intelligence/sources/mcp_groww_source.py` | GrowwMCPSource |
| `backend/app/intelligence/sources/mcp_zerodha_source.py` | ZerodhaMCPSource |
| `backend/app/intelligence/sources/gdelt_source.py` | GdeltSource |
| `backend/app/intelligence/sources/news_scraper_source.py` | NewsScraperSource (trafilatura) |
| `backend/app/intelligence/correlation/__init__.py` | Correlation package init |
| `backend/app/intelligence/correlation/types.py` | SignalEvidence, ConvergenceCard dataclasses |
| `backend/app/intelligence/correlation/adapters.py` | DomainAdapter ABC + 4 concrete adapters |
| `backend/app/intelligence/correlation/engine.py` | CorrelationEngine pipeline |
| `backend/app/intelligence/scoring/__init__.py` | Scoring package init |
| `backend/app/intelligence/scoring/composite.py` | SignalQuality dataclass + compute_isq() |
| `backend/app/intelligence/scoring/weights.py` | WEIGHT_PROFILES |
| `backend/app/intelligence/sentiment/__init__.py` | Sentiment package init |
| `backend/app/intelligence/sentiment/finbert.py` | FinBertSentiment classifier wrapper |
| `backend/config/data_sources.yaml` | Vendor routing config |
| `backend/tests/intelligence/__init__.py` | Test package |
| `backend/tests/intelligence/test_base.py` | DataSource ABC + error type tests |
| `backend/tests/intelligence/test_registry.py` | Registry + routing + fallback tests |
| `backend/tests/intelligence/test_yfinance_source.py` | YFinanceSource tests |
| `backend/tests/intelligence/test_polymarket_source.py` | PolymarketSource tests |
| `backend/tests/intelligence/test_mcp_sources.py` | Groww/Zerodha MCP source tests |
| `backend/tests/intelligence/test_gdelt_source.py` | GDELT source tests |
| `backend/tests/intelligence/test_news_scraper_source.py` | trafilatura source tests |
| `backend/tests/intelligence/test_correlation_types.py` | SignalEvidence + ConvergenceCard tests |
| `backend/tests/intelligence/test_correlation_adapters.py` | DomainAdapter tests |
| `backend/tests/intelligence/test_correlation_engine.py` | Engine pipeline tests |
| `backend/tests/intelligence/test_scoring.py` | compute_isq exhaustive tests |
| `backend/tests/intelligence/test_finbert.py` | FinBertSentiment tests |
| `backend/tests/intelligence/test_context_builder.py` | IntelligenceContextBuilder integration tests |
| `backend/tests/intelligence/test_source_conformance.py` | Generic conformance suite for any source |

### Modified Files

| File | Change |
|------|--------|
| `backend/app/agents/analyst.py` | Accept optional `intelligence_builder` param, build intel context, enrich prompt |
| `backend/app/agents/debate.py` | JudgeAgent accepts optional intel context for richer evaluation |
| `backend/app/agents/pod.py` | Inject `intelligence_builder` into AnalystAgent + JudgeAgent |
| `backend/app/main.py` | Init DataSourceRegistry + IntelligenceContextBuilder on startup |
| `backend/app/config.py` | Add INTELLIGENCE_CONFIG_PATH, POLYMARKET_* env vars |
| `backend/config/accounts.yaml` | Add `intelligence:` section per account |
| `backend/prompts/defaults/analyst.md` | Add expected intelligence sections in prompt |
| `backend/requirements.txt` | Add libraries |

---

## Task 1: DataSource ABC + Error Types

**Files:**
- Create: `backend/app/intelligence/__init__.py`
- Create: `backend/app/intelligence/base.py`
- Create: `backend/tests/intelligence/__init__.py`
- Create: `backend/tests/intelligence/test_base.py`

- [ ] **Step 1: Write tests**

```python
# backend/tests/intelligence/__init__.py
"""Tests for intelligence layer."""

# backend/tests/intelligence/test_base.py
"""Tests for DataSource ABC and error types."""
import pytest


def test_data_source_is_abstract():
    from app.intelligence.base import DataSource

    with pytest.raises(TypeError):
        DataSource()


def test_rate_limit_error():
    from app.intelligence.base import RateLimitError

    err = RateLimitError("yfinance rate limited")
    assert "yfinance" in str(err)


def test_source_unavailable_error():
    from app.intelligence.base import SourceUnavailableError

    err = SourceUnavailableError("polymarket unavailable")
    assert "polymarket" in str(err)


def test_data_source_concrete_subclass():
    from app.intelligence.base import DataSource

    class TestSource(DataSource):
        @property
        def name(self):
            return "test"

        @property
        def capabilities(self):
            return ["get_test"]

        def supports(self, method):
            return method in self.capabilities

        async def fetch(self, method, **kwargs):
            return {"method": method, "kwargs": kwargs}

    src = TestSource()
    assert src.name == "test"
    assert src.supports("get_test") is True
    assert src.supports("get_other") is False


@pytest.mark.asyncio
async def test_concrete_subclass_fetch():
    from app.intelligence.base import DataSource

    class TestSource(DataSource):
        @property
        def name(self):
            return "test"

        @property
        def capabilities(self):
            return ["get_test"]

        def supports(self, method):
            return method in self.capabilities

        async def fetch(self, method, **kwargs):
            return {"method": method, "data": "ok"}

    src = TestSource()
    result = await src.fetch("get_test", symbol="NIFTY")
    assert result["method"] == "get_test"
    assert result["data"] == "ok"
```

- [ ] **Step 2: Run tests — FAIL**

Run: `cd backend && python -m pytest tests/intelligence/test_base.py -v`
Expected: ModuleNotFoundError

- [ ] **Step 3: Implement base.py**

```python
# backend/app/intelligence/__init__.py
"""Intelligence layer — multi-source data aggregation, correlation, scoring, sentiment."""
from app.intelligence.base import (
    DataSource,
    RateLimitError,
    SourceUnavailableError,
)

__all__ = ["DataSource", "RateLimitError", "SourceUnavailableError"]
```

```python
# backend/app/intelligence/base.py
"""DataSource abstract interface and error types for intelligence layer."""
from abc import ABC, abstractmethod
from typing import Any


class RateLimitError(Exception):
    """Source rate-limited. Triggers fallback to next vendor."""
    pass


class SourceUnavailableError(Exception):
    """Source unreachable or returned a fatal error. Triggers fallback."""
    pass


class DataSource(ABC):
    """Abstract data source.

    Each broker MCP, market data SDK, or scraper implements this interface.
    The DataSourceRegistry routes method calls to registered sources with
    primary + fallback chains based on per-category configuration.
    """

    @property
    @abstractmethod
    def name(self) -> str:
        """Short stable identifier (e.g. 'yfinance', 'polymarket', 'groww_mcp')."""
        ...

    @property
    @abstractmethod
    def capabilities(self) -> list[str]:
        """Methods this source can serve (e.g. ['get_ohlcv', 'get_news'])."""
        ...

    @abstractmethod
    def supports(self, method: str) -> bool:
        """Whether the source can serve the given method."""
        ...

    @abstractmethod
    async def fetch(self, method: str, **kwargs) -> Any:
        """Fetch data for the given method.

        Raises:
            RateLimitError: source rate-limited
            SourceUnavailableError: source unreachable
        """
        ...
```

- [ ] **Step 4: Run tests — PASS (5 tests)**

Run: `cd backend && python -m pytest tests/intelligence/test_base.py -v`
Expected: 5 passed

- [ ] **Step 5: Commit**

```bash
git add backend/app/intelligence/__init__.py backend/app/intelligence/base.py backend/tests/intelligence/__init__.py backend/tests/intelligence/test_base.py
git commit -m "feat(intelligence): add DataSource ABC and error types

Foundation for vendor-abstracted data sources. RateLimitError and
SourceUnavailableError trigger fallback chain in registry. Each
source declares capabilities and async fetch(method, **kwargs).

Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>"
```

---

## Task 2: DataSourceRegistry

**Files:**
- Create: `backend/app/intelligence/registry.py`
- Create: `backend/tests/intelligence/test_registry.py`
- Create: `backend/config/data_sources.yaml`

- [ ] **Step 1: Write tests**

```python
# backend/tests/intelligence/test_registry.py
"""Tests for DataSourceRegistry routing + fallback."""
import pytest
from app.intelligence.base import DataSource, RateLimitError, SourceUnavailableError


class MockSource(DataSource):
    def __init__(self, name, capabilities, fetch_impl=None):
        self._name = name
        self._capabilities = capabilities
        self._fetch_impl = fetch_impl or (lambda method, **kw: {"src": name, "method": method})

    @property
    def name(self):
        return self._name

    @property
    def capabilities(self):
        return self._capabilities

    def supports(self, method):
        return method in self._capabilities

    async def fetch(self, method, **kwargs):
        result = self._fetch_impl(method, **kwargs)
        if isinstance(result, Exception):
            raise result
        return result


@pytest.fixture
def basic_config():
    return {
        "data_vendors": {
            "ohlcv": "yfinance,zerodha_mcp",
            "news": "trafilatura,gdelt",
            "odds": "polymarket",
        }
    }


def test_registry_creation(basic_config):
    from app.intelligence.registry import DataSourceRegistry

    reg = DataSourceRegistry(basic_config)
    assert reg is not None


def test_register_and_get_source(basic_config):
    from app.intelligence.registry import DataSourceRegistry

    reg = DataSourceRegistry(basic_config)
    src = MockSource("yfinance", ["get_ohlcv"])
    reg.register(src)
    assert reg.get_source("yfinance") is src


def test_get_unknown_source_raises(basic_config):
    from app.intelligence.registry import DataSourceRegistry

    reg = DataSourceRegistry(basic_config)
    with pytest.raises(KeyError):
        reg.get_source("nonexistent")


def test_get_category_for_method(basic_config):
    from app.intelligence.registry import DataSourceRegistry

    reg = DataSourceRegistry(basic_config)
    assert reg.get_category_for_method("get_ohlcv") == "ohlcv"
    assert reg.get_category_for_method("get_news") == "news"
    assert reg.get_category_for_method("get_polymarket_odds") == "odds"


def test_get_category_for_unknown_method_raises(basic_config):
    from app.intelligence.registry import DataSourceRegistry

    reg = DataSourceRegistry(basic_config)
    with pytest.raises(ValueError):
        reg.get_category_for_method("get_nonsense")


def test_get_vendor_chain(basic_config):
    from app.intelligence.registry import DataSourceRegistry

    reg = DataSourceRegistry(basic_config)
    chain = reg.get_vendor_chain("get_ohlcv")
    assert chain == ["yfinance", "zerodha_mcp"]


@pytest.mark.asyncio
async def test_fetch_uses_primary(basic_config):
    from app.intelligence.registry import DataSourceRegistry

    reg = DataSourceRegistry(basic_config)
    reg.register(MockSource("yfinance", ["get_ohlcv"]))
    reg.register(MockSource("zerodha_mcp", ["get_ohlcv"]))

    result = await reg.fetch("get_ohlcv", symbol="NIFTY")
    assert result["src"] == "yfinance"


@pytest.mark.asyncio
async def test_fetch_falls_back_on_rate_limit(basic_config):
    from app.intelligence.registry import DataSourceRegistry

    reg = DataSourceRegistry(basic_config)
    reg.register(MockSource("yfinance", ["get_ohlcv"], fetch_impl=lambda m, **k: RateLimitError("y")))
    reg.register(MockSource("zerodha_mcp", ["get_ohlcv"]))

    result = await reg.fetch("get_ohlcv", symbol="NIFTY")
    assert result["src"] == "zerodha_mcp"


@pytest.mark.asyncio
async def test_fetch_falls_back_on_source_unavailable(basic_config):
    from app.intelligence.registry import DataSourceRegistry

    reg = DataSourceRegistry(basic_config)
    reg.register(MockSource("yfinance", ["get_ohlcv"], fetch_impl=lambda m, **k: SourceUnavailableError("y")))
    reg.register(MockSource("zerodha_mcp", ["get_ohlcv"]))

    result = await reg.fetch("get_ohlcv", symbol="NIFTY")
    assert result["src"] == "zerodha_mcp"


@pytest.mark.asyncio
async def test_fetch_skips_unsupported_source(basic_config):
    from app.intelligence.registry import DataSourceRegistry

    reg = DataSourceRegistry(basic_config)
    # yfinance registered but doesn't support get_ohlcv
    reg.register(MockSource("yfinance", ["get_news"]))
    reg.register(MockSource("zerodha_mcp", ["get_ohlcv"]))

    result = await reg.fetch("get_ohlcv", symbol="NIFTY")
    assert result["src"] == "zerodha_mcp"


@pytest.mark.asyncio
async def test_fetch_exhausts_chain_raises(basic_config):
    from app.intelligence.registry import DataSourceRegistry

    reg = DataSourceRegistry(basic_config)
    reg.register(MockSource("yfinance", ["get_ohlcv"], fetch_impl=lambda m, **k: RateLimitError("y")))
    reg.register(MockSource("zerodha_mcp", ["get_ohlcv"], fetch_impl=lambda m, **k: SourceUnavailableError("z")))

    with pytest.raises((RateLimitError, SourceUnavailableError)):
        await reg.fetch("get_ohlcv", symbol="NIFTY")


@pytest.mark.asyncio
async def test_fetch_no_vendors_raises(basic_config):
    from app.intelligence.registry import DataSourceRegistry

    reg = DataSourceRegistry(basic_config)
    # No source registered for ohlcv

    with pytest.raises(RuntimeError):
        await reg.fetch("get_ohlcv", symbol="NIFTY")
```

- [ ] **Step 2: Run tests — FAIL**

Run: `cd backend && python -m pytest tests/intelligence/test_registry.py -v`

- [ ] **Step 3: Implement registry.py**

```python
# backend/app/intelligence/registry.py
"""DataSourceRegistry — routes method calls across registered sources with fallback."""
import logging
from typing import Any

from app.intelligence.base import DataSource, RateLimitError, SourceUnavailableError

logger = logging.getLogger(__name__)


TOOLS_CATEGORIES: dict[str, dict] = {
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
    """Registry of data sources with vendor routing + rate-limit fallback chain."""

    def __init__(self, config: dict):
        self._sources: dict[str, DataSource] = {}
        self._vendor_config: dict[str, list[str]] = {}
        self._load_config(config)

    def _load_config(self, config: dict) -> None:
        vendors = config.get("data_vendors", {})
        for category, chain_str in vendors.items():
            chain = [v.strip() for v in str(chain_str).split(",") if v.strip()]
            self._vendor_config[category] = chain

    def register(self, source: DataSource) -> None:
        """Register a data source under its name."""
        self._sources[source.name] = source
        logger.info(f"Registered data source: {source.name} (capabilities={source.capabilities})")

    def get_source(self, name: str) -> DataSource:
        """Get a registered source. Raises KeyError if unknown."""
        if name not in self._sources:
            raise KeyError(f"Source '{name}' not registered")
        return self._sources[name]

    def get_category_for_method(self, method: str) -> str:
        """Find the category that contains the method. Raises ValueError if unknown."""
        for cat, info in TOOLS_CATEGORIES.items():
            if method in info["tools"]:
                return cat
        raise ValueError(f"Unknown method: {method}")

    def get_vendor_chain(self, method: str) -> list[str]:
        """Get configured vendor chain for the method's category."""
        category = self.get_category_for_method(method)
        return self._vendor_config.get(category, [])

    async def fetch(self, method: str, **kwargs) -> Any:
        """Fetch from primary vendor, fall back on rate limit / unavailable."""
        chain = self.get_vendor_chain(method)
        last_error: Exception | None = None

        for vendor_name in chain:
            if vendor_name not in self._sources:
                continue
            source = self._sources[vendor_name]
            if not source.supports(method):
                continue
            try:
                return await source.fetch(method, **kwargs)
            except (RateLimitError, SourceUnavailableError) as exc:
                logger.warning(f"Source {vendor_name} failed for {method}: {exc}")
                last_error = exc
                continue

        if last_error:
            raise last_error
        raise RuntimeError(f"No vendor available for '{method}'")
```

- [ ] **Step 4: Create data_sources.yaml**

```yaml
# backend/config/data_sources.yaml
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

- [ ] **Step 5: Run tests — PASS (12 tests)**

Run: `cd backend && python -m pytest tests/intelligence/test_registry.py -v`

- [ ] **Step 6: Commit**

```bash
git add backend/app/intelligence/registry.py backend/tests/intelligence/test_registry.py backend/config/data_sources.yaml
git commit -m "feat(intelligence): add DataSourceRegistry with vendor fallback chain

Routes method calls to registered sources via TOOLS_CATEGORIES.
On RateLimitError or SourceUnavailableError, falls through to next
vendor in chain. Configured via data_sources.yaml.

Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>"
```

---

## Task 3: Source Conformance Suite

**Files:**
- Create: `backend/tests/intelligence/test_source_conformance.py`

Generic test suite that runs against any DataSource implementation. New sources just add to ADAPTER_FACTORIES.

- [ ] **Step 1: Write conformance tests**

```python
# backend/tests/intelligence/test_source_conformance.py
"""Conformance tests for DataSource implementations."""
import pytest
from app.intelligence.base import DataSource


class StubSource(DataSource):
    @property
    def name(self):
        return "stub"

    @property
    def capabilities(self):
        return ["get_test", "scrape_article"]

    def supports(self, method):
        return method in self._capabilities_set

    @property
    def _capabilities_set(self):
        return set(self.capabilities)

    async def fetch(self, method, **kwargs):
        return {"src": self.name, "method": method, "kwargs": kwargs}


def make_stub_source():
    return StubSource()


SOURCE_FACTORIES = [
    pytest.param(make_stub_source, id="stub"),
]


@pytest.fixture(params=SOURCE_FACTORIES)
def source(request) -> DataSource:
    return request.param()


def test_source_name_is_string(source):
    assert isinstance(source.name, str)
    assert len(source.name) > 0


def test_source_capabilities_is_list(source):
    caps = source.capabilities
    assert isinstance(caps, list)
    assert all(isinstance(c, str) for c in caps)


def test_source_supports_returns_bool(source):
    for cap in source.capabilities:
        assert source.supports(cap) is True
    assert source.supports("definitely_not_a_method") is False


@pytest.mark.asyncio
async def test_source_fetch_supported_method(source):
    if not source.capabilities:
        return
    method = source.capabilities[0]
    result = await source.fetch(method, foo="bar")
    assert result is not None
```

- [ ] **Step 2: Run — PASS (4 tests for stub)**

Run: `cd backend && python -m pytest tests/intelligence/test_source_conformance.py -v`

- [ ] **Step 3: Commit**

```bash
git add backend/tests/intelligence/test_source_conformance.py
git commit -m "test(intelligence): add DataSource conformance test suite

Generic parameterized tests run against any DataSource implementation.
New sources (yfinance, polymarket, etc.) add factory to SOURCE_FACTORIES
and inherit all conformance checks automatically.

Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>"
```

---

## Task 4: Composite Scoring (compute_isq)

**Files:**
- Create: `backend/app/intelligence/scoring/__init__.py`
- Create: `backend/app/intelligence/scoring/weights.py`
- Create: `backend/app/intelligence/scoring/composite.py`
- Create: `backend/tests/intelligence/test_scoring.py`

- [ ] **Step 1: Write exhaustive tests**

```python
# backend/tests/intelligence/test_scoring.py
"""Exhaustive tests for compute_isq composite scoring."""
import pytest


def test_weight_profiles_sum_to_one():
    from app.intelligence.scoring.weights import WEIGHT_PROFILES

    for profile, weights in WEIGHT_PROFILES.items():
        assert abs(sum(weights) - 1.0) < 0.001, f"Profile '{profile}' weights don't sum to 1.0"


def test_signal_quality_dataclass():
    from app.intelligence.scoring.composite import SignalQuality

    sq = SignalQuality(
        confidence=0.8, intensity=0.6, expectation_gap=0.5,
        timeliness=0.7, composite=0.7, tier="notable",
    )
    assert sq.composite == 0.7
    assert sq.tier == "notable"


def test_compute_isq_strong_tier():
    from app.intelligence.scoring.composite import compute_isq

    sq = compute_isq(
        source_count=3, is_alert=True, source_tier=1,
        intensity_value=1.0, expectation_gap_value=0.8,
        velocity_level="spike", velocity_trend="rising",
        profile="default",
    )
    assert sq.tier == "strong"
    assert sq.composite >= 0.75


def test_compute_isq_noise_tier():
    from app.intelligence.scoring.composite import compute_isq

    sq = compute_isq(
        source_count=1, is_alert=False, source_tier=None,
        intensity_value=0.1, expectation_gap_value=0.1,
        velocity_level="normal", velocity_trend=None,
        profile="default",
    )
    assert sq.tier == "noise"


def test_compute_isq_confidence_high_with_3_sources():
    from app.intelligence.scoring.composite import compute_isq

    sq = compute_isq(
        source_count=3, is_alert=False, source_tier=None,
        intensity_value=0.5, expectation_gap_value=0.5,
        velocity_level="normal", velocity_trend=None,
        profile="default",
    )
    assert sq.confidence == 1.0


def test_compute_isq_confidence_medium_with_2_sources():
    from app.intelligence.scoring.composite import compute_isq

    sq = compute_isq(
        source_count=2, is_alert=False, source_tier=None,
        intensity_value=0.5, expectation_gap_value=0.5,
        velocity_level="normal", velocity_trend=None,
        profile="default",
    )
    assert sq.confidence == 0.7


def test_compute_isq_confidence_low_with_1_source():
    from app.intelligence.scoring.composite import compute_isq

    sq = compute_isq(
        source_count=1, is_alert=False, source_tier=None,
        intensity_value=0.5, expectation_gap_value=0.5,
        velocity_level="normal", velocity_trend=None,
        profile="default",
    )
    assert sq.confidence == 0.4


def test_compute_isq_alert_boost():
    from app.intelligence.scoring.composite import compute_isq

    plain = compute_isq(
        source_count=2, is_alert=False, source_tier=None,
        intensity_value=0.5, expectation_gap_value=0.5,
        velocity_level="normal", velocity_trend=None,
    )
    alert = compute_isq(
        source_count=2, is_alert=True, source_tier=None,
        intensity_value=0.5, expectation_gap_value=0.5,
        velocity_level="normal", velocity_trend=None,
    )
    assert alert.confidence > plain.confidence


def test_compute_isq_tier_boost():
    from app.intelligence.scoring.composite import compute_isq

    no_tier = compute_isq(
        source_count=2, is_alert=False, source_tier=None,
        intensity_value=0.5, expectation_gap_value=0.5,
        velocity_level="normal", velocity_trend=None,
    )
    tier1 = compute_isq(
        source_count=2, is_alert=False, source_tier=1,
        intensity_value=0.5, expectation_gap_value=0.5,
        velocity_level="normal", velocity_trend=None,
    )
    assert tier1.confidence > no_tier.confidence


def test_compute_isq_velocity_spike():
    from app.intelligence.scoring.composite import compute_isq

    normal = compute_isq(
        source_count=2, is_alert=False, source_tier=None,
        intensity_value=0.5, expectation_gap_value=0.5,
        velocity_level="normal", velocity_trend=None,
    )
    spike = compute_isq(
        source_count=2, is_alert=False, source_tier=None,
        intensity_value=0.5, expectation_gap_value=0.5,
        velocity_level="spike", velocity_trend=None,
    )
    assert spike.timeliness > normal.timeliness
    assert spike.timeliness == 1.0


def test_compute_isq_velocity_rising_boost():
    from app.intelligence.scoring.composite import compute_isq

    elevated = compute_isq(
        source_count=2, is_alert=False, source_tier=None,
        intensity_value=0.5, expectation_gap_value=0.5,
        velocity_level="elevated", velocity_trend=None,
    )
    rising = compute_isq(
        source_count=2, is_alert=False, source_tier=None,
        intensity_value=0.5, expectation_gap_value=0.5,
        velocity_level="elevated", velocity_trend="rising",
    )
    assert rising.timeliness > elevated.timeliness


def test_compute_isq_risk_profile_weights_confidence_higher():
    from app.intelligence.scoring.composite import compute_isq

    # Same inputs, different profiles. Risk profile weights confidence highest.
    default = compute_isq(
        source_count=3, is_alert=True, source_tier=1,
        intensity_value=0.3, expectation_gap_value=0.3,
        velocity_level="normal", velocity_trend=None,
        profile="default",
    )
    risk = compute_isq(
        source_count=3, is_alert=True, source_tier=1,
        intensity_value=0.3, expectation_gap_value=0.3,
        velocity_level="normal", velocity_trend=None,
        profile="risk",
    )
    # Both have max confidence, but risk weights it 0.45 vs default 0.35
    assert risk.composite > default.composite


def test_compute_isq_macro_profile_weights_intensity_higher():
    from app.intelligence.scoring.composite import compute_isq

    default = compute_isq(
        source_count=1, is_alert=False, source_tier=None,
        intensity_value=1.0, expectation_gap_value=0.3,
        velocity_level="normal", velocity_trend=None,
        profile="default",
    )
    macro = compute_isq(
        source_count=1, is_alert=False, source_tier=None,
        intensity_value=1.0, expectation_gap_value=0.3,
        velocity_level="normal", velocity_trend=None,
        profile="macro",
    )
    assert macro.composite > default.composite


def test_compute_isq_unknown_profile_raises():
    from app.intelligence.scoring.composite import compute_isq

    with pytest.raises(KeyError):
        compute_isq(
            source_count=1, is_alert=False, source_tier=None,
            intensity_value=0.5, expectation_gap_value=0.5,
            velocity_level="normal", velocity_trend=None,
            profile="nonexistent",
        )


def test_compute_isq_tier_boundaries():
    from app.intelligence.scoring.composite import compute_isq

    # Build cases that land at each tier boundary
    # noise: composite < 0.25
    # weak: 0.25 <= composite < 0.50
    # notable: 0.50 <= composite < 0.75
    # strong: composite >= 0.75

    very_high = compute_isq(
        source_count=3, is_alert=True, source_tier=1,
        intensity_value=1.0, expectation_gap_value=1.0,
        velocity_level="spike", velocity_trend="rising",
        profile="default",
    )
    assert very_high.tier == "strong"

    very_low = compute_isq(
        source_count=1, is_alert=False, source_tier=None,
        intensity_value=0.0, expectation_gap_value=0.0,
        velocity_level="normal", velocity_trend=None,
        profile="default",
    )
    assert very_low.tier in ("noise", "weak")
```

- [ ] **Step 2: Run — FAIL**

- [ ] **Step 3: Implement scoring**

```python
# backend/app/intelligence/scoring/__init__.py
"""Composite scoring for intelligence signals."""
from app.intelligence.scoring.composite import SignalQuality, compute_isq
from app.intelligence.scoring.weights import WEIGHT_PROFILES

__all__ = ["SignalQuality", "compute_isq", "WEIGHT_PROFILES"]
```

```python
# backend/app/intelligence/scoring/weights.py
"""Weight profiles for compute_isq.

Each profile is a 4-tuple: (confidence, intensity, expectation_gap, timeliness).
All profiles sum to 1.0.
"""

WEIGHT_PROFILES: dict[str, tuple[float, float, float, float]] = {
    # Balanced — generic use
    "default":    (0.35, 0.30, 0.20, 0.15),
    # Risk-aware — confidence weighted higher (avoid false positives)
    "risk":       (0.45, 0.25, 0.20, 0.10),
    # Macro — intensity weighted higher (find big moves)
    "macro":      (0.25, 0.40, 0.20, 0.15),
    # Short-term — timeliness weighted higher (act fast on fresh signals)
    "short_term": (0.30, 0.25, 0.20, 0.25),
}
```

```python
# backend/app/intelligence/scoring/composite.py
"""compute_isq — 4-dimensional composite signal quality scoring.

Ported algorithm from WorldMonitor signal-quality.ts.
Returns SignalQuality with tier classification.
"""
from dataclasses import dataclass

from app.intelligence.scoring.weights import WEIGHT_PROFILES


@dataclass
class SignalQuality:
    """Composite signal quality score across 4 dimensions."""
    confidence: float        # 0-1, how reliable
    intensity: float         # 0-1, how strong
    expectation_gap: float   # 0-1, how unexpected vs baseline
    timeliness: float        # 0-1, how fresh / accelerating
    composite: float         # 0-1, weighted sum
    tier: str                # "strong" | "notable" | "weak" | "noise"


_VELOCITY_LEVELS = {"spike": 1.0, "elevated": 0.6}
_DEFAULT_VELOCITY = 0.2


def compute_isq(
    source_count: int,
    is_alert: bool,
    source_tier: int | None,
    intensity_value: float,
    expectation_gap_value: float,
    velocity_level: str,
    velocity_trend: str | None,
    profile: str = "default",
) -> SignalQuality:
    """Compute composite signal quality.

    Args:
        source_count: number of distinct sources reporting the signal
        is_alert: source flagged the signal as an alert
        source_tier: tier of source (1=best). None if unknown.
        intensity_value: 0-1, magnitude of the signal
        expectation_gap_value: 0-1, how unexpected vs baseline
        velocity_level: 'spike' | 'elevated' | 'normal'
        velocity_trend: 'rising' | None
        profile: weight profile key

    Returns:
        SignalQuality with all 4 dimensions, composite, and tier.
    """
    if profile not in WEIGHT_PROFILES:
        raise KeyError(f"Unknown weight profile: {profile}")

    w_conf, w_int, w_gap, w_time = WEIGHT_PROFILES[profile]

    # confidence
    if source_count >= 3:
        conf_base = 1.0
    elif source_count == 2:
        conf_base = 0.7
    else:
        conf_base = 0.4
    conf = conf_base
    if is_alert:
        conf += 0.2
    if source_tier is not None and source_tier <= 2:
        conf += 0.1
    conf = min(1.0, conf)

    # timeliness
    timeliness = _VELOCITY_LEVELS.get(velocity_level, _DEFAULT_VELOCITY)
    if velocity_trend == "rising":
        timeliness = min(1.0, timeliness + 0.2)

    composite = (
        w_conf * conf
        + w_int * intensity_value
        + w_gap * expectation_gap_value
        + w_time * timeliness
    )

    if composite >= 0.75:
        tier = "strong"
    elif composite >= 0.50:
        tier = "notable"
    elif composite >= 0.25:
        tier = "weak"
    else:
        tier = "noise"

    return SignalQuality(
        confidence=conf,
        intensity=intensity_value,
        expectation_gap=expectation_gap_value,
        timeliness=timeliness,
        composite=composite,
        tier=tier,
    )
```

- [ ] **Step 4: Run — PASS (15 tests)**

Run: `cd backend && python -m pytest tests/intelligence/test_scoring.py -v`

- [ ] **Step 5: Commit**

```bash
git add backend/app/intelligence/scoring/ backend/tests/intelligence/test_scoring.py
git commit -m "feat(intelligence): add compute_isq composite scoring

4-dim signal quality: confidence, intensity, expectation_gap, timeliness.
Weight profiles: default, risk, macro, short_term. Tier classification:
strong/notable/weak/noise. Algorithm ported from WorldMonitor
signal-quality.ts.

Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>"
```

---

## Task 5: Correlation Types + DomainAdapter ABC

**Files:**
- Create: `backend/app/intelligence/correlation/__init__.py`
- Create: `backend/app/intelligence/correlation/types.py`
- Create: `backend/tests/intelligence/test_correlation_types.py`

- [ ] **Step 1: Write tests**

```python
# backend/tests/intelligence/test_correlation_types.py
"""Tests for correlation engine types."""
import pytest
from datetime import datetime


def test_signal_evidence_creation():
    from app.intelligence.correlation.types import SignalEvidence

    sig = SignalEvidence(
        type="vix_spike",
        source="zerodha_mcp",
        severity=85.0,
        timestamp=datetime.utcnow(),
        label="VIX spiked above 18",
        market="NIFTY",
        raw={"vix": 18.5},
    )
    assert sig.type == "vix_spike"
    assert sig.severity == 85.0
    assert sig.market == "NIFTY"


def test_signal_evidence_optional_raw():
    from app.intelligence.correlation.types import SignalEvidence

    sig = SignalEvidence(
        type="news_spike", source="trafilatura", severity=50.0,
        timestamp=datetime.utcnow(), label="news event", market="BTC",
    )
    assert sig.raw is None


def test_convergence_card_creation():
    from app.intelligence.correlation.types import SignalEvidence, ConvergenceCard

    sig = SignalEvidence(
        type="vix_spike", source="zerodha_mcp", severity=85.0,
        timestamp=datetime.utcnow(), label="spike", market="NIFTY",
    )
    card = ConvergenceCard(
        id="card-001",
        domain="equity",
        title="VIX Spike + OI Buildup",
        score=78.5,
        signals=[sig],
        markets=["NIFTY"],
        trend="escalating",
        timestamp=datetime.utcnow(),
    )
    assert card.domain == "equity"
    assert card.score == 78.5
    assert card.trend == "escalating"
    assert len(card.signals) == 1
    assert card.assessment is None


def test_convergence_card_optional_assessment():
    from app.intelligence.correlation.types import ConvergenceCard

    card = ConvergenceCard(
        id="c", domain="crypto", title="t", score=60.0,
        signals=[], markets=[], trend="stable", timestamp=datetime.utcnow(),
        assessment="LLM said: be cautious",
    )
    assert card.assessment == "LLM said: be cautious"
```

- [ ] **Step 2: Run — FAIL**

- [ ] **Step 3: Implement types.py**

```python
# backend/app/intelligence/correlation/__init__.py
"""Correlation engine — clusters signals across markets, scores convergence."""
from app.intelligence.correlation.types import SignalEvidence, ConvergenceCard

__all__ = ["SignalEvidence", "ConvergenceCard"]
```

```python
# backend/app/intelligence/correlation/types.py
"""Types for the correlation engine.

Ported from WorldMonitor correlation-engine/types.ts.
"""
from dataclasses import dataclass
from datetime import datetime


@dataclass
class SignalEvidence:
    """A single evidence point for a market signal."""
    type: str           # e.g. "vix_spike", "news_polarity_shift", "polymarket_swing"
    source: str         # data source name
    severity: float     # 0-100
    timestamp: datetime
    label: str
    market: str         # affected market identifier
    raw: dict | None = None


@dataclass
class ConvergenceCard:
    """A clustered + scored set of signals indicating market convergence."""
    id: str
    domain: str         # "equity" | "crypto" | "forex" | "cross_market"
    title: str
    score: float        # 0-100 composite
    signals: list[SignalEvidence]
    markets: list[str]
    trend: str          # "escalating" | "stable" | "de-escalating"
    timestamp: datetime
    assessment: str | None = None
```

- [ ] **Step 4: Run — PASS (4 tests)**

Run: `cd backend && python -m pytest tests/intelligence/test_correlation_types.py -v`

- [ ] **Step 5: Commit**

```bash
git add backend/app/intelligence/correlation/__init__.py backend/app/intelligence/correlation/types.py backend/tests/intelligence/test_correlation_types.py
git commit -m "feat(intelligence): add SignalEvidence + ConvergenceCard types

Ported from WorldMonitor correlation-engine. Foundation for the
correlation pipeline: collect evidence → cluster → score → emit cards.

Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>"
```

---

## Task 6: DomainAdapter ABC + Concrete Adapters

**Files:**
- Create: `backend/app/intelligence/correlation/adapters.py`
- Create: `backend/tests/intelligence/test_correlation_adapters.py`

- [ ] **Step 1: Write tests**

```python
# backend/tests/intelligence/test_correlation_adapters.py
"""Tests for DomainAdapter implementations."""
import pytest
from datetime import datetime
from app.intelligence.correlation.types import SignalEvidence


@pytest.fixture
def stub_intel_ctx():
    # Use a minimal dict-based stand-in to avoid circular dependency on context module
    class StubCtx:
        def __init__(self):
            self.symbol = "NIFTY"
            self.market_state = {"vix": 18.5, "ltp": 22500}
            self.relevant_news = [{"title": "test", "polarity": -0.6}]
            self.polymarket_odds = {"war_escalation": 0.15}
            self.geopolitical_events = []
            self.aggregated_sentiment = -0.3
    return StubCtx()


def test_domain_adapter_is_abstract():
    from app.intelligence.correlation.adapters import DomainAdapter

    with pytest.raises(TypeError):
        DomainAdapter()


def test_equity_adapter_attributes():
    from app.intelligence.correlation.adapters import EquityDomainAdapter

    adapter = EquityDomainAdapter()
    assert adapter.domain == "equity"
    assert adapter.threshold > 0
    assert adapter.time_window_hours > 0
    assert "vix_spike" in adapter.weights


def test_crypto_adapter_attributes():
    from app.intelligence.correlation.adapters import CryptoDomainAdapter

    adapter = CryptoDomainAdapter()
    assert adapter.domain == "crypto"
    assert adapter.threshold > 0


def test_forex_adapter_attributes():
    from app.intelligence.correlation.adapters import ForexDomainAdapter

    adapter = ForexDomainAdapter()
    assert adapter.domain == "forex"


def test_cross_market_adapter_attributes():
    from app.intelligence.correlation.adapters import CrossMarketAdapter

    adapter = CrossMarketAdapter()
    assert adapter.domain == "cross_market"
    assert adapter.threshold >= 70


@pytest.mark.asyncio
async def test_equity_adapter_collects_vix_spike(stub_intel_ctx):
    from app.intelligence.correlation.adapters import EquityDomainAdapter

    adapter = EquityDomainAdapter()
    signals = await adapter.collect_signals(stub_intel_ctx)
    # With vix=18.5 (>18), should produce a vix_spike signal
    vix_signals = [s for s in signals if s.type == "vix_spike"]
    assert len(vix_signals) >= 1


@pytest.mark.asyncio
async def test_equity_adapter_collects_news_polarity(stub_intel_ctx):
    from app.intelligence.correlation.adapters import EquityDomainAdapter

    adapter = EquityDomainAdapter()
    signals = await adapter.collect_signals(stub_intel_ctx)
    polarity_signals = [s for s in signals if s.type == "news_polarity"]
    assert len(polarity_signals) >= 1


def test_equity_adapter_generate_title():
    from app.intelligence.correlation.adapters import EquityDomainAdapter

    adapter = EquityDomainAdapter()
    sigs = [
        SignalEvidence(
            type="vix_spike", source="x", severity=80, timestamp=datetime.utcnow(),
            label="VIX spike", market="NIFTY",
        ),
    ]
    title = adapter.generate_title(sigs)
    assert isinstance(title, str)
    assert len(title) > 0
```

- [ ] **Step 2: Run — FAIL**

- [ ] **Step 3: Implement adapters.py**

```python
# backend/app/intelligence/correlation/adapters.py
"""DomainAdapter implementations — per-market signal collectors."""
from abc import ABC, abstractmethod
from datetime import datetime
from typing import Any

from app.intelligence.correlation.types import SignalEvidence


class DomainAdapter(ABC):
    """Abstract per-market signal collector."""

    domain: str = ""
    weights: dict[str, float] = {}
    threshold: float = 50.0
    time_window_hours: int = 24

    @abstractmethod
    async def collect_signals(self, ctx: Any) -> list[SignalEvidence]:
        """Collect signal evidence from intelligence context."""
        ...

    @abstractmethod
    def generate_title(self, cluster: list[SignalEvidence]) -> str:
        """Generate a human-readable title for a cluster of signals."""
        ...


class EquityDomainAdapter(DomainAdapter):
    """Detects equity-market signals: VIX spikes, OI buildups, sentiment shifts."""

    domain = "equity"
    weights = {"vix_spike": 0.4, "oi_buildup": 0.3, "news_polarity": 0.2, "rsi_extreme": 0.1}
    threshold = 60.0
    time_window_hours = 24

    async def collect_signals(self, ctx: Any) -> list[SignalEvidence]:
        signals: list[SignalEvidence] = []
        ms = getattr(ctx, "market_state", {}) or {}
        now = datetime.utcnow()

        vix = ms.get("vix")
        if vix is not None and vix > 18:
            signals.append(SignalEvidence(
                type="vix_spike", source="market_state", severity=min(100, (vix - 14) * 10),
                timestamp=now, label=f"VIX at {vix:.1f}",
                market=getattr(ctx, "symbol", ""),
                raw={"vix": vix},
            ))

        oi = ms.get("oi_change_pct")
        if oi is not None and abs(oi) > 10:
            signals.append(SignalEvidence(
                type="oi_buildup", source="market_state", severity=min(100, abs(oi) * 5),
                timestamp=now, label=f"OI change {oi:+.1f}%",
                market=getattr(ctx, "symbol", ""),
                raw={"oi_change_pct": oi},
            ))

        polarity = getattr(ctx, "aggregated_sentiment", 0.0) or 0.0
        if abs(polarity) > 0.3:
            signals.append(SignalEvidence(
                type="news_polarity", source="finbert", severity=min(100, abs(polarity) * 100),
                timestamp=now, label=f"Aggregated polarity {polarity:+.2f}",
                market=getattr(ctx, "symbol", ""),
                raw={"polarity": polarity},
            ))

        rsi = ms.get("rsi")
        if rsi is not None and (rsi < 25 or rsi > 75):
            signals.append(SignalEvidence(
                type="rsi_extreme", source="market_state", severity=80,
                timestamp=now, label=f"RSI at {rsi:.1f}",
                market=getattr(ctx, "symbol", ""),
                raw={"rsi": rsi},
            ))

        return signals

    def generate_title(self, cluster: list[SignalEvidence]) -> str:
        types = sorted({s.type for s in cluster})
        return "Equity " + " + ".join(t.replace("_", " ").title() for t in types)


class CryptoDomainAdapter(DomainAdapter):
    """Detects crypto signals: BTC dominance shifts, funding divergence, volume spikes."""

    domain = "crypto"
    weights = {"funding_divergence": 0.35, "dominance_shift": 0.3, "volume_spike": 0.2, "polymarket_swing": 0.15}
    threshold = 60.0
    time_window_hours = 12

    async def collect_signals(self, ctx: Any) -> list[SignalEvidence]:
        signals: list[SignalEvidence] = []
        ms = getattr(ctx, "market_state", {}) or {}
        now = datetime.utcnow()

        funding = ms.get("funding_rate")
        if funding is not None and abs(funding) > 0.01:
            signals.append(SignalEvidence(
                type="funding_divergence", source="market_state",
                severity=min(100, abs(funding) * 5000),
                timestamp=now, label=f"Funding rate {funding:+.4f}",
                market=getattr(ctx, "symbol", ""),
                raw={"funding_rate": funding},
            ))

        dominance = ms.get("btc_dominance_change_pct")
        if dominance is not None and abs(dominance) > 1:
            signals.append(SignalEvidence(
                type="dominance_shift", source="market_state",
                severity=min(100, abs(dominance) * 20),
                timestamp=now, label=f"BTC dominance {dominance:+.2f}%",
                market="BTC", raw={"dominance_pct": dominance},
            ))

        vol = ms.get("volume_zscore")
        if vol is not None and abs(vol) > 2:
            signals.append(SignalEvidence(
                type="volume_spike", source="market_state",
                severity=min(100, abs(vol) * 20),
                timestamp=now, label=f"Volume z-score {vol:+.1f}",
                market=getattr(ctx, "symbol", ""),
                raw={"volume_zscore": vol},
            ))

        return signals

    def generate_title(self, cluster: list[SignalEvidence]) -> str:
        types = sorted({s.type for s in cluster})
        return "Crypto " + " + ".join(t.replace("_", " ").title() for t in types)


class ForexDomainAdapter(DomainAdapter):
    """Detects forex signals: rate-cut prediction shifts, DXY moves, correlation breaks."""

    domain = "forex"
    weights = {"polymarket_rate_swing": 0.4, "dxy_move": 0.3, "correlation_break": 0.2, "news_polarity": 0.1}
    threshold = 55.0
    time_window_hours = 12

    async def collect_signals(self, ctx: Any) -> list[SignalEvidence]:
        signals: list[SignalEvidence] = []
        ms = getattr(ctx, "market_state", {}) or {}
        polymarket = getattr(ctx, "polymarket_odds", {}) or {}
        now = datetime.utcnow()

        # Polymarket rate-cut swing — look for fed_rate_cut keys
        for key, prob in polymarket.items():
            if "rate" in key.lower() and prob > 0.7:
                signals.append(SignalEvidence(
                    type="polymarket_rate_swing", source="polymarket",
                    severity=min(100, prob * 100),
                    timestamp=now, label=f"{key} probability {prob:.0%}",
                    market="USD", raw={key: prob},
                ))

        dxy = ms.get("dxy_change_pct")
        if dxy is not None and abs(dxy) > 0.5:
            signals.append(SignalEvidence(
                type="dxy_move", source="market_state",
                severity=min(100, abs(dxy) * 50),
                timestamp=now, label=f"DXY {dxy:+.2f}%",
                market="USD", raw={"dxy_change_pct": dxy},
            ))

        return signals

    def generate_title(self, cluster: list[SignalEvidence]) -> str:
        types = sorted({s.type for s in cluster})
        return "Forex " + " + ".join(t.replace("_", " ").title() for t in types)


class CrossMarketAdapter(DomainAdapter):
    """Detects convergence across asset classes — systemic risk signals."""

    domain = "cross_market"
    weights = {
        "equity_vix": 0.25, "crypto_dump": 0.25, "forex_safe_haven": 0.20,
        "geopolitical_severity": 0.15, "polymarket_war_odds": 0.15,
    }
    threshold = 70.0
    time_window_hours = 6

    async def collect_signals(self, ctx: Any) -> list[SignalEvidence]:
        signals: list[SignalEvidence] = []
        ms = getattr(ctx, "market_state", {}) or {}
        polymarket = getattr(ctx, "polymarket_odds", {}) or {}
        geo = getattr(ctx, "geopolitical_events", []) or []
        now = datetime.utcnow()

        vix = ms.get("vix")
        if vix is not None and vix > 20:
            signals.append(SignalEvidence(
                type="equity_vix", source="market_state",
                severity=min(100, (vix - 15) * 8),
                timestamp=now, label=f"Cross-market VIX at {vix:.1f}",
                market="GLOBAL", raw={"vix": vix},
            ))

        for key, prob in polymarket.items():
            kl = key.lower()
            if any(w in kl for w in ("war", "conflict", "escalation")) and prob > 0.2:
                signals.append(SignalEvidence(
                    type="polymarket_war_odds", source="polymarket",
                    severity=min(100, prob * 200),
                    timestamp=now, label=f"{key} probability {prob:.0%}",
                    market="GLOBAL", raw={key: prob},
                ))

        if len(geo) > 0:
            severities = [e.get("severity", 0) for e in geo if isinstance(e, dict)]
            if severities:
                max_sev = max(severities)
                if max_sev > 50:
                    signals.append(SignalEvidence(
                        type="geopolitical_severity", source="gdelt",
                        severity=max_sev, timestamp=now,
                        label=f"Geopolitical event severity {max_sev}",
                        market="GLOBAL", raw={"max_severity": max_sev},
                    ))

        return signals

    def generate_title(self, cluster: list[SignalEvidence]) -> str:
        types = sorted({s.type for s in cluster})
        return "Cross-Market " + " + ".join(t.replace("_", " ").title() for t in types)
```

- [ ] **Step 4: Run — PASS (8 tests)**

Run: `cd backend && python -m pytest tests/intelligence/test_correlation_adapters.py -v`

- [ ] **Step 5: Commit**

```bash
git add backend/app/intelligence/correlation/adapters.py backend/tests/intelligence/test_correlation_adapters.py
git commit -m "feat(intelligence): add DomainAdapter ABC + 4 concrete adapters

Per-market signal collectors: equity (VIX/OI/sentiment/RSI), crypto
(funding/dominance/volume), forex (polymarket rate odds/DXY),
cross_market (systemic risk convergence). Thresholds + weights
configurable per domain.

Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>"
```

---

## Task 7: CorrelationEngine Pipeline

**Files:**
- Create: `backend/app/intelligence/correlation/engine.py`
- Create: `backend/tests/intelligence/test_correlation_engine.py`

- [ ] **Step 1: Write tests**

```python
# backend/tests/intelligence/test_correlation_engine.py
"""Tests for CorrelationEngine pipeline."""
import pytest
from datetime import datetime, timedelta
from app.intelligence.correlation.types import SignalEvidence


class StubAdapter:
    domain = "test"
    weights = {"a": 0.5, "b": 0.5}
    threshold = 50.0
    time_window_hours = 24

    def __init__(self, signals=None):
        self._signals = signals or []

    async def collect_signals(self, ctx):
        return list(self._signals)

    def generate_title(self, cluster):
        return f"Test cluster ({len(cluster)} signals)"


@pytest.mark.asyncio
async def test_engine_creation():
    from app.intelligence.correlation.engine import CorrelationEngine

    eng = CorrelationEngine()
    assert eng is not None


@pytest.mark.asyncio
async def test_engine_register_adapter():
    from app.intelligence.correlation.engine import CorrelationEngine

    eng = CorrelationEngine()
    eng.register_adapter(StubAdapter())
    # No crash = good


@pytest.mark.asyncio
async def test_engine_runs_with_no_adapters():
    from app.intelligence.correlation.engine import CorrelationEngine

    eng = CorrelationEngine()
    cards = await eng.run(ctx=None)
    assert cards == []


@pytest.mark.asyncio
async def test_engine_emits_card_above_threshold():
    from app.intelligence.correlation.engine import CorrelationEngine

    now = datetime.utcnow()
    sigs = [
        SignalEvidence(type="a", source="x", severity=90, timestamp=now,
                       label="strong a", market="NIFTY"),
        SignalEvidence(type="b", source="y", severity=80, timestamp=now,
                       label="strong b", market="NIFTY"),
    ]
    eng = CorrelationEngine()
    eng.register_adapter(StubAdapter(signals=sigs))

    cards = await eng.run(ctx=None)
    # cluster of 2 signals at high severity should pass threshold of 50
    assert len(cards) >= 1
    assert cards[0].score > 50


@pytest.mark.asyncio
async def test_engine_skips_below_threshold():
    from app.intelligence.correlation.engine import CorrelationEngine

    now = datetime.utcnow()
    sigs = [
        SignalEvidence(type="a", source="x", severity=10, timestamp=now,
                       label="weak", market="NIFTY"),
    ]
    eng = CorrelationEngine()
    eng.register_adapter(StubAdapter(signals=sigs))

    cards = await eng.run(ctx=None)
    assert cards == []


@pytest.mark.asyncio
async def test_engine_dedupes_recent_card():
    from app.intelligence.correlation.engine import CorrelationEngine

    now = datetime.utcnow()
    sigs = [
        SignalEvidence(type="a", source="x", severity=90, timestamp=now,
                       label="strong", market="NIFTY"),
        SignalEvidence(type="b", source="y", severity=85, timestamp=now,
                       label="strong", market="NIFTY"),
    ]
    eng = CorrelationEngine()
    eng.register_adapter(StubAdapter(signals=sigs))

    first_run = await eng.run(ctx=None)
    second_run = await eng.run(ctx=None)
    # Same signals → second run should be deduped
    assert len(first_run) >= 1
    assert len(second_run) == 0


@pytest.mark.asyncio
async def test_engine_sorts_by_score_desc():
    from app.intelligence.correlation.engine import CorrelationEngine

    now = datetime.utcnow()
    high = [
        SignalEvidence(type="a", source="x", severity=95, timestamp=now,
                       label="h1", market="A"),
        SignalEvidence(type="b", source="y", severity=95, timestamp=now,
                       label="h2", market="A"),
    ]
    mid = [
        SignalEvidence(type="a", source="x", severity=70, timestamp=now,
                       label="m1", market="B"),
        SignalEvidence(type="b", source="y", severity=70, timestamp=now,
                       label="m2", market="B"),
    ]

    high_adapter = StubAdapter(signals=high)
    high_adapter.domain = "high_dom"
    mid_adapter = StubAdapter(signals=mid)
    mid_adapter.domain = "mid_dom"

    eng = CorrelationEngine()
    eng.register_adapter(high_adapter)
    eng.register_adapter(mid_adapter)

    cards = await eng.run(ctx=None)
    if len(cards) >= 2:
        assert cards[0].score >= cards[1].score
```

- [ ] **Step 2: Run — FAIL**

- [ ] **Step 3: Implement engine.py**

```python
# backend/app/intelligence/correlation/engine.py
"""CorrelationEngine — runs the pipeline: collect → cluster → score → filter → trend → dedupe."""
import logging
from datetime import datetime, timedelta
from typing import Any
from uuid import uuid4

from app.intelligence.correlation.adapters import DomainAdapter
from app.intelligence.correlation.types import SignalEvidence, ConvergenceCard

logger = logging.getLogger(__name__)


# Dedupe TTLs per signal type (port from WorldMonitor)
DEDUPE_TTLS: dict[str, timedelta] = {
    "default": timedelta(minutes=30),
    "silent_divergence": timedelta(hours=6),
    "explained_market_move": timedelta(hours=6),
    "polymarket_swing": timedelta(hours=2),
    "news_spike": timedelta(minutes=30),
}


class CorrelationEngine:
    """Pipeline: collect → cluster → score → filter → trend → dedupe → emit cards."""

    def __init__(self):
        self._adapters: list[DomainAdapter] = []
        self._previous_cards: dict[str, list[ConvergenceCard]] = {}
        self._dedupe_seen: dict[str, datetime] = {}

    def register_adapter(self, adapter: DomainAdapter) -> None:
        self._adapters.append(adapter)

    async def run(self, ctx: Any) -> list[ConvergenceCard]:
        """Run the full pipeline across all registered adapters."""
        all_cards: list[ConvergenceCard] = []

        for adapter in self._adapters:
            try:
                signals = await adapter.collect_signals(ctx)
            except Exception as exc:
                logger.error(f"Adapter {adapter.domain} collect_signals failed: {exc}")
                continue

            clusters = self._cluster(signals, adapter)
            scored = [(cluster, self._score_cluster(cluster, adapter)) for cluster in clusters]
            filtered = [(c, s) for c, s in scored if s >= adapter.threshold]
            cards = [self._to_card(c, s, adapter) for c, s in filtered]
            cards = self._apply_trends(cards, adapter)
            cards = self._dedupe(cards)
            self._previous_cards[adapter.domain] = cards
            all_cards.extend(cards)

        return sorted(all_cards, key=lambda c: c.score, reverse=True)

    def _cluster(self, signals: list[SignalEvidence], adapter: DomainAdapter) -> list[list[SignalEvidence]]:
        """Group signals by market within the adapter's time window."""
        if not signals:
            return []
        cutoff = datetime.utcnow() - timedelta(hours=adapter.time_window_hours)
        recent = [s for s in signals if s.timestamp >= cutoff]

        groups: dict[str, list[SignalEvidence]] = {}
        for s in recent:
            groups.setdefault(s.market, []).append(s)

        return list(groups.values())

    def _score_cluster(self, cluster: list[SignalEvidence], adapter: DomainAdapter) -> float:
        """Composite score for a cluster: weighted sum of signal severities."""
        if not cluster:
            return 0.0
        total = 0.0
        total_weight = 0.0
        for sig in cluster:
            weight = adapter.weights.get(sig.type, 0.1)
            total += sig.severity * weight
            total_weight += weight
        if total_weight <= 0:
            return 0.0
        return total / total_weight

    def _apply_trends(self, cards: list[ConvergenceCard], adapter: DomainAdapter) -> list[ConvergenceCard]:
        """Compare against previous cards for the same domain to set trend."""
        previous = self._previous_cards.get(adapter.domain, [])
        previous_by_id = {c.id: c for c in previous}
        out: list[ConvergenceCard] = []
        for card in cards:
            prev = previous_by_id.get(card.id)
            if prev is None:
                trend = "stable"
            elif card.score > prev.score + 5:
                trend = "escalating"
            elif card.score < prev.score - 5:
                trend = "de-escalating"
            else:
                trend = "stable"
            out.append(ConvergenceCard(
                id=card.id, domain=card.domain, title=card.title, score=card.score,
                signals=card.signals, markets=card.markets, trend=trend,
                timestamp=card.timestamp, assessment=card.assessment,
            ))
        return out

    def _dedupe(self, cards: list[ConvergenceCard]) -> list[ConvergenceCard]:
        """Skip cards seen recently (per signal-type TTL)."""
        now = datetime.utcnow()
        out: list[ConvergenceCard] = []
        for card in cards:
            key = self._dedupe_key(card)
            seen_at = self._dedupe_seen.get(key)
            ttl = DEDUPE_TTLS.get(card.domain, DEDUPE_TTLS["default"])
            if seen_at is not None and now - seen_at < ttl:
                continue
            self._dedupe_seen[key] = now
            out.append(card)
        # Periodic prune
        if len(self._dedupe_seen) > 500:
            cutoff = now - timedelta(hours=24)
            self._dedupe_seen = {k: v for k, v in self._dedupe_seen.items() if v > cutoff}
        return out

    def _dedupe_key(self, card: ConvergenceCard) -> str:
        types = "+".join(sorted({s.type for s in card.signals}))
        markets = "+".join(sorted(card.markets))
        return f"{card.domain}:{markets}:{types}"

    def _to_card(self, cluster: list[SignalEvidence], score: float, adapter: DomainAdapter) -> ConvergenceCard:
        markets = sorted({s.market for s in cluster})
        types = sorted({s.type for s in cluster})
        card_id = f"{adapter.domain}:{'+'.join(markets)}:{'+'.join(types)}"
        return ConvergenceCard(
            id=card_id,
            domain=adapter.domain,
            title=adapter.generate_title(cluster),
            score=round(score, 2),
            signals=cluster,
            markets=markets,
            trend="stable",
            timestamp=datetime.utcnow(),
        )
```

- [ ] **Step 4: Run — PASS (7 tests)**

Run: `cd backend && python -m pytest tests/intelligence/test_correlation_engine.py -v`

- [ ] **Step 5: Commit**

```bash
git add backend/app/intelligence/correlation/engine.py backend/tests/intelligence/test_correlation_engine.py
git commit -m "feat(intelligence): add CorrelationEngine pipeline

Pipeline: collect signals from each registered DomainAdapter, cluster
by market within time window, score by adapter weights, filter above
threshold, apply trend vs previous cycle, dedupe via per-type TTLs.
Returns ConvergenceCards sorted by score.

Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>"
```

---

## Task 8: FinBertSentiment

**Files:**
- Create: `backend/app/intelligence/sentiment/__init__.py`
- Create: `backend/app/intelligence/sentiment/finbert.py`
- Create: `backend/tests/intelligence/test_finbert.py`

- [ ] **Step 1: Write tests**

```python
# backend/tests/intelligence/test_finbert.py
"""Tests for FinBertSentiment classifier wrapper."""
import pytest
from unittest.mock import MagicMock, patch


def test_finbert_creation():
    from app.intelligence.sentiment.finbert import FinBertSentiment

    fb = FinBertSentiment()
    assert fb is not None


def test_finbert_lazy_load():
    from app.intelligence.sentiment.finbert import FinBertSentiment

    fb = FinBertSentiment()
    # Pipeline should not be loaded until first call
    assert fb._pipeline is None


def test_finbert_score_positive():
    from app.intelligence.sentiment.finbert import FinBertSentiment

    fb = FinBertSentiment()
    fb._pipeline = MagicMock(return_value=[{"label": "positive", "score": 0.85}])

    result = fb.score("Stock surges on great earnings")
    assert result["label"] == "positive"
    assert result["score"] == 0.85
    assert result["polarity"] == pytest.approx(0.85)


def test_finbert_score_negative():
    from app.intelligence.sentiment.finbert import FinBertSentiment

    fb = FinBertSentiment()
    fb._pipeline = MagicMock(return_value=[{"label": "negative", "score": 0.92}])

    result = fb.score("Company files for bankruptcy")
    assert result["label"] == "negative"
    assert result["polarity"] == pytest.approx(-0.92)


def test_finbert_score_neutral():
    from app.intelligence.sentiment.finbert import FinBertSentiment

    fb = FinBertSentiment()
    fb._pipeline = MagicMock(return_value=[{"label": "neutral", "score": 0.7}])

    result = fb.score("Quarterly report released")
    assert result["label"] == "neutral"
    assert result["polarity"] == 0.0


def test_finbert_score_truncates_long_text():
    from app.intelligence.sentiment.finbert import FinBertSentiment

    fb = FinBertSentiment()
    long_text = "x" * 10000
    captured = {}

    def fake_pipeline(text):
        captured["len"] = len(text)
        return [{"label": "neutral", "score": 0.5}]

    fb._pipeline = fake_pipeline
    fb.score(long_text)
    assert captured["len"] <= 512


def test_finbert_score_batch():
    from app.intelligence.sentiment.finbert import FinBertSentiment

    fb = FinBertSentiment()
    fb._pipeline = MagicMock(return_value=[
        {"label": "positive", "score": 0.8},
        {"label": "negative", "score": 0.7},
        {"label": "neutral", "score": 0.6},
    ])

    results = fb.score_batch(["bull text", "bear text", "neutral text"])
    assert len(results) == 3
    assert results[0]["polarity"] == pytest.approx(0.8)
    assert results[1]["polarity"] == pytest.approx(-0.7)
    assert results[2]["polarity"] == 0.0


def test_finbert_aggregate_polarity_empty():
    from app.intelligence.sentiment.finbert import FinBertSentiment

    fb = FinBertSentiment()
    assert fb.aggregate_polarity([]) == 0.0


def test_finbert_aggregate_polarity_average():
    from app.intelligence.sentiment.finbert import FinBertSentiment

    fb = FinBertSentiment()
    scores = [
        {"polarity": 0.8},
        {"polarity": -0.4},
        {"polarity": 0.0},
    ]
    avg = fb.aggregate_polarity(scores)
    assert avg == pytest.approx((0.8 - 0.4 + 0.0) / 3)


def test_finbert_unknown_label_polarity_zero():
    from app.intelligence.sentiment.finbert import FinBertSentiment

    fb = FinBertSentiment()
    fb._pipeline = MagicMock(return_value=[{"label": "weird_label", "score": 0.5}])

    result = fb.score("text")
    assert result["polarity"] == 0.0
```

- [ ] **Step 2: Run — FAIL**

- [ ] **Step 3: Implement finbert.py**

```python
# backend/app/intelligence/sentiment/__init__.py
"""Sentiment classification for financial text."""
from app.intelligence.sentiment.finbert import FinBertSentiment

__all__ = ["FinBertSentiment"]
```

```python
# backend/app/intelligence/sentiment/finbert.py
"""FinBertSentiment — financial sentiment via ProsusAI/finbert (HuggingFace)."""
import logging

logger = logging.getLogger(__name__)


_POLARITY_MAP: dict[str, int] = {"positive": 1, "negative": -1, "neutral": 0}
_MAX_INPUT_LEN = 512


class FinBertSentiment:
    """Lazy-loading FinBERT classifier with polarity helpers."""

    def __init__(self, model_name: str = "ProsusAI/finbert"):
        self._model_name = model_name
        self._pipeline = None  # lazy

    def _ensure_loaded(self) -> None:
        if self._pipeline is None:
            from transformers import pipeline
            logger.info(f"Loading FinBERT model: {self._model_name}")
            self._pipeline = pipeline("sentiment-analysis", model=self._model_name)

    def score(self, text: str) -> dict:
        """Classify a single text. Returns {label, score, polarity}."""
        self._ensure_loaded()
        truncated = text[:_MAX_INPUT_LEN]
        result = self._pipeline(truncated)[0]
        polarity = _POLARITY_MAP.get(result["label"], 0) * result["score"]
        return {
            "label": result["label"],
            "score": result["score"],
            "polarity": polarity,
        }

    def score_batch(self, texts: list[str]) -> list[dict]:
        """Batch classify multiple texts."""
        if not texts:
            return []
        self._ensure_loaded()
        truncated = [t[:_MAX_INPUT_LEN] for t in texts]
        results = self._pipeline(truncated)
        return [
            {
                "label": r["label"],
                "score": r["score"],
                "polarity": _POLARITY_MAP.get(r["label"], 0) * r["score"],
            }
            for r in results
        ]

    def aggregate_polarity(self, scores: list[dict]) -> float:
        """Mean polarity across a list of scored items."""
        if not scores:
            return 0.0
        return sum(s.get("polarity", 0) for s in scores) / len(scores)
```

- [ ] **Step 4: Run — PASS (10 tests)**

Run: `cd backend && python -m pytest tests/intelligence/test_finbert.py -v`

- [ ] **Step 5: Commit**

```bash
git add backend/app/intelligence/sentiment/ backend/tests/intelligence/test_finbert.py
git commit -m "feat(intelligence): add FinBertSentiment classifier wrapper

Wraps ProsusAI/finbert via transformers.pipeline. Lazy model load
(loaded once per pod). Returns label + score + polarity (-1..+1).
Batch scoring + aggregate_polarity for news aggregation.

Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>"
```

---

## Task 9: Concrete Data Sources

**Files:**
- Create: `backend/app/intelligence/sources/__init__.py`
- Create: `backend/app/intelligence/sources/yfinance_source.py`
- Create: `backend/app/intelligence/sources/polymarket_source.py`
- Create: `backend/app/intelligence/sources/mcp_groww_source.py`
- Create: `backend/app/intelligence/sources/mcp_zerodha_source.py`
- Create: `backend/app/intelligence/sources/gdelt_source.py`
- Create: `backend/app/intelligence/sources/news_scraper_source.py`
- Create: `backend/tests/intelligence/test_yfinance_source.py`
- Create: `backend/tests/intelligence/test_polymarket_source.py`
- Create: `backend/tests/intelligence/test_mcp_sources.py`
- Create: `backend/tests/intelligence/test_gdelt_source.py`
- Create: `backend/tests/intelligence/test_news_scraper_source.py`

- [ ] **Step 1: Write all source tests**

```python
# backend/tests/intelligence/test_yfinance_source.py
"""Tests for YFinanceSource (mocked yfinance.Ticker)."""
import pytest
from unittest.mock import MagicMock, patch


@pytest.fixture
def mock_ticker():
    t = MagicMock()
    hist = MagicMock()
    hist.to_dict.return_value = {"Close": {0: 100.0}, "Volume": {0: 1000}}
    hist.empty = False
    t.history.return_value = hist
    t.news = [{"title": "Big news", "link": "https://example.com/news"}]
    t.info = {"sector": "Tech"}
    return t


def test_yfinance_name():
    from app.intelligence.sources.yfinance_source import YFinanceSource

    src = YFinanceSource()
    assert src.name == "yfinance"


def test_yfinance_supports():
    from app.intelligence.sources.yfinance_source import YFinanceSource

    src = YFinanceSource()
    assert src.supports("get_ohlcv") is True
    assert src.supports("nonexistent") is False


@pytest.mark.asyncio
async def test_yfinance_get_ohlcv(mock_ticker):
    from app.intelligence.sources.yfinance_source import YFinanceSource

    src = YFinanceSource()
    with patch("yfinance.Ticker", return_value=mock_ticker):
        result = await src.fetch("get_ohlcv", symbol="AAPL", period="5d")
    assert result is not None
    assert "Close" in result


@pytest.mark.asyncio
async def test_yfinance_get_news(mock_ticker):
    from app.intelligence.sources.yfinance_source import YFinanceSource

    src = YFinanceSource()
    with patch("yfinance.Ticker", return_value=mock_ticker):
        result = await src.fetch("get_news", symbol="AAPL")
    assert isinstance(result, list)
    assert len(result) >= 1
```

```python
# backend/tests/intelligence/test_polymarket_source.py
"""Tests for PolymarketSource (read-only, mocked HTTP)."""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch


def test_polymarket_name():
    from app.intelligence.sources.polymarket_source import PolymarketSource

    src = PolymarketSource()
    assert src.name == "polymarket"


def test_polymarket_supports():
    from app.intelligence.sources.polymarket_source import PolymarketSource

    src = PolymarketSource()
    assert src.supports("get_polymarket_odds") is True
    assert src.supports("get_ohlcv") is False


@pytest.mark.asyncio
async def test_polymarket_get_odds():
    from app.intelligence.sources.polymarket_source import PolymarketSource

    src = PolymarketSource()
    fake_response = MagicMock()
    fake_response.status_code = 200
    fake_response.json.return_value = [
        {"slug": "fed-rate-cut-jun", "outcomePrices": ["0.82", "0.18"]},
        {"slug": "war-escalation", "outcomePrices": ["0.15", "0.85"]},
    ]
    fake_response.raise_for_status = MagicMock()

    with patch("httpx.AsyncClient.get", new_callable=AsyncMock, return_value=fake_response):
        result = await src.fetch("get_polymarket_odds", limit=5)
    assert isinstance(result, dict)
    assert "fed-rate-cut-jun" in result
    assert result["fed-rate-cut-jun"] == pytest.approx(0.82)
```

```python
# backend/tests/intelligence/test_mcp_sources.py
"""Tests for GrowwMCPSource and ZerodhaMCPSource."""
import pytest
from unittest.mock import AsyncMock, MagicMock


@pytest.fixture
def mock_mcp_client():
    client = MagicMock()
    client.call_tool = AsyncMock(return_value={"data": "mcp_result"})
    return client


def test_groww_mcp_name(mock_mcp_client):
    from app.intelligence.sources.mcp_groww_source import GrowwMCPSource

    src = GrowwMCPSource(mcp_client=mock_mcp_client)
    assert src.name == "groww_mcp"


def test_groww_mcp_supports(mock_mcp_client):
    from app.intelligence.sources.mcp_groww_source import GrowwMCPSource

    src = GrowwMCPSource(mcp_client=mock_mcp_client)
    assert src.supports("get_ltp") is True
    assert src.supports("get_oi") is True


@pytest.mark.asyncio
async def test_groww_mcp_fetch(mock_mcp_client):
    from app.intelligence.sources.mcp_groww_source import GrowwMCPSource

    src = GrowwMCPSource(mcp_client=mock_mcp_client)
    result = await src.fetch("get_ltp", symbol="NIFTY")
    assert result == {"data": "mcp_result"}
    mock_mcp_client.call_tool.assert_called_once()


def test_zerodha_mcp_name(mock_mcp_client):
    from app.intelligence.sources.mcp_zerodha_source import ZerodhaMCPSource

    src = ZerodhaMCPSource(mcp_client=mock_mcp_client)
    assert src.name == "zerodha_mcp"


@pytest.mark.asyncio
async def test_zerodha_mcp_fetch(mock_mcp_client):
    from app.intelligence.sources.mcp_zerodha_source import ZerodhaMCPSource

    src = ZerodhaMCPSource(mcp_client=mock_mcp_client)
    result = await src.fetch("get_ltp", symbol="RELIANCE")
    assert result is not None
```

```python
# backend/tests/intelligence/test_gdelt_source.py
"""Tests for GdeltSource."""
import pytest
from unittest.mock import MagicMock, patch


def test_gdelt_name():
    from app.intelligence.sources.gdelt_source import GdeltSource

    src = GdeltSource()
    assert src.name == "gdelt"


def test_gdelt_supports():
    from app.intelligence.sources.gdelt_source import GdeltSource

    src = GdeltSource()
    assert src.supports("get_gdelt_events") is True
    assert src.supports("get_news") is True


@pytest.mark.asyncio
async def test_gdelt_get_events():
    from app.intelligence.sources.gdelt_source import GdeltSource

    src = GdeltSource()
    fake_filters = MagicMock()
    fake_client = MagicMock()
    fake_client.article_search.return_value = [
        {"title": "Event 1", "url": "http://e1", "domain": "src.com"},
    ]

    with patch("app.intelligence.sources.gdelt_source.Filters", return_value=fake_filters), \
         patch("app.intelligence.sources.gdelt_source.GdeltDoc", return_value=fake_client):
        result = await src.fetch("get_gdelt_events", keyword="oil")
    assert isinstance(result, list)
```

```python
# backend/tests/intelligence/test_news_scraper_source.py
"""Tests for NewsScraperSource (trafilatura)."""
import pytest
from unittest.mock import patch


def test_news_scraper_name():
    from app.intelligence.sources.news_scraper_source import NewsScraperSource

    src = NewsScraperSource()
    assert src.name == "trafilatura"


def test_news_scraper_supports():
    from app.intelligence.sources.news_scraper_source import NewsScraperSource

    src = NewsScraperSource()
    assert src.supports("scrape_article") is True


@pytest.mark.asyncio
async def test_news_scraper_extracts_article():
    from app.intelligence.sources.news_scraper_source import NewsScraperSource

    src = NewsScraperSource()
    with patch("trafilatura.fetch_url", return_value="<html><body>test</body></html>"), \
         patch("trafilatura.extract", return_value="Extracted text body."):
        result = await src.fetch("scrape_article", url="http://example.com")
    assert result is not None
    assert result["text"] == "Extracted text body."


@pytest.mark.asyncio
async def test_news_scraper_returns_none_on_failure():
    from app.intelligence.sources.news_scraper_source import NewsScraperSource

    src = NewsScraperSource()
    with patch("trafilatura.fetch_url", return_value=None):
        result = await src.fetch("scrape_article", url="http://broken.com")
    # Should not raise — returns None or empty
    assert result is None or result.get("text") in (None, "")
```

- [ ] **Step 2: Run — FAIL**

- [ ] **Step 3: Implement sources**

```python
# backend/app/intelligence/sources/__init__.py
"""Concrete data sources for intelligence layer."""
from app.intelligence.sources.yfinance_source import YFinanceSource
from app.intelligence.sources.polymarket_source import PolymarketSource
from app.intelligence.sources.mcp_groww_source import GrowwMCPSource
from app.intelligence.sources.mcp_zerodha_source import ZerodhaMCPSource
from app.intelligence.sources.gdelt_source import GdeltSource
from app.intelligence.sources.news_scraper_source import NewsScraperSource

__all__ = [
    "YFinanceSource",
    "PolymarketSource",
    "GrowwMCPSource",
    "ZerodhaMCPSource",
    "GdeltSource",
    "NewsScraperSource",
]
```

```python
# backend/app/intelligence/sources/yfinance_source.py
"""yfinance data source — global market OHLCV/news/fundamentals."""
import asyncio
import logging
from typing import Any

from app.intelligence.base import DataSource, SourceUnavailableError

logger = logging.getLogger(__name__)


class YFinanceSource(DataSource):
    """yfinance wrapper. yfinance is sync — wrapped in asyncio.to_thread."""

    _CAPABILITIES = ["get_ohlcv", "get_news", "get_fundamentals", "get_balance_sheet", "get_cashflow"]

    @property
    def name(self) -> str:
        return "yfinance"

    @property
    def capabilities(self) -> list[str]:
        return list(self._CAPABILITIES)

    def supports(self, method: str) -> bool:
        return method in self._CAPABILITIES

    async def fetch(self, method: str, **kwargs) -> Any:
        try:
            import yfinance
        except ImportError as exc:
            raise SourceUnavailableError(f"yfinance not installed: {exc}")

        symbol = kwargs.get("symbol", "")
        if not symbol:
            return None

        def _sync_fetch():
            ticker = yfinance.Ticker(symbol)
            if method == "get_ohlcv":
                period = kwargs.get("period", "5d")
                interval = kwargs.get("interval", "1d")
                hist = ticker.history(period=period, interval=interval)
                if hist.empty:
                    return {}
                return hist.to_dict()
            if method == "get_news":
                return list(ticker.news) if ticker.news else []
            if method == "get_fundamentals":
                return dict(ticker.info)
            if method == "get_balance_sheet":
                bs = ticker.balance_sheet
                return bs.to_dict() if bs is not None and not bs.empty else {}
            if method == "get_cashflow":
                cf = ticker.cashflow
                return cf.to_dict() if cf is not None and not cf.empty else {}
            return None

        try:
            return await asyncio.to_thread(_sync_fetch)
        except Exception as exc:
            raise SourceUnavailableError(f"yfinance fetch failed: {exc}")
```

```python
# backend/app/intelligence/sources/polymarket_source.py
"""Polymarket read-only data source — odds, event probabilities."""
import logging
from typing import Any

import httpx

from app.intelligence.base import DataSource, RateLimitError, SourceUnavailableError

logger = logging.getLogger(__name__)


class PolymarketSource(DataSource):
    """Read-only Polymarket CLOB API wrapper."""

    _CAPABILITIES = ["get_polymarket_odds", "get_event_probability"]

    def __init__(self, host: str = "https://clob.polymarket.com", gamma_host: str = "https://gamma-api.polymarket.com"):
        self._host = host
        self._gamma_host = gamma_host

    @property
    def name(self) -> str:
        return "polymarket"

    @property
    def capabilities(self) -> list[str]:
        return list(self._CAPABILITIES)

    def supports(self, method: str) -> bool:
        return method in self._CAPABILITIES

    async def fetch(self, method: str, **kwargs) -> Any:
        try:
            if method == "get_polymarket_odds":
                limit = kwargs.get("limit", 20)
                return await self._fetch_odds(limit)
            if method == "get_event_probability":
                slug = kwargs.get("slug", "")
                return await self._fetch_event_probability(slug)
            return None
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code == 429:
                raise RateLimitError(f"polymarket rate limited: {exc}")
            raise SourceUnavailableError(f"polymarket http error: {exc}")
        except httpx.HTTPError as exc:
            raise SourceUnavailableError(f"polymarket http error: {exc}")

    async def _fetch_odds(self, limit: int) -> dict[str, float]:
        url = f"{self._gamma_host}/markets"
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.get(url, params={"limit": limit, "active": "true"})
            resp.raise_for_status()
            data = resp.json()
        odds: dict[str, float] = {}
        for market in data:
            slug = market.get("slug")
            prices = market.get("outcomePrices") or []
            if slug and prices:
                try:
                    odds[slug] = float(prices[0])
                except (ValueError, TypeError):
                    continue
        return odds

    async def _fetch_event_probability(self, slug: str) -> float | None:
        if not slug:
            return None
        url = f"{self._gamma_host}/markets"
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.get(url, params={"slug": slug})
            resp.raise_for_status()
            data = resp.json()
        if not data:
            return None
        prices = data[0].get("outcomePrices") or []
        if not prices:
            return None
        try:
            return float(prices[0])
        except (ValueError, TypeError):
            return None
```

```python
# backend/app/intelligence/sources/mcp_groww_source.py
"""Groww MCP data source — wraps existing Groww MCP server tools."""
import logging
from typing import Any

from app.intelligence.base import DataSource, SourceUnavailableError

logger = logging.getLogger(__name__)


_METHOD_TO_MCP_TOOL = {
    "get_ltp": "get_ltp",
    "get_quotes": "get_quotes_and_depth",
    "get_market_depth": "get_quotes_and_depth",
    "get_oi": "get_open_interest_analysis",
    "get_option_chain": "get_atm_straddle_chart",
    "get_greeks": "get_greeks_for_fno_symbol",
    "screen_technical": "fetch_technical_screener",
    "screen_fundamental": "fetch_fundamentals_screener",
}


class GrowwMCPSource(DataSource):
    """Wraps Groww MCP server tools."""

    def __init__(self, mcp_client: Any):
        self._client = mcp_client

    @property
    def name(self) -> str:
        return "groww_mcp"

    @property
    def capabilities(self) -> list[str]:
        return list(_METHOD_TO_MCP_TOOL.keys())

    def supports(self, method: str) -> bool:
        return method in _METHOD_TO_MCP_TOOL

    async def fetch(self, method: str, **kwargs) -> Any:
        tool = _METHOD_TO_MCP_TOOL.get(method)
        if tool is None:
            raise SourceUnavailableError(f"groww_mcp does not support {method}")
        try:
            return await self._client.call_tool(tool, **kwargs)
        except Exception as exc:
            raise SourceUnavailableError(f"groww_mcp call failed: {exc}")
```

```python
# backend/app/intelligence/sources/mcp_zerodha_source.py
"""Zerodha MCP data source."""
import logging
from typing import Any

from app.intelligence.base import DataSource, SourceUnavailableError

logger = logging.getLogger(__name__)


_METHOD_TO_MCP_TOOL = {
    "get_ltp": "get_ltp",
    "get_quotes": "get_quote",
    "get_ohlcv": "get_ohlc",
}


class ZerodhaMCPSource(DataSource):
    """Wraps Zerodha (kite-mcp) server tools."""

    def __init__(self, mcp_client: Any):
        self._client = mcp_client

    @property
    def name(self) -> str:
        return "zerodha_mcp"

    @property
    def capabilities(self) -> list[str]:
        return list(_METHOD_TO_MCP_TOOL.keys())

    def supports(self, method: str) -> bool:
        return method in _METHOD_TO_MCP_TOOL

    async def fetch(self, method: str, **kwargs) -> Any:
        tool = _METHOD_TO_MCP_TOOL.get(method)
        if tool is None:
            raise SourceUnavailableError(f"zerodha_mcp does not support {method}")
        try:
            return await self._client.call_tool(tool, **kwargs)
        except Exception as exc:
            raise SourceUnavailableError(f"zerodha_mcp call failed: {exc}")
```

```python
# backend/app/intelligence/sources/gdelt_source.py
"""GDELT geopolitical event source via gdelt-doc-api."""
import asyncio
import logging
from typing import Any

from app.intelligence.base import DataSource, SourceUnavailableError

logger = logging.getLogger(__name__)


# Lazy imports — gdelt-doc-api may not be installed in all environments
try:
    from gdeltdoc import GdeltDoc, Filters
except ImportError:
    GdeltDoc = None
    Filters = None


class GdeltSource(DataSource):
    """GDELT 2.0 article search."""

    _CAPABILITIES = ["get_gdelt_events", "get_news", "get_global_news"]

    @property
    def name(self) -> str:
        return "gdelt"

    @property
    def capabilities(self) -> list[str]:
        return list(self._CAPABILITIES)

    def supports(self, method: str) -> bool:
        return method in self._CAPABILITIES

    async def fetch(self, method: str, **kwargs) -> Any:
        if GdeltDoc is None or Filters is None:
            raise SourceUnavailableError("gdelt-doc-api not installed")

        keyword = kwargs.get("keyword") or kwargs.get("symbol", "")
        if not keyword:
            return []

        def _sync_fetch():
            f = Filters(keyword=keyword, timespan="1d")
            client = GdeltDoc()
            articles = client.article_search(f)
            if hasattr(articles, "to_dict"):
                return articles.to_dict("records")
            return list(articles) if articles else []

        try:
            return await asyncio.to_thread(_sync_fetch)
        except Exception as exc:
            raise SourceUnavailableError(f"gdelt fetch failed: {exc}")
```

```python
# backend/app/intelligence/sources/news_scraper_source.py
"""trafilatura news article extraction."""
import asyncio
import logging
from typing import Any

from app.intelligence.base import DataSource, SourceUnavailableError

logger = logging.getLogger(__name__)


class NewsScraperSource(DataSource):
    """Extracts clean text from news article URLs via trafilatura."""

    @property
    def name(self) -> str:
        return "trafilatura"

    @property
    def capabilities(self) -> list[str]:
        return ["scrape_article"]

    def supports(self, method: str) -> bool:
        return method == "scrape_article"

    async def fetch(self, method: str, **kwargs) -> Any:
        try:
            import trafilatura
        except ImportError as exc:
            raise SourceUnavailableError(f"trafilatura not installed: {exc}")

        url = kwargs.get("url", "")
        if not url:
            return None

        def _sync_fetch():
            downloaded = trafilatura.fetch_url(url)
            if not downloaded:
                return None
            text = trafilatura.extract(downloaded)
            if not text:
                return None
            return {"url": url, "text": text}

        try:
            return await asyncio.to_thread(_sync_fetch)
        except Exception as exc:
            raise SourceUnavailableError(f"trafilatura fetch failed: {exc}")
```

- [ ] **Step 4: Run — PASS**

Run: `cd backend && python -m pytest tests/intelligence/ -v -k "source"`
Expected: ~17 tests PASS (yfinance: 4, polymarket: 3, mcp: 5, gdelt: 3, news: 3 — actual counts may vary)

- [ ] **Step 5: Add sources to conformance suite**

Append to `backend/tests/intelligence/test_source_conformance.py` after `SOURCE_FACTORIES`:

```python
# Concrete sources (with mocked dependencies)

def make_yfinance_source():
    from app.intelligence.sources.yfinance_source import YFinanceSource
    return YFinanceSource()


def make_polymarket_source():
    from app.intelligence.sources.polymarket_source import PolymarketSource
    return PolymarketSource()


def make_groww_mcp_source():
    from unittest.mock import MagicMock, AsyncMock
    from app.intelligence.sources.mcp_groww_source import GrowwMCPSource
    client = MagicMock()
    client.call_tool = AsyncMock(return_value={})
    return GrowwMCPSource(mcp_client=client)


def make_zerodha_mcp_source():
    from unittest.mock import MagicMock, AsyncMock
    from app.intelligence.sources.mcp_zerodha_source import ZerodhaMCPSource
    client = MagicMock()
    client.call_tool = AsyncMock(return_value={})
    return ZerodhaMCPSource(mcp_client=client)


def make_gdelt_source():
    from app.intelligence.sources.gdelt_source import GdeltSource
    return GdeltSource()


def make_news_scraper_source():
    from app.intelligence.sources.news_scraper_source import NewsScraperSource
    return NewsScraperSource()


SOURCE_FACTORIES.extend([
    pytest.param(make_yfinance_source, id="yfinance"),
    pytest.param(make_polymarket_source, id="polymarket"),
    pytest.param(make_groww_mcp_source, id="groww_mcp"),
    pytest.param(make_zerodha_mcp_source, id="zerodha_mcp"),
    pytest.param(make_gdelt_source, id="gdelt"),
    pytest.param(make_news_scraper_source, id="news_scraper"),
])
```

- [ ] **Step 6: Run conformance — PASS**

Run: `cd backend && python -m pytest tests/intelligence/test_source_conformance.py -v`
Expected: 4 tests × 7 sources = 28 PASS

- [ ] **Step 7: Update requirements.txt**

Append to `backend/requirements.txt`:

```
# Intelligence layer (SP3)
yfinance>=0.2.40
trafilatura>=1.12.0
gdelt-doc-api>=1.7.0
py-clob-client>=0.1.0
transformers>=4.40.0
torch>=2.2.0; platform_machine != 'aarch64'
```

- [ ] **Step 8: Commit**

```bash
git add backend/app/intelligence/sources/ backend/tests/intelligence/test_yfinance_source.py backend/tests/intelligence/test_polymarket_source.py backend/tests/intelligence/test_mcp_sources.py backend/tests/intelligence/test_gdelt_source.py backend/tests/intelligence/test_news_scraper_source.py backend/tests/intelligence/test_source_conformance.py backend/requirements.txt
git commit -m "feat(intelligence): add 6 concrete data sources

YFinanceSource (sync wrapped in asyncio.to_thread), PolymarketSource
(read-only Gamma API), GrowwMCPSource and ZerodhaMCPSource (wrap
existing MCP servers), GdeltSource (geopolitical events),
NewsScraperSource (trafilatura). All implement DataSource ABC and
pass conformance suite. Lazy imports for optional dependencies.

Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>"
```

---

## Task 10: IntelligenceContext + Builder

**Files:**
- Create: `backend/app/intelligence/context.py`
- Create: `backend/tests/intelligence/test_context_builder.py`

- [ ] **Step 1: Write tests**

```python
# backend/tests/intelligence/test_context_builder.py
"""Integration tests for IntelligenceContext + Builder."""
import json
import pytest
from datetime import datetime
from unittest.mock import AsyncMock, MagicMock


def test_intelligence_context_creation():
    from app.intelligence.context import IntelligenceContext

    ctx = IntelligenceContext(
        symbol="NIFTY",
        market_state={"ltp": 22500},
        convergence_cards=[],
        cross_market_signals=[],
        composite_score=None,
        relevant_news=[],
        aggregated_sentiment=0.0,
        polymarket_odds={},
        geopolitical_events=[],
        sources_used=["yfinance"],
        fetch_latency_ms={"yfinance": 50.0},
        built_at=datetime.utcnow(),
    )
    assert ctx.symbol == "NIFTY"
    assert ctx.aggregated_sentiment == 0.0


@pytest.mark.asyncio
async def test_builder_build_assembles_context():
    from app.intelligence.context import IntelligenceContextBuilder
    from app.intelligence.sentiment.finbert import FinBertSentiment
    from app.intelligence.correlation.engine import CorrelationEngine

    registry = MagicMock()
    registry.fetch = AsyncMock(side_effect=[
        {"Close": {0: 22500}},  # ohlcv
        [{"title": "Stock surges"}],  # news
        {"fed-rate-cut-jun": 0.82},  # polymarket
        [],  # geopolitical
    ])
    sentiment = MagicMock(spec=FinBertSentiment)
    sentiment.score_batch = MagicMock(return_value=[{"polarity": 0.8, "label": "positive", "score": 0.8}])
    sentiment.aggregate_polarity = MagicMock(return_value=0.8)

    engine = CorrelationEngine()

    redis_client = MagicMock()
    redis_client.get = AsyncMock(return_value=None)
    redis_client.set = AsyncMock(return_value=True)
    redis_client.setex = AsyncMock(return_value=True)

    builder = IntelligenceContextBuilder(
        registry=registry, correlation_engine=engine,
        sentiment=sentiment, redis_client=redis_client, cache_ttl_seconds=60,
    )

    ctx = await builder.build(symbol="NIFTY", account_name="paper_test")
    assert ctx.symbol == "NIFTY"
    assert ctx.aggregated_sentiment == 0.8
    assert ctx.polymarket_odds == {"fed-rate-cut-jun": 0.82}


@pytest.mark.asyncio
async def test_builder_uses_cache_when_present():
    from app.intelligence.context import IntelligenceContextBuilder
    from app.intelligence.sentiment.finbert import FinBertSentiment
    from app.intelligence.correlation.engine import CorrelationEngine

    cached_payload = {
        "symbol": "NIFTY",
        "market_state": {"ltp": 22500},
        "convergence_cards": [],
        "cross_market_signals": [],
        "composite_score": None,
        "relevant_news": [],
        "aggregated_sentiment": 0.0,
        "polymarket_odds": {},
        "geopolitical_events": [],
        "sources_used": [],
        "fetch_latency_ms": {},
        "built_at": datetime.utcnow().isoformat(),
    }

    registry = MagicMock()
    registry.fetch = AsyncMock()  # should not be called
    sentiment = MagicMock(spec=FinBertSentiment)
    engine = CorrelationEngine()

    redis_client = MagicMock()
    redis_client.get = AsyncMock(return_value=json.dumps(cached_payload))
    redis_client.set = AsyncMock(return_value=True)
    redis_client.setex = AsyncMock(return_value=True)

    builder = IntelligenceContextBuilder(
        registry=registry, correlation_engine=engine,
        sentiment=sentiment, redis_client=redis_client, cache_ttl_seconds=60,
    )

    ctx = await builder.build(symbol="NIFTY", account_name="paper_test")
    assert ctx.symbol == "NIFTY"
    registry.fetch.assert_not_called()


@pytest.mark.asyncio
async def test_builder_handles_source_failure_gracefully():
    from app.intelligence.context import IntelligenceContextBuilder
    from app.intelligence.sentiment.finbert import FinBertSentiment
    from app.intelligence.correlation.engine import CorrelationEngine

    registry = MagicMock()
    registry.fetch = AsyncMock(side_effect=RuntimeError("all sources down"))
    sentiment = MagicMock(spec=FinBertSentiment)
    sentiment.score_batch = MagicMock(return_value=[])
    sentiment.aggregate_polarity = MagicMock(return_value=0.0)
    engine = CorrelationEngine()

    redis_client = MagicMock()
    redis_client.get = AsyncMock(return_value=None)
    redis_client.set = AsyncMock(return_value=True)
    redis_client.setex = AsyncMock(return_value=True)

    builder = IntelligenceContextBuilder(
        registry=registry, correlation_engine=engine,
        sentiment=sentiment, redis_client=redis_client,
    )

    # Should not raise — degrades gracefully
    ctx = await builder.build(symbol="NIFTY", account_name="paper_test")
    assert ctx.symbol == "NIFTY"
    assert ctx.market_state == {}
    assert ctx.polymarket_odds == {}
```

- [ ] **Step 2: Run — FAIL**

- [ ] **Step 3: Implement context.py**

```python
# backend/app/intelligence/context.py
"""IntelligenceContext + Builder.

Assembles all intelligence layer outputs into a single context object
for AnalystAgent and JudgeAgent. Cached in Redis with JSON serialization.
"""
import asyncio
import json
import logging
import time
from dataclasses import dataclass, field, asdict
from datetime import datetime
from typing import Any

from app.intelligence.correlation.engine import CorrelationEngine
from app.intelligence.correlation.types import SignalEvidence, ConvergenceCard
from app.intelligence.scoring.composite import SignalQuality, compute_isq
from app.intelligence.sentiment.finbert import FinBertSentiment

logger = logging.getLogger(__name__)


@dataclass
class IntelligenceContext:
    symbol: str
    market_state: dict
    convergence_cards: list[ConvergenceCard]
    cross_market_signals: list[SignalEvidence]
    composite_score: SignalQuality | None
    relevant_news: list[dict]
    aggregated_sentiment: float
    polymarket_odds: dict[str, float]
    geopolitical_events: list[dict]
    sources_used: list[str]
    fetch_latency_ms: dict[str, float]
    built_at: datetime


class IntelligenceContextBuilder:
    """Assembles IntelligenceContext from registry + correlation + sentiment."""

    def __init__(
        self,
        registry: Any,
        correlation_engine: CorrelationEngine,
        sentiment: FinBertSentiment,
        redis_client: Any,
        cache_ttl_seconds: int = 60,
        fetch_timeout_seconds: float = 5.0,
    ):
        self._registry = registry
        self._correlation_engine = correlation_engine
        self._sentiment = sentiment
        self._redis = redis_client
        self._cache_ttl = cache_ttl_seconds
        self._fetch_timeout = fetch_timeout_seconds

    async def build(self, symbol: str, account_name: str) -> IntelligenceContext:
        """Build IntelligenceContext for a symbol. Uses Redis cache."""
        cache_key = self._cache_key(symbol, account_name)
        cached = await self._get_cached(cache_key)
        if cached is not None:
            return cached

        sources_used: list[str] = []
        latency: dict[str, float] = {}

        ohlcv = await self._safe_fetch("get_ohlcv", "yfinance", sources_used, latency, symbol=symbol)
        news = await self._safe_fetch("get_news", "trafilatura", sources_used, latency, symbol=symbol)
        polymarket = await self._safe_fetch("get_polymarket_odds", "polymarket", sources_used, latency)
        geopolitical = await self._safe_fetch("get_gdelt_events", "gdelt", sources_used, latency, keyword=symbol)

        market_state = self._normalise_ohlcv(ohlcv)

        news_items = self._normalise_news(news)
        if news_items:
            try:
                scored = self._sentiment.score_batch([n.get("title", "") for n in news_items])
                for n, s in zip(news_items, scored):
                    n["polarity"] = s.get("polarity", 0)
                    n["label"] = s.get("label", "neutral")
                    n["score"] = s.get("score", 0)
                aggregated_sentiment = self._sentiment.aggregate_polarity(scored)
            except Exception as exc:
                logger.warning(f"FinBERT scoring failed: {exc}")
                aggregated_sentiment = 0.0
        else:
            aggregated_sentiment = 0.0

        polymarket_odds = polymarket if isinstance(polymarket, dict) else {}
        geopolitical_events = geopolitical if isinstance(geopolitical, list) else []

        partial_ctx = IntelligenceContext(
            symbol=symbol,
            market_state=market_state,
            convergence_cards=[],
            cross_market_signals=[],
            composite_score=None,
            relevant_news=news_items,
            aggregated_sentiment=aggregated_sentiment,
            polymarket_odds=polymarket_odds,
            geopolitical_events=geopolitical_events,
            sources_used=sources_used,
            fetch_latency_ms=latency,
            built_at=datetime.utcnow(),
        )

        cards = await self._run_correlation(partial_ctx)
        cross_market = self._extract_cross_market_signals(cards)

        composite = compute_isq(
            source_count=len(sources_used),
            is_alert=any(c.score >= 80 for c in cards),
            source_tier=1 if len(sources_used) >= 3 else 2,
            intensity_value=self._intensity_from_cards(cards),
            expectation_gap_value=abs(aggregated_sentiment),
            velocity_level="spike" if any(c.trend == "escalating" for c in cards) else "normal",
            velocity_trend="rising" if any(c.trend == "escalating" for c in cards) else None,
            profile="default",
        )

        ctx = IntelligenceContext(
            symbol=symbol,
            market_state=market_state,
            convergence_cards=cards,
            cross_market_signals=cross_market,
            composite_score=composite,
            relevant_news=news_items,
            aggregated_sentiment=aggregated_sentiment,
            polymarket_odds=polymarket_odds,
            geopolitical_events=geopolitical_events,
            sources_used=sources_used,
            fetch_latency_ms=latency,
            built_at=datetime.utcnow(),
        )

        await self._cache(cache_key, ctx)
        return ctx

    async def _safe_fetch(
        self,
        method: str,
        source_label: str,
        sources_used: list[str],
        latency: dict[str, float],
        **kwargs,
    ) -> Any:
        start = time.perf_counter()
        try:
            result = await asyncio.wait_for(
                self._registry.fetch(method, **kwargs),
                timeout=self._fetch_timeout,
            )
            sources_used.append(source_label)
            latency[source_label] = round((time.perf_counter() - start) * 1000, 2)
            return result
        except Exception as exc:
            latency[source_label] = round((time.perf_counter() - start) * 1000, 2)
            logger.warning(f"safe_fetch({method}) failed: {exc}")
            return None

    async def _run_correlation(self, partial_ctx: IntelligenceContext) -> list[ConvergenceCard]:
        try:
            return await self._correlation_engine.run(partial_ctx)
        except Exception as exc:
            logger.warning(f"Correlation engine failed: {exc}")
            return []

    def _extract_cross_market_signals(self, cards: list[ConvergenceCard]) -> list[SignalEvidence]:
        out: list[SignalEvidence] = []
        for card in cards:
            if card.domain == "cross_market":
                out.extend(card.signals)
        return out

    def _intensity_from_cards(self, cards: list[ConvergenceCard]) -> float:
        if not cards:
            return 0.0
        return min(1.0, max(c.score for c in cards) / 100.0)

    def _normalise_ohlcv(self, ohlcv: Any) -> dict:
        if not ohlcv:
            return {}
        if isinstance(ohlcv, dict):
            return ohlcv
        return {}

    def _normalise_news(self, news: Any) -> list[dict]:
        if not news:
            return []
        if isinstance(news, list):
            return [n if isinstance(n, dict) else {"title": str(n)} for n in news]
        return []

    def _cache_key(self, symbol: str, account_name: str) -> str:
        return f"intel:{account_name}:{symbol}"

    async def _get_cached(self, key: str) -> IntelligenceContext | None:
        try:
            raw = await self._redis.get(key)
        except Exception as exc:
            logger.warning(f"Redis get failed: {exc}")
            return None
        if raw is None:
            return None
        try:
            data = json.loads(raw)
            return self._from_dict(data)
        except Exception as exc:
            logger.warning(f"Cache deserialization failed: {exc}")
            return None

    async def _cache(self, key: str, ctx: IntelligenceContext) -> None:
        try:
            payload = json.dumps(self._to_dict(ctx))
            if hasattr(self._redis, "setex"):
                await self._redis.setex(key, self._cache_ttl, payload)
            else:
                await self._redis.set(key, payload, ex=self._cache_ttl)
        except Exception as exc:
            logger.warning(f"Cache write failed: {exc}")

    def _to_dict(self, ctx: IntelligenceContext) -> dict:
        return {
            "symbol": ctx.symbol,
            "market_state": ctx.market_state,
            "convergence_cards": [self._card_to_dict(c) for c in ctx.convergence_cards],
            "cross_market_signals": [self._signal_to_dict(s) for s in ctx.cross_market_signals],
            "composite_score": asdict(ctx.composite_score) if ctx.composite_score else None,
            "relevant_news": ctx.relevant_news,
            "aggregated_sentiment": ctx.aggregated_sentiment,
            "polymarket_odds": ctx.polymarket_odds,
            "geopolitical_events": ctx.geopolitical_events,
            "sources_used": ctx.sources_used,
            "fetch_latency_ms": ctx.fetch_latency_ms,
            "built_at": ctx.built_at.isoformat(),
        }

    def _from_dict(self, d: dict) -> IntelligenceContext:
        composite_data = d.get("composite_score")
        composite = SignalQuality(**composite_data) if composite_data else None
        return IntelligenceContext(
            symbol=d.get("symbol", ""),
            market_state=d.get("market_state", {}),
            convergence_cards=[self._dict_to_card(c) for c in d.get("convergence_cards", [])],
            cross_market_signals=[self._dict_to_signal(s) for s in d.get("cross_market_signals", [])],
            composite_score=composite,
            relevant_news=d.get("relevant_news", []),
            aggregated_sentiment=d.get("aggregated_sentiment", 0.0),
            polymarket_odds=d.get("polymarket_odds", {}),
            geopolitical_events=d.get("geopolitical_events", []),
            sources_used=d.get("sources_used", []),
            fetch_latency_ms=d.get("fetch_latency_ms", {}),
            built_at=datetime.fromisoformat(d.get("built_at", datetime.utcnow().isoformat())),
        )

    def _card_to_dict(self, card: ConvergenceCard) -> dict:
        return {
            "id": card.id, "domain": card.domain, "title": card.title,
            "score": card.score,
            "signals": [self._signal_to_dict(s) for s in card.signals],
            "markets": card.markets, "trend": card.trend,
            "timestamp": card.timestamp.isoformat(), "assessment": card.assessment,
        }

    def _dict_to_card(self, d: dict) -> ConvergenceCard:
        return ConvergenceCard(
            id=d.get("id", ""), domain=d.get("domain", ""), title=d.get("title", ""),
            score=d.get("score", 0.0),
            signals=[self._dict_to_signal(s) for s in d.get("signals", [])],
            markets=d.get("markets", []), trend=d.get("trend", "stable"),
            timestamp=datetime.fromisoformat(d.get("timestamp", datetime.utcnow().isoformat())),
            assessment=d.get("assessment"),
        )

    def _signal_to_dict(self, sig: SignalEvidence) -> dict:
        return {
            "type": sig.type, "source": sig.source, "severity": sig.severity,
            "timestamp": sig.timestamp.isoformat(), "label": sig.label,
            "market": sig.market, "raw": sig.raw,
        }

    def _dict_to_signal(self, d: dict) -> SignalEvidence:
        return SignalEvidence(
            type=d.get("type", ""), source=d.get("source", ""),
            severity=d.get("severity", 0.0),
            timestamp=datetime.fromisoformat(d.get("timestamp", datetime.utcnow().isoformat())),
            label=d.get("label", ""), market=d.get("market", ""), raw=d.get("raw"),
        )
```

- [ ] **Step 4: Run — PASS (4 tests)**

Run: `cd backend && python -m pytest tests/intelligence/test_context_builder.py -v`

- [ ] **Step 5: Commit**

```bash
git add backend/app/intelligence/context.py backend/tests/intelligence/test_context_builder.py
git commit -m "feat(intelligence): add IntelligenceContext + IntelligenceContextBuilder

Context dataclass holds: market state, convergence cards, composite
score, news + sentiment, polymarket odds, geopolitical events.
Builder fetches in parallel via registry, scores news through FinBERT,
runs correlation engine, computes composite quality.
JSON-serialized Redis cache with configurable TTL.
Graceful degradation on source failure.

Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>"
```

---

## Task 11: Wire Intelligence into AnalystAgent + Pod

**Files:**
- Modify: `backend/app/agents/analyst.py`
- Modify: `backend/app/agents/pod.py`
- Modify: `backend/prompts/defaults/analyst.md`

- [ ] **Step 1: Update AnalystAgent**

Replace `backend/app/agents/analyst.py` with:

```python
"""AnalystAgent — reads market data + memory + intelligence, emits signals."""
from __future__ import annotations

import json
import logging
import re
import time
from typing import Any

from app.agents.base import AgentContext, AgentOutput, BaseAgent

logger = logging.getLogger(__name__)

_VALID_SIGNALS = {"BUY", "SELL", "HOLD", "EXIT"}

_SAFE_DEFAULT: dict[str, Any] = {
    "signal": "HOLD",
    "confidence": 0.0,
    "reasoning": "parse_failure",
    "entry_price": None,
    "stoploss": None,
    "target": None,
}


class AnalystAgent(BaseAgent):
    """LLM-backed analyst. Optionally enriched via IntelligenceContextBuilder."""

    def __init__(
        self,
        llm_router: Any,
        prompts_dir: str,
        account_name: str,
        intelligence_builder: Any | None = None,
    ) -> None:
        self._intelligence_builder = intelligence_builder
        super().__init__(
            name="analyst",
            role="market_analyst",
            llm_tier="quick",
            account_name=account_name,
            llm_router=llm_router,
            prompts_dir=prompts_dir,
        )

    async def run(self, context: AgentContext) -> AgentOutput:
        start = time.perf_counter()

        intel = await self._build_intelligence(context)
        prompt = self._build_prompt(context, intel)
        raw_response = await self.think(prompt, tier="quick")
        parsed = self._parse_response(raw_response)

        return self._timed_output(
            start,
            agent_name=self.name,
            action="SIGNAL",
            data=parsed,
            reasoning=parsed.get("reasoning", ""),
            confidence=parsed.get("confidence", 0.0),
            llm_tier_used=self.llm_tier,
        )

    async def _build_intelligence(self, context: AgentContext) -> Any | None:
        if self._intelligence_builder is None:
            return None
        try:
            return await self._intelligence_builder.build(
                symbol=context.symbol,
                account_name=context.account_name,
            )
        except Exception as exc:
            logger.warning(f"Intelligence build failed: {exc}")
            return None

    def _build_prompt(self, context: AgentContext, intel: Any | None) -> str:
        sections: list[str] = []

        sections.append(f"## Symbol\n{context.symbol}")
        sections.append("## Market State\n" + json.dumps(context.market_state, indent=2))

        if context.memory_recall:
            learnings = "\n".join(
                f"- {item.get('learning', json.dumps(item))}"
                for item in context.memory_recall
            )
            sections.append(f"## Past Learnings\n{learnings}")
        else:
            sections.append("## Past Learnings\nNone available.")

        if context.recent_decisions:
            decisions = "\n".join(
                f"- {json.dumps(d)}" for d in context.recent_decisions
            )
            sections.append(f"## Recent Decisions\n{decisions}")
        else:
            sections.append("## Recent Decisions\nNone.")

        # Intelligence enrichment
        if intel is not None:
            cards = getattr(intel, "convergence_cards", []) or []
            if cards:
                lines = [
                    f"- [{c.score:.0f}] {c.title} ({c.trend})"
                    for c in cards[:5]
                ]
                sections.append("## Convergence Signals\n" + "\n".join(lines))

            odds = getattr(intel, "polymarket_odds", {}) or {}
            if odds:
                lines = [f"- {k}: {v:.0%}" for k, v in list(odds.items())[:10]]
                sections.append("## Polymarket Odds\n" + "\n".join(lines))

            polarity = getattr(intel, "aggregated_sentiment", 0.0) or 0.0
            sections.append(f"## News Sentiment\nAggregated polarity: {polarity:+.2f}")

            score = getattr(intel, "composite_score", None)
            if score is not None:
                sections.append(
                    f"## Signal Quality\nTier: {score.tier} (composite {score.composite:.2f})"
                )

        sections.append(
            "## Task\n"
            "Analyse the market state, intelligence signals, and learnings above. "
            "Respond with a single JSON object containing these fields:\n"
            "  signal       : 'BUY' | 'SELL' | 'HOLD' | 'EXIT'\n"
            "  confidence   : float 0.0–1.0\n"
            "  reasoning    : string (concise explanation)\n"
            "  entry_price  : float or null\n"
            "  stoploss     : float or null\n"
            "  target       : float or null\n"
            "Return ONLY the JSON object — no extra text."
        )

        return "\n\n".join(sections)

    def _parse_response(self, raw: str) -> dict[str, Any]:
        try:
            text = raw.strip()
            fence_match = re.search(r"```(?:json)?\s*([\s\S]*?)```", text)
            if fence_match:
                text = fence_match.group(1).strip()

            parsed = json.loads(text)

            signal = str(parsed.get("signal", "HOLD")).upper()
            if signal not in _VALID_SIGNALS:
                logger.warning(
                    "AnalystAgent received unknown signal '%s', defaulting to HOLD",
                    signal,
                )
                signal = "HOLD"
            parsed["signal"] = signal
            parsed["confidence"] = float(parsed.get("confidence", 0.0))
            return parsed

        except Exception as exc:
            logger.warning(
                "AnalystAgent failed to parse LLM response: %s — using safe default",
                exc,
            )
            return dict(_SAFE_DEFAULT)
```

- [ ] **Step 2: Add intelligence enrichment tests to test_analyst.py**

Append to `backend/tests/agents/test_analyst.py`:

```python
@pytest.mark.asyncio
async def test_analyst_uses_intelligence_when_provided(mock_llm_router, tmp_path):
    """Analyst injects intelligence sections into prompt when builder provided."""
    import json
    from app.agents.analyst import AnalystAgent
    from app.agents.base import AgentContext
    from app.brokers.base import MarginInfo
    from unittest.mock import AsyncMock, MagicMock

    defaults = tmp_path / "defaults"
    defaults.mkdir(exist_ok=True)
    (defaults / "analyst.md").write_text("You are a market analyst.")

    fake_intel = MagicMock()
    fake_intel.convergence_cards = []
    fake_intel.polymarket_odds = {"fed-rate-cut": 0.85}
    fake_intel.aggregated_sentiment = -0.3
    fake_intel.composite_score = MagicMock(tier="notable", composite=0.6)

    builder = MagicMock()
    builder.build = AsyncMock(return_value=fake_intel)

    analyst = AnalystAgent(
        llm_router=mock_llm_router, prompts_dir=str(tmp_path),
        account_name="paper_test", intelligence_builder=builder,
    )

    context = AgentContext(
        account_name="paper_test", symbol="NIFTY",
        market_state={"ltp": 22500},
        positions=[], margins=MarginInfo(
            available_cash=500000, used_margin=0, total_margin=500000,
            broker_name="paper", raw={},
        ),
        recent_decisions=[], memory_recall=[],
        signals={}, debate_result=None, guardian_verdict=None,
        config={"eval_interval_seconds": 300},
    )

    await analyst.run(context)
    builder.build.assert_called_once()
    call_args = mock_llm_router.generate.call_args
    prompt = call_args[1].get("prompt") or (call_args[0][0] if call_args[0] else "")
    assert "Polymarket" in prompt
    assert "fed-rate-cut" in prompt
    assert "Aggregated polarity" in prompt
    assert "notable" in prompt


@pytest.mark.asyncio
async def test_analyst_works_without_intelligence_builder(analyst, context):
    """Regression test: analyst still works when no builder provided."""
    output = await analyst.run(context)
    assert output.action == "SIGNAL"


@pytest.mark.asyncio
async def test_analyst_handles_intelligence_build_failure(mock_llm_router, tmp_path, context):
    """If builder raises, analyst should still run."""
    from app.agents.analyst import AnalystAgent
    from unittest.mock import AsyncMock, MagicMock

    defaults = tmp_path / "defaults"
    defaults.mkdir(exist_ok=True)
    (defaults / "analyst.md").write_text("You are a market analyst.")

    builder = MagicMock()
    builder.build = AsyncMock(side_effect=RuntimeError("intel down"))

    analyst = AnalystAgent(
        llm_router=mock_llm_router, prompts_dir=str(tmp_path),
        account_name="paper_test", intelligence_builder=builder,
    )

    output = await analyst.run(context)
    assert output.action == "SIGNAL"
```

- [ ] **Step 3: Update AgentPod to inject builder**

Modify `backend/app/agents/pod.py` constructor:

Replace the `AgentPod.__init__` signature line:
```python
    def __init__(self, account_name, adapter, config, db, alert_service=None, stream_publisher=None):
```
with:
```python
    def __init__(self, account_name, adapter, config, db, alert_service=None, stream_publisher=None, intelligence_builder=None):
```

Add after `self._stream_publisher = stream_publisher`:
```python
        self._intelligence_builder = intelligence_builder
```

Replace the line that creates `self.analyst`:
```python
        self.analyst = AnalystAgent(self.llm_router, prompts_dir, account_name)
```
with:
```python
        self.analyst = AnalystAgent(
            self.llm_router, prompts_dir, account_name,
            intelligence_builder=intelligence_builder,
        )
```

- [ ] **Step 4: Update analyst.md to document intelligence sections**

Append to `backend/prompts/defaults/analyst.md`:

```markdown

## Intelligence Sections (when present)
You may also see these sections in your prompt:
- **Convergence Signals**: clustered signals across markets with score (0-100) and trend
- **Polymarket Odds**: prediction market probabilities (e.g. rate cuts, geopolitical events)
- **News Sentiment**: aggregated polarity from financial news (-1.0 bearish to +1.0 bullish)
- **Signal Quality**: composite tier (strong/notable/weak/noise) and score

Use these to inform confidence and reasoning. Strong signals + supportive sentiment + favorable odds = higher confidence. Weak signals or contradicting sentiment = lower confidence or HOLD.
```

- [ ] **Step 5: Run all tests — PASS**

Run: `cd backend && python -m pytest tests/ -v --tb=short`
Expected: All previous 165 tests + new SP3 tests pass. AnalystAgent existing tests still pass with `intelligence_builder=None` default.

- [ ] **Step 6: Commit**

```bash
git add backend/app/agents/analyst.py backend/app/agents/pod.py backend/prompts/defaults/analyst.md backend/tests/agents/test_analyst.py
git commit -m "feat(intelligence): wire IntelligenceContext into AnalystAgent + Pod

AnalystAgent accepts optional intelligence_builder. When provided,
builds context per cycle and injects Convergence Signals, Polymarket
Odds, News Sentiment, Signal Quality sections into prompt.
AgentPod constructor accepts and forwards builder. Failure to build
intel degrades gracefully — analyst runs unchanged.

Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>"
```

---

## Task 12: Startup Wiring + Account Config

**Files:**
- Modify: `backend/app/main.py`
- Modify: `backend/app/config.py`
- Modify: `backend/config/accounts.yaml`

- [ ] **Step 1: Add config settings**

Append to `backend/app/config.py` after existing fields (after `ACCOUNTS_CONFIG_PATH`):

```python
    # Intelligence layer (SP3)
    INTELLIGENCE_CONFIG_PATH: str = Field(
        default="config/data_sources.yaml",
        description="Path to intelligence layer data source config"
    )
    INTELLIGENCE_ENABLED: bool = Field(
        default=False,
        description="Globally enable/disable intelligence layer"
    )
    POLYMARKET_PRIVATE_KEY: Optional[str] = Field(
        default=None,
        description="Polymarket wallet private key (read-only mode skips this)"
    )
    POLYMARKET_FUNDER_ADDRESS: Optional[str] = Field(
        default=None,
        description="Polymarket funder address"
    )
```

- [ ] **Step 2: Update main.py startup to init intelligence**

Add to `backend/app/main.py` near top imports:

```python
import yaml as _yaml
from app.intelligence import DataSource
from app.intelligence.registry import DataSourceRegistry
from app.intelligence.context import IntelligenceContextBuilder
from app.intelligence.correlation.engine import CorrelationEngine
from app.intelligence.correlation.adapters import (
    EquityDomainAdapter, CryptoDomainAdapter, ForexDomainAdapter, CrossMarketAdapter,
)
from app.intelligence.sentiment.finbert import FinBertSentiment
from app.intelligence.sources import (
    YFinanceSource, PolymarketSource, GdeltSource, NewsScraperSource,
)
from app.data.redis_client import get_redis_client
```

In the lifespan function, after AccountManager is initialised but before agent pods are built, add:

```python
    # Initialise intelligence layer (SP3)
    intelligence_builder = None
    if settings.INTELLIGENCE_ENABLED:
        try:
            intel_config_path = settings.INTELLIGENCE_CONFIG_PATH
            with open(intel_config_path, "r", encoding="utf-8") as f:
                intel_config = _yaml.safe_load(f) or {}

            registry = DataSourceRegistry(intel_config)
            registry.register(YFinanceSource())
            registry.register(PolymarketSource())
            registry.register(GdeltSource())
            registry.register(NewsScraperSource())
            # MCP sources registered when MCP clients are available

            engine = CorrelationEngine()
            engine.register_adapter(EquityDomainAdapter())
            engine.register_adapter(CryptoDomainAdapter())
            engine.register_adapter(ForexDomainAdapter())
            engine.register_adapter(CrossMarketAdapter())

            sentiment = FinBertSentiment()
            redis_client = get_redis_client()

            intelligence_builder = IntelligenceContextBuilder(
                registry=registry,
                correlation_engine=engine,
                sentiment=sentiment,
                redis_client=redis_client,
                cache_ttl_seconds=60,
            )
            logger.info("Intelligence layer initialised")
        except Exception as exc:
            logger.error(f"Intelligence layer init failed: {exc}")
```

Then where `AgentPod(...)` is instantiated, pass:
```python
intelligence_builder=intelligence_builder,
```

If `get_redis_client` does not already exist in `app/data/redis_client.py`, add it as an alias:

Append to `backend/app/data/redis_client.py`:
```python
def get_redis_client():
    """Alias for backward compatibility with intelligence layer."""
    return get_redis()
```

- [ ] **Step 3: Update accounts.yaml**

Update `backend/config/accounts.yaml` paper_test account agents section to include intelligence config:

Replace the `paper_test:` block's `agents:` section by adding an `intelligence` subkey:

```yaml
  paper_test:
    broker: paper
    segments: [CASH, FNO]
    mode: paper
    config:
      initial_capital: 1000000
      slippage_pct: 0.05
    agents:
      enabled: true
      eval_interval_seconds: 60
      watched_symbols: ["NIFTY", "RELIANCE"]
      debate:
        enabled: false
      guardian:
        max_loss_day: 100000
        max_capital_pct: 90
        max_trades_day: 100
        min_confidence: 0.5
        max_position_concentration_pct: 50
      memory:
        recall_limit: 10
      llm:
        quick_model: deepseek-v4-flash
        deep_model: deepseek-v4-flash
        ollama_base_url: http://localhost:11434
      prompts_dir: prompts/defaults/
      intelligence:
        enabled: true
        cache_ttl_seconds: 60
        cache_ttl_overrides:
          crypto: 30
          forex: 90
```

- [ ] **Step 4: Run full suite — PASS**

Run: `cd backend && python -m pytest tests/ -v --tb=short`
Expected: All tests pass. Intelligence is optional (`INTELLIGENCE_ENABLED=False` default) so no SP1/SP2 regression.

- [ ] **Step 5: Commit**

```bash
git add backend/app/main.py backend/app/config.py backend/config/accounts.yaml backend/app/data/redis_client.py
git commit -m "feat(intelligence): wire intelligence layer into startup

main.py initialises DataSourceRegistry + CorrelationEngine + FinBERT
+ IntelligenceContextBuilder when INTELLIGENCE_ENABLED. Builder is
injected into AgentPods. accounts.yaml gains optional intelligence
section. Intelligence is opt-in — defaults preserve SP1/SP2 behaviour.

Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>"
```

---

## Final Verification

- [ ] **Run full test suite**

```bash
cd backend && python -m pytest tests/ -v --tb=short
```

Expected: All previous 165 tests + ~80 new SP3 tests = ~245 passing.

- [ ] **Tag milestone**

```bash
git tag -a v0.4.0-intelligence-layer -m "Sub-project 3: Intelligence Layer complete"
```
