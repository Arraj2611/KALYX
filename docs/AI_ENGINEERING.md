# KALYX — AI Engineering Reference

This document describes everything in the repository related to **AI, LLMs, agents, and the intelligence layer**: architecture, configuration, APIs, dependencies, tests, and developer tooling. It is the canonical in-repo reference for AI engineering on this project.

---

## 1. Executive summary

| Area | What it is |
|------|----------------|
| **Intelligence layer** | Multi-source market context: registry of `DataSource` implementations, correlation engine, FinBERT sentiment on news, composite signal quality (ISQ), Redis-backed cache. Feeds **`AnalystAgent`** in trading pods when enabled. |
| **Agent framework (pods)** | Per-account **`AgentPod`**: analyst → optional debate/judge → guardian → executor, with memory and strategist hooks. LLM calls for the pod go through **`LLMRouter`** (Ollama HTTP API, configured per account YAML). |
| **REST LLM service** | **`AgentService`** exposes one-off LLM tasks (market analysis, strategy critique, trade explanation) via **`/api/agents`**, using **`LLMProvider`** abstraction: OpenAI, Anthropic, or Ollama from **environment** settings. |
| **ML in the stack** | **FinBERT** (`transformers` pipeline) for **classification** sentiment on news — not embeddings, not RAG. |
| **Not present** | LangChain, vector DBs, embedding indexes, semantic RAG pipelines, or a dedicated “chat UI” in the Next.js frontend for these backends. |

There are **two LLM paths**: pod pipeline (YAML + Ollama via `LLMRouter`) vs. HTTP agent endpoints (env `LLM_PROVIDER` + `llm_providers.py`).

---

## 2. Repository map (AI-related)

### 2.1 Backend — intelligence (`backend/app/intelligence/`)

| Path | Role |
|------|------|
| `base.py` | `DataSource` ABC, `RateLimitError`, `SourceUnavailableError`. |
| `registry.py` | `DataSourceRegistry`, vendor chains, `TOOLS_CATEGORIES`, `fetch` / `fetch_with_meta`. |
| `context.py` | `IntelligenceContext` dataclass; `IntelligenceContextBuilder.build()` orchestrates registry, FinBERT, `CorrelationEngine`, `compute_isq`, Redis JSON cache (`intel:{account}:{symbol}`). |
| `correlation/engine.py` | `CorrelationEngine.run()` — collect → cluster → score → filter → trend → dedupe → `ConvergenceCard` list. |
| `correlation/adapters.py` | Domain adapters (equity, crypto, forex, cross-market). |
| `correlation/types.py` | `SignalEvidence`, `ConvergenceCard`. |
| `scoring/composite.py` | `SignalQuality`, `compute_isq`. |
| `scoring/weights.py` | `WEIGHT_PROFILES`. |
| `sentiment/finbert.py` | `FinBertSentiment` — `transformers` `pipeline("sentiment-analysis", model="ProsusAI/finbert")`. |
| `sources/*.py` | Concrete sources (e.g. yfinance, GDELT, Polymarket, news scraper, scrapling, MCP-backed broker sources). |

**Configuration file:** `backend/config/data_sources.yaml` — vendor chains and credential/env mapping (e.g. Polymarket).

**Wiring:** `backend/app/main.py` lifespan, when `INTELLIGENCE_ENABLED` is true, builds registry (subset of sources registered in code), `CorrelationEngine` + adapters, `FinBertSentiment`, `IntelligenceContextBuilder`, and passes `intelligence_builder` into each **`AgentPod`** that has `agents.enabled` in account YAML.

**Consumption:** **`AnalystAgent`** calls `intelligence_builder.build(symbol, account_name)` and injects summaries into the user prompt. The module docstring in `context.py` references JudgeAgent; **debate/judge** paths in `debate.py` do not currently consume `IntelligenceContext` in code — only the analyst does.

### 2.2 Backend — agents (`backend/app/agents/`)

| Path | Role |
|------|------|
| `__init__.py` | Public exports: `BaseAgent`, `AgentContext`, `AgentOutput`, `AgentPod`, `LLMRouter`, etc. |
| `base.py` | `AgentContext`, `AgentOutput`, `BaseAgent` — prompt files under `{prompts_dir}/{account}/{name}.md` or `defaults/{name}.md`; `think()` uses `llm_router`. |
| `llm_router.py` | `LLMRouter` — **Ollama** `POST {ollama_base_url}/api/generate` via `httpx`; quick/deep tiers; `register_model` for debate personas. |
| `llm_providers.py` | `LLMProvider` ABC; `OpenAIProvider`, `AnthropicProvider`, `OllamaProvider`; `get_llm_provider()` from `settings.LLM_PROVIDER`. |
| `service.py` | `AgentService` — inline prompts for REST endpoints; uses `get_llm_provider().generate()`. |
| `pod.py` | `AgentPod` — wires LLM config from YAML, all agents, eval loop; optional `intelligence_builder`. |
| `analyst.py` | `AnalystAgent` — optional intelligence context + JSON trading signal from LLM. |
| `debate.py` | `DebateAgent`, `JudgeAgent` — council flow; optional per-model generation when debate enabled. |
| `memory.py` | `MemoryAgent` — DB recall + deep-tier reflections. |
| `strategist.py` | `StrategistAgent` — planning / deep-tier usage. |
| `guardian.py` | Risk checks — **no LLM**. |
| `executor.py` | Order placement — **no LLM**. |
| `router.py` | FastAPI routes under `/api/agents`. |
| `streams.py` | Optional Redis stream publishing for agent events. |

### 2.3 Prompts on disk

| Location | Contents |
|----------|----------|
| `backend/prompts/defaults/` | Markdown system/user templates: e.g. `analyst.md`, `bullish.md`, `bearish.md`, `judge.md`, `memory.md`, `strategist.md` (exact set may evolve). |

Resolution order is implemented in `BaseAgent` (account-specific override, then defaults).

### 2.4 API surface (AI)

Mounted in `main.py` with prefix **`/api/agents`** (OpenAPI also at `/api/docs`).

| Method | Path | Handler |
|--------|------|---------|
| POST | `/api/agents/market-analysis` | `AgentService.analyze_market` |
| POST | `/api/agents/strategy-critic` | `AgentService.critique_strategy` |
| POST | `/api/agents/trade-explanation` | `AgentService.explain_trade` |
| GET | `/api/agents/pods` | All pod statuses |
| GET | `/api/agents/pods/{account_name}` | One pod status |
| POST | `/api/agents/pods/{account_name}/start` | Start pod + eval loop |
| POST | `/api/agents/pods/{account_name}/stop` | Stop pod |
| POST | `/api/agents/pods/{account_name}/cycle` | Single eval cycle |

The **intelligence layer** has no separate public REST resource; it runs inside the backend and enriches the analyst inside pods when enabled.

### 2.5 Configuration and environment (`backend/app/config.py`)

AI-relevant settings (from env / `.env`):

| Variable | Purpose |
|----------|---------|
| `LLM_PROVIDER` | `openai` \| `anthropic` \| `ollama` — drives `AgentService` via `get_llm_provider()`. |
| `OPENAI_API_KEY` | OpenAI API key. |
| `ANTHROPIC_API_KEY` | Anthropic API key. |
| `OLLAMA_BASE_URL` | Ollama base URL (providers + related tooling). |
| `LLM_MODEL` | Model id for provider-based `AgentService` path. |
| `INTELLIGENCE_ENABLED` | Master switch for intelligence init in `main.py`. |
| `INTELLIGENCE_CONFIG_PATH` | Path to YAML (default `config/data_sources.yaml`). |
| `POLYMARKET_PRIVATE_KEY` | Polymarket signing (when used by sources). |
| `POLYMARKET_FUNDER_ADDRESS` | Polymarket funder address. |

**Account YAML** (`backend/config/accounts.yaml`): under `accounts.<name>.agents` — `enabled`, `llm` (e.g. `quick_model`, `deep_model`, `ollama_base_url`), `debate`, `guardian`, `prompts_dir`, etc. Pods are created only when `agents.enabled` is true.

### 2.6 Dependencies (`backend/requirements.txt`)

Relevant packages typically include: **`openai`**, **`anthropic`**, **`httpx`**, **`transformers`** (FinBERT), **`torch`** (as required by transformers), **`ollama`** (where used), plus FastAPI stack. There is **no LangChain** dependency in this project’s Python tree as of this document.

### 2.7 Tests

| Directory | Focus |
|-----------|--------|
| `backend/tests/intelligence/` | Registry, context builder, sources, correlation, scoring, FinBERT-related behavior. |
| `backend/tests/agents/` | Pod, LLM router, analyst, debate, memory, guardian, executor, streams, service/router integration patterns. |

---

## 3. Runtime flow (conceptual)

### 3.1 Trading pod (one symbol / one cycle)

1. **`AnalystAgent`** builds optional **`IntelligenceContext`** (if builder present and enabled at startup).
2. Analyst composes prompt (market state + intelligence sections) and calls **`LLMRouter`** (Ollama) at **quick** tier → parsed BUY/SELL/HOLD/EXIT JSON-style signal.
3. If **debate** enabled: bullish/bearish **`DebateAgent`** instances and **`JudgeAgent`** may run (model names registered on router).
4. **`GuardianAgent`** applies rule-based risk checks (no LLM).
5. **`ExecutorAgent`** places orders if allowed (no LLM).
6. **`MemoryAgent`** / **`StrategistAgent`** participate per pod configuration (memory recall, deep-tier planning).

### 3.2 REST “agent service” path

1. Client calls **`POST /api/agents/...`** with JSON body.
2. **`AgentService`** builds a string prompt and calls **`get_llm_provider()`** → **`generate()`** (OpenAI / Anthropic / Ollama per `LLM_PROVIDER`).
3. Response returned as API JSON (shape per endpoint).

---

## 4. Design and planning documents

| Path | Topic |
|------|--------|
| `docs/plans/2026-04-29-agent-framework.md` | Agent framework plan. |
| `docs/plans/2026-04-30-intelligence-layer.md` | Intelligence layer plan. |
| `docs/specs/2026-04-29-agent-framework-design.md` | Agent framework design spec. |

These may diverge slightly from code; **this `AI_ENGINEERING.md` + source** are the ground truth for “what runs today.”

---

## 5. Frontend (Next.js)

The **`frontend/`** app is a trading dashboard (dashboard, strategies, auth). It does **not** currently bundle AI SDKs (`@ai-sdk/*`, Vercel AI SDK, streaming chat to `/api/agents`). AI capabilities are **backend-first**; any UI integration would call the FastAPI base URL directly (CORS is configured in backend settings for local dev origins).

---

## 6. Developer tooling (MCP, Cursor, Claude)

| Artifact | Purpose |
|----------|---------|
| `.cursor/mcp.json` / `.mcp.json` | MCP server config — e.g. **`code-review-graph`** (`uvx code-review-graph serve`) for structural code exploration and review workflows. |
| `AGENTS.md` / `CLAUDE.md` | Project rules for agents: prefer graph MCP tools before blind grep for exploration. |
| `.claude/skills/` | Optional Claude skills in this workspace (e.g. explore-codebase, review patterns). |

These improve **how** you work on AI code; they are not runtime dependencies of the trading system.

---

## 7. Glossary

| Term | Meaning in KALYX |
|------|------------------|
| **AgentPod** | Per-account orchestrator for the full LLM + risk + execution pipeline. |
| **LLMRouter** | Ollama-only HTTP client for pod agents; tiered models. |
| **LLMProvider** | Pluggable async client for `AgentService` (OpenAI / Anthropic / Ollama). |
| **IntelligenceContext** | Single snapshot: correlations, news, sentiment, Polymarket odds, ISQ, latencies, etc. |
| **ISQ** | Composite **intrinsic / signal quality** style score from `scoring/composite.py`. |
| **DataSource** | Pluggable fetcher registered on **`DataSourceRegistry`**. |

---

## 8. Changelog of this document

- **2026-05-11** — Initial consolidated AI engineering reference (no Next.js in-app viewer; repo markdown only).

When you add new agents, sources, or LLM providers, update the tables and flows in sections **2**, **3**, and **5** in the same PR.
