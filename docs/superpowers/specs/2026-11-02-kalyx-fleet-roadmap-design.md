# KALYX Fleet: Deep Agents Adoption Plan and Roadmap to the Full Desk Network

Date: 2026-11-02 | Branch: `feat/broker-abstraction` | Status: draft for approval

Everything here is a proposal unless marked **(verified)**, meaning I checked it in the repo, on this
machine, or in the vendor's own documentation on 2026-11-02. Numbers marked *(proposal)* are my
starting points and must be re-set from measured data.

---

## 1. Intent and why

KALYX is meant to run unattended. The owner will trust it with full autonomy only if everything that
moves a market is analysed. The fleet therefore has to:

1. notice relevant events anywhere in the world quickly, including events outside the two traded
   markets (India, US) that reach them through currencies, commodities, flows or sentiment;
2. separate real signal from noise, rumour and false alarms, and learn from the alarms that were false;
3. judge, with the live state of the related markets in view, whether a move can actually happen and
   whether it is worth a shot;
4. act only inside hard limits that no model can override;
5. learn from every outcome, including the trades it did not take.

**Anti-goals** (a failure even if it technically works):

- a large, impressive fleet that does not make money after costs;
- any model inside the order, risk or kill-switch path;
- trading on a single unverified headline;
- silent failure: a dead feed or desk that looks healthy;
- unbounded compute: a desk that costs more than it adds.

## 2. Rules that never bend

| # | Rule | Why |
|---|---|---|
| R1 | Only plain code places, changes or cancels orders. Guardian, quant gate, position manager and kill switch are code. | A model in the money path can be talked into anything. |
| R2 | All outside text is untrusted data. It is delimited, never obeyed, and readers of news have no tool with side effects. | Fake headlines have crashed simulated markets run by LLM agents (SoK, arXiv 2609.19705, as summarised by the search tool). |
| R3 | Agent output that can lead to action is schema-validated structured data. Free text never triggers anything. | Parse failures must degrade to "do nothing". |
| R4 | Every claim carries provenance: source, tier, link, hash, time. Every position is tied to story IDs; a denial of the story triggers exit review. | The owner asked for false alarms to be caught "later". |
| R5 | Fail closed. No price, no data or no model means no new risk. Stops and exits must work with every model down. | Today stops are plain code but are checked only once per cycle (60 s configured, 300 s default), and a missing price only logs a warning. Phase 0 adds a faster dedicated monitor and broker-side stops. |
| R6 | Every decision is logged, including those not taken. | Existing owner rule. |
| R7 | Shadow, then paper, then micro-live, then scale. Each step has numeric gates. | Owner wants no "learning phase" losses. |
| R8 | A desk earns its compute: measured lift or a closed coverage gap, otherwise it sleeps or is retired. | Existing "efficiency first" rule. |
| R9 | The agent runtime sits behind our own interface, versions are pinned, and a plain-code fallback exists. | Deep Agents is young (0.7.x). |
| R10 | Humans keep control: kill switch, approval gate for the first live trades, and agent memory/skill changes are proposed by the system and approved by a person until trust is earned. | Self-modifying live behaviour is the largest unmeasured risk. |

## 3. Where we are (verified 2026-11-02)

- One pod per account with 8 agents: Analyst, Bull, Bear, Judge, Guardian, Executor, Memory, Strategist.
- Core path fixed this week (commits `73957e1`..`6e3d758`): the model-call crash, the guardian await,
  enforced limits, EXIT handling, stop/target monitor, memory loop, daily P&L, paper price source.
  A real paper cycle ran with `llama3`. 341 backend tests pass.
- **Not done in the pod:** options support of any kind (see 6.7), market-hours gate, real lot sizes, broker-side stop orders, kill switch,
  auth on pod endpoints, cooldown after a stop-out, hindsight for skipped trades, Strategist scheduling.
- **News:** a prototype collector in `backend/spike/` scores headlines and, where it can reach them,
  full articles and NSE filings with Laya. Per row it keeps only derived data: link, hash, Laya's answers
  on headline and on full text, token counts and up to 12 numbers. **Full text is not stored.** The
  database holds 3,606 rows from 27 to 30 October; 79 were read in full, 19 more were filings in
  unsupported formats, the rest are headline-only Google News items **(verified 2026-11-02)**. Nothing
  is price-labeled, so there is no verdict on whether news helps. The collector stopped on 30 October
  when the app session restarted and has not run since. It is a separate process with its own Python
  environment and is **not connected to the pod**.
- **Desks, master, council, story ledger, quant gate, orchestrator, US broker:** none exist.
- `docs/ROADMAP.md` lists LangGraph, pgvector and Redis agent messaging under a completed sub-project.
  None is wired. It must be corrected (Section 12).

## 4. Target architecture

```
Sensors ──► Triage ──► Story ledger ──► Desks ──► Master + council ──► Quant gate ──► Execution ──► Nightly review
(code)     (Laya +     (Postgres,      (Deep      (Deep Agents,        (code)         & position     (Deep Agent +
           rules)      one record)     Agents)    gold stories only)                  manager (code)  code metrics)
                                          ▲                                                              │
                                          └──────── lessons, source scores, base rates ◄─────────────────┘
Reflex path: triage ─► risk cutter (code). It may only reduce or close risk, never add it.
```

| Component | Built as | Model | Side effects |
|---|---|---|---|
| Sensors (feeds, filings, prices, calendar, alt data) | plain async jobs | none | writes raw items |
| Triage | Laya + rules | local small; spike measured about 50 ms median and 95 ms p95 on headlines, about 0.4 s on full text | writes story status |
| Story ledger | Postgres tables + service | none | the single shared record |
| Reader / fact-checker | Deep Agent subagent | fast model | read-only tools |
| Desk head | Deep Agent | mid model | read-only tools, writes an assessment |
| Master and council | Deep Agents | strongest model | writes a verdict |
| Quant gate | code | none | approves or rejects size |
| Guardian, executor, position manager, kill switch | code (existing, extended) | none | orders |
| Nightly review | Deep Agent plus code metrics | strong model, batch | proposes memory/skill changes |
| Watchdog, coverage audit | mostly code | small summary model | alerts |

## 5. Deep Agents adoption plan

### 5.1 What it is (verified from vendor docs and PyPI)

`deepagents` 0.7.32 (released 2026-10-23), MIT, Python 3.11 or newer, built on LangChain `create_agent`
and the LangGraph runtime. It provides: a planning tool (`write_todos`); a virtual filesystem with
swappable backends (in-memory, disk, LangGraph store, composite); sync and async **subagents** with
isolated context by default, per-subagent tools, model and skills, and structured return via
`response_format`; **skills** as `SKILL.md` folders loaded progressively; `AGENTS.md` long-term memory;
history summarising and large-result offloading; `interrupt_on` human approval; MCP tools; durable
runs through a LangGraph checkpointer. It requires a chat model that supports **tool calling**.

### 5.2 Blocking finding: our installed local model cannot do tool calling (verified)

Ollama reports these capabilities on this machine:

| Model | Capabilities | Fit on the 8 GB RTX 4070 laptop GPU |
|---|---|---|
| `llama3` (8B, now configured for the pod) | completion only, **no tools** | fits |
| `gpt-oss:20b` | completion, tools, thinking | 13 GB, does not fit; runs partly on CPU, slowly |
| `llama2` | completion only | fits |

So Deep Agents cannot run on anything installed today. The existing pod analyst does not use tools, so
`llama3` stays valid there. The vendor's own model-evaluation table gives no guidance for small local
models. Phase 2 therefore starts with a model bake-off over tool-capable candidates (for example
`qwen3:8b`, `llama3.1:8b`, `gpt-oss:20b`, and a cloud model). I have not verified any of those tags or
their tool quality. Downloading them needs your approval (several GB each).

### 5.3 Integration boundary

New package `backend/fleet/` (the name is a proposal), **outside the app package and with its own environment**:

| Path | Purpose |
|---|---|
| `contracts.py` | Pydantic models: `Story`, `Evidence`, `Claim`, `DeskAssessment`, `CouncilMemo`, `CouncilVerdict`, `TradeThesis` |
| `ledger/` | SQLAlchemy models and service (Section 6.5), created through Alembic migrations |
| `runtime/` | `DeskRuntime` interface with two implementations: `DeepAgentsRuntime` and `PlainRuntime` (hand-built). This is what makes the Phase 2 A/B test and the fallback possible |
| `tools/` | Read-only tool registry. Each tool has typed input/output, a timeout and a call budget: `ledger_query`, `market_state`, `price_history`, `fetch_filing`, `calendar`, `base_rates`, `source_score`, `symbol_map` |
| `skills/` | `SKILL.md` packs per desk family (Section 5.4) |
| `desks/` | One YAML per desk: id, family, region/exchange, sources, schedule, wake triggers, model tier, skills, subagents, budgets |
| `triage/`, `council/`, `gate/`, `review/` | the matching stages |

**Why a separate package.** `deepagents` 0.7.32 requires `langchain>=1.4.7`, `langchain-core>=1.7.0`,
`langchain-anthropic>=1.7.6`, `langchain-google-genai>=4.4.2` and `langsmith>=0.14.12` (PyPI, verified).
The app pins `pydantic==2.5.0`, `anthropic==0.7.7`, `httpx==0.25.2` and `fastapi==0.104.1` (verified).
I have not tested the combination, but the gap is large enough that I assume a conflict. So the fleet
package and the app share **no Python imports**: they meet only through Postgres tables (`stories`,
`theses`, `risk_actions`) and Redis streams, with the contracts defined once in the ledger schema.
Alembic is pinned in `requirements.txt` but has no config or migrations directory (verified), so
Phase 0 sets it up; the ledger will change often.

**Process layout.** Laya needs torch 2.4 or newer and transformers 4.48 or newer; the app environment
has torch 2.3.1 on Python 3.12 and cannot import it (verified, Phase 0 findings). So:

1. **App and pods** (FastAPI, existing environment).
2. **Sensor and triage service** (the `backend/spike` environment, promoted to a service).
3. **Desk workers** (own environment: `deepagents`, `langchain`, `langgraph`, a Postgres checkpointer).
4. **Postgres** (ledger, run log, checkpoints), **Redis** (event streams), **LLM endpoint(s)**.

Events flow sensor, then ledger insert, then Redis stream `stories.new`, then the desks subscribed by
routing rule (symbol, region, topic), then `assessments`, then council for gold stories, then `verdicts`,
then quant gate, then the pod's executor. The pod only ever consumes a validated `TradeThesis`.

### 5.4 Standard desk anatomy

| Part | Content |
|---|---|
| **MO** (system prompt) | Role, scope, what "material" means for this desk, output contract, refusal rules. Stored as a file, versioned. |
| **Skills** | `SKILL.md` packs, each under about 5,000 tokens and 500 lines, descriptions that say when to use them. Examples: `read-earnings-release`, `read-central-bank-statement`, `read-exchange-filing`, `compare-to-consensus`, `read-through-sector`, `check-rumour-vs-confirmed`, region packs such as `japan-disclosure-tdnet`. Custom subagents do not inherit skills, so each lists its own. |
| **Tools** | Read-only from Section 5.3. No shell, no order tool, no network tool beyond the allowlisted fetcher. |
| **Subagents** | `reader` (extract claims and numbers from one document), `market-analyst` (current state of related prices), `historian` (base rates for this event type), `fact-checker` (corroboration). Isolated context, structured returns. |
| **Memory** | `AGENTS.md` per desk (lessons), stored in Postgres through the store backend with version history. Written only by an approved nightly-review proposal. |
| **Context rules** | The run receives a task payload (story plus evidence references), not whole histories. Long documents live in the filesystem backend; only extracted facts and citations enter the prompt. |
| **Budgets** | Max steps, max tokens, wall-clock limit per run; exceeded means "no assessment" plus an alert, never a guess. |

### 5.5 Safety design

- **Injection:** document text is wrapped as quoted data; readers have no side-effect tools; the only
  thing a desk can emit is a schema-valid assessment; assessments cannot name tools or orders.
- **Corroboration:** an official source or two independent sources are needed before a story can become
  gold. One unverified source can raise a watch, never a trade.
- **Human gates:** `interrupt_on` for any future tool with side effects; none exist for desks.
- **Sandbox:** no `execute` shell tool; filesystem access limited to the desk workspace.
- **Data egress:** tracing to a hosted service (for example LangSmith) is off by default because it
  sends prompts and documents out. I have not confirmed Deep Agents' default tracing behaviour; check
  before the first run.

### 5.6 Observability and evaluation

- **Run log (ours):** every run records inputs hash, tools called, tokens, latency, cost, output, status.
- **Replay harness:** recorded stories (from the collector) replayed through any desk implementation and
  scored against labeled outcomes. This is how the A/B test and every later change is judged.
- **Fixtures:** fake news, conflicting sources, injection strings, stale items, wrong-language items.
- **Dashboards:** cost per desk per day, schema-valid rate, p50/p95 latency, lift (Section 7, Phase 6).

### 5.7 The Phase 2 test (adopt or not)

Build the **India Markets desk** both ways (`DeepAgentsRuntime`, `PlainRuntime`) on the same 200 or more
recorded stories and compare *(all thresholds are proposals)*:

| Measure | Adopt Deep Agents for desks/council if |
|---|---|
| Schema-valid output | at least 98% |
| Tool-call correctness | at least 95% of calls valid and useful |
| Quality (materiality, direction, false-alarm labels vs. human labels) | not worse than the plain version |
| p95 latency, desk | 60 s or less; council 5 min or less |
| Cost per story | at most 1.5 times the plain version |
| Runaway or stuck runs | 1% or less |
| Build and maintain effort | clearly lower, judged by code size and bug count |

If it fails: use `PlainRuntime` for desks and keep Deep Agents only where it clearly wins (likely the
council), or drop it. The interface makes that a configuration change.

## 6. The network: desks, council, ledger

### 6.1 Region desks (12). Times are main-market open in IST, winter *(computed with tz rules)*

| Desk | Covers | Open IST | Role |
|---|---|---|---|
| Oceania | Australia, New Zealand | 02:30 | watch: first open; iron ore, coal, RBA |
| East Asia | Japan, Korea | 05:30 | watch: chips, yen, BoJ/BoK, TSE/KRX disclosures |
| Southeast Asia | Singapore, Indonesia, Malaysia, Thailand, Vietnam, Philippines | 06:30 | watch: palm oil, Malacca shipping, SGX index futures |
| Greater China | China A-shares, Hong Kong, Taiwan | 06:30 to 07:00 | watch: stimulus, PBoC, ADR/H-share, TSMC |
| **South Asia** | **India** plus neighbours | 09:15 | **trades**: NSE/BSE, RBI, SEBI, ministries, budget |
| Middle East | Gulf, Israel, Iran, Iraq, Turkey | 12:30 (Tadawul Sun to Thu) | watch: crude, Hormuz, Gulf money |
| Russia and CIS | Russia, Kazakhstan | 12:30 | watch: sanctions, oil supply to India |
| Africa | South Africa, Egypt, Nigeria | 12:30 | watch: Suez, gold, platinum, cobalt |
| UK and Ireland | London | 13:30 | watch: BoE, LSE, sterling |
| Europe | Germany, France, Italy, Spain, Nordics, Switzerland, EU | 13:30 | watch: ECB, EU rules, autos, luxury |
| Latin America | Brazil, Chile, Peru, Argentina | 18:30 | watch: copper, iron ore, soy, sugar |
| **North America** | **US**, Canada, Mexico | 20:00 | **trades (US)**: Fed, SEC, earnings, US close relays to India |

Each region desk: head, news reader, market reader (indices, currency, rates, local), policy reader
(central bank, regulator), local-language skills. Watch-only desks never trade; they publish
assessments that India/US desks and the council consume.

### 6.2 Global desks (20), always on, no country

| Desk | Watches | First sources |
|---|---|---|
| FX | dollar, rupee, yen, euro, carry | central bank feeds, price data |
| Rates and credit | yields, spreads, bank stress | Fed/ECB/RBI releases, price data |
| Flows | FII/DII, ETF flows, options positioning | NSE/SEBI data, exchange data |
| Crypto | 24/7 risk gauge | price data |
| Energy | crude, gas, OPEC+ | agency releases, price data |
| Metals | gold, copper, steel | price data, filings |
| Food and agri | palm oil, wheat, sugar, monsoon | IMD, agency releases |
| Shipping | freight, chokepoints | public port/agency data |
| Geopolitics | war, sanctions, elections | official statements, wires |
| Weather and disasters | storms, quakes | meteorology and survey agencies |
| Health | outbreaks, drug approvals | WHO, FDA, CDSCO |
| Cyber and outages | hacks, cloud outages | CERT feeds, status pages |
| Regulators | SEBI, SEC, RBI actions | official sites |
| Global bodies | IMF, MSCI, rating agencies, G20 | official sites |
| Key people | leaders, CEOs, large holders | filings, official accounts |
| Calendar | holidays, expiries, index rebalances, results season | exchange calendars |
| Sectors | IT, pharma, chips, autos, banks | filings, desk assessments |
| Crowd and rumour | social buzz, short-seller reports | public feeds; low trust tier |
| Prediction odds | Polymarket, Kalshi | public APIs (Polymarket source already exists) |
| Alt data | GST, power demand, UPI, freight | public statistics |

### 6.3 House desks (6)

| Desk | Job |
|---|---|
| Historian | base rates for event types (reaction size, drift, reversal rate); the council's memory |
| Red team | nightly fake-news and injection drills; reports which got through |
| Watchdog | dead feeds, silent desks, schema failures, cost overruns; coverage audit (Section 6.6) |
| Compliance | monitors SEBI/exchange/broker rules and FEMA limits against what the system does |
| Portfolio risk | overlap across stories and positions, correlated exposure |
| Owner desk | owner preferences, alerts, approvals, a Telegram interface |

### 6.4 Master and council

Council runs only for gold stories. Members, each independent first:

| Member | Question it answers |
|---|---|
| Skeptic | Is it rumour, old, already priced in, or wrongly reported? |
| Mechanism analyst | Through what channel can this move the instrument, and is it strong enough? |
| Read-through analyst | Which related stocks, sectors, indices and currencies move, and how? |
| Market-state analyst | Volatility, positioning, liquidity, calendar, circuit limits: can the move happen now? |
| Risk officer | Worst case, correlation with open positions, what would prove us wrong? |

Each writes a schema-valid memo without seeing the others (the existing judge pattern anonymises sides).
The **master (chair)** synthesises one `CouncilVerdict`: act / watch / ignore, thesis, instruments,
invalidation conditions, validity window, size band, dissent recorded. The quant gate then sizes and
approves from track record, tradability and limits. The master never sets size or places orders.

### 6.5 Story ledger (single shared record)

Tables *(proposal)*: `stories`, `evidence` (source, tier, link, hash, time), `claims` (extracted facts with
numbers), `assessments` (per desk), `verdicts`, `theses` (links to decision IDs), `outcomes` (labels),
`sources` (reliability scores), `base_rates`, `desk_runs` (the run log), `memory_proposals`.
Lifecycle: `new` → `triaged` (noise or keep) → `corroborating` → `confirmed` / `rumour` / `denied` →
`gold` → `assessed` → `council` → `acted` / `ignored` → `outcome labeled` → `reviewed`.
Raw publisher text is not stored beyond what terms allow (current collector keeps hash, answers, numbers).

### 6.6 False alarms and coverage

- Every dropped story keeps its drop reason. Later price action and later confirmations auto-flag
  **missed gold** and feed triage retraining.
- A story that was acted on and later **denied** opens exit review immediately.
- **Coverage audit (nightly):** every country, exchange, currency, commodity and chokepoint must have
  one owning desk; every large India/US move without a prior story opens a *gap ticket*; the report is
  the answer to "is anything missing". It is a test, not a list.
- **Gold rule v1** *(proposal, calibrated from collector labels)*: source tier plus corroboration,
  materiality (Laya answers plus numbers against company/market size), novelty (not already in price),
  tradability, relevance to our universe.

### 6.7 From verdict to order: intake, size, stops, instruments

- **Intake.** The pod gets a new path that reads approved `theses` rows from Postgres and sends them to the
  existing guardian and executor. It bypasses the analyst. The guardian stays the final limit check.
- **Who owns size and stop.** The quant gate (code) sets both, from the thesis invalidation level, measured
  volatility and the system's track record. Model confidence is an input and never the size. Today the
  guardian sizes by the model's own confidence and requires a model-chosen stop; that behaviour stays only
  for the legacy analyst arm and is marked for removal.
- **Two arms, two accounts.** The legacy analyst path and the thesis path run on separate paper accounts, so
  every gate measures one strategy and the analyst arm is a baseline.
- **Thesis-to-position link.** `theses.position_ref` in Postgres. A position manager (plain code in the app
  process) enforces invalidation, time stops and denial exits, and writes `risk_actions`. It does not depend
  on any model or on the in-memory plan the pod keeps today.
- **Accounts.** `main.py` creates only paper accounts today (verified); wiring real Zerodha and Groww
  adapters is a Phase 0 and Phase 9 task, and the US adapter belongs to Phase 5.
- **Instruments (decided 2026-11-02, D11):** NIFTY 50 **cash equities** and **index options**. **No futures.**
  Horizon default: intraday up to a few days (my default; say if you want otherwise).
- **How options change the design** *(proposals unless noted)*:
  - **Buy-only first (D14).** Long calls and puts, so the most that can be lost is the premium paid. No
    selling, spreads or naked positions until the system has a long record.
  - **The council decides the idea, code picks the contract.** The thesis states direction, size of the
    expected move, horizon and invalidation level on the underlying. A contract picker (code) chooses
    expiry and strike by rules: enough days to expiry for the horizon, a delta band, a spread and open-
    interest limit, no entry on expiry day unless the thesis is explicitly intraday.
  - **Risk is in premium.** Size is premium at risk. Each position carries two exits: a premium stop and an
    underlying-level invalidation, plus a time stop because time decay works against a long option.
  - **Volatility matters.** The market-state analyst and the quant gate need implied volatility, its
    percentile and the event calendar, because a correct view can still lose to a volatility drop after the
    event. IV and greeks are computed by our own code from option quotes.
  - **Prices have no free proxy.** Yahoo gives the NIFTY index level, not option premiums. Paper trading
    options needs live option quotes from the broker API (see D13). Today the paper account prices
    `NIFTY` as the spot index.
  - **What exists today (verified):** `Instrument` has lot size and expiry, Zerodha and Groww adapters can
    list instruments, and the config defaults say `OPTIDX`/`NFO`. Not wired into any agent: option chain,
    greeks, open interest, IV, contract selection, premium-based stops. The registry declares `get_option_chain`,
    `get_greeks` and `get_oi` only through the Groww MCP wrapper.

## 7. Roadmap

Sizes are my rough estimates for one builder working with Claude; **confidence is low beyond Phase 4**.
Phases overlap where noted. Every gate must be met before the next stage trades anything.

| Phase | Goal | Rough size | Gate (proposal) |
|---|---|---|---|
| 0 | Finish the core path, including the options foundation | 5 to 8 weeks (was 2 to 3 before D11) | one unattended paper day with no limit breach; kill switch tested; option paper fills use live quotes |
| 1 | Evidence on news (parallel with 0 and 2) | 2 to 4 weeks, mostly waiting | at least 500 labeled and 150 independent clusters; reading-gain verdict |
| 2 | Runtime decision, model bake-off | 2 weeks | Section 5.7 thresholds met or fallback chosen |
| 3 | Ledger, triage and the India news desk in shadow | 5 to 7 weeks | beats a no-news baseline on real moves; false-alarm rate and latency inside targets |
| 4 | Master, council, quant gate; paper trading from stories | 5 to 7 weeks | 4 weeks paper P&L after costs beats baseline; zero limit breaches; red-team drills pass |
| 5 | US desk, US broker, overnight relay | 4 to 6 weeks | relay (US close to India open) shows measurable edge in shadow |
| 6 | Global desks in three waves | 10 to 14 weeks | each desk shows lift or closes a coverage gap, else sleeps |
| 7 | Region desks in waves | 8 to 12 weeks | same per-desk rule |
| 8 | House desks complete | 4 to 6 weeks, parallel with 6 and 7 | red-team and watchdog catch planted failures |
| 9 | Autonomy ladder and live | at least 8 weeks of evidence | see 7.9 |
| 10 | Continuous improvement | ongoing | none |

Rough total to a complete paper-trading fleet: **8 to 12 months**; live scaling depends on evidence, not date.

### 7.0 Phase 0: finish the core path

- Market-hours and holiday gate per exchange (the spike already has IST session logic to reuse).
- **Options foundation (new, because of D11):** instrument master with option contracts, lot sizes and
  expiries; live option quotes and chain from the broker API; IV and greeks module; contract picker;
  premium-at-risk sizing; premium plus underlying stops and time stops; expiry handling; margin and premium
  budgeting. Cash equities use the same instrument master (quantity in shares, product MIS or CNC).
- Broker-side stop orders for live accounts (software stops stay as backup).
- Kill switch (global and per account) and authentication on pod endpoints; neither exists today.
- Cooldown after a stop-out; hindsight for skipped trades; schedule or remove the Strategist.
- Reuse one HTTP client in `LLMRouter` (about 1 s per call is spent building it); no-mock CI test with a
  fake Ollama (exists) plus a nightly real-model smoke test.
- Correct `docs/ROADMAP.md`. Pick a tool-capable model for later phases (Section 5.2) but keep `llama3`
  for the current pod.
- A dedicated position-monitor loop, separate from the analysis cycle and much faster than 60 s, so stops
  do not wait behind model calls; missing prices raise an alert instead of a log line.
- Set up Alembic (pinned, not configured) and wire real broker adapters into `main.py`.
- Restart the collector (stopped since 30 October).

### 7.1 Phase 1: evidence (runs now)

- Run the collector continuously on always-on hosting; fill labels daily; read the evaluation report.
- Add sources only after terms are read; add Hindi/regional-language and exchange-disclosure feeds.
- Decide: does reading the full text help, and does Laya need fine-tuning and temperature calibration
  on our labels (the model card says it ships over-confident)?
- **Labels.** Outcome labels (material move, direction) come from prices automatically. False-alarm and
  relevance labels need people: a small labeling tool and a sample of a few hundred stories labeled by you.
- **Replay needs text.** Today the collector discards article text, so a replay would have to re-fetch it
  (links rot, results change). Decision D12 says what may be stored.
- **Index-level labels (new, because of D11).** Index options trade the NIFTY level, not single stocks. The
  collector currently watches company names and labels stock returns. Add market-wide queries (Nifty, Sensex,
  RBI, Fed, crude oil, rupee, budget, elections) and label NIFTY moves and realised volatility after them.
  Without this the news test says nothing about the instrument we will trade.
- Output: a recorded, labeled story set that becomes the replay harness for Phases 2 to 4.

### 7.2 Phase 2: runtime decision

Model bake-off (needs approval to download), then the India Markets desk both ways (Section 5.7), then a
decision memo. Also decide hosting and the LLM budget (Section 8).

### 7.3 Phase 3: ledger, triage, India news desk (shadow)

- Ledger schema and service; promote the collector to the sensor/triage service.
- Triage rules and Laya tagging; false-alarm lifecycle; source scoring.
- India desk (head, reader, market-analyst, fact-checker, historian lookup), owner-preferences desk,
  watchdog first version, coverage audit first version.
- **Shadow mode:** the system writes "would have traded" records linked to story IDs and scores them
  against real moves. No orders.

### 7.4 Phase 4: master, council, quant gate, paper trading

- Council protocol, memo and verdict schemas, dissent log; master as chair.
- Quant gate: calibrated sizing from track record, tradability (liquidity, circuit limits, F&O ban,
  lot size), correlation with open positions.
- Position manager: thesis-linked exits (story denied or invalidation reached), time stops, trailing
  logic; reflex risk-cutter fed by triage.
- Paper trading driven by council verdicts through the existing guardian/executor.

### 7.5 Phase 5: US and the overnight relay

- US broker adapter (choice is a decision, Section 10), North America desk, GIFT Nifty and US-close to
  India-open relay pipeline, US filings sensors (SEC EDGAR needs a descriptive User-Agent; it returned 403
  to my plain client).
- Test the relay hypothesis in shadow before it ever trades. It is an untested guess today.

### 7.6 Phase 6: global desks in waves

Wave A (highest transmission to India/US): FX, Rates and credit, Energy, Flows, Calendar, Regulators.
**Because index options trade the NIFTY level, which macro and global events drive, Wave A moves forward: it
starts alongside Phase 4 and its desks join the council before Phase 4's paper gate.**
Wave B: Metals, Food and agri, Shipping, Geopolitics, Global bodies, Key people, Sectors.
Wave C: Weather, Health, Cyber, Crowd and rumour, Prediction odds, Alt data, Crypto.
A new desk is a config file, a skill pack and a source list on the template. Each wave ends with a
lift/coverage review; desks that do not earn their compute go to sleep (wake only on trigger).

### 7.7 Phase 7: region desks in waves

East Asia, Greater China, Europe, UK, Middle East, then Russia and CIS, Southeast Asia, Oceania, Latin
America, Africa, South Asia neighbours. Watch-only. Local-language skills and local official sources per
desk; availability must be checked per exchange (EDGAR and BLS refused my client; TDnet and BoJ gave no
response; HKEX has no documented public feed; NSE, RBI, Fed, ECB and BoE feeds answered).

### 7.8 Phase 8: house desks complete

Historian with base rates, red-team nightly drills, full watchdog and coverage audit, compliance monitor,
portfolio-risk desk, owner desk with Telegram approvals. Starts in Phase 3 and finishes alongside 6 and 7.

### 7.9 Phase 9: autonomy ladder

| Stage | Rule |
|---|---|
| Paper | at least 8 weeks, after costs positive vs baseline, no limit breach, red-team pass |
| Approval-gated live | tiny capital cap; every order needs a Telegram approval |
| Micro-live autonomous | tiny cap, no approval, kill switch armed, daily review |
| Scale | capital raised stepwise by track record; any breach drops one stage |

Requires: a static-IP always-on host and exchange Algo-ID registration (reported SEBI retail algo rules
effective April 2026; broker blogs only, confirm with your broker), full audit trail, runbooks, backups.

### 7.10 Parallel workstreams

| Stream | Content |
|---|---|
| Platform | Postgres, Redis, hosting, CI, secrets, backups, deployment |
| Data | sources, terms, parsers, language support, calendars |
| Agents | skills, desks, council, prompts |
| Evaluation | replay harness, labels, dashboards, red-team fixtures |
| Control room | UI for the desk feed, ledger viewer, coverage map, positions and kill switch (this absorbs old SP6) |
| Compliance and ops | SEBI/FEMA/terms, runbooks, incident drills |

### 7.11 Evidence standard and baselines

- **Price realism.** Paper accounts price from Yahoo, whose Indian quotes can lag by minutes, with fills at
  the last price plus 0.05% slippage. For options there is no usable proxy at all: paper fills need live
  option quotes and a bid-ask spread model. Any gate about speed, latency or the overnight relay needs
  exchange-grade real-time quotes and a cost model (brokerage, taxes, slippage by liquidity). Until then
  those gates are indicative only (decision D13).
- **Baselines** *(proposal)*: B1 a price-only analyst with no news; B2 the index held over the same
  horizon; B3 a random-timing placebo with the same sizes and instruments. Passing a gate means beating B1
  and B3 after costs with a confidence-interval lower bound above zero.
- **Numbers behind the gates** *(proposal)*: false-alarm rate (gold stories later denied or with no abnormal
  move inside the horizon) at most 40% to start; publication-to-verdict p95 at most 10 minutes for official
  filings and 30 minutes for other sources; reading-gain verdict means the interval lower bound is above zero.
- **Paper duration.** Phase 4's 4 weeks only unlocks later phases. Phase 9 needs at least 8 weeks of paper
  record with the complete configuration; Phase 4's weeks count only if the system did not change materially.

## 8. Cross-cutting

**Hosting.** A laptop that sleeps cannot run a 24/7 fleet. Needs: always-on host with a static IP, Postgres
and Redis, and a plan for the model workload (local GPU, cloud GPU, or API models). This is the biggest
open infrastructure decision.

**Cost envelope** *(illustrative, to be measured in Phase 2)*: if triage keeps about 300 stories a day for
desks at about 25k tokens each, and the council handles about 10 gold stories a day at about 150k tokens,
the fleet reads roughly 9M tokens a day. Cost per token depends on the model choice and is unknown.

**Compliance and terms.** Index-derivative rules have changed repeatedly since 2024 (lot sizes, weekly
expiries, premium collection, position monitoring); I have not verified the current rules, so the
compliance desk and Phase 0 must check them with your broker before any options order. Reported SEBI algo rules (Algo-ID, static IP per user); FEMA/RBI: remittances for
overseas margin trading are not permitted under LRS, overseas forex platforms are not an allowed route,
exchange-traded currency derivatives are; US equity access via LRS has its own limits (secondary sources,
confirm). Publisher and feed terms: Google News RSS is an unofficial public feed; Moneycontrol and CNBC
refuse AI agents in robots.txt and are excluded; storing full text needs permission, so only derived data
is kept. Time zones, DST and exchange holidays need one calendar service.

**Security.** Secrets in a vault or env, auth on every control endpoint, least-privilege tools,
append-only decision and run logs, signed config for limits.

**Testing.** Unit tests for code; no-mock cycle tests (pattern exists); replay tests for desks; red-team
fixtures in CI; a nightly real-model smoke test.

## 9. Risks

| Risk | Effect | Mitigation |
|---|---|---|
| News gives no edge after costs | whole fleet is cost without return | Phase 1 and 3 gates; shadow first; desks must earn compute |
| Deep Agents immaturity or churn | rework | runtime interface, pinned versions, plain fallback |
| Small local models call tools badly | desks fail or loop | bake-off, schema validation, budgets, cloud tier for council |
| Prompt injection or fake news | bad trades | R1 to R4, corroboration, red team |
| Latency (published multi-agent trading stacks took more than 4 min per decision) | miss the move | tiering, reflex path, relay and read-through strategy instead of first-reaction |
| LLM confidence is not calibration | oversizing | quant gate sizes from track record |
| Silent failure of feeds or desks | blind spots | watchdog, coverage audit |
| Source terms or blocking | loss of data | official sources first, per-source health, alternates |
| Options mechanics: time decay, volatility drop after events, wide spreads, expiry-day swings | a right view still loses money | buy-only, contract rules, IV awareness, time stops, spread limits |
| Regulatory change or breach | account or legal risk | compliance desk, broker confirmation |
| Cost growth with desk count | budget | per-desk budgets, sleep mode, monthly review |
| Single builder bandwidth | slips | phase gates, cut scope by desk wave not by safety |

## 10. Decisions needed from you

| # | Decision | My default |
|---|---|---|
| D1 | Hosting for 24/7 and a static IP | small cloud VPS; local GPU only for triage if kept |
| D2 | Monthly LLM budget and policy | hybrid: local for triage/readers, API for council |
| D3 | Download a tool-capable local model (several GB each) | test `qwen3:8b` and `llama3.1:8b` first |
| D4 | US route (broker, LRS limits) | decide in Phase 5 after a compliance check |
| D5 | Forex: exchange-traded currency derivatives only, or skip | skip until Phase 9 |
| D6 | First live trades need your Telegram approval | yes |
| D7 | Owner preferences format (watchlist, sectors, themes, risk appetite, quiet hours) | simple YAML first |
| D8 | One real news event you wish KALYX had caught (asked three times) | needed before Phase 3 design |
| D9 | Paid feeds (for example Benzinga, Finnhub) and terms review | free official feeds first |
| D10 | May the Strategist change live parameters by itself | no; it proposes, you approve |
| D11 | **Instruments for the first version** | **Decided 2026-11-02: NIFTY 50 cash equities plus index options, no futures.** Holding period default: intraday to a few days (confirm) |
| D14 | Options style | buy-only (long calls and puts, loss limited to the premium) until a long track record exists |
| D15 | Which indices | NIFTY only first; BANKNIFTY, FINNIFTY, SENSEX later |
| D12 | May full article text be stored for private replay | filings from the exchange yes; publisher articles derived-only until terms are reviewed |
| D13 | Budget for real-time quotes and a cost model | use the broker's live data API; decide after the Phase 3 shadow results |

## 11. Traceability: what you asked for, and where it is covered

| You asked | Covered by |
|---|---|
| Agents with their own skills, tools, MO, subagents | 5.4 desk anatomy |
| How context and memory are managed | 5.4 context rules, 5.4 memory, ledger 6.5 |
| How signals become actionable and then actions | 4, 6.4, 6.5, 7.4 (story, verdict, quant gate, executor) |
| A news-processing wing, owner preferences, own alerts | 6.5, 7.3, owner desk 6.3 |
| False alarms, later exposed | 6.6 |
| Gold news to master plus council, check related markets and state | 6.4 |
| A league per country, reporting up, then council, then dispatch | 6.1, 5.3 event flow |
| World scale, FX channel effects, every region | 6.1, 6.2 (FX desk), template rollout 7.6 and 7.7 |
| Nothing missing | 6.6 coverage audit, red team, gap tickets |
| Full autonomy only when trusted | 2, 7.9 |

## 12. First 30 days

1. Restart the collector now, then move it to always-on hosting; run `fill` daily; produce the first evaluation report.
2. Phase 0 items: market-hours gate, kill switch with endpoint auth, lot sizes, cooldown, HTTP client reuse.
3. Correct `docs/ROADMAP.md` and add this roadmap to it.
4. You answer D1 to D3 and D8; I run the model bake-off once approved.
5. Write the ledger schema and the `contracts.py` models (they are needed by every later phase).
6. Build the replay harness from the stored stories.

## 13. Not decided here

Choice of strongest council model; exact gold-rule thresholds; which brokers beyond Zerodha, Groww and
paper; whether triage moves to the app environment after a torch upgrade; dashboards design.

## 14. Facts used (checked 2026-11-02)

- `deepagents` 0.7.32, MIT, Python 3.11+ (PyPI); subagents, skills, models pages of docs.langchain.com/oss/python/deepagents.
- `deepagents` 0.7.32 `requires_dist` (PyPI JSON) against the app's `requirements.txt` pins.
- Ollama `/api/show` on this machine for `llama3`, `gpt-oss:20b`, `llama2`; `nvidia-smi` reports an 8 GB RTX 4070 laptop GPU.
- Repo state and tests from this session; Laya findings in `2026-10-28-laya-phase0-findings.md`.
- Secondary sources, unverified against primary: SEBI retail algo framework (broker blogs), RBI/FEMA positions (tax and trading blogs), LLM-trading-agent critiques (arXiv 2605.16895, 2609.19705, read through summaries).
