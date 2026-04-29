# AI Agent Framework — Design Spec

**Date:** 2026-04-29
**Sub-project:** 2 of N
**Status:** Draft
**Depends on:** Sub-project 1 (Broker Abstraction) ✅

---

## 1. Purpose

Build the autonomous AI agent layer for KALYX. Each broker account gets a self-contained agent pod that analyzes markets, debates trades, enforces risk, executes orders, remembers outcomes, and optimizes strategies — all without human intervention.

### What This Sub-project Delivers

- `BaseAgent` class + `LLMRouter` (two-tier: quick/deep)
- `AgentPod` — per-account agent container with lifecycle management
- `AnalystAgent` — reads market, emits signals
- `DebateAgent` (Bullish + Bearish) + `JudgeAgent` — multi-model debate with anonymization
- `GuardianAgent` — risk checks (mostly math, not LLM)
- `ExecutorAgent` — places orders via BrokerAdapter, logs via DecisionLogger
- `MemoryAgent` — stores outcomes, fills hindsight, recalls learnings
- `StrategistAgent` — overnight fixed-budget optimization loop
- Agent prompts as hot-reloadable markdown files
- Redis Streams infrastructure for cross-pod communication
- Extended accounts.yaml with agent config

### What This Sub-project Does NOT Deliver

- Master Orchestrator / cross-pod coordination (SP5)
- Memory Mesh / cross-account memory queries (SP5)
- Cross-signal correlation engine (SP3)
- pgvector semantic search (SP3)
- Additional broker adapters (SP4)
- Frontend agent dashboard (SP6)

### Patterns Adopted from Open Source

- **TradingAgents** — bull/bear debate, memory reflections, structured data flows
- **WorldMonitor** — local-first AI, multi-source aggregation
- **Autoresearch** (Karpathy) — fixed-budget experiments for strategy optimization, markdown-as-program for agent prompts, single-file constraint per agent scope
- **LLM Council** (Karpathy) — multi-model debate (different models per side), anonymous peer review, chairman synthesis

---

## 2. Architecture

### 2.1 Pod Diagram

```
┌─────────────────── AgentPod (per account) ───────────────────┐
│                                                               │
│  ┌──────────┐    ┌─────────────────┐    ┌──────────┐         │
│  │ ANALYST  │───→│ DEBATE          │───→│ GUARDIAN │         │
│  │ (quick)  │    │ Bull (model A)  │    │ (math)   │         │
│  │          │    │ Bear (model B)  │    │          │         │
│  │ reads    │    │ Judge (model C) │    │ approves │         │
│  │ market   │    │ anonymized      │    │ or blocks│         │
│  └──────────┘    └─────────────────┘    └────┬─────┘         │
│                                              │                │
│                                    ┌─────────▼─────────┐     │
│                                    │ EXECUTOR           │     │
│                                    │ (no LLM)           │     │
│                                    │ BrokerAdapter +    │     │
│                                    │ DecisionLogger     │     │
│                                    └─────────┬─────────┘     │
│                                              │                │
│  ┌──────────┐    ┌──────────┐               │                │
│  │STRATEGIST│    │ MEMORY   │←──────────────┘                │
│  │ (deep)   │    │ (deep)   │                                │
│  │ overnight│    │ recall + │                                │
│  │ optimize │    │ hindsight│                                │
│  └──────────┘    └──────────┘                                │
│                                                               │
│  Shared: LLMRouter, DecisionLogger, TelegramAlertService     │
├───────────────────────────────────────────────────────────────┤
│  Redis Streams: publish signals + subscribe to orchestrator   │
└───────────────────────────────────────────────────────────────┘
```

### 2.2 File Structure

```
backend/app/
├── agents/                      # REFACTORED — was simple service, now full framework
│   ├── __init__.py
│   ├── base.py                  # BaseAgent ABC, AgentContext, AgentOutput
│   ├── llm_router.py            # LLMRouter (two-tier: quick/deep)
│   ├── pod.py                   # AgentPod — per-account container
│   ├── analyst.py               # AnalystAgent
│   ├── debate.py                # DebateAgent (Bullish/Bearish) + JudgeAgent
│   ├── guardian.py              # GuardianAgent (risk math)
│   ├── executor.py              # ExecutorAgent (adapter + logger)
│   ├── memory.py                # MemoryAgent (recall, hindsight, session review)
│   ├── strategist.py            # StrategistAgent (overnight optimization)
│   ├── streams.py               # Redis Streams pub/sub wrapper
│   ├── router.py                # FastAPI endpoints (existing, updated)
│   ├── service.py               # DEPRECATED — replaced by pod system
│   └── llm_providers.py         # DEPRECATED — replaced by llm_router.py
├── prompts/                     # Agent prompts as markdown (hot-reloadable)
│   ├── defaults/
│   │   ├── analyst.md
│   │   ├── bullish.md
│   │   ├── bearish.md
│   │   ├── judge.md
│   │   ├── memory.md
│   │   └── strategist.md
│   └── {account_name}/          # per-account overrides (optional)
│       └── analyst.md
└── ...
```

---

## 3. Agent Core

### 3.1 BaseAgent

```python
class BaseAgent(ABC):
    name: str
    role: str
    llm_tier: str                    # "quick", "deep", or "none"
    account_name: str
    llm_router: LLMRouter
    system_prompt: str               # loaded from markdown file

    async def run(self, context: AgentContext) -> AgentOutput
    async def think(self, prompt: str, tier: str | None = None) -> str
    def load_prompt(self, prompts_dir: str) -> str
    def reload_prompt(self) -> None   # hot-reload from file
```

### 3.2 AgentContext

Shared state passed through the evaluation cycle within a pod.

```python
@dataclass
class AgentContext:
    account_name: str
    symbol: str
    market_state: dict              # LTP, indicators, OI, volume
    positions: list[Position]
    margins: MarginInfo
    recent_decisions: list[dict]    # last N decisions for this symbol from DecisionLog
    memory_recall: list[dict]       # relevant past learnings from MemoryAgent
    signals: dict                   # analyst output
    debate_result: dict | None      # bull/bear/judge outcome
    guardian_verdict: dict | None   # ALLOW/BLOCK + reason
    config: dict                    # account agent config from yaml
```

### 3.3 AgentOutput

```python
@dataclass
class AgentOutput:
    agent_name: str
    action: str                     # SIGNAL, ARGUE, JUDGE, ALLOW, BLOCK, EXECUTE, RECALL, OPTIMIZE
    data: dict                      # agent-specific output
    reasoning: str
    confidence: float               # 0.0 - 1.0
    llm_tier_used: str | None       # which model was used
    latency_ms: float               # how long agent took
```

### 3.4 LLMRouter

Replaces existing `LLMProvider` / `get_llm_provider()`.

```python
class LLMRouter:
    def __init__(self, config: dict):
        self._quick = OllamaProvider(model=config["quick_model"], base_url=config["ollama_base_url"])
        self._deep = OllamaProvider(model=config["deep_model"], base_url=config["ollama_base_url"])
        self._models: dict[str, OllamaProvider] = {}  # named models for debate

    async def generate(self, prompt: str, system_prompt: str = "", tier: str = "quick") -> str
    async def generate_with_model(self, prompt: str, system_prompt: str, model_name: str) -> str
    
    def register_model(self, name: str, model: str) -> None
        """Register named model for debate (e.g., 'bullish_model': 'deepseek-v4-flash')."""
```

Config:
```yaml
llm:
  quick_model: deepseek-v4-flash
  deep_model: kimi-k2.6
  ollama_base_url: http://localhost:11434
```

---

## 4. Agent Roles

### 4.1 AnalystAgent

**Tier:** quick
**Runs:** Every eval cycle (configurable interval, default 5 min)
**Input:** Market data (LTP, indicators, OI, volume) + memory recall
**Output:** Signal (BUY/SELL/HOLD) + reasoning + confidence

```python
class AnalystAgent(BaseAgent):
    llm_tier = "quick"
    
    async def run(self, context: AgentContext) -> AgentOutput:
        # 1. Build prompt with market data + memory context
        # 2. Call LLM
        # 3. Parse signal, confidence, reasoning from response
        # 4. Return AgentOutput(action="SIGNAL", data={"signal": "BUY", ...})
```

If signal is HOLD → log as SKIPPED decision, move to next symbol.
If signal is BUY/SELL → proceed to debate.

### 4.2 Debate: Bullish + Bearish + Judge

**Multi-model debate** (LLM Council pattern). Different models argue different sides. Judge evaluates anonymized arguments.

```python
class DebateAgent(BaseAgent):
    """Argues one side of a trade. Bullish or Bearish."""
    llm_tier = "quick"  # but uses specific named model from config
    side: str  # "bullish" or "bearish"
    
    async def run(self, context: AgentContext) -> AgentOutput:
        # Uses debate.bullish_model or debate.bearish_model
        # Prompt: "Given this signal and market data, argue {FOR/AGAINST} this trade"
        # Returns argument text + conviction score

class JudgeAgent(BaseAgent):
    """Evaluates anonymized bull/bear arguments. Makes final call."""
    llm_tier = "deep"  # uses judge_model
    
    async def run(self, context: AgentContext) -> AgentOutput:
        bull_arg = context.debate_result["bullish"]
        bear_arg = context.debate_result["bearish"]
        
        # Anonymize: strip model names, randomize order
        args = self._anonymize(bull_arg, bear_arg)
        
        # Judge prompt: "Two analysts disagree. Argument A: ... Argument B: ... Your verdict?"
        # Returns: proceed/reject + adjusted confidence + reasoning
```

**Debate config:**
```yaml
debate:
  enabled: true
  max_rounds: 1
  bullish_model: deepseek-v4-flash
  bearish_model: kimi-k2.6
  judge_model: deepseek-v4-pro
  anonymize: true
  skip_for_exits: true    # don't debate exit signals
```

When debate disabled or skip_for_exits: analyst signal goes directly to guardian.

### 4.3 GuardianAgent

**Tier:** none (math, no LLM)
**Runs:** Before every order
**Input:** Signal/verdict + positions + margins + risk config

```python
class GuardianAgent(BaseAgent):
    llm_tier = "none"
    
    async def run(self, context: AgentContext) -> AgentOutput:
        checks = []
        
        # 1. Daily loss limit
        if daily_pnl < -config["max_loss_day"]:
            return AgentOutput(action="BLOCK", data={"reason": "daily_loss_exceeded"})
        
        # 2. Capital usage
        if capital_usage_pct > config["max_capital_pct"]:
            return AgentOutput(action="BLOCK", data={"reason": "capital_limit"})
        
        # 3. Trade count
        if daily_trades >= config["max_trades_day"]:
            return AgentOutput(action="BLOCK", data={"reason": "trade_count_limit"})
        
        # 4. Minimum confidence
        if confidence < config["min_confidence"]:
            return AgentOutput(action="BLOCK", data={"reason": "low_confidence"})
        
        # 5. Position concentration (no more than X% in one symbol)
        # 6. Correlated exposure check
        
        return AgentOutput(action="ALLOW", data={"position_size": calculated_size})
```

Guardian also computes position size based on confidence:
- confidence 0.6-0.7 → 1 lot
- confidence 0.7-0.8 → 2 lots
- confidence 0.8-0.9 → 3 lots
- confidence 0.9+ → max lots (from config)

### 4.4 ExecutorAgent

**Tier:** none (no LLM)
**Runs:** When guardian allows

```python
class ExecutorAgent(BaseAgent):
    llm_tier = "none"
    
    async def run(self, context: AgentContext) -> AgentOutput:
        order = UnifiedOrder(
            symbol=context.symbol,
            exchange=..., segment=...,
            transaction_type=context.signals["signal"],
            quantity=context.guardian_verdict["position_size"],
            order_type="MARKET",
            product="MIS",
            context=TradeContext(
                strategy_id=...,
                account_name=context.account_name,
                signals=context.signals,
                market_state=context.market_state,
                reasoning=context.debate_result["reasoning"] if context.debate_result else context.signals["reasoning"],
                confidence=context.guardian_verdict.get("adjusted_confidence", context.signals["confidence"]),
            ),
        )
        
        result = await self.adapter.place_order(order)
        
        await self.decision_logger.log_decision(
            account_name=context.account_name,
            symbol=context.symbol,
            signal=context.signals["signal"],
            action=DecisionAction.EXECUTED,
            confidence=order.context.confidence,
            reasoning=order.context.reasoning,
            market_state=context.market_state,
            context=order.context,
        )
        
        return AgentOutput(action="EXECUTE", data={"order_id": result.broker_order_id})
```

### 4.5 MemoryAgent

**Tier:** deep
**Runs:** After trade closes + end-of-session

```python
class MemoryAgent(BaseAgent):
    llm_tier = "deep"
    
    async def store_outcome(self, decision_id: int, entry_price: float, exit_price: float, pnl: float) -> None:
        """Called when trade closes."""
        # 1. Get original DecisionLog entry
        # 2. Calculate outcome_if_taken (for blocked/skipped) or outcome_actual (for executed)
        # 3. Fill hindsight via decision_logger.fill_hindsight()
        # 4. Generate reflection via LLM:
        #    Input: original reasoning + market state + actual outcome
        #    Output: "Learning: RSI oversold worked but VIX was low. When VIX > 18, skip RSI entries."
        # 5. Store reflection as tagged learning in DecisionLog
    
    async def recall(self, symbol: str, strategy_id: int | None, market_state: dict) -> list[dict]:
        """Query relevant past decisions + learnings for current setup."""
        # SQL: WHERE symbol=X AND strategy_id=Y AND was_correct IS NOT NULL
        # ORDER BY timestamp DESC LIMIT 10
        # Return decisions with outcomes + reflections
        # Injected into Analyst/Judge prompts
    
    async def end_of_session_review(self) -> dict:
        """Post-market-close review. Fill hindsight on skipped/blocked decisions."""
        # 1. Get all today's decisions
        # 2. For SKIPPED/BLOCKED: query current LTP, calculate what would have happened
        # 3. Fill hindsight
        # 4. Generate session summary via LLM
        # 5. Send Telegram daily report
        # 6. Return summary dict
```

### 4.6 StrategistAgent

**Tier:** deep
**Runs:** Scheduled (overnight, configurable)

```python
class StrategistAgent(BaseAgent):
    llm_tier = "deep"
    
    async def overnight_optimization(self) -> list[dict]:
        """Autoresearch pattern: fixed-budget experiments."""
        results = []
        
        strategies = self.get_strategies_ranked_by_performance()
        
        for experiment in range(self.config["max_experiments_per_night"]):
            worst = strategies[-1]
            
            # 1. Ask LLM to suggest ONE parameter change
            memory_context = await self.memory.recall(symbol=None, strategy_id=worst.id, market_state={})
            suggestion = await self.think(f"""
                Strategy '{worst.name}': win_rate={worst.win_rate}, sharpe={worst.sharpe}
                Past learnings: {memory_context}
                Suggest ONE specific parameter change to improve.
            """)
            
            # 2. Apply to copy
            modified = self.apply_suggestion(worst, suggestion)
            
            # 3. Fixed-duration paper backtest
            baseline = await self.backtest(worst, duration_min=self.config["experiment_duration_min"])
            modified_result = await self.backtest(modified, duration_min=self.config["experiment_duration_min"])
            
            # 4. Keep or discard
            kept = modified_result.sharpe > baseline.sharpe
            if kept:
                self.apply_to_live(modified)
            
            results.append({
                "strategy": worst.name,
                "suggestion": suggestion,
                "baseline_sharpe": baseline.sharpe,
                "modified_sharpe": modified_result.sharpe,
                "kept": kept,
            })
            
            self.decision_logger.log_decision(
                account_name=self.account_name,
                symbol="STRATEGY_OPT",
                signal="OPTIMIZE",
                action=DecisionAction.EXECUTED if kept else DecisionAction.SKIPPED,
                confidence=1.0,
                reasoning=f"{'Kept' if kept else 'Discarded'}: {suggestion}",
                market_state={"experiment": experiment},
            )
        
        return results
```

---

## 5. AgentPod

### 5.1 Lifecycle

```python
class AgentPod:
    def __init__(self, account_name: str, adapter: BrokerAdapter, config: dict):
        self.account_name = account_name
        self.adapter = adapter
        self.config = config
        
        # Initialize LLM router
        self.llm_router = LLMRouter(config["agents"]["llm"])
        
        # Register debate models
        debate_cfg = config["agents"].get("debate", {})
        if debate_cfg.get("enabled"):
            self.llm_router.register_model("bullish", debate_cfg["bullish_model"])
            self.llm_router.register_model("bearish", debate_cfg["bearish_model"])
            self.llm_router.register_model("judge", debate_cfg["judge_model"])
        
        # Initialize agents
        prompts_dir = config["agents"].get("prompts_dir", "prompts/defaults")
        self.analyst = AnalystAgent(llm_router=self.llm_router, prompts_dir=prompts_dir, account_name=account_name)
        self.bullish = DebateAgent(side="bullish", llm_router=self.llm_router, prompts_dir=prompts_dir, account_name=account_name)
        self.bearish = DebateAgent(side="bearish", llm_router=self.llm_router, prompts_dir=prompts_dir, account_name=account_name)
        self.judge = JudgeAgent(llm_router=self.llm_router, prompts_dir=prompts_dir, account_name=account_name)
        self.guardian = GuardianAgent(config=config["agents"]["guardian"], account_name=account_name)
        self.executor = ExecutorAgent(adapter=adapter, decision_logger=..., account_name=account_name)
        self.memory = MemoryAgent(llm_router=self.llm_router, db=..., prompts_dir=prompts_dir, account_name=account_name)
        self.strategist = StrategistAgent(llm_router=self.llm_router, memory=self.memory, prompts_dir=prompts_dir, account_name=account_name)
        
        self._running = False
        self._eval_task: asyncio.Task | None = None
    
    async def start(self) -> None:
        """Login adapter, start evaluation loop."""
        await self.adapter.login(self._get_credentials())
        self._running = True
        self._eval_task = asyncio.create_task(self._eval_loop())
    
    async def stop(self) -> None:
        """Stop evaluation loop, run end-of-session review."""
        self._running = False
        if self._eval_task:
            self._eval_task.cancel()
        summary = await self.memory.end_of_session_review()
        await self.adapter.logout()
    
    async def _eval_loop(self) -> None:
        """Main loop — runs evaluation cycles at configured interval."""
        interval = self.config["agents"]["eval_interval_seconds"]
        while self._running:
            try:
                await self.run_cycle()
            except Exception as e:
                logger.error(f"[{self.account_name}] Eval cycle failed: {e}")
                await self.alert_service.send_warning(self.account_name, f"Eval cycle error: {e}")
            await asyncio.sleep(interval)
```

### 5.2 Evaluation Cycle

```python
    async def run_cycle(self) -> None:
        """One evaluation cycle — analyze all watched symbols."""
        positions = await self.adapter.get_positions()
        margins = await self.adapter.get_margins()
        
        for symbol in self.config["agents"]["watched_symbols"]:
            # Build context
            market_state = await self._get_market_state(symbol)
            memory_recall = await self.memory.recall(symbol, strategy_id=None, market_state=market_state)
            recent_decisions = self._get_recent_decisions(symbol)
            
            context = AgentContext(
                account_name=self.account_name,
                symbol=symbol,
                market_state=market_state,
                positions=positions,
                margins=margins,
                recent_decisions=recent_decisions,
                memory_recall=memory_recall,
                signals={},
                debate_result=None,
                guardian_verdict=None,
                config=self.config["agents"],
            )
            
            # 1. Analyst evaluates
            analyst_output = await self.analyst.run(context)
            context.signals = analyst_output.data
            
            signal = analyst_output.data.get("signal", "HOLD")
            
            if signal == "HOLD":
                await self._log_decision(context, DecisionAction.SKIPPED, "no_signal", analyst_output)
                continue
            
            # 2. Debate (if enabled and not exit)
            debate_cfg = self.config["agents"].get("debate", {})
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
                    await self._log_decision(context, DecisionAction.BLOCKED, "judge_rejected", judge_output)
                    continue
                
                # Judge may adjust confidence
                context.signals["confidence"] = judge_output.confidence
            
            # 3. Guardian checks
            guardian_output = await self.guardian.run(context)
            context.guardian_verdict = guardian_output.data
            
            if guardian_output.action == "BLOCK":
                await self._log_decision(context, DecisionAction.BLOCKED, guardian_output.data.get("reason", "guardian"), guardian_output)
                continue
            
            # 4. Execute
            executor_output = await self.executor.run(context)
```

---

## 6. Redis Streams (Cross-Pod Infrastructure)

Laid now for SP5 Orchestrator to plug into later.

```python
# backend/app/agents/streams.py

class AgentStreamPublisher:
    """Publishes pod events to Redis Streams."""
    
    async def publish_signal(self, account_name: str, signal_data: dict) -> None:
        """Publish to stream:signals:{account_name}"""
    
    async def publish_decision(self, account_name: str, decision_data: dict) -> None:
        """Publish to stream:decisions:{account_name}"""
    
    async def publish_alert(self, account_name: str, alert_data: dict) -> None:
        """Publish to stream:alerts:{account_name}"""

class AgentStreamSubscriber:
    """Subscribes to Redis Streams. Used by future Orchestrator."""
    
    async def subscribe(self, stream_name: str, callback: Callable) -> None:
    async def subscribe_all_signals(self, callback: Callable) -> None:
    async def unsubscribe(self, stream_name: str) -> None:
```

Stream naming:
- `stream:signals:{account_name}` — analyst signals
- `stream:decisions:{account_name}` — all decision log events
- `stream:alerts:{account_name}` — alerts
- `stream:orchestrator:commands` — future: orchestrator → pods

---

## 7. Agent Prompts (Markdown Files)

### 7.1 Directory Structure

```
backend/prompts/
├── defaults/
│   ├── analyst.md
│   ├── bullish.md
│   ├── bearish.md
│   ├── judge.md
│   ├── memory.md
│   └── strategist.md
└── {account_name}/         # optional per-account overrides
    └── analyst.md           # overrides defaults/analyst.md for this account
```

### 7.2 Prompt Loading

Agent loads prompt on init:
1. Check `prompts/{account_name}/{role}.md` — use if exists
2. Else fall back to `prompts/defaults/{role}.md`
3. `reload_prompt()` re-reads from file — hot-reload without restart

### 7.3 Example: defaults/analyst.md

```markdown
You are a market analyst for {segment} trading on {exchange}.

Your job: analyze current market conditions and emit a trading signal.

## Input
You receive:
- Current LTP, OHLC, volume, OI (if F&O)
- Technical indicators (RSI, MACD, Bollinger Bands)
- Recent decisions and their outcomes for this symbol
- Learnings from past trades (memory recall)

## Output Format
Respond in this exact JSON format:
{
  "signal": "BUY" | "SELL" | "HOLD",
  "confidence": 0.0 to 1.0,
  "reasoning": "explanation",
  "entry_price": suggested price or null,
  "stoploss": suggested SL or null,
  "target": suggested target or null
}

## Rules
- Only emit BUY/SELL when confidence > 0.5
- HOLD is the default — only trade when setup is clear
- Factor in past learnings: if similar setup lost before, lower confidence
- Never ignore risk: mention stoploss for every BUY/SELL
```

---

## 8. Extended Account Configuration

```yaml
# config/accounts.yaml
accounts:
  zerodha_fno:
    broker: zerodha
    segments: [FNO]
    mode: paper
    credentials_env:
      api_key: ZERODHA_API_KEY
      api_secret: ZERODHA_API_SECRET
    
    agents:
      enabled: true
      eval_interval_seconds: 300
      watched_symbols: ["NIFTY", "BANKNIFTY"]
      
      debate:
        enabled: true
        max_rounds: 1
        bullish_model: deepseek-v4-flash
        bearish_model: kimi-k2.6
        judge_model: deepseek-v4-pro
        anonymize: true
        skip_for_exits: true
      
      guardian:
        max_loss_day: 50000
        max_capital_pct: 80
        max_trades_day: 50
        min_confidence: 0.6
        max_position_concentration_pct: 30
      
      strategist:
        enabled: true
        optimization_schedule: "02:00"
        experiment_duration_min: 30
        max_experiments_per_night: 10
      
      memory:
        recall_limit: 10
        session_review_enabled: true
      
      llm:
        quick_model: deepseek-v4-flash
        deep_model: kimi-k2.6
        ollama_base_url: http://localhost:11434
      
      prompts_dir: prompts/zerodha_fno/

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
      llm:
        quick_model: deepseek-v4-flash
        deep_model: deepseek-v4-flash
        ollama_base_url: http://localhost:11434
      prompts_dir: prompts/defaults/
```

---

## 9. Communication Patterns

### Within Pod (Direct Async Calls)
```
analyst.run(ctx) → returns AgentOutput
bullish.run(ctx) → returns AgentOutput  
bearish.run(ctx) → returns AgentOutput
judge.run(ctx) → returns AgentOutput
guardian.run(ctx) → returns AgentOutput
executor.run(ctx) → returns AgentOutput
```
Simple. Fast. No serialization overhead.

### Between Pods (Redis Streams — infrastructure only in SP2)
```
pod.publish_signal(signal_data)     # → stream:signals:{account}
pod.publish_decision(decision_data) # → stream:decisions:{account}
```
Orchestrator (SP5) subscribes to all streams.

---

## 10. Error Handling

### Agent Errors
- If any agent fails, log error + continue to next symbol
- If LLM call fails (Ollama down), retry 3x, then skip symbol + alert Telegram
- If adapter call fails (broker down), retry 3x → pause pod + alert (existing SP1 logic)
- Guardian never fails — it's math. If it throws, treat as BLOCK (fail-safe)

### Pod Crash Recovery
- Pod catches all exceptions in eval loop, logs, continues
- If pod process dies, supervisor/systemd restarts it
- On restart: re-login adapter, resume eval loop
- No state to recover — DecisionLog in DB, positions in broker

---

## 11. Migration Plan

### What Changes in Existing Code

| File | Change |
|------|--------|
| `app/agents/service.py` | DEPRECATED — replaced by pod system. Keep for backward compat. |
| `app/agents/llm_providers.py` | DEPRECATED — replaced by llm_router.py. Keep providers for backward compat. |
| `app/agents/router.py` | Updated to expose pod status, start/stop endpoints |
| `app/main.py` | Initialize AgentPods from accounts.yaml on startup |
| `config/accounts.yaml` | Extended with agents section |

### What Stays Unchanged
- Broker abstraction (SP1) — unchanged
- Decision logging — unchanged, agents use existing DecisionLogger
- Telegram alerting — unchanged, agents use existing service
- Strategy engine (`strategies/`) — unchanged, Strategist reads from it
- Frontend — unchanged

---

## 12. Testing Strategy

1. **Unit tests per agent:** Mock LLMRouter, verify prompt construction + output parsing
2. **Integration test:** PaperAdapter + full pod eval cycle end-to-end (analyst → debate → guardian → executor)
3. **LLMRouter tests:** Mock Ollama HTTP, verify tier routing + model selection
4. **Guardian tests:** Pure math — exhaustive edge cases (all block conditions)
5. **Memory tests:** Mock DB, verify recall queries + hindsight fill logic
6. **Strategist tests:** Mock backtest, verify keep/discard logic
7. **Debate tests:** Verify anonymization, multi-round, skip-for-exits
8. **Redis Streams tests:** Mock Redis, verify publish/subscribe

---

## 13. Success Criteria

1. AgentPod starts, runs eval cycles at configured interval against PaperAdapter
2. Analyst emits signals based on LLM analysis of market data
3. Multi-model debate runs with anonymization when enabled
4. Guardian blocks trades that violate risk limits (math-based, no LLM)
5. Executor places orders via BrokerAdapter, logs via DecisionLogger
6. Memory recalls past decisions, fills hindsight after trade closes
7. Strategist runs overnight optimization loop, keeps/discards based on backtest comparison
8. Agent prompts load from markdown files, hot-reloadable
9. Redis Streams publish signals/decisions (subscriber tested but Orchestrator deferred)
10. All existing SP1 tests still pass (no regression)
11. Full pod eval cycle works end-to-end with PaperAdapter + mocked Ollama
