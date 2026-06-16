# KALYX Production-Readiness Hardening Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Harden KALYX before it touches real money — protect the existing work with CI, make the LLM eval loop reliable against malformed local-model output, add live-trading safety controls (kill switch, endpoint auth, startup reconciliation), and stop the overnight strategist from curve-fitting itself into losses.

**Architecture:** Four independent areas, each shippable on its own. Area A is infra/docs (no TDD). Areas B/C/D are TDD: write the failing test, run it, implement minimally, run it green, commit. All agent code is async; tests use `pytest.mark.asyncio` and `unittest.mock.AsyncMock`, matching the existing suite. The pod pipeline already degrades gracefully (try/except per agent); these changes make the degradation *explicit and observed* rather than silent.

**Tech Stack:** Python 3.10+, FastAPI, pydantic 2.5, pytest 7.4 + pytest-asyncio 0.21 (strict mode — every async test needs `@pytest.mark.asyncio`), httpx, Ollama. Tests run from `backend/`: `python -m pytest tests/... -v`.

---

## Context the engineer needs (read before starting)

- **Repo layout:** backend at `backend/`, agents at `backend/app/agents/`, brokers at `backend/app/brokers/`, tests mirror under `backend/tests/`. Run all pytest commands **from `backend/`**.
- **No pytest config file exists.** Async tests work because every async test is decorated `@pytest.mark.asyncio`. Keep that convention.
- **`BaseAgent.think(prompt, tier)`** (`backend/app/agents/base.py`) is a *sync* method returning the coroutine from `llm_router.generate(...)`; callers `await self.think(...)`. It currently calls `generate(system_prompt=..., user_prompt=..., tier=...)` — **but `LLMRouter.generate`'s parameter is `prompt`, not `user_prompt`.** This works in unit tests only because the router is always an `AsyncMock`. Against the real router it raises `TypeError`. **Task B1 fixes this**; two existing tests (`test_analyst.py`, `test_debate.py`) assert on the `user_prompt` kwarg and are updated there.
- **LLM agents that parse JSON today:** `analyst.py`, `debate.py` (DebateAgent + JudgeAgent), `strategist.py`, `memory.py`. Each strips ```` ```json ```` fences and `json.loads`, falling back to a hardcoded safe dict on any exception. None validate field types, none retry, and a parse failure is indistinguishable from a real HOLD in the decision log.
- **Pod control endpoints** (`backend/app/agents/router.py`): `/pods/{name}/start|stop|cycle` have **no auth**. There is **no kill switch**. `AgentPod.start()` does **not** reconcile broker positions/orders against internal state.
- **Strategist** (`backend/app/agents/strategist.py`): `overnight_optimization` has `kept = False` placeholder (nothing is auto-applied yet) — Area D makes that gate principled and explicit so it stays safe when the real backtest lands.
- **Broker interface** (`backend/app/brokers/base.py`): `get_positions() -> list[Position]`, `get_orders() -> list[OrderStatus]`, `cancel_order(order_id, segment) -> str`, `place_order(UnifiedOrder) -> OrderResult`. `Position` has `.symbol .quantity .product .segment .exchange .average_price`. `OrderStatus` has `.broker_order_id .status .symbol`.

---

## File Structure

| File | Responsibility | Area |
|------|----------------|------|
| `backend/.github/` → repo-root `.github/workflows/ci.yml` | CI: install + run pytest on push/PR | A |
| `README.md`, `docs/ROADMAP.md` | Docs reflect multi-market reality + true SP statuses | A |
| `backend/app/agents/llm_router.py` | Add JSON `format` support; align signature | B |
| `backend/app/agents/base.py` | Fix `think()` call; thread `fmt` through | B |
| `backend/app/agents/schemas.py` (NEW) | Pydantic models + `parse_llm_json()` validator | B |
| `backend/app/agents/analyst.py` | Schema-validate + 1 retry + explicit parse-failure flag | B |
| `backend/app/agents/debate.py` | JudgeAgent schema-validate + retry | B |
| `backend/app/agents/strategist.py` | Suggestion schema-validate + retry; guardrails + approval gate | B, D |
| `backend/app/config.py` | `AGENT_CONTROL_API_KEY` setting | C |
| `backend/app/agents/security.py` (NEW) | `require_api_key` FastAPI dependency | C |
| `backend/app/agents/router.py` | Auth on mutating endpoints + kill-switch route | C |
| `backend/app/agents/pod.py` | `flatten_and_halt()`, startup reconciliation | C |
| Tests mirror each under `backend/tests/...` | | B/C/D |

---

# AREA A — Foundation hygiene + CI + docs

### Task A1: Commit the pending SP3 work

**Files:**
- Modify (commit only): `backend/app/intelligence/context.py`, `backend/app/intelligence/registry.py`, `backend/app/main.py`, `backend/tests/intelligence/test_context_builder.py`, `backend/tests/intelligence/test_registry.py`
- Add (commit only): `docs/AI_ENGINEERING.md`, `docs/plans/2026-04-29-agent-framework.md`, `docs/plans/2026-04-30-intelligence-layer.md`

- [ ] **Step 1: Confirm the suite is green before committing**

Run from `backend/`: `python -m pytest tests -q`
Expected: `289 passed` (warnings OK).

- [ ] **Step 2: Stage and commit the in-flight SP3 changes**

```bash
git add backend/app/intelligence/context.py backend/app/intelligence/registry.py backend/app/main.py backend/tests/intelligence/test_context_builder.py backend/tests/intelligence/test_registry.py docs/AI_ENGINEERING.md docs/plans/2026-04-29-agent-framework.md docs/plans/2026-04-30-intelligence-layer.md
git commit -m "feat(intelligence): vendor-attributed news fetch + wire ScraplingSource

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

Expected: clean commit; `git status` shows only the new plan file untracked.

---

### Task A2: Add GitHub Actions CI

**Files:**
- Create: `.github/workflows/ci.yml` (at repo root, NOT under `backend/`)

- [ ] **Step 1: Write the workflow**

```yaml
name: CI

on:
  push:
  pull_request:

jobs:
  backend-tests:
    runs-on: ubuntu-latest
    defaults:
      run:
        working-directory: backend
    steps:
      - uses: actions/checkout@v4

      - name: Set up Python
        uses: actions/setup-python@v5
        with:
          python-version: "3.11"
          cache: pip
          cache-dependency-path: backend/requirements.txt

      - name: Install dependencies
        run: pip install -r requirements.txt

      - name: Run tests
        run: python -m pytest tests -q
```

- [ ] **Step 2: Validate YAML locally**

Run from repo root: `python -c "import yaml; yaml.safe_load(open('.github/workflows/ci.yml')); print('ok')"`
Expected: `ok`

- [ ] **Step 3: Commit**

```bash
git add .github/workflows/ci.yml
git commit -m "ci: run backend pytest on push and PR

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

> **CHECKPOINT (human action, do not automate):** CI only executes once a GitHub remote exists. No remote is configured (`git remote -v` is empty). Pause here and ask the owner before creating/pushing to a remote or merging `feat/broker-abstraction` → `master`. Those are outward-facing and the owner's call.

---

### Task A3: Refresh README and ROADMAP to match reality

**Files:**
- Modify: `README.md:1-13`
- Modify: `docs/ROADMAP.md:20-54`

- [ ] **Step 1: Replace the README title + intro**

Replace lines 1-13 of `README.md`:

```markdown
# KALYX — Autonomous Multi-Market AI Trading Platform

KALYX is an autonomous, multi-broker, multi-asset trading platform. A broker-abstraction
layer (Zerodha, Groww, Paper) feeds per-account AI agent pods (analyst → debate → guardian →
executor → memory → strategist) enriched by a multi-source intelligence layer (market data,
news/sentiment, prediction-market odds, geopolitical events, cross-market correlation).
Every decision — including trades **not** taken — is logged with full reasoning for a
self-improving learning loop.

## Features

- **Multi-broker execution**: unified `BrokerAdapter` over Zerodha, Groww, and a Paper simulator
- **Per-account agent pods**: analyst, bull/bear debate + judge, math-based guardian, executor, memory, overnight strategist
- **Intelligence layer**: 6+ data sources with vendor fallback, FinBERT sentiment, composite signal-quality scoring, cross-market convergence detection
- **Decision log + hindsight**: every signal/skip/block recorded; outcomes filled post-session to drive learning
- **Two-tier local LLM**: Ollama quick/deep routing — near-zero inference cost for 24/7 loops
- **Risk management**: capital/loss/trade limits, circuit breakers, paper-mode default
```

- [ ] **Step 2: Correct the sub-project statuses in ROADMAP**

In `docs/ROADMAP.md`, change the Sub-project 2 header line (currently `**Status:** Not started | **Depends on:** Sub-project 1`) to:

```markdown
**Status:** ✅ COMPLETE | **Depends on:** Sub-project 1
```

And change the Sub-project 3 header line (currently `**Status:** Not started | **Depends on:** Sub-project 2`) to:

```markdown
**Status:** ✅ COMPLETE | **Depends on:** Sub-project 2
```

- [ ] **Step 3: Commit**

```bash
git add README.md docs/ROADMAP.md
git commit -m "docs: README reflects multi-market platform; ROADMAP marks SP2/SP3 complete

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

# AREA B — LLM output reliability

### Task B1: JSON `format` support in LLMRouter + fix the `think()` signature bug

**Files:**
- Modify: `backend/app/agents/llm_router.py:57-101` (`generate`, `generate_with_model`), `:107-133` (`_call_ollama`)
- Modify: `backend/app/agents/base.py:116-126` (`think`)
- Test: `backend/tests/agents/test_llm_router.py`, `backend/tests/agents/test_base.py`
- Update: `backend/tests/agents/test_analyst.py:144-148`, `backend/tests/agents/test_debate.py:178-180`

- [ ] **Step 1: Write failing tests for `fmt` plumbing + signature**

Append to `backend/tests/agents/test_llm_router.py`:

```python
@pytest.mark.asyncio
async def test_generate_passes_format_json(monkeypatch):
    """When fmt='json', the Ollama payload carries format='json'."""
    from app.agents.llm_router import LLMRouter

    captured = {}

    class FakeResponse:
        def raise_for_status(self): ...
        def json(self): return {"response": "{}"}

    class FakeClient:
        def __init__(self, *a, **k): ...
        async def __aenter__(self): return self
        async def __aexit__(self, *a): return False
        async def post(self, url, json):
            captured["payload"] = json
            return FakeResponse()

    monkeypatch.setattr("app.agents.llm_router.httpx.AsyncClient", FakeClient)

    router = LLMRouter({"quick_model": "q", "deep_model": "d"})
    await router.generate("hi", system_prompt="s", tier="quick", fmt="json")

    assert captured["payload"]["format"] == "json"


@pytest.mark.asyncio
async def test_generate_omits_format_by_default(monkeypatch):
    """Without fmt, no 'format' key is sent (back-compat)."""
    from app.agents.llm_router import LLMRouter

    captured = {}

    class FakeResponse:
        def raise_for_status(self): ...
        def json(self): return {"response": "{}"}

    class FakeClient:
        def __init__(self, *a, **k): ...
        async def __aenter__(self): return self
        async def __aexit__(self, *a): return False
        async def post(self, url, json):
            captured["payload"] = json
            return FakeResponse()

    monkeypatch.setattr("app.agents.llm_router.httpx.AsyncClient", FakeClient)

    router = LLMRouter({"quick_model": "q", "deep_model": "d"})
    await router.generate("hi", system_prompt="s", tier="quick")

    assert "format" not in captured["payload"]
```

Append to `backend/tests/agents/test_base.py`:

```python
@pytest.mark.asyncio
async def test_think_calls_generate_with_positional_prompt(tmp_path):
    """think() must call generate(prompt, system_prompt, tier, fmt) — not user_prompt=."""
    from unittest.mock import AsyncMock
    from app.agents.base import AgentContext, AgentOutput, BaseAgent

    class _Agent(BaseAgent):
        async def run(self, context):  # pragma: no cover - not exercised
            return AgentOutput("x", "X", {}, "", 0.0)

    router = AsyncMock()
    router.generate = AsyncMock(return_value="ok")

    defaults = tmp_path / "defaults"
    defaults.mkdir()
    (defaults / "t.md").write_text("sys")

    agent = _Agent("t", "r", "quick", "acct", router, str(tmp_path))
    result = await agent.think("hello", tier="quick")

    assert result == "ok"
    # prompt passed positionally; system_prompt is the loaded file; no user_prompt kwarg
    args, kwargs = router.generate.call_args
    assert "user_prompt" not in kwargs
    assert args[0] == "hello"
```

- [ ] **Step 2: Run to verify failure**

Run from `backend/`: `python -m pytest tests/agents/test_llm_router.py::test_generate_passes_format_json tests/agents/test_base.py::test_think_calls_generate_with_positional_prompt -v`
Expected: FAIL (`generate() got an unexpected keyword argument 'fmt'`; and `think` currently passes `user_prompt=`).

- [ ] **Step 3: Implement `fmt` in LLMRouter**

In `backend/app/agents/llm_router.py`, change `generate`, `generate_with_model`, and `_call_ollama`:

```python
    async def generate(
        self,
        prompt: str,
        system_prompt: str = "",
        tier: str = "quick",
        fmt: str | None = None,
    ) -> str:
        model = self._deep_model if tier == "deep" else self._quick_model
        return await self._call_ollama(model, prompt, system_prompt, fmt)

    async def generate_with_model(
        self,
        prompt: str,
        system_prompt: str,
        model_name: str,
        fmt: str | None = None,
    ) -> str:
        if model_name not in self._named_models:
            raise KeyError(
                f"Model name '{model_name}' is not registered. "
                f"Call register_model('{model_name}', '<ollama-model>') first."
            )
        model = self._named_models[model_name]
        return await self._call_ollama(model, prompt, system_prompt, fmt)
```

And update `_call_ollama`'s signature + payload:

```python
    async def _call_ollama(
        self,
        model: str,
        prompt: str,
        system_prompt: str,
        fmt: str | None = None,
    ) -> str:
        url = f"{self._base_url}/api/generate"
        payload: dict[str, Any] = {
            "model": model,
            "prompt": prompt,
            "system": system_prompt,
            "stream": False,
        }
        if fmt:
            payload["format"] = fmt
        # ... retry loop unchanged ...
```

- [ ] **Step 4: Fix `think()` in base.py to pass positionally + thread `fmt`**

Replace `think` in `backend/app/agents/base.py`:

```python
    def think(
        self,
        prompt: str,
        tier: Optional[str] = None,
        fmt: Optional[str] = None,
    ) -> Any:
        """Send a prompt to the LLM router and return the response coroutine.

        Passes the prompt positionally so it binds to LLMRouter.generate's
        ``prompt`` parameter. ``fmt='json'`` requests structured JSON output.
        """
        chosen_tier = tier or self.llm_tier
        return self.llm_router.generate(prompt, self.system_prompt, chosen_tier, fmt)
```

- [ ] **Step 5: Update the two tests coupled to the `user_prompt` kwarg**

In `backend/tests/agents/test_analyst.py`, replace lines 144-148 with:

```python
    mock_llm_router.generate.assert_called_once()
    args, kwargs = mock_llm_router.generate.call_args
    user_prompt = args[0] if args else kwargs.get("prompt")
    assert "RSI works below 30" in user_prompt
```

And replace lines 196-205 (the prompt-extraction block in `test_analyst_uses_intelligence_when_provided`) with:

```python
    args, kwargs = mock_llm_router.generate.call_args
    prompt = args[0] if args else kwargs.get("prompt", "")
    assert "Polymarket" in prompt
    assert "fed-rate-cut" in prompt
    assert "Aggregated polarity" in prompt
    assert "notable" in prompt
```

In `backend/tests/agents/test_debate.py`, replace lines 179-180 with:

```python
    # Extract the prompt (positional first arg or 'prompt' kwarg)
    args, kwargs = call_kwargs
    prompt_text = args[0] if args else kwargs.get("prompt")
```

> Note: `call_kwargs` in that test is the `call_args` object; `args, kwargs = call_kwargs` unpacks it. If the surrounding test binds it differently, adapt to `mock.generate.call_args`.

- [ ] **Step 6: Run the full agent suite green**

Run from `backend/`: `python -m pytest tests/agents -q`
Expected: all pass (no `user_prompt` references remain; new tests green).

- [ ] **Step 7: Commit**

```bash
git add backend/app/agents/llm_router.py backend/app/agents/base.py backend/tests/agents/test_llm_router.py backend/tests/agents/test_base.py backend/tests/agents/test_analyst.py backend/tests/agents/test_debate.py
git commit -m "fix(agents): align think()->generate signature; add Ollama JSON format support

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

### Task B2: Pydantic schemas + validating JSON parser

**Files:**
- Create: `backend/app/agents/schemas.py`
- Test: `backend/tests/agents/test_schemas.py`

- [ ] **Step 1: Write failing tests**

Create `backend/tests/agents/test_schemas.py`:

```python
"""Tests for agent output schemas + the validating JSON parser."""
import pytest

from app.agents.schemas import (
    AnalystSignal, JudgeVerdict, StrategistSuggestion, parse_llm_json,
)


def test_parse_plain_json():
    raw = '{"signal": "BUY", "confidence": 0.7, "reasoning": "ok"}'
    model = parse_llm_json(raw, AnalystSignal)
    assert model is not None
    assert model.signal == "BUY"
    assert model.confidence == 0.7


def test_parse_strips_code_fences():
    raw = '```json\n{"signal": "SELL", "confidence": 0.6, "reasoning": "x"}\n```'
    model = parse_llm_json(raw, AnalystSignal)
    assert model is not None
    assert model.signal == "SELL"


def test_parse_returns_none_on_garbage():
    assert parse_llm_json("not json at all", AnalystSignal) is None


def test_parse_returns_none_on_wrong_type():
    # confidence must be a float in [0,1]; "high" is invalid
    raw = '{"signal": "BUY", "confidence": "high", "reasoning": "x"}'
    assert parse_llm_json(raw, AnalystSignal) is None


def test_analyst_signal_rejects_unknown_signal():
    raw = '{"signal": "MOON", "confidence": 0.9, "reasoning": "x"}'
    assert parse_llm_json(raw, AnalystSignal) is None


def test_analyst_signal_clamps_confidence_range():
    raw = '{"signal": "BUY", "confidence": 1.5, "reasoning": "x"}'
    assert parse_llm_json(raw, AnalystSignal) is None


def test_judge_verdict_parses():
    raw = '{"proceed": true, "adjusted_confidence": 0.55, "reasoning": "A wins"}'
    model = parse_llm_json(raw, JudgeVerdict)
    assert model is not None
    assert model.proceed is True
    assert model.adjusted_confidence == 0.55


def test_strategist_suggestion_parses():
    raw = (
        '{"parameter_name": "rsi_period", "current_value": 14, '
        '"suggested_value": 21, "reasoning": "smoother", '
        '"expected_improvement": "sharpe +0.2"}'
    )
    model = parse_llm_json(raw, StrategistSuggestion)
    assert model is not None
    assert model.parameter_name == "rsi_period"
```

- [ ] **Step 2: Run to verify failure**

Run from `backend/`: `python -m pytest tests/agents/test_schemas.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.agents.schemas'`.

- [ ] **Step 3: Implement the schemas module**

Create `backend/app/agents/schemas.py`:

```python
"""Pydantic schemas for LLM agent outputs + a validating JSON parser.

Local models (deepseek-flash class) emit malformed or wrongly-typed JSON
regularly. These schemas turn "looks like JSON" into "is a valid, typed
agent output". ``parse_llm_json`` returns ``None`` on any failure so callers
can retry or fall back explicitly — a parse failure is never mistaken for a
real decision.
"""
from __future__ import annotations

import json
import logging
import re
from typing import Optional, Type, TypeVar

from pydantic import BaseModel, Field, ValidationError, field_validator

logger = logging.getLogger(__name__)

_FENCE = re.compile(r"```(?:json)?\s*([\s\S]*?)```")

T = TypeVar("T", bound=BaseModel)

_VALID_SIGNALS = {"BUY", "SELL", "HOLD", "EXIT"}


class AnalystSignal(BaseModel):
    """Validated analyst trading signal."""

    signal: str
    confidence: float = Field(ge=0.0, le=1.0)
    reasoning: str = ""
    entry_price: Optional[float] = None
    stoploss: Optional[float] = None
    target: Optional[float] = None

    @field_validator("signal")
    @classmethod
    def _known_signal(cls, v: str) -> str:
        up = str(v).upper()
        if up not in _VALID_SIGNALS:
            raise ValueError(f"unknown signal: {v}")
        return up


class JudgeVerdict(BaseModel):
    """Validated judge adjudication."""

    proceed: bool
    adjusted_confidence: float = Field(ge=0.0, le=1.0)
    reasoning: str = ""
    stronger_argument: Optional[str] = None


class StrategistSuggestion(BaseModel):
    """Validated single-parameter optimisation suggestion."""

    parameter_name: str
    current_value: object = None
    suggested_value: object = None
    reasoning: str = ""
    expected_improvement: str = ""


def parse_llm_json(raw: str, model: Type[T]) -> Optional[T]:
    """Strip code fences, decode JSON, validate against ``model``.

    Returns the validated model instance, or ``None`` on any failure
    (bad JSON, missing/wrong-typed fields, failed validators).
    """
    try:
        text = raw.strip()
        fence = _FENCE.search(text)
        if fence:
            text = fence.group(1).strip()
        data = json.loads(text)
        return model.model_validate(data)
    except (json.JSONDecodeError, ValidationError, TypeError, ValueError) as exc:
        logger.warning("parse_llm_json(%s) failed: %s", model.__name__, exc)
        return None
```

- [ ] **Step 4: Run to verify pass**

Run from `backend/`: `python -m pytest tests/agents/test_schemas.py -v`
Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/app/agents/schemas.py backend/tests/agents/test_schemas.py
git commit -m "feat(agents): add Pydantic output schemas + validating JSON parser

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

### Task B3: Harden AnalystAgent — validate, retry once, flag parse failures

**Files:**
- Modify: `backend/app/agents/analyst.py:46-62` (`run`), `:138-163` (`_parse_response`)
- Test: `backend/tests/agents/test_analyst.py`

- [ ] **Step 1: Write failing tests**

Append to `backend/tests/agents/test_analyst.py`:

```python
@pytest.mark.asyncio
async def test_analyst_retries_once_on_bad_json(analyst, context, mock_llm_router):
    """First response is garbage, second is valid BUY → analyst returns BUY."""
    mock_llm_router.generate = AsyncMock(side_effect=["garbage", BUY_RESPONSE])

    output = await analyst.run(context)

    assert output.data["signal"] == "BUY"
    assert mock_llm_router.generate.await_count == 2


@pytest.mark.asyncio
async def test_analyst_flags_parse_failure_after_retry(analyst, context, mock_llm_router):
    """Both attempts garbage → safe HOLD with explicit parse_failed flag."""
    mock_llm_router.generate = AsyncMock(side_effect=["nope", "still nope"])

    output = await analyst.run(context)

    assert output.data["signal"] == "HOLD"
    assert output.confidence == 0.0
    assert output.data.get("parse_failed") is True
    assert mock_llm_router.generate.await_count == 2


@pytest.mark.asyncio
async def test_analyst_requests_json_format(analyst, context, mock_llm_router):
    """Analyst asks Ollama for JSON-formatted output (fmt='json')."""
    await analyst.run(context)
    args, kwargs = mock_llm_router.generate.call_args
    # fmt is the 4th positional arg or the 'fmt' kwarg
    fmt = args[3] if len(args) >= 4 else kwargs.get("fmt")
    assert fmt == "json"
```

- [ ] **Step 2: Run to verify failure**

Run from `backend/`: `python -m pytest tests/agents/test_analyst.py::test_analyst_retries_once_on_bad_json tests/agents/test_analyst.py::test_analyst_flags_parse_failure_after_retry tests/agents/test_analyst.py::test_analyst_requests_json_format -v`
Expected: FAIL (no retry today; no `parse_failed` flag; `fmt` not passed).

- [ ] **Step 3: Implement validate + retry in `run`**

Replace the body of `run` and `_parse_response` in `backend/app/agents/analyst.py`. Add import at top: `from app.agents.schemas import AnalystSignal, parse_llm_json`. Then:

```python
    async def run(self, context: AgentContext) -> AgentOutput:
        start = time.perf_counter()

        intel = await self._build_intelligence(context)
        prompt = self._build_prompt(context, intel)
        parsed = await self._think_validated(prompt)

        return self._timed_output(
            start,
            agent_name=self.name,
            action="SIGNAL",
            data=parsed,
            reasoning=parsed.get("reasoning", ""),
            confidence=parsed.get("confidence", 0.0),
            llm_tier_used=self.llm_tier,
        )

    async def _think_validated(self, prompt: str) -> dict[str, Any]:
        """Call the LLM (JSON mode), validate, retry once, then safe default.

        Returns a plain dict. On total failure returns the safe HOLD default
        with ``parse_failed=True`` so the decision log can distinguish a model
        failure from a genuine HOLD.
        """
        for attempt in range(2):
            raw = await self.think(prompt, tier="quick", fmt="json")
            model = parse_llm_json(raw, AnalystSignal)
            if model is not None:
                return model.model_dump()
            logger.warning(
                "AnalystAgent parse attempt %d/2 failed for %s",
                attempt + 1,
                self.account_name,
            )
        failed = dict(_SAFE_DEFAULT)
        failed["parse_failed"] = True
        return failed
```

Delete the now-unused `_parse_response` method and the `re` import if nothing else uses it (the fence logic now lives in `schemas.parse_llm_json`).

- [ ] **Step 4: Run to verify pass (incl. regression)**

Run from `backend/`: `python -m pytest tests/agents/test_analyst.py -q`
Expected: all PASS. The existing `test_analyst_handles_malformed_json` still passes (garbage twice → HOLD/0.0; it does not assert call count).

- [ ] **Step 5: Commit**

```bash
git add backend/app/agents/analyst.py backend/tests/agents/test_analyst.py
git commit -m "feat(analyst): schema-validate signal, retry once, flag parse failures

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

### Task B4: Harden JudgeAgent — validate + retry

**Files:**
- Modify: `backend/app/agents/debate.py:189-230` (`JudgeAgent.run`), `:272-286` (`JudgeAgent._parse`)
- Test: `backend/tests/agents/test_debate.py`

- [ ] **Step 1: Write failing tests**

Append to `backend/tests/agents/test_debate.py` (use the file's existing fixtures for a judge + context with a populated `debate_result`; if none exists, construct inline as below):

```python
@pytest.mark.asyncio
async def test_judge_retries_once_on_bad_json(tmp_path):
    from unittest.mock import AsyncMock
    from app.agents.debate import JudgeAgent
    from app.agents.base import AgentContext
    from app.brokers.base import MarginInfo

    defaults = tmp_path / "defaults"
    defaults.mkdir()
    (defaults / "judge.md").write_text("You are a judge.")

    good = '{"proceed": true, "adjusted_confidence": 0.6, "reasoning": "A"}'
    router = AsyncMock()
    router.generate = AsyncMock(side_effect=["garbage", good])

    judge = JudgeAgent(router, str(tmp_path), "paper_test")
    ctx = AgentContext(
        account_name="paper_test", symbol="NIFTY", market_state={},
        positions=[], margins=MarginInfo(0, 0, 0, "paper", {}),
        recent_decisions=[], memory_recall=[],
        signals={"signal": "BUY", "confidence": 0.7},
        debate_result={"bullish": {"argument": "up"}, "bearish": {"argument": "down"}},
        guardian_verdict=None, config={"debate": {"anonymize": False}},
    )

    output = await judge.run(ctx)
    assert output.data["proceed"] is True
    assert router.generate.await_count == 2


@pytest.mark.asyncio
async def test_judge_blocks_on_total_parse_failure(tmp_path):
    from unittest.mock import AsyncMock
    from app.agents.debate import JudgeAgent
    from app.agents.base import AgentContext
    from app.brokers.base import MarginInfo

    defaults = tmp_path / "defaults"
    defaults.mkdir()
    (defaults / "judge.md").write_text("You are a judge.")

    router = AsyncMock()
    router.generate = AsyncMock(side_effect=["nope", "still nope"])

    judge = JudgeAgent(router, str(tmp_path), "paper_test")
    ctx = AgentContext(
        account_name="paper_test", symbol="NIFTY", market_state={},
        positions=[], margins=MarginInfo(0, 0, 0, "paper", {}),
        recent_decisions=[], memory_recall=[],
        signals={"signal": "BUY", "confidence": 0.7},
        debate_result={"bullish": {"argument": "up"}, "bearish": {"argument": "down"}},
        guardian_verdict=None, config={"debate": {"anonymize": False}},
    )

    output = await judge.run(ctx)
    # fail-safe: do NOT proceed when the judge can't be parsed
    assert output.data["proceed"] is False
    assert output.data.get("parse_failed") is True
```

- [ ] **Step 2: Run to verify failure**

Run from `backend/`: `python -m pytest tests/agents/test_debate.py::test_judge_retries_once_on_bad_json tests/agents/test_debate.py::test_judge_blocks_on_total_parse_failure -v`
Expected: FAIL (no retry; no `parse_failed`).

- [ ] **Step 3: Implement validate + retry in JudgeAgent**

Add import at top of `backend/app/agents/debate.py`: `from app.agents.schemas import JudgeVerdict, parse_llm_json`. Replace the parse-and-return tail of `JudgeAgent.run` (the block after `prompt = self._anonymize_and_build_prompt(...)`):

```python
        verdict = await self._judge_validated(prompt)

        return self._timed_output(
            start,
            agent_name=self.name,
            action="JUDGE",
            data=verdict,
            reasoning=verdict.get("reasoning", ""),
            confidence=float(verdict.get("adjusted_confidence", 0.0)),
            llm_tier_used="deep",
        )

    async def _judge_validated(self, prompt: str) -> dict[str, Any]:
        """Adjudicate with JSON mode + one retry. Fail-safe to BLOCK."""
        for attempt in range(2):
            raw = await self.think(prompt, tier="deep", fmt="json")
            model = parse_llm_json(raw, JudgeVerdict)
            if model is not None:
                return model.model_dump()
            logger.warning("JudgeAgent parse attempt %d/2 failed", attempt + 1)
        return {
            "proceed": False,
            "adjusted_confidence": 0.0,
            "reasoning": "parse_failure",
            "stronger_argument": None,
            "parse_failed": True,
        }
```

Delete the now-unused `JudgeAgent._parse` method.

- [ ] **Step 4: Run to verify pass**

Run from `backend/`: `python -m pytest tests/agents/test_debate.py -q`
Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/app/agents/debate.py backend/tests/agents/test_debate.py
git commit -m "feat(judge): schema-validate verdict, retry once, fail-safe BLOCK on parse failure

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

### Task B5: Harden StrategistAgent suggestion parsing

**Files:**
- Modify: `backend/app/agents/strategist.py:103-130` (`suggest_improvement`), `:243-262` (`_parse`)
- Test: `backend/tests/agents/test_strategist.py`

- [ ] **Step 1: Write failing test**

Append to `backend/tests/agents/test_strategist.py` (reuse existing fixtures; otherwise build a strategist with an `AsyncMock` router + `AsyncMock` memory whose `recall` returns `[]`):

```python
@pytest.mark.asyncio
async def test_strategist_retries_then_flags_parse_failure(tmp_path):
    from unittest.mock import AsyncMock
    from app.agents.strategist import StrategistAgent

    defaults = tmp_path / "defaults"
    defaults.mkdir()
    (defaults / "strategist.md").write_text("You optimise strategies.")

    router = AsyncMock()
    router.generate = AsyncMock(side_effect=["garbage", "still bad"])
    memory = AsyncMock()
    memory.recall = AsyncMock(return_value=[])

    strat = StrategistAgent(
        router, memory, AsyncMock(), str(tmp_path), "paper_test", {}
    )

    suggestion = await strat.suggest_improvement(
        strategy_name="s", strategy_config={}, performance={"sharpe": 0.5},
    )

    assert suggestion["parameter_name"] == "unknown"
    assert suggestion.get("parse_failed") is True
    assert router.generate.await_count == 2
```

- [ ] **Step 2: Run to verify failure**

Run from `backend/`: `python -m pytest tests/agents/test_strategist.py::test_strategist_retries_then_flags_parse_failure -v`
Expected: FAIL (single attempt; no `parse_failed`).

- [ ] **Step 3: Implement validate + retry**

Add import at top of `backend/app/agents/strategist.py`: `from app.agents.schemas import StrategistSuggestion, parse_llm_json`. Replace the tail of `suggest_improvement` (the `raw = ...; return self._parse(raw)` lines):

```python
        for attempt in range(2):
            raw = await self.think(prompt, tier="deep", fmt="json")
            model = parse_llm_json(raw, StrategistSuggestion)
            if model is not None:
                return model.model_dump()
            logger.warning(
                "StrategistAgent suggestion parse attempt %d/2 failed", attempt + 1
            )
        failed = dict(_SUGGESTION_FALLBACK)
        failed["parse_failed"] = True
        return failed
```

Delete the now-unused `_parse` method and the `re` import if unused elsewhere.

- [ ] **Step 4: Run to verify pass**

Run from `backend/`: `python -m pytest tests/agents/test_strategist.py -q`
Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/app/agents/strategist.py backend/tests/agents/test_strategist.py
git commit -m "feat(strategist): schema-validate suggestion, retry once, flag parse failures

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

# AREA C — Live-trading safety

### Task C1: Control-API-key setting

**Files:**
- Modify: `backend/app/config.py:46-55` (Security block)
- Test: `backend/tests/test_config.py` (create if absent)

- [ ] **Step 1: Write failing test**

Create `backend/tests/test_config.py` (or append):

```python
def test_agent_control_api_key_setting_exists(monkeypatch):
    monkeypatch.setenv("ZERODHA_API_KEY", "x")
    monkeypatch.setenv("ZERODHA_API_SECRET", "y")
    monkeypatch.setenv("AGENT_CONTROL_API_KEY", "secret123")
    from app.config import Settings
    s = Settings()
    assert s.AGENT_CONTROL_API_KEY == "secret123"


def test_agent_control_api_key_defaults_none(monkeypatch):
    monkeypatch.setenv("ZERODHA_API_KEY", "x")
    monkeypatch.setenv("ZERODHA_API_SECRET", "y")
    monkeypatch.delenv("AGENT_CONTROL_API_KEY", raising=False)
    from app.config import Settings
    s = Settings()
    assert s.AGENT_CONTROL_API_KEY is None
```

- [ ] **Step 2: Run to verify failure**

Run from `backend/`: `python -m pytest tests/test_config.py -v`
Expected: FAIL (`AttributeError: AGENT_CONTROL_API_KEY`).

- [ ] **Step 3: Implement the setting**

In `backend/app/config.py`, inside the `# Security` block (after `ENCRYPTION_KEY`):

```python
    AGENT_CONTROL_API_KEY: Optional[str] = Field(
        default=None,
        description="API key required to start/stop pods and trigger the kill switch. "
                    "When None, control endpoints are open (dev only).",
    )
```

- [ ] **Step 4: Run to verify pass**

Run from `backend/`: `python -m pytest tests/test_config.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/app/config.py backend/tests/test_config.py
git commit -m "feat(config): add AGENT_CONTROL_API_KEY for pod control auth

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

### Task C2: `require_api_key` dependency + auth on mutating pod endpoints

**Files:**
- Create: `backend/app/agents/security.py`
- Modify: `backend/app/agents/router.py:98-121` (start/stop/cycle)
- Test: `backend/tests/agents/test_router_auth.py`

- [ ] **Step 1: Write failing tests**

Create `backend/tests/agents/test_router_auth.py`:

```python
"""Auth tests for mutating pod-control endpoints."""
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from unittest.mock import AsyncMock, MagicMock

from app.agents import router as agents_router_mod


@pytest.fixture
def client(monkeypatch):
    # one fake pod
    pod = MagicMock()
    pod.get_status.return_value = {"account_name": "paper_test", "running": False}
    pod.start = AsyncMock()
    pod.start_eval_loop = AsyncMock()
    pod.stop = AsyncMock()
    pod.run_cycle = AsyncMock()
    agents_router_mod.set_pods({"paper_test": pod})

    app = FastAPI()
    app.include_router(agents_router_mod.router, prefix="/api/agents")
    return TestClient(app), pod


def test_start_requires_key_when_configured(client, monkeypatch):
    from app.agents import security
    monkeypatch.setattr(security.settings, "AGENT_CONTROL_API_KEY", "secret", raising=False)
    c, _ = client
    resp = c.post("/api/agents/pods/paper_test/start")
    assert resp.status_code == 401


def test_start_accepts_correct_key(client, monkeypatch):
    from app.agents import security
    monkeypatch.setattr(security.settings, "AGENT_CONTROL_API_KEY", "secret", raising=False)
    c, _ = client
    resp = c.post("/api/agents/pods/paper_test/start", headers={"X-API-Key": "secret"})
    assert resp.status_code == 200


def test_start_open_when_key_unset(client, monkeypatch):
    from app.agents import security
    monkeypatch.setattr(security.settings, "AGENT_CONTROL_API_KEY", None, raising=False)
    c, _ = client
    resp = c.post("/api/agents/pods/paper_test/start")
    assert resp.status_code == 200


def test_status_endpoint_stays_open(client, monkeypatch):
    from app.agents import security
    monkeypatch.setattr(security.settings, "AGENT_CONTROL_API_KEY", "secret", raising=False)
    c, _ = client
    resp = c.get("/api/agents/pods")
    assert resp.status_code == 200
```

> If `fastapi.testclient` requires `httpx`/`starlette` testclient extras, they are already transitive deps of FastAPI 0.104 in this repo.

- [ ] **Step 2: Run to verify failure**

Run from `backend/`: `python -m pytest tests/agents/test_router_auth.py -v`
Expected: FAIL (`ModuleNotFoundError: app.agents.security`).

- [ ] **Step 3: Implement the dependency**

Create `backend/app/agents/security.py`:

```python
"""Auth dependency for agent control endpoints.

When ``settings.AGENT_CONTROL_API_KEY`` is set, mutating pod endpoints
(start/stop/cycle/kill-switch) require a matching ``X-API-Key`` header.
When unset (default), endpoints stay open for local development.
"""
from __future__ import annotations

from fastapi import Header, HTTPException, status

from app.config import settings


async def require_api_key(x_api_key: str | None = Header(default=None)) -> None:
    """Reject the request unless the X-API-Key header matches the configured key.

    No-op when AGENT_CONTROL_API_KEY is unset.
    """
    expected = settings.AGENT_CONTROL_API_KEY
    if expected is None:
        return
    if x_api_key != expected:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or missing X-API-Key",
        )
```

- [ ] **Step 4: Apply the dependency to mutating endpoints**

In `backend/app/agents/router.py`, add imports:

```python
from fastapi import APIRouter, HTTPException, Depends
from app.agents.security import require_api_key
```

Add `dependencies=[Depends(require_api_key)]` to the three mutating routes:

```python
@router.post("/pods/{account_name}/start", dependencies=[Depends(require_api_key)])
async def start_pod(account_name: str):
    ...

@router.post("/pods/{account_name}/stop", dependencies=[Depends(require_api_key)])
async def stop_pod(account_name: str):
    ...

@router.post("/pods/{account_name}/cycle", dependencies=[Depends(require_api_key)])
async def run_single_cycle(account_name: str):
    ...
```

Leave `GET /pods` and `GET /pods/{account_name}` unauthenticated.

- [ ] **Step 5: Run to verify pass**

Run from `backend/`: `python -m pytest tests/agents/test_router_auth.py -v`
Expected: all PASS.

- [ ] **Step 6: Commit**

```bash
git add backend/app/agents/security.py backend/app/agents/router.py backend/tests/agents/test_router_auth.py
git commit -m "feat(agents): require X-API-Key on pod start/stop/cycle endpoints

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

### Task C3: `AgentPod.flatten_and_halt()` — emergency close + halt

**Files:**
- Modify: `backend/app/agents/pod.py` (add method after `stop`)
- Test: `backend/tests/agents/test_pod.py`

- [ ] **Step 1: Write failing test**

Append to `backend/tests/agents/test_pod.py` (follow the file's existing pod-construction fixture; the sketch below builds the adapter mock explicitly):

```python
@pytest.mark.asyncio
async def test_flatten_and_halt_closes_positions_cancels_orders(monkeypatch):
    from unittest.mock import AsyncMock, MagicMock
    from app.agents.pod import AgentPod
    from app.brokers.base import Position, OrderStatus, OrderResult

    adapter = MagicMock()
    adapter.name = "paper"
    adapter.is_connected = True
    adapter.get_positions = AsyncMock(return_value=[
        Position("NIFTY", "NFO", "FNO", 50, 100.0, 105.0, 250.0, "MIS", "paper"),
        Position("BANKNIFTY", "NFO", "FNO", -25, 200.0, 195.0, 125.0, "MIS", "paper"),
    ])
    adapter.get_orders = AsyncMock(return_value=[
        OrderStatus("o1", "NIFTY", "OPEN", 50, 0, 0.0, "LIMIT", "BUY", "paper"),
    ])
    adapter.cancel_order = AsyncMock(return_value="o1")
    adapter.place_order = AsyncMock(
        return_value=OrderResult("exit1", "COMPLETE", "paper", {})
    )

    pod = AgentPod(
        account_name="paper_test", adapter=adapter,
        config={"agents": {"llm": {"quick_model": "q", "deep_model": "d"}}},
        db=MagicMock(),
    )
    pod._running = True

    result = await pod.flatten_and_halt()

    assert pod._running is False
    adapter.cancel_order.assert_awaited_once()      # the one open order
    assert adapter.place_order.await_count == 2      # square off both positions
    assert result["positions_closed"] == 2
    assert result["orders_cancelled"] == 1


@pytest.mark.asyncio
async def test_flatten_and_halt_squares_off_with_opposite_side(monkeypatch):
    from unittest.mock import AsyncMock, MagicMock
    from app.agents.pod import AgentPod
    from app.brokers.base import Position, OrderResult

    adapter = MagicMock()
    adapter.name = "paper"
    adapter.is_connected = True
    adapter.get_positions = AsyncMock(return_value=[
        Position("NIFTY", "NFO", "FNO", 50, 100.0, 105.0, 250.0, "MIS", "paper"),
    ])
    adapter.get_orders = AsyncMock(return_value=[])
    adapter.cancel_order = AsyncMock()
    placed = {}
    async def _capture(order):
        placed["order"] = order
        return OrderResult("exit1", "COMPLETE", "paper", {})
    adapter.place_order = AsyncMock(side_effect=_capture)

    pod = AgentPod(
        account_name="paper_test", adapter=adapter,
        config={"agents": {"llm": {"quick_model": "q", "deep_model": "d"}}},
        db=MagicMock(),
    )
    pod._running = True

    await pod.flatten_and_halt()

    # long 50 → square off with SELL 50
    assert placed["order"].transaction_type == "SELL"
    assert placed["order"].quantity == 50
```

- [ ] **Step 2: Run to verify failure**

Run from `backend/`: `python -m pytest tests/agents/test_pod.py::test_flatten_and_halt_closes_positions_cancels_orders tests/agents/test_pod.py::test_flatten_and_halt_squares_off_with_opposite_side -v`
Expected: FAIL (`AttributeError: 'AgentPod' object has no attribute 'flatten_and_halt'`).

- [ ] **Step 3: Implement `flatten_and_halt`**

Add to `backend/app/agents/pod.py` (import `UnifiedOrder` at top: `from app.brokers.base import UnifiedOrder`). Insert after `stop`:

```python
    async def flatten_and_halt(self) -> dict:
        """Emergency stop: halt the loop, cancel open orders, square off positions.

        Best-effort and idempotent. Every broker call is individually guarded so
        one failure never prevents the rest of the flattening. Returns a summary
        dict for the caller / alerting.
        """
        self._running = False
        if self._eval_task:
            self._eval_task.cancel()
            try:
                await self._eval_task
            except asyncio.CancelledError:
                pass

        orders_cancelled = 0
        positions_closed = 0
        errors: list[str] = []

        # 1. Cancel resting orders
        try:
            for o in await self.adapter.get_orders():
                if o.status in {"OPEN", "PENDING", "TRIGGER PENDING"}:
                    try:
                        await self.adapter.cancel_order(o.broker_order_id, "")
                        orders_cancelled += 1
                    except Exception as exc:  # noqa: BLE001
                        errors.append(f"cancel {o.broker_order_id}: {exc}")
        except Exception as exc:  # noqa: BLE001
            errors.append(f"get_orders: {exc}")

        # 2. Square off open positions with an opposite-side market order
        try:
            for p in await self.adapter.get_positions():
                if p.quantity == 0:
                    continue
                side = "SELL" if p.quantity > 0 else "BUY"
                try:
                    await self.adapter.place_order(UnifiedOrder(
                        symbol=p.symbol,
                        exchange=p.exchange,
                        segment=p.segment,
                        transaction_type=side,
                        quantity=abs(p.quantity),
                        order_type="MARKET",
                        product=p.product,
                    ))
                    positions_closed += 1
                except Exception as exc:  # noqa: BLE001
                    errors.append(f"flatten {p.symbol}: {exc}")
        except Exception as exc:  # noqa: BLE001
            errors.append(f"get_positions: {exc}")

        summary = {
            "account_name": self.account_name,
            "halted": True,
            "orders_cancelled": orders_cancelled,
            "positions_closed": positions_closed,
            "errors": errors,
        }
        logger.warning("[%s] FLATTEN+HALT: %s", self.account_name, summary)
        return summary
```

- [ ] **Step 4: Run to verify pass**

Run from `backend/`: `python -m pytest tests/agents/test_pod.py -q`
Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/app/agents/pod.py backend/tests/agents/test_pod.py
git commit -m "feat(pod): add flatten_and_halt emergency square-off + loop halt

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

### Task C4: Kill-switch endpoint (all pods)

**Files:**
- Modify: `backend/app/agents/router.py` (add route)
- Test: `backend/tests/agents/test_router_auth.py`

- [ ] **Step 1: Write failing test**

Append to `backend/tests/agents/test_router_auth.py`:

```python
def test_kill_switch_flattens_all_pods(client, monkeypatch):
    from app.agents import security
    monkeypatch.setattr(security.settings, "AGENT_CONTROL_API_KEY", "secret", raising=False)
    c, pod = client
    pod.flatten_and_halt = AsyncMock(return_value={
        "account_name": "paper_test", "halted": True,
        "orders_cancelled": 0, "positions_closed": 0, "errors": [],
    })
    resp = c.post("/api/agents/kill-switch", headers={"X-API-Key": "secret"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "killed"
    assert "paper_test" in body["results"]
    pod.flatten_and_halt.assert_awaited_once()


def test_kill_switch_requires_key(client, monkeypatch):
    from app.agents import security
    monkeypatch.setattr(security.settings, "AGENT_CONTROL_API_KEY", "secret", raising=False)
    c, _ = client
    resp = c.post("/api/agents/kill-switch")
    assert resp.status_code == 401
```

- [ ] **Step 2: Run to verify failure**

Run from `backend/`: `python -m pytest tests/agents/test_router_auth.py::test_kill_switch_flattens_all_pods tests/agents/test_router_auth.py::test_kill_switch_requires_key -v`
Expected: FAIL (404 — route missing).

- [ ] **Step 3: Implement the route**

In `backend/app/agents/router.py`, add after the `/pods/{account_name}/cycle` route:

```python
@router.post("/kill-switch", dependencies=[Depends(require_api_key)])
async def kill_switch():
    """EMERGENCY: flatten positions, cancel orders, and halt every pod."""
    results = {}
    for name, pod in _pods.items():
        try:
            results[name] = await pod.flatten_and_halt()
        except Exception as exc:  # noqa: BLE001
            results[name] = {"halted": False, "error": str(exc)}
    return {"status": "killed", "results": results}
```

- [ ] **Step 4: Run to verify pass**

Run from `backend/`: `python -m pytest tests/agents/test_router_auth.py -q`
Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/app/agents/router.py backend/tests/agents/test_router_auth.py
git commit -m "feat(agents): add authenticated /kill-switch that flattens+halts all pods

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

### Task C5: Startup reconciliation in `AgentPod.start()`

**Files:**
- Modify: `backend/app/agents/pod.py:131-139` (`start`)
- Test: `backend/tests/agents/test_pod.py`

- [ ] **Step 1: Write failing test**

Append to `backend/tests/agents/test_pod.py`:

```python
@pytest.mark.asyncio
async def test_start_reconciles_and_returns_snapshot():
    from unittest.mock import AsyncMock, MagicMock
    from app.agents.pod import AgentPod
    from app.brokers.base import Position, OrderStatus

    adapter = MagicMock()
    adapter.name = "paper"
    adapter.is_connected = True
    adapter.get_positions = AsyncMock(return_value=[
        Position("NIFTY", "NFO", "FNO", 50, 100.0, 105.0, 250.0, "MIS", "paper"),
    ])
    adapter.get_orders = AsyncMock(return_value=[
        OrderStatus("o1", "NIFTY", "OPEN", 50, 0, 0.0, "LIMIT", "BUY", "paper"),
    ])

    pod = AgentPod(
        account_name="paper_test", adapter=adapter,
        config={"agents": {"llm": {"quick_model": "q", "deep_model": "d"}}},
        db=MagicMock(),
    )

    snapshot = await pod.reconcile()

    assert snapshot["open_positions"] == 1
    assert snapshot["open_orders"] == 1
    adapter.get_positions.assert_awaited()
    adapter.get_orders.assert_awaited()


@pytest.mark.asyncio
async def test_start_calls_reconcile():
    from unittest.mock import AsyncMock, MagicMock
    from app.agents.pod import AgentPod

    adapter = MagicMock()
    adapter.name = "paper"
    adapter.is_connected = True

    pod = AgentPod(
        account_name="paper_test", adapter=adapter,
        config={"agents": {"llm": {"quick_model": "q", "deep_model": "d"}}},
        db=MagicMock(),
    )
    pod.reconcile = AsyncMock(return_value={"open_positions": 0, "open_orders": 0})

    await pod.start()

    pod.reconcile.assert_awaited_once()
    assert pod._running is True
```

- [ ] **Step 2: Run to verify failure**

Run from `backend/`: `python -m pytest tests/agents/test_pod.py::test_start_reconciles_and_returns_snapshot tests/agents/test_pod.py::test_start_calls_reconcile -v`
Expected: FAIL (no `reconcile`; `start` doesn't call it).

- [ ] **Step 3: Implement `reconcile` + call it from `start`**

In `backend/app/agents/pod.py`, add a `reconcile` method and call it from `start`:

```python
    async def reconcile(self) -> dict:
        """Snapshot broker truth at startup so internal state never drifts blind.

        Logs current open positions and resting orders. Returns counts. Failures
        are caught and reported (never block pod startup).
        """
        snapshot = {"open_positions": 0, "open_orders": 0, "errors": []}
        try:
            positions = await self.adapter.get_positions()
            snapshot["open_positions"] = sum(1 for p in positions if p.quantity != 0)
        except Exception as exc:  # noqa: BLE001
            snapshot["errors"].append(f"get_positions: {exc}")
        try:
            orders = await self.adapter.get_orders()
            snapshot["open_orders"] = sum(
                1 for o in orders if o.status in {"OPEN", "PENDING", "TRIGGER PENDING"}
            )
        except Exception as exc:  # noqa: BLE001
            snapshot["errors"].append(f"get_orders: {exc}")
        logger.info("[%s] Reconciliation: %s", self.account_name, snapshot)
        return snapshot
```

Then update `start` to call it after login:

```python
    async def start(self) -> None:
        """Connect the broker, reconcile against broker truth, mark running."""
        if not self.adapter.is_connected:
            try:
                await self.adapter.login({})
            except Exception as exc:  # noqa: BLE001
                logger.warning("[%s] Auto-login failed: %s", self.account_name, exc)
        try:
            await self.reconcile()
        except Exception as exc:  # noqa: BLE001
            logger.error("[%s] Reconciliation failed: %s", self.account_name, exc)
        self._running = True
        logger.info("[%s] Pod started", self.account_name)
```

- [ ] **Step 4: Run to verify pass**

Run from `backend/`: `python -m pytest tests/agents/test_pod.py -q`
Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/app/agents/pod.py backend/tests/agents/test_pod.py
git commit -m "feat(pod): reconcile broker positions/orders on start

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

# AREA D — Strategist guardrails

### Task D1: Statistical guardrails for keeping an optimisation

**Files:**
- Modify: `backend/app/agents/strategist.py` (add `_passes_guardrails`; extend config keys)
- Test: `backend/tests/agents/test_strategist.py`

- [ ] **Step 1: Write failing tests**

Append to `backend/tests/agents/test_strategist.py`:

```python
def _make_strategist(tmp_path, config):
    from unittest.mock import AsyncMock
    from app.agents.strategist import StrategistAgent
    defaults = tmp_path / "defaults"
    defaults.mkdir(exist_ok=True)
    (defaults / "strategist.md").write_text("optimise")
    return StrategistAgent(
        AsyncMock(), AsyncMock(), AsyncMock(), str(tmp_path), "paper_test", config
    )


def test_guardrails_reject_low_sample(tmp_path):
    strat = _make_strategist(tmp_path, {"min_trades_for_validation": 30})
    ok = strat._passes_guardrails(
        baseline={"sharpe": 0.5}, modified={"sharpe": 1.0},
        oos={"sharpe": 1.0}, trade_count=5,
    )
    assert ok is False


def test_guardrails_reject_no_oos_improvement(tmp_path):
    strat = _make_strategist(tmp_path, {"min_trades_for_validation": 30})
    ok = strat._passes_guardrails(
        baseline={"sharpe": 0.5}, modified={"sharpe": 1.2},
        oos={"sharpe": 0.4}, trade_count=100,   # OOS worse than baseline
    )
    assert ok is False


def test_guardrails_reject_no_insample_improvement(tmp_path):
    strat = _make_strategist(tmp_path, {"min_trades_for_validation": 30})
    ok = strat._passes_guardrails(
        baseline={"sharpe": 0.5}, modified={"sharpe": 0.5},
        oos={"sharpe": 0.9}, trade_count=100,
    )
    assert ok is False


def test_guardrails_pass_when_all_conditions_met(tmp_path):
    strat = _make_strategist(tmp_path, {"min_trades_for_validation": 30})
    ok = strat._passes_guardrails(
        baseline={"sharpe": 0.5}, modified={"sharpe": 1.2},
        oos={"sharpe": 0.8}, trade_count=100,
    )
    assert ok is True
```

- [ ] **Step 2: Run to verify failure**

Run from `backend/`: `python -m pytest tests/agents/test_strategist.py -k guardrails -v`
Expected: FAIL (`AttributeError: _passes_guardrails`).

- [ ] **Step 3: Implement `_passes_guardrails`**

Add to `StrategistAgent` in `backend/app/agents/strategist.py`:

```python
    def _passes_guardrails(
        self,
        baseline: dict,
        modified: dict,
        oos: dict,
        trade_count: int,
    ) -> bool:
        """Return True only if a change is worth keeping.

        Three conditions, ALL required (defends against curve-fitting noise):
          1. Sample size: trade_count >= min_trades_for_validation.
          2. In-sample improvement: modified Sharpe strictly > baseline.
          3. Out-of-sample holds up: OOS Sharpe strictly > baseline (the change
             generalises, not just fits the training window).
        """
        min_trades = int(self._config.get("min_trades_for_validation", 30))
        if trade_count < min_trades:
            return False
        base_sharpe = baseline.get("sharpe", 0)
        if modified.get("sharpe", 0) <= base_sharpe:
            return False
        if oos.get("sharpe", 0) <= base_sharpe:
            return False
        return True
```

- [ ] **Step 4: Run to verify pass**

Run from `backend/`: `python -m pytest tests/agents/test_strategist.py -k guardrails -v`
Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/app/agents/strategist.py backend/tests/agents/test_strategist.py
git commit -m "feat(strategist): add sample-size + OOS guardrails for keeping changes

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

### Task D2: Human-approval gate in `overnight_optimization`

**Files:**
- Modify: `backend/app/agents/strategist.py:132-185` (`overnight_optimization`)
- Test: `backend/tests/agents/test_strategist.py`

- [ ] **Step 1: Write failing tests**

Append to `backend/tests/agents/test_strategist.py`:

```python
@pytest.mark.asyncio
async def test_overnight_never_applies_when_approval_required(tmp_path):
    from unittest.mock import AsyncMock
    strat = _make_strategist(
        tmp_path,
        {"require_human_approval": True, "min_trades_for_validation": 30,
         "max_experiments_per_night": 5},
    )
    strat._memory.recall = AsyncMock(return_value=[])
    strat.llm_router.generate = AsyncMock(return_value=(
        '{"parameter_name": "p", "current_value": 1, "suggested_value": 2, '
        '"reasoning": "r", "expected_improvement": "sharpe +0.3"}'
    ))
    strat._decision_logger.log_decision = AsyncMock()

    strategies = [{
        "name": "s1", "config": {}, "performance": {"sharpe": 0.5},
        "modified": {"sharpe": 1.2}, "oos": {"sharpe": 0.9}, "trade_count": 100,
    }]

    results = await strat.overnight_optimization(strategies)

    assert results[0]["guardrails_passed"] is True   # stats are good
    assert results[0]["approved"] is False           # but approval gate holds
    assert results[0]["kept"] is False


@pytest.mark.asyncio
async def test_overnight_marks_approved_when_gate_open_and_stats_pass(tmp_path):
    from unittest.mock import AsyncMock
    strat = _make_strategist(
        tmp_path,
        {"require_human_approval": False, "min_trades_for_validation": 30,
         "max_experiments_per_night": 5},
    )
    strat._memory.recall = AsyncMock(return_value=[])
    strat.llm_router.generate = AsyncMock(return_value=(
        '{"parameter_name": "p", "current_value": 1, "suggested_value": 2, '
        '"reasoning": "r", "expected_improvement": "sharpe +0.3"}'
    ))
    strat._decision_logger.log_decision = AsyncMock()

    strategies = [{
        "name": "s1", "config": {}, "performance": {"sharpe": 0.5},
        "modified": {"sharpe": 1.2}, "oos": {"sharpe": 0.9}, "trade_count": 100,
    }]

    results = await strat.overnight_optimization(strategies)

    assert results[0]["guardrails_passed"] is True
    assert results[0]["approved"] is True
    assert results[0]["kept"] is True


@pytest.mark.asyncio
async def test_overnight_rejects_when_stats_fail_even_if_gate_open(tmp_path):
    from unittest.mock import AsyncMock
    strat = _make_strategist(
        tmp_path,
        {"require_human_approval": False, "min_trades_for_validation": 30,
         "max_experiments_per_night": 5},
    )
    strat._memory.recall = AsyncMock(return_value=[])
    strat.llm_router.generate = AsyncMock(return_value=(
        '{"parameter_name": "p", "current_value": 1, "suggested_value": 2, '
        '"reasoning": "r", "expected_improvement": "noise"}'
    ))
    strat._decision_logger.log_decision = AsyncMock()

    strategies = [{
        "name": "s1", "config": {}, "performance": {"sharpe": 0.5},
        "modified": {"sharpe": 1.2}, "oos": {"sharpe": 0.3},  # OOS fails
        "trade_count": 100,
    }]

    results = await strat.overnight_optimization(strategies)

    assert results[0]["guardrails_passed"] is False
    assert results[0]["kept"] is False
```

- [ ] **Step 2: Run to verify failure**

Run from `backend/`: `python -m pytest tests/agents/test_strategist.py -k overnight -v`
Expected: FAIL (result lacks `guardrails_passed`/`approved`; `kept` always False).

- [ ] **Step 3: Reimplement `overnight_optimization`**

Replace `overnight_optimization` in `backend/app/agents/strategist.py`:

```python
    async def overnight_optimization(
        self, strategies: list[dict]
    ) -> list[dict]:
        """Run the autoresearch loop with statistical + approval guardrails.

        For each strategy: generate a suggestion, evaluate guardrails
        (sample size + in-sample + out-of-sample), then apply the human-approval
        gate. A change is only ``kept`` when guardrails pass AND approval is not
        required. When approval IS required, a passing change is logged as
        SKIPPED with a PENDING_APPROVAL reason so a human can review it.

        Each strategy dict may carry: name, config, performance (baseline),
        modified, oos, trade_count.
        """
        max_experiments = self._config.get("max_experiments_per_night", 10)
        require_approval = bool(self._config.get("require_human_approval", True))
        results: list[dict] = []

        for i, strategy in enumerate(strategies[:max_experiments]):
            name = strategy.get("name", f"strategy_{i}")
            config = strategy.get("config", {})
            baseline = strategy.get("performance", {})
            modified = strategy.get("modified", {})
            oos = strategy.get("oos", {})
            trade_count = int(strategy.get("trade_count", 0))

            suggestion = await self.suggest_improvement(
                strategy_name=name,
                strategy_config=config,
                performance=baseline,
            )

            guardrails_passed = self._passes_guardrails(
                baseline=baseline, modified=modified,
                oos=oos, trade_count=trade_count,
            )
            approved = guardrails_passed and not require_approval
            kept = approved

            if kept:
                action = DecisionAction.EXECUTED
                reasoning_text = f"Applied: {suggestion}"
            elif guardrails_passed and require_approval:
                action = DecisionAction.SKIPPED
                reasoning_text = f"PENDING_APPROVAL: {suggestion}"
            else:
                action = DecisionAction.SKIPPED
                reasoning_text = f"Rejected by guardrails: {suggestion}"

            await self._decision_logger.log_decision(
                account_name=self.account_name,
                symbol="STRATEGY_OPT",
                signal="OPTIMIZE",
                action=action,
                confidence=1.0,
                reasoning=reasoning_text,
                market_state={
                    "experiment": i, "strategy": name,
                    "guardrails_passed": guardrails_passed, "approved": approved,
                },
            )

            results.append({
                "strategy": name,
                "suggestion": suggestion,
                "guardrails_passed": guardrails_passed,
                "approved": approved,
                "kept": kept,
            })

        return results
```

- [ ] **Step 4: Run to verify pass (incl. existing strategist tests)**

Run from `backend/`: `python -m pytest tests/agents/test_strategist.py -q`
Expected: all PASS. (If a pre-existing overnight test asserted the old result shape `{"strategy","suggestion","kept"}`, update it to the new shape — the new keys are a superset plus `guardrails_passed`/`approved`.)

- [ ] **Step 5: Add config keys to the paper account so the gate is explicit**

In `backend/config/accounts.yaml`, under `paper_test.agents`, add a `strategist` block (after the `memory` block):

```yaml
      strategist:
        enabled: true
        require_human_approval: true
        min_trades_for_validation: 30
        max_experiments_per_night: 10
```

- [ ] **Step 6: Commit**

```bash
git add backend/app/agents/strategist.py backend/tests/agents/test_strategist.py backend/config/accounts.yaml
git commit -m "feat(strategist): human-approval gate + guardrail-gated overnight optimisation

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

## Final verification

- [ ] **Run the entire suite**

Run from `backend/`: `python -m pytest tests -q`
Expected: all pass — original 289 plus the new tests added across B/C/D (no regressions).

- [ ] **Confirm working tree is clean**

Run: `git status --short`
Expected: empty (everything committed).

---

## Self-Review (completed by plan author)

**Spec coverage vs the four selected areas + "something else":**
- Foundation hygiene + CI → A1 (commit), A2 (GitHub Actions), A3 (docs refresh = the "something else" doc-truth gap). Merge-to-master/remote is a flagged human checkpoint (outward-facing, owner's call).
- LLM output reliability → B1 (format + the latent `user_prompt` bug), B2 (schemas/parser), B3/B4/B5 (analyst/judge/strategist validate + retry + explicit parse-failure flag).
- Live-trading safety → C1/C2 (endpoint auth), C3 (flatten_and_halt), C4 (kill switch), C5 (startup reconciliation).
- Strategist guardrails → D1 (sample-size + in-sample + OOS), D2 (human-approval gate, default ON).

**Deliberately out of scope (call out to owner):** the evaluation/backtest harness that would prove edge (the single highest-value item, but a multi-day plan of its own — recommend it as the next plan); FinBERT Indian-market validation (needs hand-labelled data, not a code task); options hindsight-fill data storage (needs a tick/quote store — its own plan). D1's `_passes_guardrails` is wired to consume backtest metrics the harness will eventually produce, so the harness plan slots in cleanly.

**Placeholder scan:** none — every code step contains complete code; every test step contains runnable test bodies; every command states expected output.

**Type/name consistency:** `parse_llm_json(raw, Model)` signature identical across B2–B5; `AnalystSignal`/`JudgeVerdict`/`StrategistSuggestion` field names match their `.model_dump()` consumers; `flatten_and_halt()`/`reconcile()` names match their router callers and tests; `_passes_guardrails(baseline, modified, oos, trade_count)` signature identical in D1 definition and D2 caller; `require_api_key` dependency name matches import in router.
