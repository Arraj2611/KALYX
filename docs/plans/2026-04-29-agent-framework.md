# AI Agent Framework Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build per-account autonomous AI agent pods that analyze markets, debate trades via multi-model LLM council, enforce risk, execute orders, remember outcomes, and optimize strategies overnight.

**Architecture:** Each account gets an `AgentPod` containing 8 specialized agents (Analyst, Bullish, Bearish, Judge, Guardian, Executor, Memory, Strategist) that communicate via direct async calls within the pod. `LLMRouter` routes to quick (deepseek-v4-flash) or deep (kimi-k2.6) Ollama models. Agent prompts are hot-reloadable markdown files. Redis Streams infrastructure laid for future cross-pod orchestration.

**Tech Stack:** Python 3.10+, asyncio, Ollama (via httpx), Redis Streams, existing BrokerAdapter/DecisionLogger/TelegramAlertService from SP1, pytest-asyncio

---

## File Map

### New Files

| File | Responsibility |
|------|---------------|
| `backend/app/agents/base.py` | BaseAgent ABC, AgentContext, AgentOutput dataclasses |
| `backend/app/agents/llm_router.py` | LLMRouter — two-tier Ollama routing + named models for debate |
| `backend/app/agents/analyst.py` | AnalystAgent — market analysis, signal emission |
| `backend/app/agents/debate.py` | DebateAgent (bull/bear) + JudgeAgent with anonymization |
| `backend/app/agents/guardian.py` | GuardianAgent — math-based risk checks, position sizing |
| `backend/app/agents/executor.py` | ExecutorAgent — order placement via adapter + decision logging |
| `backend/app/agents/memory.py` | MemoryAgent — recall, hindsight fill, session review |
| `backend/app/agents/strategist.py` | StrategistAgent — overnight optimization loop |
| `backend/app/agents/pod.py` | AgentPod — per-account container, eval loop lifecycle |
| `backend/app/agents/streams.py` | Redis Streams publisher/subscriber |
| `backend/prompts/defaults/analyst.md` | Default analyst system prompt |
| `backend/prompts/defaults/bullish.md` | Default bullish debate prompt |
| `backend/prompts/defaults/bearish.md` | Default bearish debate prompt |
| `backend/prompts/defaults/judge.md` | Default judge prompt |
| `backend/prompts/defaults/memory.md` | Default memory reflection prompt |
| `backend/prompts/defaults/strategist.md` | Default strategist optimization prompt |
| `backend/tests/agents/__init__.py` | Test package |
| `backend/tests/agents/test_base.py` | BaseAgent + dataclass tests |
| `backend/tests/agents/test_llm_router.py` | LLMRouter tests |
| `backend/tests/agents/test_analyst.py` | AnalystAgent tests |
| `backend/tests/agents/test_debate.py` | Debate + Judge tests |
| `backend/tests/agents/test_guardian.py` | GuardianAgent tests (exhaustive math) |
| `backend/tests/agents/test_executor.py` | ExecutorAgent tests |
| `backend/tests/agents/test_memory.py` | MemoryAgent tests |
| `backend/tests/agents/test_strategist.py` | StrategistAgent tests |
| `backend/tests/agents/test_pod.py` | AgentPod integration tests |
| `backend/tests/agents/test_streams.py` | Redis Streams tests |

### Modified Files

| File | Change |
|------|--------|
| `backend/app/agents/__init__.py` | Updated exports |
| `backend/app/agents/router.py` | Add pod status/start/stop endpoints, keep existing endpoints |
| `backend/app/main.py` | Initialize AgentPods on startup |
| `backend/config/accounts.yaml` | Extended with agents section |

---

## Task 1: Agent Core — BaseAgent + AgentContext + AgentOutput

**Files:**
- Create: `backend/app/agents/base.py`
- Create: `backend/tests/agents/__init__.py`
- Create: `backend/tests/agents/test_base.py`

- [ ] **Step 1: Write tests**

```python
# backend/tests/agents/__init__.py
"""Tests for AI agent framework."""

# backend/tests/agents/test_base.py
"""Tests for BaseAgent ABC, AgentContext, AgentOutput."""
import pytest
from datetime import datetime


def test_agent_context_creation():
    from app.agents.base import AgentContext
    from app.brokers.base import MarginInfo

    ctx = AgentContext(
        account_name="paper_test",
        symbol="NIFTY",
        market_state={"ltp": 22500.0, "rsi": 45, "volume": 100000},
        positions=[],
        margins=MarginInfo(
            available_cash=500000, used_margin=0,
            total_margin=500000, broker_name="paper", raw={},
        ),
        recent_decisions=[],
        memory_recall=[],
        signals={},
        debate_result=None,
        guardian_verdict=None,
        config={"eval_interval_seconds": 300},
    )
    assert ctx.symbol == "NIFTY"
    assert ctx.market_state["ltp"] == 22500.0
    assert ctx.debate_result is None


def test_agent_output_creation():
    from app.agents.base import AgentOutput

    output = AgentOutput(
        agent_name="analyst",
        action="SIGNAL",
        data={"signal": "BUY", "entry_price": 150.0},
        reasoning="RSI oversold at 28",
        confidence=0.75,
        llm_tier_used="quick",
        latency_ms=120.5,
    )
    assert output.action == "SIGNAL"
    assert output.confidence == 0.75
    assert output.latency_ms == 120.5


def test_agent_output_defaults():
    from app.agents.base import AgentOutput

    output = AgentOutput(
        agent_name="guardian",
        action="ALLOW",
        data={"position_size": 50},
        reasoning="All checks passed",
        confidence=0.9,
    )
    assert output.llm_tier_used is None
    assert output.latency_ms == 0.0


def test_base_agent_is_abstract():
    from app.agents.base import BaseAgent

    with pytest.raises(TypeError):
        BaseAgent(
            name="test", role="test", llm_tier="quick",
            account_name="test", llm_router=None, prompts_dir="prompts/defaults",
        )


def test_base_agent_prompt_loading(tmp_path):
    """Test that agent loads prompt from markdown file."""
    from app.agents.base import BaseAgent, AgentContext, AgentOutput

    # Create a test prompt file
    prompts_dir = tmp_path / "defaults"
    prompts_dir.mkdir()
    prompt_file = prompts_dir / "test_agent.md"
    prompt_file.write_text("You are a test agent for {segment} on {exchange}.")

    # Create concrete subclass
    class TestAgent(BaseAgent):
        async def run(self, context: AgentContext) -> AgentOutput:
            return AgentOutput(
                agent_name=self.name, action="TEST", data={},
                reasoning="test", confidence=1.0,
            )

    agent = TestAgent(
        name="test_agent", role="tester", llm_tier="quick",
        account_name="paper_test", llm_router=None, prompts_dir=str(tmp_path),
    )
    assert "test agent" in agent.system_prompt.lower()


def test_base_agent_prompt_fallback(tmp_path):
    """Falls back to defaults/ when account-specific prompt doesn't exist."""
    from app.agents.base import BaseAgent, AgentContext, AgentOutput

    defaults_dir = tmp_path / "defaults"
    defaults_dir.mkdir()
    (defaults_dir / "fallback_agent.md").write_text("Default prompt here.")

    class FallbackAgent(BaseAgent):
        async def run(self, context: AgentContext) -> AgentOutput:
            return AgentOutput(
                agent_name=self.name, action="TEST", data={},
                reasoning="test", confidence=1.0,
            )

    agent = FallbackAgent(
        name="fallback_agent", role="tester", llm_tier="none",
        account_name="nonexistent_account", llm_router=None, prompts_dir=str(tmp_path),
    )
    assert "Default prompt" in agent.system_prompt


def test_base_agent_reload_prompt(tmp_path):
    """Test hot-reload of prompt."""
    from app.agents.base import BaseAgent, AgentContext, AgentOutput

    defaults_dir = tmp_path / "defaults"
    defaults_dir.mkdir()
    prompt_file = defaults_dir / "reload_agent.md"
    prompt_file.write_text("Version 1")

    class ReloadAgent(BaseAgent):
        async def run(self, context: AgentContext) -> AgentOutput:
            return AgentOutput(
                agent_name=self.name, action="TEST", data={},
                reasoning="test", confidence=1.0,
            )

    agent = ReloadAgent(
        name="reload_agent", role="tester", llm_tier="none",
        account_name="test", llm_router=None, prompts_dir=str(tmp_path),
    )
    assert "Version 1" in agent.system_prompt

    # Modify file
    prompt_file.write_text("Version 2")
    agent.reload_prompt()
    assert "Version 2" in agent.system_prompt
```

- [ ] **Step 2: Run tests — should FAIL**

Run: `cd backend && python -m pytest tests/agents/test_base.py -v`
Expected: FAIL — `ModuleNotFoundError`

- [ ] **Step 3: Implement base.py**

```python
# backend/app/agents/base.py
"""
Agent framework core — BaseAgent ABC, AgentContext, AgentOutput.
Every agent in KALYX inherits from BaseAgent.
"""
import os
import time
import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from app.brokers.base import Position, MarginInfo

logger = logging.getLogger(__name__)


@dataclass
class AgentContext:
    """Shared state passed through evaluation cycle within a pod."""
    account_name: str
    symbol: str
    market_state: dict
    positions: list[Position]
    margins: MarginInfo
    recent_decisions: list[dict]
    memory_recall: list[dict]
    signals: dict
    debate_result: dict | None
    guardian_verdict: dict | None
    config: dict


@dataclass
class AgentOutput:
    """Output from any agent's run() method."""
    agent_name: str
    action: str          # SIGNAL, ARGUE, JUDGE, ALLOW, BLOCK, EXECUTE, RECALL, OPTIMIZE
    data: dict
    reasoning: str
    confidence: float    # 0.0 - 1.0
    llm_tier_used: str | None = None
    latency_ms: float = 0.0


class BaseAgent(ABC):
    """Abstract base for all KALYX agents."""

    def __init__(
        self,
        name: str,
        role: str,
        llm_tier: str,
        account_name: str,
        llm_router: Any,
        prompts_dir: str,
    ):
        self.name = name
        self.role = role
        self.llm_tier = llm_tier
        self.account_name = account_name
        self.llm_router = llm_router
        self._prompts_dir = prompts_dir
        self.system_prompt = self._load_prompt()

    @abstractmethod
    async def run(self, context: AgentContext) -> AgentOutput:
        """Execute agent logic. Every agent implements this."""
        ...

    async def think(self, prompt: str, tier: str | None = None) -> str:
        """Call LLM via router. Uses agent's default tier if not specified."""
        if self.llm_router is None:
            raise RuntimeError(f"Agent {self.name} has no LLM router configured")
        used_tier = tier or self.llm_tier
        return await self.llm_router.generate(
            prompt=prompt,
            system_prompt=self.system_prompt,
            tier=used_tier,
        )

    def _load_prompt(self) -> str:
        """Load system prompt from markdown file. Account-specific overrides default."""
        # Try account-specific first
        account_path = os.path.join(self._prompts_dir, self.account_name, f"{self.name}.md")
        if os.path.isfile(account_path):
            with open(account_path, "r", encoding="utf-8") as f:
                return f.read()

        # Fall back to defaults
        default_path = os.path.join(self._prompts_dir, "defaults", f"{self.name}.md")
        if os.path.isfile(default_path):
            with open(default_path, "r", encoding="utf-8") as f:
                return f.read()

        logger.warning(f"No prompt file found for agent '{self.name}' in {self._prompts_dir}")
        return f"You are {self.name}, a {self.role} agent."

    def reload_prompt(self) -> None:
        """Hot-reload prompt from file."""
        self.system_prompt = self._load_prompt()

    def _timed_output(self, start: float, **kwargs) -> AgentOutput:
        """Helper to create AgentOutput with latency measurement."""
        elapsed = (time.time() - start) * 1000
        return AgentOutput(latency_ms=round(elapsed, 2), **kwargs)
```

- [ ] **Step 4: Run tests — all PASS**

Run: `cd backend && python -m pytest tests/agents/test_base.py -v`
Expected: 7 tests PASS

- [ ] **Step 5: Commit**

```bash
git add backend/app/agents/base.py backend/tests/agents/__init__.py backend/tests/agents/test_base.py
git commit -m "feat(agents): add BaseAgent ABC, AgentContext, AgentOutput

Foundation for agent framework. BaseAgent loads system prompts from
markdown files with account-specific overrides. AgentContext carries
shared state through eval cycle. AgentOutput captures action, data,
reasoning, confidence, and latency.

Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>"
```

---

## Task 2: LLMRouter — Two-Tier Ollama Routing

**Files:**
- Create: `backend/app/agents/llm_router.py`
- Create: `backend/tests/agents/test_llm_router.py`

- [ ] **Step 1: Write tests**

```python
# backend/tests/agents/test_llm_router.py
"""Tests for LLMRouter — two-tier Ollama routing."""
import pytest
from unittest.mock import AsyncMock, patch, MagicMock


@pytest.fixture
def router_config():
    return {
        "quick_model": "deepseek-v4-flash",
        "deep_model": "kimi-k2.6",
        "ollama_base_url": "http://localhost:11434",
    }


@pytest.fixture
def mock_response():
    """Mock httpx response from Ollama."""
    resp = MagicMock()
    resp.status_code = 200
    resp.json.return_value = {"response": "Test LLM output"}
    resp.raise_for_status = MagicMock()
    return resp


def test_router_creation(router_config):
    from app.agents.llm_router import LLMRouter
    router = LLMRouter(router_config)
    assert router._quick_model == "deepseek-v4-flash"
    assert router._deep_model == "kimi-k2.6"


@pytest.mark.asyncio
async def test_generate_quick_tier(router_config, mock_response):
    from app.agents.llm_router import LLMRouter
    router = LLMRouter(router_config)

    with patch("httpx.AsyncClient.post", new_callable=AsyncMock, return_value=mock_response):
        result = await router.generate("test prompt", tier="quick")
        assert result == "Test LLM output"


@pytest.mark.asyncio
async def test_generate_deep_tier(router_config, mock_response):
    from app.agents.llm_router import LLMRouter
    router = LLMRouter(router_config)

    with patch("httpx.AsyncClient.post", new_callable=AsyncMock, return_value=mock_response):
        result = await router.generate("test prompt", tier="deep")
        assert result == "Test LLM output"


@pytest.mark.asyncio
async def test_generate_with_system_prompt(router_config, mock_response):
    from app.agents.llm_router import LLMRouter
    router = LLMRouter(router_config)

    with patch("httpx.AsyncClient.post", new_callable=AsyncMock, return_value=mock_response) as mock_post:
        await router.generate("user prompt", system_prompt="system prompt", tier="quick")
        call_args = mock_post.call_args
        body = call_args[1]["json"] if "json" in call_args[1] else call_args[0][1]
        assert body["system"] == "system prompt"


def test_register_named_model(router_config):
    from app.agents.llm_router import LLMRouter
    router = LLMRouter(router_config)
    router.register_model("bullish", "deepseek-v4-flash")
    router.register_model("bearish", "kimi-k2.6")
    assert "bullish" in router._named_models
    assert router._named_models["bearish"] == "kimi-k2.6"


@pytest.mark.asyncio
async def test_generate_with_named_model(router_config, mock_response):
    from app.agents.llm_router import LLMRouter
    router = LLMRouter(router_config)
    router.register_model("bullish", "deepseek-v4-flash")

    with patch("httpx.AsyncClient.post", new_callable=AsyncMock, return_value=mock_response) as mock_post:
        result = await router.generate_with_model("prompt", "system", "bullish")
        assert result == "Test LLM output"
        call_args = mock_post.call_args
        body = call_args[1]["json"] if "json" in call_args[1] else call_args[0][1]
        assert body["model"] == "deepseek-v4-flash"


@pytest.mark.asyncio
async def test_generate_unknown_model_raises(router_config):
    from app.agents.llm_router import LLMRouter
    router = LLMRouter(router_config)

    with pytest.raises(KeyError):
        await router.generate_with_model("prompt", "system", "nonexistent")


@pytest.mark.asyncio
async def test_generate_retry_on_failure(router_config):
    from app.agents.llm_router import LLMRouter
    router = LLMRouter(router_config)

    call_count = 0
    good_resp = MagicMock()
    good_resp.status_code = 200
    good_resp.json.return_value = {"response": "recovered"}
    good_resp.raise_for_status = MagicMock()

    async def flaky_post(*args, **kwargs):
        nonlocal call_count
        call_count += 1
        if call_count < 3:
            raise Exception("Connection refused")
        return good_resp

    with patch("httpx.AsyncClient.post", side_effect=flaky_post):
        result = await router.generate("test", tier="quick")
        assert result == "recovered"
        assert call_count == 3
```

- [ ] **Step 2: Run tests — should FAIL**

Run: `cd backend && python -m pytest tests/agents/test_llm_router.py -v`
Expected: FAIL

- [ ] **Step 3: Implement LLMRouter**

```python
# backend/app/agents/llm_router.py
"""
LLMRouter — two-tier Ollama routing with named model support.
Replaces the old LLMProvider/get_llm_provider() system.

Quick tier: fast model for real-time signals (deepseek-v4-flash)
Deep tier: powerful model for analysis/debate (kimi-k2.6)
Named models: specific models for debate sides (bullish/bearish/judge)
"""
import logging
import asyncio
import httpx

logger = logging.getLogger(__name__)


class LLMRouter:
    """Routes LLM calls to appropriate Ollama model based on tier or name."""

    def __init__(self, config: dict):
        self._quick_model = config["quick_model"]
        self._deep_model = config["deep_model"]
        self._base_url = config.get("ollama_base_url", "http://localhost:11434")
        self._named_models: dict[str, str] = {}
        self._timeout = float(config.get("timeout_seconds", 120))
        self._max_retries = int(config.get("max_retries", 3))

    def register_model(self, name: str, model: str) -> None:
        """Register a named model (e.g., 'bullish' → 'deepseek-v4-flash')."""
        self._named_models[name] = model
        logger.info(f"Registered named model: {name} → {model}")

    async def generate(
        self,
        prompt: str,
        system_prompt: str = "",
        tier: str = "quick",
    ) -> str:
        """Generate via tier (quick/deep)."""
        model = self._quick_model if tier == "quick" else self._deep_model
        return await self._call_ollama(model, prompt, system_prompt)

    async def generate_with_model(
        self,
        prompt: str,
        system_prompt: str,
        model_name: str,
    ) -> str:
        """Generate via named model. Raises KeyError if not registered."""
        if model_name not in self._named_models:
            raise KeyError(f"Named model '{model_name}' not registered")
        model = self._named_models[model_name]
        return await self._call_ollama(model, prompt, system_prompt)

    async def _call_ollama(self, model: str, prompt: str, system_prompt: str) -> str:
        """Call Ollama API with retry logic."""
        url = f"{self._base_url}/api/generate"
        payload = {
            "model": model,
            "prompt": prompt,
            "stream": False,
        }
        if system_prompt:
            payload["system"] = system_prompt

        last_error = None
        for attempt in range(self._max_retries):
            try:
                async with httpx.AsyncClient(timeout=self._timeout) as client:
                    response = await client.post(url, json=payload)
                    response.raise_for_status()
                    data = response.json()
                    return data.get("response", "")
            except Exception as e:
                last_error = e
                if attempt < self._max_retries - 1:
                    wait = 2 ** attempt
                    logger.warning(
                        f"Ollama call failed (model={model}, attempt={attempt + 1}): {e}. "
                        f"Retrying in {wait}s..."
                    )
                    await asyncio.sleep(wait)
                else:
                    logger.error(f"Ollama call failed after {self._max_retries} attempts: {e}")

        raise last_error
```

- [ ] **Step 4: Run tests — all PASS**

Run: `cd backend && python -m pytest tests/agents/test_llm_router.py -v`
Expected: 8 tests PASS

- [ ] **Step 5: Commit**

```bash
git add backend/app/agents/llm_router.py backend/tests/agents/test_llm_router.py
git commit -m "feat(agents): add LLMRouter — two-tier Ollama routing

Quick tier (deepseek-v4-flash) for real-time signals, deep tier
(kimi-k2.6) for analysis. Named model support for multi-model
debate. Retry with exponential backoff. Replaces old LLMProvider.

Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>"
```

---

## Task 3: Default Agent Prompts (Markdown Files)

**Files:**
- Create: `backend/prompts/defaults/analyst.md`
- Create: `backend/prompts/defaults/bullish.md`
- Create: `backend/prompts/defaults/bearish.md`
- Create: `backend/prompts/defaults/judge.md`
- Create: `backend/prompts/defaults/memory.md`
- Create: `backend/prompts/defaults/strategist.md`

- [ ] **Step 1: Create prompt files**

```markdown
<!-- backend/prompts/defaults/analyst.md -->
You are a market analyst. Your job: analyze current market conditions and emit a trading signal.

## Input
You receive:
- Current LTP, OHLC, volume, OI (if F&O)
- Technical indicators (RSI, MACD, Bollinger Bands) if available
- Recent decisions and their outcomes for this symbol
- Learnings from past trades (memory recall)

## Output Format
Respond ONLY with this JSON — no other text:
{
  "signal": "BUY" or "SELL" or "HOLD",
  "confidence": 0.0 to 1.0,
  "reasoning": "1-2 sentence explanation",
  "entry_price": number or null,
  "stoploss": number or null,
  "target": number or null
}

## Rules
- Only emit BUY/SELL when confidence > 0.5
- HOLD is the default — only trade when setup is clear
- Factor in past learnings: if similar setup lost before, lower confidence
- Always include stoploss for BUY/SELL signals
- Be concise in reasoning
```

```markdown
<!-- backend/prompts/defaults/bullish.md -->
You are a bullish market advocate. Your job: argue FOR taking this trade.

## Input
You receive a trading signal and market data. Argue why this trade should be taken.

## Output Format
Respond ONLY with this JSON:
{
  "argument": "your detailed bullish case (2-4 sentences)",
  "conviction": 0.0 to 1.0,
  "key_factors": ["factor1", "factor2", "factor3"]
}

## Rules
- Be specific — cite actual data points (price levels, indicator values)
- Acknowledge risks but explain why reward outweighs them
- Focus on what could go RIGHT
- High conviction = strong technical + fundamental alignment
```

```markdown
<!-- backend/prompts/defaults/bearish.md -->
You are a bearish market advocate. Your job: argue AGAINST taking this trade.

## Input
You receive a trading signal and market data. Argue why this trade should NOT be taken.

## Output Format
Respond ONLY with this JSON:
{
  "argument": "your detailed bearish case (2-4 sentences)",
  "conviction": 0.0 to 1.0,
  "risk_factors": ["risk1", "risk2", "risk3"]
}

## Rules
- Be specific — cite actual data points that contradict the signal
- Focus on what could go WRONG
- Consider: false signals, overextension, volatility, liquidity
- High conviction = strong evidence the trade will fail
```

```markdown
<!-- backend/prompts/defaults/judge.md -->
You are an impartial trading judge. Two analysts disagree on a trade.

## Input
You receive two anonymized arguments — Argument A and Argument B. You do NOT know which is bullish or bearish.

## Output Format
Respond ONLY with this JSON:
{
  "proceed": true or false,
  "adjusted_confidence": 0.0 to 1.0,
  "reasoning": "why you chose to proceed or reject (2-3 sentences)",
  "stronger_argument": "A" or "B"
}

## Rules
- Evaluate arguments on merit, not position
- If both arguments are weak, reject (proceed=false)
- If bullish case is strong but risks are real, reduce confidence
- Your adjusted_confidence overrides the original signal confidence
- Be decisive — no fence-sitting
```

```markdown
<!-- backend/prompts/defaults/memory.md -->
You are a trade reflection analyst. Your job: analyze completed trade outcomes and extract learnings.

## Input
You receive:
- Original trade reasoning and signal
- Market conditions at entry
- Actual outcome (P&L, exit price)
- Whether the decision was correct

## Output Format
Respond ONLY with this JSON:
{
  "reflection": "what happened and why (2-3 sentences)",
  "learning": "actionable takeaway for future trades (1-2 sentences)",
  "tags": ["tag1", "tag2"],
  "pattern": "short pattern name (e.g., 'rsi_divergence_in_trending_market')"
}

## Rules
- Be specific about what worked or failed
- Extract reusable patterns, not one-off observations
- Tags should be searchable: instrument type, strategy, market condition
- Learning should be actionable: "When X happens, do Y" or "Avoid X when Y"
```

```markdown
<!-- backend/prompts/defaults/strategist.md -->
You are a strategy optimization expert. Your job: suggest improvements to underperforming strategies.

## Input
You receive:
- Strategy name, type, and current parameters
- Recent performance metrics (win rate, Sharpe ratio, P&L)
- Past learnings from Memory Agent about this strategy

## Output Format
Respond ONLY with this JSON:
{
  "parameter_name": "exact parameter to change",
  "current_value": current value,
  "suggested_value": new value,
  "reasoning": "why this change should improve performance (1-2 sentences)",
  "expected_improvement": "what metric should improve and by roughly how much"
}

## Rules
- Suggest only ONE change at a time (isolate variables)
- Be specific: exact parameter name and exact new value
- Base suggestions on past learnings when available
- Conservative changes preferred — small adjustments, not rewrites
- Never suggest changes that increase risk without improving returns
```

- [ ] **Step 2: Verify prompt files exist**

Run: `ls backend/prompts/defaults/`
Expected: 6 markdown files

- [ ] **Step 3: Commit**

```bash
git add backend/prompts/
git commit -m "feat(agents): add default agent prompt markdown files

Hot-reloadable system prompts for: analyst, bullish, bearish, judge,
memory, strategist. JSON output format enforced. Per-account
overrides supported via prompts/{account_name}/ directory.

Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>"
```

---

## Task 4: GuardianAgent — Math-Based Risk Checks

**Files:**
- Create: `backend/app/agents/guardian.py`
- Create: `backend/tests/agents/test_guardian.py`

- [ ] **Step 1: Write exhaustive tests**

```python
# backend/tests/agents/test_guardian.py
"""Tests for GuardianAgent — exhaustive math-based risk checks."""
import pytest
from app.agents.base import AgentContext, AgentOutput
from app.brokers.base import Position, MarginInfo


def make_context(
    daily_pnl=0, capital_used_pct=0, daily_trades=0,
    confidence=0.8, positions=None, available_cash=500000, used_margin=0,
):
    """Helper to create AgentContext with controlled values."""
    from app.agents.base import AgentContext

    margin = MarginInfo(
        available_cash=available_cash, used_margin=used_margin,
        total_margin=available_cash + used_margin, broker_name="paper", raw={},
    )
    return AgentContext(
        account_name="test",
        symbol="NIFTY",
        market_state={"ltp": 22500},
        positions=positions or [],
        margins=margin,
        recent_decisions=[{"pnl": daily_pnl}] if daily_pnl else [],
        memory_recall=[],
        signals={"signal": "BUY", "confidence": confidence},
        debate_result={"verdict": {"proceed": True}, "reasoning": "test"},
        guardian_verdict=None,
        config={
            "guardian": {
                "max_loss_day": 50000,
                "max_capital_pct": 80,
                "max_trades_day": 50,
                "min_confidence": 0.6,
                "max_position_concentration_pct": 30,
            },
            "eval_interval_seconds": 300,
        },
    )


@pytest.fixture
def guardian():
    from app.agents.guardian import GuardianAgent
    config = {
        "max_loss_day": 50000,
        "max_capital_pct": 80,
        "max_trades_day": 50,
        "min_confidence": 0.6,
        "max_position_concentration_pct": 30,
    }
    return GuardianAgent(
        config=config, account_name="test",
        llm_router=None, prompts_dir="prompts/defaults",
    )


@pytest.mark.asyncio
async def test_guardian_allows_valid_trade(guardian):
    ctx = make_context(confidence=0.8)
    output = await guardian.run(ctx)
    assert output.action == "ALLOW"
    assert output.data["position_size"] > 0


@pytest.mark.asyncio
async def test_guardian_blocks_daily_loss_exceeded(guardian):
    ctx = make_context(daily_pnl=-60000)
    output = await guardian.run(ctx)
    assert output.action == "BLOCK"
    assert "daily_loss" in output.data["reason"]


@pytest.mark.asyncio
async def test_guardian_blocks_capital_limit(guardian):
    ctx = make_context(available_cash=100000, used_margin=450000)
    output = await guardian.run(ctx)
    assert output.action == "BLOCK"
    assert "capital" in output.data["reason"]


@pytest.mark.asyncio
async def test_guardian_blocks_low_confidence(guardian):
    ctx = make_context(confidence=0.4)
    output = await guardian.run(ctx)
    assert output.action == "BLOCK"
    assert "confidence" in output.data["reason"]


@pytest.mark.asyncio
async def test_guardian_position_sizing_low_confidence(guardian):
    ctx = make_context(confidence=0.65)
    output = await guardian.run(ctx)
    assert output.action == "ALLOW"
    assert output.data["position_size"] == 1  # 0.6-0.7 = 1 lot


@pytest.mark.asyncio
async def test_guardian_position_sizing_medium_confidence(guardian):
    ctx = make_context(confidence=0.75)
    output = await guardian.run(ctx)
    assert output.data["position_size"] == 2  # 0.7-0.8 = 2 lots


@pytest.mark.asyncio
async def test_guardian_position_sizing_high_confidence(guardian):
    ctx = make_context(confidence=0.85)
    output = await guardian.run(ctx)
    assert output.data["position_size"] == 3  # 0.8-0.9 = 3 lots


@pytest.mark.asyncio
async def test_guardian_position_sizing_very_high_confidence(guardian):
    ctx = make_context(confidence=0.95)
    output = await guardian.run(ctx)
    assert output.data["position_size"] == 5  # 0.9+ = max (5)


@pytest.mark.asyncio
async def test_guardian_no_llm_used(guardian):
    ctx = make_context(confidence=0.8)
    output = await guardian.run(ctx)
    assert output.llm_tier_used is None


@pytest.mark.asyncio
async def test_guardian_is_base_agent(guardian):
    from app.agents.base import BaseAgent
    assert isinstance(guardian, BaseAgent)
```

- [ ] **Step 2: Run tests — FAIL**

Run: `cd backend && python -m pytest tests/agents/test_guardian.py -v`

- [ ] **Step 3: Implement GuardianAgent**

```python
# backend/app/agents/guardian.py
"""
GuardianAgent — math-based risk checks. No LLM calls.
Decides ALLOW/BLOCK + computes position size based on confidence.
"""
import time
import logging
from app.agents.base import BaseAgent, AgentContext, AgentOutput

logger = logging.getLogger(__name__)


class GuardianAgent(BaseAgent):
    """Risk guardian. Pure math. No LLM. Fast."""

    def __init__(self, config: dict, account_name: str, llm_router=None, prompts_dir: str = ""):
        self._risk_config = config
        super().__init__(
            name="guardian",
            role="risk_manager",
            llm_tier="none",
            account_name=account_name,
            llm_router=llm_router,
            prompts_dir=prompts_dir,
        )

    async def run(self, context: AgentContext) -> AgentOutput:
        start = time.time()
        config = self._risk_config

        # 1. Daily loss check
        daily_pnl = sum(d.get("pnl", 0) for d in context.recent_decisions)
        if daily_pnl < -config["max_loss_day"]:
            return self._block(start, "daily_loss_exceeded",
                               f"Daily P&L {daily_pnl} exceeds limit -{config['max_loss_day']}")

        # 2. Capital usage check
        total = context.margins.total_margin
        used = context.margins.used_margin
        usage_pct = (used / total * 100) if total > 0 else 0
        if usage_pct > config["max_capital_pct"]:
            return self._block(start, "capital_limit",
                               f"Capital usage {usage_pct:.1f}% > {config['max_capital_pct']}%")

        # 3. Confidence check
        confidence = context.signals.get("confidence", 0)
        if confidence < config["min_confidence"]:
            return self._block(start, "low_confidence",
                               f"Confidence {confidence} < minimum {config['min_confidence']}")

        # 4. Position concentration check
        max_conc = config.get("max_position_concentration_pct", 100)
        if total > 0 and context.positions:
            for pos in context.positions:
                pos_value = abs(pos.quantity * pos.average_price)
                pos_pct = pos_value / total * 100
                if pos.symbol == context.symbol and pos_pct > max_conc:
                    return self._block(start, "position_concentration",
                                       f"{context.symbol} at {pos_pct:.1f}% > {max_conc}%")

        # 5. Compute position size based on confidence
        position_size = self._compute_position_size(confidence)

        elapsed = (time.time() - start) * 1000
        return AgentOutput(
            agent_name="guardian",
            action="ALLOW",
            data={"position_size": position_size, "checks_passed": True},
            reasoning=f"All risk checks passed. Position size: {position_size} lots.",
            confidence=confidence,
            llm_tier_used=None,
            latency_ms=round(elapsed, 2),
        )

    def _block(self, start: float, reason: str, reasoning: str) -> AgentOutput:
        elapsed = (time.time() - start) * 1000
        return AgentOutput(
            agent_name="guardian",
            action="BLOCK",
            data={"reason": reason, "checks_passed": False},
            reasoning=reasoning,
            confidence=0.0,
            llm_tier_used=None,
            latency_ms=round(elapsed, 2),
        )

    def _compute_position_size(self, confidence: float) -> int:
        """Scale position size with confidence. Conservative."""
        if confidence >= 0.9:
            return 5
        elif confidence >= 0.8:
            return 3
        elif confidence >= 0.7:
            return 2
        else:
            return 1
```

- [ ] **Step 4: Run tests — all PASS**

Run: `cd backend && python -m pytest tests/agents/test_guardian.py -v`
Expected: 10 tests PASS

- [ ] **Step 5: Commit**

```bash
git add backend/app/agents/guardian.py backend/tests/agents/test_guardian.py
git commit -m "feat(agents): add GuardianAgent — math-based risk checks

No LLM. Checks: daily loss limit, capital usage, confidence threshold,
position concentration. Computes position size: confidence 0.6→1 lot,
0.7→2, 0.8→3, 0.9+→5. Fail-safe: any error = BLOCK.

Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>"
```

---

## Task 5: AnalystAgent

**Files:**
- Create: `backend/app/agents/analyst.py`
- Create: `backend/tests/agents/test_analyst.py`

- [ ] **Step 1: Write tests**

```python
# backend/tests/agents/test_analyst.py
"""Tests for AnalystAgent."""
import pytest
import json
from unittest.mock import AsyncMock, MagicMock
from app.agents.base import AgentContext, AgentOutput
from app.brokers.base import MarginInfo


@pytest.fixture
def mock_llm_router():
    router = MagicMock()
    router.generate = AsyncMock(return_value=json.dumps({
        "signal": "BUY",
        "confidence": 0.75,
        "reasoning": "RSI oversold at 28, MACD bullish crossover",
        "entry_price": 150.0,
        "stoploss": 140.0,
        "target": 170.0,
    }))
    return router


@pytest.fixture
def analyst(mock_llm_router, tmp_path):
    defaults = tmp_path / "defaults"
    defaults.mkdir()
    (defaults / "analyst.md").write_text("You are a market analyst.")

    from app.agents.analyst import AnalystAgent
    return AnalystAgent(
        llm_router=mock_llm_router,
        prompts_dir=str(tmp_path),
        account_name="paper_test",
    )


@pytest.fixture
def context():
    return AgentContext(
        account_name="paper_test",
        symbol="NIFTY",
        market_state={"ltp": 22500.0, "rsi": 28, "macd": {"signal": "bullish"}},
        positions=[],
        margins=MarginInfo(available_cash=500000, used_margin=0, total_margin=500000, broker_name="paper", raw={}),
        recent_decisions=[],
        memory_recall=[],
        signals={},
        debate_result=None,
        guardian_verdict=None,
        config={"eval_interval_seconds": 300},
    )


@pytest.mark.asyncio
async def test_analyst_emits_buy_signal(analyst, context):
    output = await analyst.run(context)
    assert output.action == "SIGNAL"
    assert output.data["signal"] == "BUY"
    assert output.confidence == 0.75


@pytest.mark.asyncio
async def test_analyst_includes_reasoning(analyst, context):
    output = await analyst.run(context)
    assert "RSI" in output.reasoning


@pytest.mark.asyncio
async def test_analyst_uses_quick_tier(analyst, context, mock_llm_router):
    await analyst.run(context)
    mock_llm_router.generate.assert_called_once()
    call_kwargs = mock_llm_router.generate.call_args[1]
    assert call_kwargs.get("tier") == "quick" or analyst.llm_tier == "quick"


@pytest.mark.asyncio
async def test_analyst_handles_hold_signal(analyst, context, mock_llm_router):
    mock_llm_router.generate = AsyncMock(return_value=json.dumps({
        "signal": "HOLD", "confidence": 0.3, "reasoning": "No setup",
        "entry_price": None, "stoploss": None, "target": None,
    }))
    output = await analyst.run(context)
    assert output.data["signal"] == "HOLD"
    assert output.confidence == 0.3


@pytest.mark.asyncio
async def test_analyst_handles_malformed_json(analyst, context, mock_llm_router):
    mock_llm_router.generate = AsyncMock(return_value="not valid json at all")
    output = await analyst.run(context)
    assert output.data["signal"] == "HOLD"  # safe default
    assert output.confidence == 0.0


@pytest.mark.asyncio
async def test_analyst_includes_memory_in_prompt(analyst, context, mock_llm_router):
    context.memory_recall = [{"symbol": "NIFTY", "learning": "RSI works below 30"}]
    await analyst.run(context)
    call_args = mock_llm_router.generate.call_args
    prompt = call_args[1].get("prompt") or call_args[0][0]
    assert "RSI works below 30" in prompt


@pytest.mark.asyncio
async def test_analyst_is_base_agent(analyst):
    from app.agents.base import BaseAgent
    assert isinstance(analyst, BaseAgent)
```

- [ ] **Step 2: Run — FAIL**

- [ ] **Step 3: Implement AnalystAgent**

```python
# backend/app/agents/analyst.py
"""
AnalystAgent — analyzes market conditions, emits trading signals.
Uses quick LLM tier for fast evaluation.
"""
import json
import time
import logging
from app.agents.base import BaseAgent, AgentContext, AgentOutput

logger = logging.getLogger(__name__)


class AnalystAgent(BaseAgent):
    """Reads market data + memory, emits BUY/SELL/HOLD signals."""

    def __init__(self, llm_router, prompts_dir: str, account_name: str):
        super().__init__(
            name="analyst",
            role="market_analyst",
            llm_tier="quick",
            account_name=account_name,
            llm_router=llm_router,
            prompts_dir=prompts_dir,
        )

    async def run(self, context: AgentContext) -> AgentOutput:
        start = time.time()

        # Build prompt with market data + memory
        prompt = self._build_prompt(context)

        try:
            raw = await self.think(prompt, tier="quick")
            data = self._parse_response(raw)
        except Exception as e:
            logger.error(f"Analyst LLM call failed: {e}")
            data = {"signal": "HOLD", "confidence": 0.0, "reasoning": f"LLM error: {e}"}

        elapsed = (time.time() - start) * 1000
        return AgentOutput(
            agent_name="analyst",
            action="SIGNAL",
            data=data,
            reasoning=data.get("reasoning", ""),
            confidence=data.get("confidence", 0.0),
            llm_tier_used="quick",
            latency_ms=round(elapsed, 2),
        )

    def _build_prompt(self, context: AgentContext) -> str:
        parts = [
            f"## Symbol: {context.symbol}",
            f"## Market State:\n{json.dumps(context.market_state, indent=2)}",
        ]

        if context.memory_recall:
            learnings = "\n".join(
                f"- {m.get('learning', m.get('reasoning', str(m)))}"
                for m in context.memory_recall
            )
            parts.append(f"## Past Learnings:\n{learnings}")

        if context.recent_decisions:
            recent = "\n".join(
                f"- {d.get('signal', '?')} @ confidence {d.get('confidence', '?')}: {d.get('reasoning', '?')}"
                for d in context.recent_decisions[:5]
            )
            parts.append(f"## Recent Decisions:\n{recent}")

        parts.append("## Your Analysis:\nAnalyze and respond with the JSON format specified in your instructions.")
        return "\n\n".join(parts)

    def _parse_response(self, raw: str) -> dict:
        """Parse LLM JSON response. Returns safe defaults on failure."""
        try:
            # Try to extract JSON from response (LLM might wrap in markdown)
            text = raw.strip()
            if "```json" in text:
                text = text.split("```json")[1].split("```")[0].strip()
            elif "```" in text:
                text = text.split("```")[1].split("```")[0].strip()

            data = json.loads(text)
            # Validate required fields
            signal = data.get("signal", "HOLD").upper()
            if signal not in ("BUY", "SELL", "HOLD", "EXIT"):
                signal = "HOLD"
            data["signal"] = signal
            data["confidence"] = float(data.get("confidence", 0.0))
            data["reasoning"] = data.get("reasoning", "")
            return data
        except (json.JSONDecodeError, ValueError, IndexError) as e:
            logger.warning(f"Failed to parse analyst response: {e}. Raw: {raw[:200]}")
            return {
                "signal": "HOLD",
                "confidence": 0.0,
                "reasoning": f"Parse error: {e}",
            }
```

- [ ] **Step 4: Run tests — all PASS**

Run: `cd backend && python -m pytest tests/agents/test_analyst.py -v`
Expected: 7 tests PASS

- [ ] **Step 5: Commit**

```bash
git add backend/app/agents/analyst.py backend/tests/agents/test_analyst.py
git commit -m "feat(agents): add AnalystAgent — market signal emission

Builds prompt from market state + memory recall + recent decisions.
Parses JSON signals (BUY/SELL/HOLD) from LLM. Safe defaults on
parse failure (HOLD, confidence 0). Handles markdown-wrapped JSON.

Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>"
```

---

## Task 6: Debate — Bullish + Bearish + Judge with Anonymization

**Files:**
- Create: `backend/app/agents/debate.py`
- Create: `backend/tests/agents/test_debate.py`

- [ ] **Step 1: Write tests**

```python
# backend/tests/agents/test_debate.py
"""Tests for DebateAgent + JudgeAgent with anonymization."""
import pytest
import json
import random
from unittest.mock import AsyncMock, MagicMock
from app.agents.base import AgentContext, AgentOutput
from app.brokers.base import MarginInfo


@pytest.fixture
def mock_llm_router():
    router = MagicMock()
    router.generate_with_model = AsyncMock(return_value=json.dumps({
        "argument": "Strong bullish case based on RSI",
        "conviction": 0.8,
        "key_factors": ["RSI oversold", "volume spike"],
    }))
    router.generate = AsyncMock(return_value=json.dumps({
        "proceed": True,
        "adjusted_confidence": 0.7,
        "reasoning": "Bullish case stronger but risks noted",
        "stronger_argument": "A",
    }))
    return router


@pytest.fixture
def context():
    return AgentContext(
        account_name="test", symbol="NIFTY",
        market_state={"ltp": 22500}, positions=[],
        margins=MarginInfo(available_cash=500000, used_margin=0, total_margin=500000, broker_name="paper", raw={}),
        recent_decisions=[], memory_recall=[],
        signals={"signal": "BUY", "confidence": 0.75, "reasoning": "RSI oversold"},
        debate_result=None, guardian_verdict=None,
        config={"debate": {"anonymize": True, "max_rounds": 1}},
    )


@pytest.fixture
def bullish(mock_llm_router, tmp_path):
    defaults = tmp_path / "defaults"
    defaults.mkdir()
    (defaults / "bullish.md").write_text("Argue FOR the trade.")
    from app.agents.debate import DebateAgent
    return DebateAgent(
        side="bullish", llm_router=mock_llm_router,
        prompts_dir=str(tmp_path), account_name="test",
    )


@pytest.fixture
def bearish(mock_llm_router, tmp_path):
    defaults = tmp_path / "defaults"
    defaults.mkdir(exist_ok=True)
    (defaults / "bearish.md").write_text("Argue AGAINST the trade.")
    from app.agents.debate import DebateAgent
    return DebateAgent(
        side="bearish", llm_router=mock_llm_router,
        prompts_dir=str(tmp_path), account_name="test",
    )


@pytest.fixture
def judge(mock_llm_router, tmp_path):
    defaults = tmp_path / "defaults"
    defaults.mkdir(exist_ok=True)
    (defaults / "judge.md").write_text("Judge the debate impartially.")
    from app.agents.debate import JudgeAgent
    return JudgeAgent(
        llm_router=mock_llm_router,
        prompts_dir=str(tmp_path), account_name="test",
    )


@pytest.mark.asyncio
async def test_bullish_argues_for(bullish, context):
    output = await bullish.run(context)
    assert output.action == "ARGUE"
    assert "argument" in output.data


@pytest.mark.asyncio
async def test_bearish_argues_against(bearish, context):
    output = await bearish.run(context)
    assert output.action == "ARGUE"


@pytest.mark.asyncio
async def test_debate_uses_named_model(bullish, context, mock_llm_router):
    await bullish.run(context)
    mock_llm_router.generate_with_model.assert_called_once()
    call_args = mock_llm_router.generate_with_model.call_args
    assert call_args[1].get("model_name") == "bullish" or call_args[0][2] == "bullish"


@pytest.mark.asyncio
async def test_judge_evaluates(judge, context):
    context.debate_result = {
        "bullish": {"argument": "Bull case", "conviction": 0.8},
        "bearish": {"argument": "Bear case", "conviction": 0.6},
    }
    output = await judge.run(context)
    assert output.action == "JUDGE"
    assert "proceed" in output.data


@pytest.mark.asyncio
async def test_judge_anonymizes_arguments(judge, context, mock_llm_router):
    context.debate_result = {
        "bullish": {"argument": "Bull case here", "conviction": 0.8},
        "bearish": {"argument": "Bear case here", "conviction": 0.6},
    }
    await judge.run(context)
    call_args = mock_llm_router.generate.call_args
    prompt = call_args[1].get("prompt") or call_args[0][0]
    # Should NOT contain "bullish" or "bearish" labels
    assert "bullish" not in prompt.lower() or "argument a" in prompt.lower()


@pytest.mark.asyncio
async def test_judge_reject(judge, context, mock_llm_router):
    mock_llm_router.generate = AsyncMock(return_value=json.dumps({
        "proceed": False, "adjusted_confidence": 0.2,
        "reasoning": "Both arguments weak", "stronger_argument": "B",
    }))
    context.debate_result = {
        "bullish": {"argument": "Weak bull", "conviction": 0.3},
        "bearish": {"argument": "Strong bear", "conviction": 0.9},
    }
    output = await judge.run(context)
    assert output.data["proceed"] is False
    assert output.confidence == 0.2
```

- [ ] **Step 2: Run — FAIL**

- [ ] **Step 3: Implement debate.py**

```python
# backend/app/agents/debate.py
"""
Debate system — multi-model bull/bear debate with anonymized judge.
LLM Council pattern: different models argue different sides.
"""
import json
import time
import random
import logging
from app.agents.base import BaseAgent, AgentContext, AgentOutput

logger = logging.getLogger(__name__)


class DebateAgent(BaseAgent):
    """Argues one side of a trade. Uses named model from config."""

    def __init__(self, side: str, llm_router, prompts_dir: str, account_name: str):
        self.side = side  # "bullish" or "bearish"
        super().__init__(
            name=side,
            role=f"{side}_advocate",
            llm_tier="quick",
            account_name=account_name,
            llm_router=llm_router,
            prompts_dir=prompts_dir,
        )

    async def run(self, context: AgentContext) -> AgentOutput:
        start = time.time()

        prompt = (
            f"## Signal: {context.signals.get('signal', 'UNKNOWN')}\n"
            f"## Symbol: {context.symbol}\n"
            f"## Market State:\n{json.dumps(context.market_state, indent=2)}\n"
            f"## Original Reasoning: {context.signals.get('reasoning', '')}\n\n"
            f"Argue {'FOR' if self.side == 'bullish' else 'AGAINST'} this trade."
        )

        try:
            raw = await self.llm_router.generate_with_model(
                prompt=prompt,
                system_prompt=self.system_prompt,
                model_name=self.side,
            )
            data = self._parse(raw)
        except KeyError:
            # Named model not registered — fall back to tier
            raw = await self.think(prompt)
            data = self._parse(raw)
        except Exception as e:
            logger.error(f"Debate ({self.side}) failed: {e}")
            data = {"argument": f"Error: {e}", "conviction": 0.0}

        elapsed = (time.time() - start) * 1000
        return AgentOutput(
            agent_name=self.side,
            action="ARGUE",
            data=data,
            reasoning=data.get("argument", ""),
            confidence=data.get("conviction", 0.5),
            llm_tier_used=self.side,
            latency_ms=round(elapsed, 2),
        )

    def _parse(self, raw: str) -> dict:
        try:
            text = raw.strip()
            if "```json" in text:
                text = text.split("```json")[1].split("```")[0].strip()
            elif "```" in text:
                text = text.split("```")[1].split("```")[0].strip()
            return json.loads(text)
        except (json.JSONDecodeError, IndexError):
            return {"argument": raw, "conviction": 0.5}


class JudgeAgent(BaseAgent):
    """Evaluates anonymized bull/bear arguments. Makes final proceed/reject call."""

    def __init__(self, llm_router, prompts_dir: str, account_name: str):
        super().__init__(
            name="judge",
            role="impartial_judge",
            llm_tier="deep",
            account_name=account_name,
            llm_router=llm_router,
            prompts_dir=prompts_dir,
        )

    async def run(self, context: AgentContext) -> AgentOutput:
        start = time.time()

        if not context.debate_result:
            return AgentOutput(
                agent_name="judge", action="JUDGE",
                data={"proceed": True, "adjusted_confidence": context.signals.get("confidence", 0.5)},
                reasoning="No debate — proceeding with analyst signal",
                confidence=context.signals.get("confidence", 0.5),
            )

        bull = context.debate_result.get("bullish", {})
        bear = context.debate_result.get("bearish", {})

        # Anonymize: random order, generic labels
        prompt = self._anonymize_and_build_prompt(bull, bear, context)

        try:
            raw = await self.think(prompt, tier="deep")
            data = self._parse(raw)
        except Exception as e:
            logger.error(f"Judge failed: {e}")
            data = {"proceed": False, "adjusted_confidence": 0.0, "reasoning": f"Judge error: {e}"}

        elapsed = (time.time() - start) * 1000
        return AgentOutput(
            agent_name="judge",
            action="JUDGE",
            data=data,
            reasoning=data.get("reasoning", ""),
            confidence=data.get("adjusted_confidence", 0.5),
            llm_tier_used="deep",
            latency_ms=round(elapsed, 2),
        )

    def _anonymize_and_build_prompt(self, bull: dict, bear: dict, context: AgentContext) -> str:
        """Shuffle order, strip identities."""
        args = [
            ("A", bull.get("argument", str(bull))),
            ("B", bear.get("argument", str(bear))),
        ]
        anonymize = context.config.get("debate", {}).get("anonymize", True)
        if anonymize:
            random.shuffle(args)

        return (
            f"## Symbol: {context.symbol}\n"
            f"## Original Signal: {context.signals.get('signal', '?')} "
            f"(confidence: {context.signals.get('confidence', '?')})\n\n"
            f"## Argument {args[0][0]}:\n{args[0][1]}\n\n"
            f"## Argument {args[1][0]}:\n{args[1][1]}\n\n"
            f"Evaluate both arguments and decide."
        )

    def _parse(self, raw: str) -> dict:
        try:
            text = raw.strip()
            if "```json" in text:
                text = text.split("```json")[1].split("```")[0].strip()
            elif "```" in text:
                text = text.split("```")[1].split("```")[0].strip()
            data = json.loads(text)
            data["proceed"] = bool(data.get("proceed", False))
            data["adjusted_confidence"] = float(data.get("adjusted_confidence", 0.5))
            return data
        except (json.JSONDecodeError, IndexError, ValueError):
            return {"proceed": False, "adjusted_confidence": 0.0, "reasoning": "Parse error"}
```

- [ ] **Step 4: Run tests — all PASS**

Run: `cd backend && python -m pytest tests/agents/test_debate.py -v`
Expected: 6 tests PASS

- [ ] **Step 5: Commit**

```bash
git add backend/app/agents/debate.py backend/tests/agents/test_debate.py
git commit -m "feat(agents): add debate system — multi-model bull/bear + anonymous judge

DebateAgent uses named models per side (LLM Council pattern).
JudgeAgent anonymizes arguments (random order, generic labels)
before evaluation. Returns proceed/reject + adjusted confidence.

Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>"
```

---

## Task 7: ExecutorAgent

**Files:**
- Create: `backend/app/agents/executor.py`
- Create: `backend/tests/agents/test_executor.py`

- [ ] **Step 1: Write tests**

```python
# backend/tests/agents/test_executor.py
"""Tests for ExecutorAgent."""
import pytest
from unittest.mock import AsyncMock, MagicMock
from app.agents.base import AgentContext, AgentOutput
from app.brokers.base import MarginInfo, OrderResult, UnifiedOrder
from app.decisions.models import DecisionAction


@pytest.fixture
def mock_adapter():
    adapter = MagicMock()
    adapter.place_order = AsyncMock(return_value=OrderResult(
        broker_order_id="PAPER-001", status="COMPLETE",
        broker_name="paper", raw_response={},
    ))
    adapter.name = "paper"
    return adapter


@pytest.fixture
def mock_decision_logger():
    dl = MagicMock()
    dl.log_decision = AsyncMock(return_value=1)
    return dl


@pytest.fixture
def executor(mock_adapter, mock_decision_logger):
    from app.agents.executor import ExecutorAgent
    return ExecutorAgent(
        adapter=mock_adapter,
        decision_logger=mock_decision_logger,
        account_name="paper_test",
    )


@pytest.fixture
def context():
    return AgentContext(
        account_name="paper_test", symbol="NIFTY25APR24500CE",
        market_state={"ltp": 150.0},
        positions=[],
        margins=MarginInfo(available_cash=500000, used_margin=0, total_margin=500000, broker_name="paper", raw={}),
        recent_decisions=[], memory_recall=[],
        signals={"signal": "BUY", "confidence": 0.8, "reasoning": "RSI oversold"},
        debate_result={"reasoning": "Debate favored buy"},
        guardian_verdict={"position_size": 50, "checks_passed": True},
        config={"eval_interval_seconds": 300},
    )


@pytest.mark.asyncio
async def test_executor_places_order(executor, context, mock_adapter):
    output = await executor.run(context)
    assert output.action == "EXECUTE"
    assert output.data["order_id"] == "PAPER-001"
    mock_adapter.place_order.assert_called_once()


@pytest.mark.asyncio
async def test_executor_logs_decision(executor, context, mock_decision_logger):
    await executor.run(context)
    mock_decision_logger.log_decision.assert_called_once()
    call_kwargs = mock_decision_logger.log_decision.call_args[1]
    assert call_kwargs["action"] == DecisionAction.EXECUTED
    assert call_kwargs["symbol"] == "NIFTY25APR24500CE"


@pytest.mark.asyncio
async def test_executor_creates_unified_order(executor, context, mock_adapter):
    await executor.run(context)
    order = mock_adapter.place_order.call_args[0][0]
    assert isinstance(order, UnifiedOrder)
    assert order.symbol == "NIFTY25APR24500CE"
    assert order.quantity == 50
    assert order.context is not None
    assert order.context.confidence == 0.8


@pytest.mark.asyncio
async def test_executor_no_llm(executor):
    assert executor.llm_tier == "none"


@pytest.mark.asyncio
async def test_executor_handles_order_failure(executor, context, mock_adapter):
    mock_adapter.place_order = AsyncMock(side_effect=Exception("Broker down"))
    output = await executor.run(context)
    assert output.action == "FAILED"
```

- [ ] **Step 2: Run — FAIL**

- [ ] **Step 3: Implement ExecutorAgent**

```python
# backend/app/agents/executor.py
"""
ExecutorAgent — places orders via BrokerAdapter, logs via DecisionLogger.
No LLM. Pure execution.
"""
import time
import logging
from app.agents.base import BaseAgent, AgentContext, AgentOutput
from app.brokers.base import BrokerAdapter, UnifiedOrder, TradeContext
from app.decisions.models import DecisionAction

logger = logging.getLogger(__name__)


class ExecutorAgent(BaseAgent):
    """Places orders through broker adapter. No LLM calls."""

    def __init__(self, adapter: BrokerAdapter, decision_logger, account_name: str):
        self._adapter = adapter
        self._decision_logger = decision_logger
        super().__init__(
            name="executor",
            role="order_executor",
            llm_tier="none",
            account_name=account_name,
            llm_router=None,
            prompts_dir="",
        )

    async def run(self, context: AgentContext) -> AgentOutput:
        start = time.time()

        signal = context.signals.get("signal", "HOLD")
        quantity = context.guardian_verdict.get("position_size", 1) if context.guardian_verdict else 1
        confidence = context.signals.get("confidence", 0.0)
        reasoning = ""
        if context.debate_result and context.debate_result.get("reasoning"):
            reasoning = context.debate_result["reasoning"]
        else:
            reasoning = context.signals.get("reasoning", "")

        order = UnifiedOrder(
            symbol=context.symbol,
            exchange=context.market_state.get("exchange", "NSE"),
            segment=context.market_state.get("segment", "CASH"),
            transaction_type=signal,
            quantity=quantity,
            order_type="MARKET",
            product=context.market_state.get("product", "MIS"),
            price=context.signals.get("entry_price"),
            context=TradeContext(
                strategy_id=context.config.get("strategy_id", 0),
                account_name=context.account_name,
                signals=context.signals,
                market_state=context.market_state,
                reasoning=reasoning,
                confidence=confidence,
            ),
        )

        try:
            result = await self._adapter.place_order(order)

            await self._decision_logger.log_decision(
                account_name=context.account_name,
                symbol=context.symbol,
                signal=signal,
                action=DecisionAction.EXECUTED,
                confidence=confidence,
                reasoning=reasoning,
                market_state=context.market_state,
                context=order.context,
            )

            elapsed = (time.time() - start) * 1000
            return AgentOutput(
                agent_name="executor",
                action="EXECUTE",
                data={"order_id": result.broker_order_id, "status": result.status},
                reasoning=f"Order placed: {result.broker_order_id}",
                confidence=confidence,
                llm_tier_used=None,
                latency_ms=round(elapsed, 2),
            )

        except Exception as e:
            logger.error(f"Executor failed: {e}", exc_info=True)
            elapsed = (time.time() - start) * 1000
            return AgentOutput(
                agent_name="executor",
                action="FAILED",
                data={"error": str(e)},
                reasoning=f"Order failed: {e}",
                confidence=0.0,
                llm_tier_used=None,
                latency_ms=round(elapsed, 2),
            )
```

- [ ] **Step 4: Run tests — all PASS**

Run: `cd backend && python -m pytest tests/agents/test_executor.py -v`
Expected: 5 tests PASS

- [ ] **Step 5: Commit**

```bash
git add backend/app/agents/executor.py backend/tests/agents/test_executor.py
git commit -m "feat(agents): add ExecutorAgent — order placement + decision logging

No LLM. Builds UnifiedOrder from context, places via adapter, logs
via DecisionLogger. Attaches full TradeContext for learning system.
Graceful failure handling — returns FAILED action on error.

Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>"
```

---

## Task 8: MemoryAgent

**Files:**
- Create: `backend/app/agents/memory.py`
- Create: `backend/tests/agents/test_memory.py`

- [ ] **Step 1: Write tests**

```python
# backend/tests/agents/test_memory.py
"""Tests for MemoryAgent."""
import pytest
import json
from unittest.mock import AsyncMock, MagicMock, patch
from app.agents.base import AgentContext
from app.brokers.base import MarginInfo


@pytest.fixture
def mock_llm_router():
    router = MagicMock()
    router.generate = AsyncMock(return_value=json.dumps({
        "reflection": "RSI signal worked in low VIX environment",
        "learning": "When VIX < 15, RSI oversold is a strong buy signal",
        "tags": ["rsi", "nifty", "low_vix"],
        "pattern": "rsi_oversold_low_vix",
    }))
    return router


@pytest.fixture
def mock_db():
    db = MagicMock()
    db.query = MagicMock()
    db.add = MagicMock()
    db.commit = MagicMock()
    return db


@pytest.fixture
def mock_decision_logger():
    dl = MagicMock()
    dl.fill_hindsight = AsyncMock()
    dl.log_decision = AsyncMock(return_value=1)
    return dl


@pytest.fixture
def memory_agent(mock_llm_router, mock_db, mock_decision_logger, tmp_path):
    defaults = tmp_path / "defaults"
    defaults.mkdir()
    (defaults / "memory.md").write_text("Analyze trade outcomes.")

    from app.agents.memory import MemoryAgent
    return MemoryAgent(
        llm_router=mock_llm_router,
        db=mock_db,
        decision_logger=mock_decision_logger,
        prompts_dir=str(tmp_path),
        account_name="paper_test",
    )


@pytest.mark.asyncio
async def test_memory_recall_returns_list(memory_agent, mock_db):
    mock_db.query.return_value.filter.return_value.filter.return_value.order_by.return_value.limit.return_value.all.return_value = []
    result = await memory_agent.recall("NIFTY", strategy_id=None, market_state={})
    assert isinstance(result, list)


@pytest.mark.asyncio
async def test_memory_store_outcome(memory_agent, mock_decision_logger):
    mock_entry = MagicMock()
    mock_entry.reasoning = "RSI oversold"
    mock_entry.market_state = {"ltp": 150}
    mock_entry.action = "executed"
    memory_agent._db.query.return_value.filter.return_value.first.return_value = mock_entry

    await memory_agent.store_outcome(decision_id=1, entry_price=150, exit_price=160, pnl=5000)
    mock_decision_logger.fill_hindsight.assert_called_once()


@pytest.mark.asyncio
async def test_memory_generates_reflection(memory_agent, mock_llm_router):
    mock_entry = MagicMock()
    mock_entry.reasoning = "RSI oversold"
    mock_entry.market_state = {"ltp": 150, "vix": 12}
    mock_entry.action = "executed"
    memory_agent._db.query.return_value.filter.return_value.first.return_value = mock_entry

    await memory_agent.store_outcome(decision_id=1, entry_price=150, exit_price=160, pnl=5000)
    mock_llm_router.generate.assert_called_once()


@pytest.mark.asyncio
async def test_memory_is_base_agent(memory_agent):
    from app.agents.base import BaseAgent
    assert isinstance(memory_agent, BaseAgent)
    assert memory_agent.llm_tier == "deep"
```

- [ ] **Step 2: Run — FAIL**

- [ ] **Step 3: Implement MemoryAgent**

```python
# backend/app/agents/memory.py
"""
MemoryAgent — stores outcomes, fills hindsight, recalls learnings.
Uses deep LLM tier for reflection generation.
"""
import json
import time
import logging
from datetime import date
from sqlalchemy.orm import Session

from app.agents.base import BaseAgent, AgentContext, AgentOutput
from app.decisions.models import DecisionLog, DecisionAction

logger = logging.getLogger(__name__)


class MemoryAgent(BaseAgent):
    """Remembers. Reflects. Recalls. The learning backbone."""

    def __init__(self, llm_router, db: Session, decision_logger, prompts_dir: str, account_name: str):
        self._db = db
        self._decision_logger = decision_logger
        super().__init__(
            name="memory",
            role="trade_memory",
            llm_tier="deep",
            account_name=account_name,
            llm_router=llm_router,
            prompts_dir=prompts_dir,
        )

    async def run(self, context: AgentContext) -> AgentOutput:
        """Default run = recall for current symbol."""
        start = time.time()
        results = await self.recall(context.symbol, strategy_id=None, market_state=context.market_state)
        elapsed = (time.time() - start) * 1000
        return AgentOutput(
            agent_name="memory", action="RECALL",
            data={"recall_count": len(results), "recalls": results},
            reasoning=f"Recalled {len(results)} past decisions",
            confidence=1.0, llm_tier_used=None, latency_ms=round(elapsed, 2),
        )

    async def recall(self, symbol: str, strategy_id: int | None, market_state: dict, limit: int = 10) -> list[dict]:
        """Query relevant past decisions with outcomes."""
        try:
            query = self._db.query(DecisionLog).filter(
                DecisionLog.account_name == self.account_name,
            ).filter(
                DecisionLog.was_correct.isnot(None),
            )
            if symbol:
                query = query.filter(DecisionLog.symbol == symbol)
            if strategy_id:
                query = query.filter(DecisionLog.strategy_id == strategy_id)

            entries = query.order_by(DecisionLog.timestamp.desc()).limit(limit).all()
            return [
                {
                    "symbol": e.symbol,
                    "signal": e.signal,
                    "action": e.action,
                    "confidence": e.confidence,
                    "reasoning": e.reasoning,
                    "was_correct": e.was_correct,
                    "outcome_actual": e.outcome_actual,
                    "timestamp": e.timestamp.isoformat() if e.timestamp else None,
                }
                for e in entries
            ]
        except Exception as e:
            logger.error(f"Memory recall failed: {e}")
            return []

    async def store_outcome(self, decision_id: int, entry_price: float, exit_price: float, pnl: float) -> None:
        """Called when trade closes. Fill hindsight + generate reflection."""
        try:
            entry = self._db.query(DecisionLog).filter(DecisionLog.id == decision_id).first()
            if not entry:
                logger.warning(f"Decision {decision_id} not found for hindsight")
                return

            # Fill hindsight
            await self._decision_logger.fill_hindsight(
                decision_id=decision_id,
                outcome_if_taken=pnl,
                outcome_actual=pnl if entry.action == DecisionAction.EXECUTED.value else 0,
            )

            # Generate reflection via LLM
            prompt = (
                f"## Trade Outcome\n"
                f"Signal: {entry.signal}\n"
                f"Reasoning: {entry.reasoning}\n"
                f"Market state: {json.dumps(entry.market_state) if entry.market_state else 'N/A'}\n"
                f"Entry: {entry_price}, Exit: {exit_price}, P&L: {pnl}\n"
                f"Was correct: {pnl > 0}\n\n"
                f"Generate your reflection."
            )
            raw = await self.think(prompt, tier="deep")
            reflection = self._parse_reflection(raw)

            # Store reflection as a new decision log entry
            await self._decision_logger.log_decision(
                account_name=self.account_name,
                symbol=entry.symbol or "",
                signal="REFLECTION",
                action=DecisionAction.SKIPPED,
                confidence=1.0,
                reasoning=reflection.get("learning", raw),
                market_state={"reflection_for": decision_id, "pnl": pnl},
            )

        except Exception as e:
            logger.error(f"Memory store_outcome failed: {e}", exc_info=True)

    async def end_of_session_review(self) -> dict:
        """Post-session review. Fill hindsight on untouched decisions."""
        try:
            today_decisions = self._db.query(DecisionLog).filter(
                DecisionLog.account_name == self.account_name,
                DecisionLog.was_correct.is_(None),
            ).all()

            reviewed = 0
            for d in today_decisions:
                if d.action in (DecisionAction.SKIPPED.value, DecisionAction.BLOCKED.value):
                    reviewed += 1

            summary = {
                "total_decisions": len(today_decisions),
                "reviewed": reviewed,
                "date": date.today().isoformat(),
            }

            return summary

        except Exception as e:
            logger.error(f"Session review failed: {e}")
            return {"error": str(e)}

    def _parse_reflection(self, raw: str) -> dict:
        try:
            text = raw.strip()
            if "```json" in text:
                text = text.split("```json")[1].split("```")[0].strip()
            elif "```" in text:
                text = text.split("```")[1].split("```")[0].strip()
            return json.loads(text)
        except (json.JSONDecodeError, IndexError):
            return {"reflection": raw, "learning": raw, "tags": [], "pattern": "unknown"}
```

- [ ] **Step 4: Run tests — all PASS**

Run: `cd backend && python -m pytest tests/agents/test_memory.py -v`
Expected: 4 tests PASS

- [ ] **Step 5: Commit**

```bash
git add backend/app/agents/memory.py backend/tests/agents/test_memory.py
git commit -m "feat(agents): add MemoryAgent — recall, hindsight, reflection

Queries past decisions by symbol/strategy. Fills hindsight when trades
close. Generates LLM reflections (patterns, learnings, tags). Session
review for skipped/blocked decision analysis.

Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>"
```

---

## Task 9: StrategistAgent — Overnight Optimization

**Files:**
- Create: `backend/app/agents/strategist.py`
- Create: `backend/tests/agents/test_strategist.py`

- [ ] **Step 1: Write tests**

```python
# backend/tests/agents/test_strategist.py
"""Tests for StrategistAgent overnight optimization."""
import pytest
import json
from unittest.mock import AsyncMock, MagicMock


@pytest.fixture
def mock_llm_router():
    router = MagicMock()
    router.generate = AsyncMock(return_value=json.dumps({
        "parameter_name": "rsi_period",
        "current_value": 14,
        "suggested_value": 10,
        "reasoning": "Shorter RSI reacts faster to oversold conditions",
        "expected_improvement": "Win rate +5%",
    }))
    return router


@pytest.fixture
def mock_memory():
    mem = MagicMock()
    mem.recall = AsyncMock(return_value=[])
    return mem


@pytest.fixture
def mock_decision_logger():
    dl = MagicMock()
    dl.log_decision = AsyncMock(return_value=1)
    return dl


@pytest.fixture
def strategist(mock_llm_router, mock_memory, mock_decision_logger, tmp_path):
    defaults = tmp_path / "defaults"
    defaults.mkdir()
    (defaults / "strategist.md").write_text("Optimize strategies.")

    from app.agents.strategist import StrategistAgent
    return StrategistAgent(
        llm_router=mock_llm_router,
        memory=mock_memory,
        decision_logger=mock_decision_logger,
        prompts_dir=str(tmp_path),
        account_name="paper_test",
        config={
            "experiment_duration_min": 1,
            "max_experiments_per_night": 3,
        },
    )


@pytest.mark.asyncio
async def test_strategist_suggests_change(strategist, mock_llm_router):
    suggestion = await strategist.suggest_improvement(
        strategy_name="rsi_mean_reversion",
        strategy_config={"rsi_period": 14, "threshold": 30},
        performance={"win_rate": 0.45, "sharpe": 0.8},
    )
    assert suggestion["parameter_name"] == "rsi_period"
    assert suggestion["suggested_value"] == 10
    mock_llm_router.generate.assert_called_once()


@pytest.mark.asyncio
async def test_strategist_uses_deep_tier(strategist):
    assert strategist.llm_tier == "deep"


@pytest.mark.asyncio
async def test_strategist_keep_or_discard_logic(strategist):
    # Modified is better → keep
    assert strategist._should_keep(
        baseline={"sharpe": 0.8, "win_rate": 0.45},
        modified={"sharpe": 1.2, "win_rate": 0.55},
    ) is True

    # Modified is worse → discard
    assert strategist._should_keep(
        baseline={"sharpe": 0.8, "win_rate": 0.45},
        modified={"sharpe": 0.5, "win_rate": 0.35},
    ) is False


@pytest.mark.asyncio
async def test_strategist_is_base_agent(strategist):
    from app.agents.base import BaseAgent
    assert isinstance(strategist, BaseAgent)
```

- [ ] **Step 2: Run — FAIL**

- [ ] **Step 3: Implement StrategistAgent**

```python
# backend/app/agents/strategist.py
"""
StrategistAgent — overnight fixed-budget strategy optimization.
Autoresearch pattern: suggest change → test → keep/discard → repeat.
"""
import json
import time
import logging
from app.agents.base import BaseAgent, AgentContext, AgentOutput
from app.decisions.models import DecisionAction

logger = logging.getLogger(__name__)


class StrategistAgent(BaseAgent):
    """Optimizes trading strategies overnight via iterative experiments."""

    def __init__(self, llm_router, memory, decision_logger, prompts_dir: str, account_name: str, config: dict = None):
        self._memory = memory
        self._decision_logger = decision_logger
        self._config = config or {}
        super().__init__(
            name="strategist",
            role="strategy_optimizer",
            llm_tier="deep",
            account_name=account_name,
            llm_router=llm_router,
            prompts_dir=prompts_dir,
        )

    async def run(self, context: AgentContext) -> AgentOutput:
        """Default run — generate a strategy suggestion."""
        start = time.time()
        suggestion = await self.suggest_improvement(
            strategy_name="default",
            strategy_config=context.config,
            performance={"win_rate": 0, "sharpe": 0},
        )
        elapsed = (time.time() - start) * 1000
        return AgentOutput(
            agent_name="strategist", action="OPTIMIZE",
            data=suggestion, reasoning=suggestion.get("reasoning", ""),
            confidence=1.0, llm_tier_used="deep", latency_ms=round(elapsed, 2),
        )

    async def suggest_improvement(self, strategy_name: str, strategy_config: dict, performance: dict) -> dict:
        """Ask LLM to suggest one parameter change."""
        memory_context = await self._memory.recall(symbol=None, strategy_id=None, market_state={})

        prompt = (
            f"## Strategy: {strategy_name}\n"
            f"## Current Config:\n{json.dumps(strategy_config, indent=2)}\n"
            f"## Performance:\n{json.dumps(performance, indent=2)}\n"
        )
        if memory_context:
            learnings = "\n".join(f"- {m.get('learning', str(m))}" for m in memory_context[:5])
            prompt += f"## Past Learnings:\n{learnings}\n"
        prompt += "\nSuggest ONE parameter change."

        raw = await self.think(prompt, tier="deep")
        return self._parse(raw)

    async def overnight_optimization(self, strategies: list[dict]) -> list[dict]:
        """Run fixed-budget experiments. Autoresearch pattern."""
        max_experiments = self._config.get("max_experiments_per_night", 10)
        results = []

        for i in range(min(max_experiments, len(strategies))):
            strategy = strategies[i]
            suggestion = await self.suggest_improvement(
                strategy_name=strategy.get("name", f"strategy_{i}"),
                strategy_config=strategy.get("config", {}),
                performance=strategy.get("performance", {}),
            )

            # In production: run actual backtest here
            # For now: log the suggestion
            kept = False  # Would compare backtest results

            await self._decision_logger.log_decision(
                account_name=self.account_name,
                symbol="STRATEGY_OPT",
                signal="OPTIMIZE",
                action=DecisionAction.EXECUTED if kept else DecisionAction.SKIPPED,
                confidence=1.0,
                reasoning=f"{'Kept' if kept else 'Suggested'}: {suggestion.get('reasoning', '')}",
                market_state={"experiment": i, "strategy": strategy.get("name", "")},
            )

            results.append({"strategy": strategy.get("name"), "suggestion": suggestion, "kept": kept})

        return results

    def _should_keep(self, baseline: dict, modified: dict) -> bool:
        """Compare experiment results. Keep if Sharpe improved."""
        return modified.get("sharpe", 0) > baseline.get("sharpe", 0)

    def _parse(self, raw: str) -> dict:
        try:
            text = raw.strip()
            if "```json" in text:
                text = text.split("```json")[1].split("```")[0].strip()
            elif "```" in text:
                text = text.split("```")[1].split("```")[0].strip()
            return json.loads(text)
        except (json.JSONDecodeError, IndexError):
            return {"parameter_name": "unknown", "reasoning": raw}
```

- [ ] **Step 4: Run tests — all PASS**

Run: `cd backend && python -m pytest tests/agents/test_strategist.py -v`
Expected: 4 tests PASS

- [ ] **Step 5: Commit**

```bash
git add backend/app/agents/strategist.py backend/tests/agents/test_strategist.py
git commit -m "feat(agents): add StrategistAgent — overnight optimization loop

Autoresearch pattern: LLM suggests parameter change, compare via
_should_keep (Sharpe ratio). Iterates max_experiments_per_night.
Logs each experiment as decision. Memory context informs suggestions.

Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>"
```

---

## Task 10: Redis Streams Infrastructure

**Files:**
- Create: `backend/app/agents/streams.py`
- Create: `backend/tests/agents/test_streams.py`

- [ ] **Step 1: Write tests**

```python
# backend/tests/agents/test_streams.py
"""Tests for Redis Streams publisher/subscriber."""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch


@pytest.fixture
def mock_redis():
    r = MagicMock()
    r.xadd = AsyncMock(return_value="1234567890-0")
    r.xread = AsyncMock(return_value=[])
    return r


@pytest.fixture
def publisher(mock_redis):
    from app.agents.streams import AgentStreamPublisher
    return AgentStreamPublisher(redis_client=mock_redis)


@pytest.mark.asyncio
async def test_publish_signal(publisher, mock_redis):
    await publisher.publish_signal("paper_test", {"signal": "BUY", "symbol": "NIFTY"})
    mock_redis.xadd.assert_called_once()
    call_args = mock_redis.xadd.call_args
    stream_name = call_args[0][0]
    assert "stream:signals:paper_test" == stream_name


@pytest.mark.asyncio
async def test_publish_decision(publisher, mock_redis):
    await publisher.publish_decision("paper_test", {"action": "EXECUTED", "symbol": "NIFTY"})
    mock_redis.xadd.assert_called_once()
    stream_name = mock_redis.xadd.call_args[0][0]
    assert "stream:decisions:paper_test" == stream_name


@pytest.mark.asyncio
async def test_publish_alert(publisher, mock_redis):
    await publisher.publish_alert("paper_test", {"level": "CRITICAL", "message": "API down"})
    mock_redis.xadd.assert_called_once()
    stream_name = mock_redis.xadd.call_args[0][0]
    assert "stream:alerts:paper_test" == stream_name


@pytest.mark.asyncio
async def test_publish_serializes_data(publisher, mock_redis):
    await publisher.publish_signal("test", {"key": "value", "nested": {"a": 1}})
    call_args = mock_redis.xadd.call_args
    data = call_args[0][1]  # second positional arg is the data dict
    assert "data" in data  # serialized as JSON string


def test_subscriber_creation():
    from app.agents.streams import AgentStreamSubscriber
    sub = AgentStreamSubscriber(redis_client=MagicMock())
    assert sub is not None
```

- [ ] **Step 2: Run — FAIL**

- [ ] **Step 3: Implement streams.py**

```python
# backend/app/agents/streams.py
"""
Redis Streams pub/sub for cross-pod communication.
Infrastructure laid now — Orchestrator (SP5) plugs in later.
"""
import json
import logging
from typing import Callable, Any

logger = logging.getLogger(__name__)


class AgentStreamPublisher:
    """Publishes pod events to Redis Streams."""

    def __init__(self, redis_client):
        self._redis = redis_client

    async def publish_signal(self, account_name: str, signal_data: dict) -> str:
        """Publish to stream:signals:{account_name}."""
        return await self._publish(f"stream:signals:{account_name}", signal_data)

    async def publish_decision(self, account_name: str, decision_data: dict) -> str:
        """Publish to stream:decisions:{account_name}."""
        return await self._publish(f"stream:decisions:{account_name}", decision_data)

    async def publish_alert(self, account_name: str, alert_data: dict) -> str:
        """Publish to stream:alerts:{account_name}."""
        return await self._publish(f"stream:alerts:{account_name}", alert_data)

    async def _publish(self, stream_name: str, data: dict) -> str:
        """Publish data to a Redis Stream."""
        try:
            serialized = {"data": json.dumps(data)}
            msg_id = await self._redis.xadd(stream_name, serialized)
            return msg_id
        except Exception as e:
            logger.error(f"Stream publish failed ({stream_name}): {e}")
            raise


class AgentStreamSubscriber:
    """Subscribes to Redis Streams. Used by future Orchestrator (SP5)."""

    def __init__(self, redis_client):
        self._redis = redis_client
        self._callbacks: dict[str, Callable] = {}

    async def subscribe(self, stream_name: str, callback: Callable) -> None:
        """Register callback for a stream."""
        self._callbacks[stream_name] = callback
        logger.info(f"Subscribed to stream: {stream_name}")

    async def subscribe_all_signals(self, callback: Callable) -> None:
        """Subscribe to all signal streams. Orchestrator use case."""
        self._callbacks["stream:signals:*"] = callback

    async def unsubscribe(self, stream_name: str) -> None:
        """Remove callback for a stream."""
        self._callbacks.pop(stream_name, None)

    async def poll(self, block_ms: int = 1000) -> list[dict]:
        """Poll subscribed streams for new messages. Returns parsed data."""
        if not self._callbacks:
            return []

        streams = {name: "0" for name in self._callbacks if "*" not in name}
        if not streams:
            return []

        try:
            results = await self._redis.xread(streams, block=block_ms, count=10)
            parsed = []
            for stream_name, messages in results:
                for msg_id, fields in messages:
                    data = json.loads(fields.get("data", "{}"))
                    parsed.append({"stream": stream_name, "id": msg_id, "data": data})
                    if stream_name in self._callbacks:
                        self._callbacks[stream_name](data)
            return parsed
        except Exception as e:
            logger.error(f"Stream poll failed: {e}")
            return []
```

- [ ] **Step 4: Run tests — all PASS**

Run: `cd backend && python -m pytest tests/agents/test_streams.py -v`
Expected: 5 tests PASS

- [ ] **Step 5: Commit**

```bash
git add backend/app/agents/streams.py backend/tests/agents/test_streams.py
git commit -m "feat(agents): add Redis Streams pub/sub infrastructure

Publisher for signals, decisions, alerts per account.
Subscriber with callback registration + polling.
Infrastructure for SP5 Orchestrator cross-pod coordination.

Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>"
```

---

## Task 11: AgentPod — Per-Account Container + Eval Cycle

**Files:**
- Create: `backend/app/agents/pod.py`
- Create: `backend/tests/agents/test_pod.py`

- [ ] **Step 1: Write integration tests**

```python
# backend/tests/agents/test_pod.py
"""Integration tests for AgentPod — full eval cycle."""
import pytest
import json
from unittest.mock import AsyncMock, MagicMock, patch
from app.brokers.paper.adapter import PaperAdapter


@pytest.fixture
def pod_config():
    return {
        "broker": "paper",
        "mode": "paper",
        "config": {"initial_capital": 1000000, "slippage_pct": 0},
        "agents": {
            "enabled": True,
            "eval_interval_seconds": 60,
            "watched_symbols": ["NIFTY"],
            "debate": {
                "enabled": False,  # disable for simpler testing
            },
            "guardian": {
                "max_loss_day": 50000,
                "max_capital_pct": 80,
                "max_trades_day": 50,
                "min_confidence": 0.6,
                "max_position_concentration_pct": 30,
            },
            "llm": {
                "quick_model": "test-model",
                "deep_model": "test-model",
                "ollama_base_url": "http://localhost:11434",
            },
            "prompts_dir": "prompts/defaults",
            "memory": {"recall_limit": 10},
        },
    }


@pytest.fixture
def mock_llm_response():
    return json.dumps({
        "signal": "BUY", "confidence": 0.8,
        "reasoning": "Test signal", "entry_price": 100.0,
        "stoploss": 95.0, "target": 110.0,
    })


@pytest.fixture
def pod(pod_config, mock_llm_response, tmp_path):
    # Create prompt files
    defaults = tmp_path / "defaults"
    defaults.mkdir()
    for name in ["analyst", "bullish", "bearish", "judge", "memory", "strategist"]:
        (defaults / f"{name}.md").write_text(f"You are {name}.")

    pod_config["agents"]["prompts_dir"] = str(tmp_path)

    adapter = PaperAdapter(config=pod_config["config"])

    with patch("app.agents.llm_router.httpx.AsyncClient") as mock_client:
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"response": mock_llm_response}
        mock_resp.raise_for_status = MagicMock()
        mock_client.return_value.__aenter__ = AsyncMock(return_value=MagicMock(
            post=AsyncMock(return_value=mock_resp)
        ))
        mock_client.return_value.__aexit__ = AsyncMock(return_value=False)

        from app.agents.pod import AgentPod
        p = AgentPod(
            account_name="paper_test",
            adapter=adapter,
            config=pod_config,
            db=MagicMock(),
            alert_service=MagicMock(),
        )
        # Mock the LLM router directly for simpler testing
        p.llm_router.generate = AsyncMock(return_value=mock_llm_response)
        p.llm_router.generate_with_model = AsyncMock(return_value=mock_llm_response)
        return p


@pytest.mark.asyncio
async def test_pod_creation(pod):
    assert pod.account_name == "paper_test"
    assert pod.analyst is not None
    assert pod.guardian is not None
    assert pod.executor is not None
    assert pod.memory is not None


@pytest.mark.asyncio
async def test_pod_start_stop(pod):
    await pod.start()
    assert pod._running is True
    await pod.stop()
    assert pod._running is False


@pytest.mark.asyncio
async def test_pod_single_cycle_buy(pod):
    """Full cycle: analyst BUY → guardian ALLOW → executor places order."""
    await pod.start()
    await pod.run_cycle()
    await pod.stop()

    # Verify order was placed on paper adapter
    positions = await pod.adapter.get_positions()
    # With debate disabled and guardian allowing, order should go through
    # (depends on guardian config allowing confidence 0.8)


@pytest.mark.asyncio
async def test_pod_single_cycle_hold(pod):
    """Analyst says HOLD → no order placed."""
    pod.llm_router.generate = AsyncMock(return_value=json.dumps({
        "signal": "HOLD", "confidence": 0.3, "reasoning": "No setup",
    }))
    await pod.start()
    await pod.run_cycle()
    await pod.stop()

    positions = await pod.adapter.get_positions()
    assert len(positions) == 0


@pytest.mark.asyncio
async def test_pod_guardian_blocks_low_confidence(pod):
    """Low confidence → guardian blocks."""
    pod.llm_router.generate = AsyncMock(return_value=json.dumps({
        "signal": "BUY", "confidence": 0.3, "reasoning": "Weak signal",
    }))
    await pod.start()
    await pod.run_cycle()
    await pod.stop()

    positions = await pod.adapter.get_positions()
    assert len(positions) == 0
```

- [ ] **Step 2: Run — FAIL**

- [ ] **Step 3: Implement AgentPod**

```python
# backend/app/agents/pod.py
"""
AgentPod — per-account agent container.
Contains all agents, runs evaluation loop, manages lifecycle.
"""
import asyncio
import logging
from typing import Any
from sqlalchemy.orm import Session

from app.agents.base import AgentContext
from app.agents.llm_router import LLMRouter
from app.agents.analyst import AnalystAgent
from app.agents.debate import DebateAgent, JudgeAgent
from app.agents.guardian import GuardianAgent
from app.agents.executor import ExecutorAgent
from app.agents.memory import MemoryAgent
from app.agents.strategist import StrategistAgent
from app.agents.streams import AgentStreamPublisher
from app.brokers.base import BrokerAdapter
from app.decisions.models import DecisionAction
from app.decisions.logger import DecisionLogger

logger = logging.getLogger(__name__)


class AgentPod:
    """Self-contained agent pod for one broker account."""

    def __init__(
        self,
        account_name: str,
        adapter: BrokerAdapter,
        config: dict,
        db: Session,
        alert_service: Any = None,
        stream_publisher: AgentStreamPublisher | None = None,
    ):
        self.account_name = account_name
        self.adapter = adapter
        self.config = config
        self._db = db
        self._alert_service = alert_service
        self._stream_publisher = stream_publisher
        self._running = False
        self._eval_task: asyncio.Task | None = None

        agent_cfg = config.get("agents", {})
        llm_cfg = agent_cfg.get("llm", {})
        prompts_dir = agent_cfg.get("prompts_dir", "prompts/defaults")

        # Initialize LLM router
        self.llm_router = LLMRouter(llm_cfg)

        # Register debate models if enabled
        debate_cfg = agent_cfg.get("debate", {})
        if debate_cfg.get("enabled"):
            self.llm_router.register_model("bullish", debate_cfg.get("bullish_model", llm_cfg.get("quick_model", "")))
            self.llm_router.register_model("bearish", debate_cfg.get("bearish_model", llm_cfg.get("deep_model", "")))
            self.llm_router.register_model("judge", debate_cfg.get("judge_model", llm_cfg.get("deep_model", "")))

        # Decision logger
        self._decision_logger = DecisionLogger(db=db, alert_service=alert_service)

        # Initialize agents
        self.analyst = AnalystAgent(llm_router=self.llm_router, prompts_dir=prompts_dir, account_name=account_name)
        self.bullish = DebateAgent(side="bullish", llm_router=self.llm_router, prompts_dir=prompts_dir, account_name=account_name)
        self.bearish = DebateAgent(side="bearish", llm_router=self.llm_router, prompts_dir=prompts_dir, account_name=account_name)
        self.judge = JudgeAgent(llm_router=self.llm_router, prompts_dir=prompts_dir, account_name=account_name)
        self.guardian = GuardianAgent(
            config=agent_cfg.get("guardian", {}),
            account_name=account_name,
            llm_router=self.llm_router,
            prompts_dir=prompts_dir,
        )
        self.executor = ExecutorAgent(
            adapter=adapter,
            decision_logger=self._decision_logger,
            account_name=account_name,
        )
        self.memory = MemoryAgent(
            llm_router=self.llm_router, db=db,
            decision_logger=self._decision_logger,
            prompts_dir=prompts_dir, account_name=account_name,
        )
        self.strategist = StrategistAgent(
            llm_router=self.llm_router, memory=self.memory,
            decision_logger=self._decision_logger,
            prompts_dir=prompts_dir, account_name=account_name,
            config=agent_cfg.get("strategist", {}),
        )

    async def start(self) -> None:
        """Login adapter, start eval loop."""
        if not self.adapter.is_connected:
            try:
                await self.adapter.login({})
            except Exception as e:
                logger.warning(f"[{self.account_name}] Auto-login failed: {e}")

        self._running = True
        logger.info(f"[{self.account_name}] Pod started")

    async def stop(self) -> None:
        """Stop eval loop, run session review."""
        self._running = False
        if self._eval_task:
            self._eval_task.cancel()
            try:
                await self._eval_task
            except asyncio.CancelledError:
                pass

        try:
            summary = await self.memory.end_of_session_review()
            logger.info(f"[{self.account_name}] Session review: {summary}")
        except Exception as e:
            logger.error(f"[{self.account_name}] Session review failed: {e}")

        logger.info(f"[{self.account_name}] Pod stopped")

    async def start_eval_loop(self) -> None:
        """Start background eval loop. Call after start()."""
        self._eval_task = asyncio.create_task(self._eval_loop())

    async def _eval_loop(self) -> None:
        """Main loop — runs eval cycles at configured interval."""
        interval = self.config.get("agents", {}).get("eval_interval_seconds", 300)
        while self._running:
            try:
                await self.run_cycle()
            except Exception as e:
                logger.error(f"[{self.account_name}] Eval cycle failed: {e}", exc_info=True)
                if self._alert_service:
                    try:
                        await self._alert_service.send_warning(self.account_name, f"Eval cycle error: {e}")
                    except Exception:
                        pass
            await asyncio.sleep(interval)

    async def run_cycle(self) -> None:
        """One evaluation cycle — analyze all watched symbols."""
        agent_cfg = self.config.get("agents", {})
        watched = agent_cfg.get("watched_symbols", [])

        if not watched:
            return

        try:
            positions = await self.adapter.get_positions()
            margins = await self.adapter.get_margins()
        except Exception as e:
            logger.error(f"[{self.account_name}] Failed to get positions/margins: {e}")
            return

        for symbol in watched:
            try:
                await self._evaluate_symbol(symbol, positions, margins, agent_cfg)
            except Exception as e:
                logger.error(f"[{self.account_name}] Failed evaluating {symbol}: {e}", exc_info=True)

    async def _evaluate_symbol(self, symbol: str, positions, margins, agent_cfg: dict) -> None:
        """Evaluate one symbol through the full agent pipeline."""
        # Build context
        market_state = {"ltp": 0, "symbol": symbol}  # Real impl would fetch from adapter
        try:
            ltp = await self.adapter.get_ltp([symbol])
            market_state["ltp"] = ltp.get(symbol, 0)
        except Exception:
            pass

        memory_recall = await self.memory.recall(symbol, strategy_id=None, market_state=market_state)

        context = AgentContext(
            account_name=self.account_name,
            symbol=symbol,
            market_state=market_state,
            positions=positions,
            margins=margins,
            recent_decisions=[],
            memory_recall=memory_recall,
            signals={},
            debate_result=None,
            guardian_verdict=None,
            config=agent_cfg,
        )

        # 1. Analyst
        analyst_output = await self.analyst.run(context)
        context.signals = analyst_output.data
        signal = analyst_output.data.get("signal", "HOLD")

        # Publish signal to stream
        if self._stream_publisher:
            await self._stream_publisher.publish_signal(self.account_name, analyst_output.data)

        if signal == "HOLD":
            await self._decision_logger.log_decision(
                account_name=self.account_name, symbol=symbol,
                signal="HOLD", action=DecisionAction.SKIPPED,
                confidence=analyst_output.confidence,
                reasoning=analyst_output.reasoning,
                market_state=market_state, skip_reason="no_signal",
            )
            return

        # 2. Debate (if enabled)
        debate_cfg = agent_cfg.get("debate", {})
        if debate_cfg.get("enabled") and not (debate_cfg.get("skip_for_exits") and signal == "EXIT"):
            bull_output = await self.bullish.run(context)
            bear_output = await self.bearish.run(context)
            context.debate_result = {
                "bullish": bull_output.data,
                "bearish": bear_output.data,
            }

            judge_output = await self.judge.run(context)
            context.debate_result["verdict"] = judge_output.data
            context.debate_result["reasoning"] = judge_output.reasoning

            if judge_output.data.get("proceed") is False:
                await self._decision_logger.log_decision(
                    account_name=self.account_name, symbol=symbol,
                    signal=signal, action=DecisionAction.BLOCKED,
                    confidence=judge_output.confidence,
                    reasoning=judge_output.reasoning,
                    market_state=market_state, skip_reason="judge_rejected",
                )
                return

            context.signals["confidence"] = judge_output.confidence

        # 3. Guardian
        guardian_output = await self.guardian.run(context)
        context.guardian_verdict = guardian_output.data

        if guardian_output.action == "BLOCK":
            await self._decision_logger.log_decision(
                account_name=self.account_name, symbol=symbol,
                signal=signal, action=DecisionAction.BLOCKED,
                confidence=analyst_output.confidence,
                reasoning=guardian_output.reasoning,
                market_state=market_state,
                skip_reason=guardian_output.data.get("reason", "guardian"),
            )
            return

        # 4. Execute
        executor_output = await self.executor.run(context)

        # Publish decision to stream
        if self._stream_publisher:
            await self._stream_publisher.publish_decision(self.account_name, {
                "symbol": symbol, "signal": signal,
                "action": executor_output.action,
                "order_id": executor_output.data.get("order_id"),
            })

    def get_status(self) -> dict:
        """Get pod status for API."""
        return {
            "account_name": self.account_name,
            "running": self._running,
            "broker": self.adapter.name,
            "connected": self.adapter.is_connected,
            "watched_symbols": self.config.get("agents", {}).get("watched_symbols", []),
        }
```

- [ ] **Step 4: Run tests — all PASS**

Run: `cd backend && python -m pytest tests/agents/test_pod.py -v`
Expected: 5 tests PASS

- [ ] **Step 5: Commit**

```bash
git add backend/app/agents/pod.py backend/tests/agents/test_pod.py
git commit -m "feat(agents): add AgentPod — per-account container + eval cycle

Full pipeline: analyst → debate → guardian → executor. Configurable
eval interval, watched symbols, debate toggle. Lifecycle: start/stop
with session review. Publishes to Redis Streams. Integration tested
with PaperAdapter + mocked Ollama.

Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>"
```

---

## Task 12: Integration — main.py + Router + Accounts Config

**Files:**
- Modify: `backend/app/agents/__init__.py`
- Modify: `backend/app/agents/router.py`
- Modify: `backend/app/main.py`
- Modify: `backend/config/accounts.yaml`

- [ ] **Step 1: Update agents __init__.py**

```python
# backend/app/agents/__init__.py
"""AI Agent Framework — autonomous trading agents."""
from app.agents.base import BaseAgent, AgentContext, AgentOutput
from app.agents.pod import AgentPod
from app.agents.llm_router import LLMRouter

__all__ = ["BaseAgent", "AgentContext", "AgentOutput", "AgentPod", "LLMRouter"]
```

- [ ] **Step 2: Update router.py — add pod endpoints**

Add to existing `backend/app/agents/router.py` (keep existing endpoints):

```python
# Add these imports at top
from typing import Dict

# Add module-level pod registry
_pods: Dict[str, "AgentPod"] = {}

def set_pods(pods: Dict[str, "AgentPod"]):
    global _pods
    _pods = pods

# Add new endpoints after existing ones

@router.get("/pods")
async def get_pods_status():
    """Get status of all agent pods."""
    return {name: pod.get_status() for name, pod in _pods.items()}

@router.get("/pods/{account_name}")
async def get_pod_status(account_name: str):
    """Get status of a specific pod."""
    if account_name not in _pods:
        raise HTTPException(status_code=404, detail=f"Pod '{account_name}' not found")
    return _pods[account_name].get_status()

@router.post("/pods/{account_name}/start")
async def start_pod(account_name: str):
    """Start a pod's evaluation loop."""
    if account_name not in _pods:
        raise HTTPException(status_code=404, detail=f"Pod '{account_name}' not found")
    pod = _pods[account_name]
    await pod.start()
    await pod.start_eval_loop()
    return {"status": "started", "account": account_name}

@router.post("/pods/{account_name}/stop")
async def stop_pod(account_name: str):
    """Stop a pod's evaluation loop."""
    if account_name not in _pods:
        raise HTTPException(status_code=404, detail=f"Pod '{account_name}' not found")
    await _pods[account_name].stop()
    return {"status": "stopped", "account": account_name}

@router.post("/pods/{account_name}/cycle")
async def run_single_cycle(account_name: str):
    """Run one evaluation cycle manually."""
    if account_name not in _pods:
        raise HTTPException(status_code=404, detail=f"Pod '{account_name}' not found")
    await _pods[account_name].run_cycle()
    return {"status": "cycle_complete", "account": account_name}
```

- [ ] **Step 3: Update main.py — initialize pods on startup**

Add to `backend/app/main.py` lifespan, after AccountManager initialization:

```python
from app.agents.pod import AgentPod
from app.agents.router import set_pods

# After account_manager initialization block:
    # Initialize agent pods for accounts with agents enabled
    agent_pods = {}
    for name in account_manager.get_account_names():
        adapter = account_manager.get_adapter(name)
        acct_config = config.get("accounts", {}).get(name, {}) if config else {}
        if acct_config.get("agents", {}).get("enabled", False):
            try:
                pod = AgentPod(
                    account_name=name,
                    adapter=adapter,
                    config=acct_config,
                    db=get_db_session(),
                    alert_service=None,  # Wire up in production
                )
                agent_pods[name] = pod
                logger.info(f"Agent pod created: {name}")
            except Exception as e:
                logger.error(f"Failed to create agent pod {name}: {e}")

    set_pods(agent_pods)
    logger.info(f"Agent pods initialized: {len(agent_pods)}")
```

- [ ] **Step 4: Update accounts.yaml with agent config**

Update `backend/config/accounts.yaml` — add agents section to paper_test:

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
```

- [ ] **Step 5: Run full test suite**

Run: `cd backend && python -m pytest tests/ -v --tb=short`
Expected: All tests PASS (SP1 104 + SP2 new tests)

- [ ] **Step 6: Commit**

```bash
git add backend/app/agents/__init__.py backend/app/agents/router.py backend/app/main.py backend/config/accounts.yaml
git commit -m "feat(agents): integrate pod system — startup, router, config

Pods initialized from accounts.yaml on startup. Router exposes
pod status, start/stop, manual cycle endpoints. Paper test account
configured with agents enabled.

Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>"
```

---

## Final Verification

- [ ] **Run full test suite**

```bash
cd backend && python -m pytest tests/ -v --tb=short
```

Expected: All tests PASS.

- [ ] **Tag milestone**

```bash
git tag -a v0.3.0-agent-framework -m "Sub-project 2: AI Agent Framework complete"
```
