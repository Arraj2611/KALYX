# Phase 0: Control Plane, Safety Loops and Options Foundation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the existing trading app safe to leave running (authenticated API, a real kill switch, fast stop enforcement, market-hours and cooldown rules, alerts that reach a person) and add the offline-testable core of index-options trading (greeks, contract picker, premium sizing), then restart the news evidence collector with index-level labels.

**Architecture:** Plain code only, in the existing app (`backend/app`). New small modules: `security.py` (API key dependency), `control/` (kill switch table, service, router), `markets/calendar.py`, `options/` (greeks, contracts, picker, sizing). The pod gains a second asyncio loop for stops and consults the kill switch, calendar and cooldown. Nothing here calls a model.

**Tech Stack:** Python 3.11+, FastAPI, SQLAlchemy (SQLite in tests), pytest + pytest-asyncio, httpx.

**Spec:** `docs/superpowers/specs/2026-11-02-kalyx-fleet-roadmap-design.md` (Phase 0, Sections 2, 6.7, 7.0, 7.1, 7.11).

## Global Constraints

- R1: no model in any order, risk, kill-switch or stop path. Everything in this plan is plain code.
- R5: fail closed. Unreadable kill-switch state, missing API key setting, missing price or closed market means no new risk. Exits and stops are never blocked by the kill switch, cooldown, limits or the market gate (the gate only pauses the monitor while the exchange is closed, because nothing can fill).
- Run tests from `backend/` with `ZERODHA_API_KEY=x ZERODHA_API_SECRET=y python -m pytest tests -q`. Baseline: 341 passing.
- `kiteconnect` is not installed in this environment, so tests that import `app.main` stub it in `tests/api/conftest.py`.
- Commit messages end with `Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>`.
- Instruments (D11, decided): NIFTY 50 cash equities and index options, no futures. Options are buy-only (D14 default). NIFTY first (D15 default).
- Do not invent exchange holidays. The holiday file ships empty with a header saying it must be filled from the exchange circular.

## Review Focus

1. A request with a wrong, empty or differently-cased API key, or with the key in the query string, must be rejected; an unset server key must reject everything with 503, not allow it.
2. Kill-switch read failure (database error) must block entries but still allow exits, stops and `flatten`.
3. The monitor loop and the analysis cycle must never close the same position twice (lock), and an exception in one tick must not kill the loop.
4. Market gate at the boundaries: 09:15:00 open, 15:30:00 close (closed at exactly 15:30), weekend, a listed holiday, and a UTC time that is a different date in IST.
5. Greeks and picker with degenerate inputs: zero time to expiry, zero or missing bid/ask, deep out-of-the-money strikes, IV solve that cannot converge, empty chain.

---

### Task 1: API key on every control and trading endpoint

**Files:**
- Create: `backend/app/security.py`, `backend/tests/api/__init__.py`, `backend/tests/api/conftest.py`, `backend/tests/api/test_security.py`
- Modify: `backend/app/config.py` (add `CONTROL_API_KEY: Optional[str] = None`, `API_AUTH_DISABLED: bool = False`), `backend/app/main.py` (router dependencies, `/ws` token check)

**Interfaces:**
- Produces: `require_api_key(x_api_key: str | None = Header(default=None)) -> None` FastAPI dependency. 401 for missing or wrong key, 503 if `settings.CONTROL_API_KEY` is empty and `API_AUTH_DISABLED` is false. Constant-time compare (`secrets.compare_digest`). When `API_AUTH_DISABLED` is true it logs one loud warning and allows.
- Produces: `check_ws_token(token: str | None) -> bool` for the WebSocket.

- [ ] **Step 1: Write failing tests** `test_missing_key_is_401`, `test_wrong_key_is_401`, `test_key_in_query_string_is_rejected`, `test_unset_server_key_is_503`, `test_correct_key_passes`, `test_disabled_flag_allows_and_warns`, `test_health_stays_public`, `test_every_router_requires_the_key` (iterate `app.routes`, call each non-public GET/POST path without a key via `TestClient(app)` without entering lifespan, assert 401 or 503, never 2xx/404), `test_ws_without_token_is_refused`.
- [ ] **Step 2: Run** `python -m pytest tests/api -q`. Expected: FAIL (module missing).
- [ ] **Step 3: Implement** `security.py`, the two settings, and `include_router(..., dependencies=[Depends(require_api_key)])` for auth, strategies, execution, risk, data, agents, decisions; `/` and `/health` stay open; `/ws` closes with code 1008 unless `?token=` matches.
- [ ] **Step 4: Run tests.** Expected: PASS. Also run the full suite.
- [ ] **Step 5: Commit** `feat(api): require an API key on every trading and control endpoint`.

---

### Task 2: Kill switch (global and per account)

**Files:**
- Create: `backend/app/control/__init__.py`, `backend/app/control/models.py`, `backend/app/control/killswitch.py`, `backend/app/control/router.py`, `backend/tests/control/__init__.py`, `backend/tests/control/test_killswitch.py`, `backend/tests/control/test_control_router.py`
- Modify: `backend/app/agents/base.py` (add `halted: bool = False` to `AgentContext`), `backend/app/agents/guardian.py`, `backend/app/agents/pod.py`, `backend/app/execution/router.py`, `backend/app/main.py` (include router, create table via `init_db` import)

**Interfaces:**
- Produces: `ControlFlag` table `control_flags(key PK, active bool, reason, updated_by, updated_at)`; keys `halt:all` and `halt:account:<name>`.
- Produces: `KillSwitch(session_provider: Callable[[], Session])` with `is_halted(account: str) -> bool` (fail closed: any exception returns True), `halt(scope: str, reason: str, by: str) -> None`, `resume(scope: str, by: str) -> None`, `status() -> dict`. `scope` is `"all"` or an account name.
- Produces: `AgentPod.flatten(reason: str) -> int` closing every open position through the executor; returns the count.
- Produces: endpoints `GET /api/control/status`, `POST /api/control/halt`, `POST /api/control/resume`, `POST /api/control/flatten/{account}` (all behind the API key).
- Consumes: `require_api_key` from Task 1.

- [ ] **Step 1: Write failing tests** `test_global_halt_halts_every_account`, `test_account_halt_only_that_account`, `test_resume_clears`, `test_read_failure_counts_as_halted`, `test_halt_persists_across_instances`; guardian: `test_guardian_blocks_entry_when_halted_with_reason_kill_switch`, `test_guardian_allows_exit_when_halted`; cycle test in `tests/agents/test_core_cycle.py`: `test_halt_blocks_entries_but_stop_still_closes`, `test_flatten_closes_all_positions`; router: `test_halt_requires_key`, `test_manual_order_returns_423_when_halted`, `test_halt_then_status_shows_reason`.
- [ ] **Step 2: Run.** Expected: FAIL.
- [ ] **Step 3: Implement** the model, service, guardian first-check (`context.halted` blocks BUY/SELL only), pod sets `context.halted` per symbol and exposes `flatten`, the manual order endpoint returns 423, and the control router.
- [ ] **Step 4: Run tests and the full suite.** Expected: PASS.
- [ ] **Step 5: Commit** `feat(control): kill switch with per-account scope, flatten, and 423 on manual orders`.

---

### Task 3: Fast position-monitor loop

**Files:**
- Modify: `backend/app/agents/pod.py`, `backend/tests/agents/test_core_cycle.py`

**Interfaces:**
- Produces: config `agents.monitor_interval_seconds` (default 5). `AgentPod.start_eval_loop()` also starts `_monitor_loop`; `stop()` cancels both. An `asyncio.Lock` (`self._trade_lock`) guards every path that places an order. Consecutive missing-price ticks for a managed position (3) send one alert and then stay quiet until the price returns.

- [ ] **Step 1: Write failing tests** `test_monitor_closes_a_stopped_position_without_waiting_for_the_cycle` (start loops with tiny intervals, move price past the stop, wait up to 2 s, assert closed), `test_monitor_and_cycle_never_double_close` (run both concurrently, assert exactly one EXIT row), `test_monitor_survives_a_broker_error` (adapter raises once, then recovers), `test_missing_price_alerts_once_after_three_ticks`.
- [ ] **Step 2: Run.** Expected: FAIL.
- [ ] **Step 3: Implement** the loop, lock and price-miss counter; `run_cycle` takes the lock for its exits step and for each order.
- [ ] **Step 4: Run tests and the full suite.** Expected: PASS.
- [ ] **Step 5: Commit** `feat(pod): dedicated fast stop monitor with a trade lock and price-miss alerts`.

---

### Task 4: Market-hours gate

**Files:**
- Create: `backend/app/markets/__init__.py`, `backend/app/markets/calendar.py`, `backend/config/market_holidays.yaml`, `backend/tests/markets/__init__.py`, `backend/tests/markets/test_calendar.py`
- Modify: `backend/app/agents/pod.py`, `backend/config/accounts.yaml` (`market: NSE` on `paper_test`), `backend/tests/agents/test_core_cycle.py`

**Interfaces:**
- Produces: `MarketCalendar(holidays: dict[str, set[date]] | None = None)` with `is_open(exchange: str, when: datetime) -> bool`; `SESSIONS` for `NSE` (09:15 to 15:30 Asia/Kolkata, Mon to Fri) and `NYSE` (09:30 to 16:00 America/New_York, Mon to Fri); `load_holidays(path) -> dict[str, set[date]]`. Naive datetimes are rejected (`ValueError`).
- Produces: `AgentPod(..., clock: Callable[[], datetime] | None = None, calendar: MarketCalendar | None = None)`. With `agents.market_gate` true (default) a closed market skips analysis (no model call, no DecisionLog spam; counted as `skipped_closed` in the cycle result and `last_cycle`) and pauses the monitor.

- [ ] **Step 1: Write failing tests** `test_nse_open_at_0915_closed_at_1530`, `test_weekend_closed`, `test_listed_holiday_closed`, `test_utc_time_maps_to_the_ist_date`, `test_naive_datetime_rejected`, `test_nyse_summer_and_winter_hours`, `test_unknown_exchange_raises`, `test_empty_holiday_file_loads`; pod: `test_closed_market_makes_no_model_call_and_reports_skipped_closed`, `test_open_market_runs_normally`, `test_gate_can_be_disabled`.
- [ ] **Step 2: Run.** Expected: FAIL.
- [ ] **Step 3: Implement** the calendar with `zoneinfo`, the empty holiday file with a header comment, and the pod gate (default exchange `NSE`; the existing cycle tests set `market_gate: false` or a clock inside the session).
- [ ] **Step 4: Run tests and the full suite.** Expected: PASS.
- [ ] **Step 5: Commit** `feat(markets): exchange calendar and a market-hours gate for the pod`.

---

### Task 5: Cooldown after a stop-out

**Files:**
- Modify: `backend/app/agents/base.py` (`now: datetime | None = None` on `AgentContext`), `backend/app/agents/guardian.py`, `backend/app/agents/executor.py`, `backend/app/agents/pod.py`, `backend/tests/agents/test_guardian.py`, `backend/tests/agents/test_core_cycle.py`

**Interfaces:**
- Produces: guardian config `cooldown_minutes` (default 30). EXIT decisions record `exit_reason` (`stop_loss`, `target`, `signal`) in `market_state`; `_todays_decisions` rows carry `symbol`, `exit_reason` and `timestamp` (ISO UTC). Guardian blocks an entry on a symbol with a `stop_loss` exit inside the window, reason `cooldown`.

- [ ] **Step 1: Write failing tests** `test_cooldown_blocks_reentry_within_window`, `test_cooldown_expires`, `test_cooldown_is_per_symbol`, `test_target_exit_does_not_cool_down`, `test_cooldown_survives_a_restart` (new pod, same database), `test_cooldown_does_not_block_exit`.
- [ ] **Step 2: Run.** Expected: FAIL.
- [ ] **Step 3: Implement** the signal field, executor logging of `exit_reason`, row fields, and the guardian check using `context.now` or the current time.
- [ ] **Step 4: Run tests and the full suite.** Expected: PASS.
- [ ] **Step 5: Commit** `feat(agents): cooldown after a stop-loss exit`.

---

### Task 6: Reuse one HTTP client in the LLM router

**Files:**
- Modify: `backend/app/agents/llm_router.py`, `backend/app/agents/pod.py` (close on stop), `backend/tests/agents/test_llm_router.py`

**Interfaces:**
- Produces: `LLMRouter.aclose() -> None`. One `httpx.AsyncClient` per running event loop, created lazily, recreated if the loop changed or the client was closed; per-request timeout still `timeout_seconds`.

- [ ] **Step 1: Write failing tests** `test_two_calls_share_one_client`, `test_new_event_loop_gets_a_new_client`, `test_aclose_closes_and_a_later_call_recreates`, `test_retry_behaviour_unchanged` (existing retry tests keep passing).
- [ ] **Step 2: Run.** Expected: FAIL.
- [ ] **Step 3: Implement** `_client()` keyed by `asyncio.get_running_loop()` and `aclose()`.
- [ ] **Step 4: Run tests and the full suite; compare `test_core_cycle.py` runtime** (was about 45 s). Expected: PASS and faster.
- [ ] **Step 5: Commit** `perf(llm): reuse one HTTP client per event loop`.

---

### Task 7: Alerts that reach a person

**Files:**
- Create: `backend/app/alerts/factory.py`, `backend/tests/alerts/test_factory.py`
- Modify: `backend/app/main.py`, `backend/app/control/router.py` (alert on halt/resume), `backend/app/config.py` only if the Telegram settings are missing

**Interfaces:**
- Produces: `build_alert_service(settings) -> TelegramAlertService | None` (None unless both bot token and chat id are set). `main.py` passes it to every pod and to the control router via `set_alert_service`.

- [ ] **Step 1: Write failing tests** `test_returns_none_without_token`, `test_returns_none_without_chat_id`, `test_returns_service_when_both_set`, `test_halt_sends_a_critical_alert` (router test with a fake service).
- [ ] **Step 2: Run.** Expected: FAIL.
- [ ] **Step 3: Implement** the factory and wire it in `main.py`.
- [ ] **Step 4: Run tests and the full suite.** Expected: PASS.
- [ ] **Step 5: Commit** `feat(alerts): wire Telegram alerts into pods and the kill switch`.

---

### Task 8: Option pricing: Black-Scholes, greeks, implied volatility

**Files:**
- Create: `backend/app/options/__init__.py`, `backend/app/options/greeks.py`, `backend/tests/options/__init__.py`, `backend/tests/options/test_greeks.py`

**Interfaces:**
- Produces (European options on an index, continuous dividend yield): `bs_price(kind: str, spot, strike, t_years, rate, div_yield, vol) -> float`; `greeks(kind, spot, strike, t_years, rate, div_yield, vol) -> Greeks` with `delta, gamma, theta_per_day, vega_per_vol_point`; `implied_vol(kind, price, spot, strike, t_years, rate, div_yield) -> float | None` (bisection, `None` when the price is outside no-arbitrage bounds or cannot converge). `kind` is `"CE"` or `"PE"`. At `t_years <= 0` the price is intrinsic value and `implied_vol` is `None`.

- [ ] **Step 1: Write failing tests**: textbook values (S=100, K=100, T=1, r=0.05, q=0, vol=0.2: call 10.4506, put 5.5735, call delta 0.6368); `test_put_call_parity` with dividends; `test_implied_vol_round_trip` over a grid; `test_implied_vol_none_below_intrinsic`; `test_zero_time_is_intrinsic`; `test_deep_otm_price_is_tiny_and_finite`; `test_theta_is_negative_for_long_options`; `test_greeks_match_finite_differences`.
- [ ] **Step 2: Run.** Expected: FAIL.
- [ ] **Step 3: Implement** with `math.erf` (no new dependency).
- [ ] **Step 4: Run tests.** Expected: PASS.
- [ ] **Step 5: Commit** `feat(options): Black-Scholes pricing, greeks and implied volatility`.

---

### Task 9: Option contracts, chain and the contract picker

**Files:**
- Create: `backend/app/options/contracts.py`, `backend/app/options/picker.py`, `backend/tests/options/test_picker.py`

**Interfaces:**
- Consumes: `greeks`, `implied_vol` from Task 8.
- Produces: `OptionContract(underlying, kind, strike, expiry: date, lot_size, symbol, exchange)`; `OptionQuote(bid, ask, ltp, open_interest, volume)`; `ChainRow(contract, quote)`; `parse_option_symbol(symbol: str)` for names like `NIFTY25APR24500CE` is NOT attempted (formats vary); contracts come from the broker's instrument list via `contracts_from_instruments(instruments) -> list[OptionContract]` using the existing `Instrument` fields.
- Produces: `PickRules(min_days_to_expiry=2, allow_expiry_day=False, delta_low=0.30, delta_high=0.55, target_delta=0.40, max_spread_pct=5.0, min_open_interest=1000, min_volume=100)` and `pick_contract(chain: list[ChainRow], direction: str, spot: float, now: datetime, horizon_days: float, rules: PickRules, rate=0.065, div_yield=0.013) -> Pick | Rejection`. `direction` is `"UP"` (call) or `"DOWN"` (put). `Pick` has `contract`, `entry_price` (the ask), `delta`, `iv`, `spread_pct`, `reasons`. `Rejection` has `reason` (`empty_chain`, `no_liquid_contract`, `expiry_too_close`, `spread_too_wide`) and detail counts.

- [ ] **Step 1: Write failing tests** with a synthetic chain: `test_up_picks_a_call_near_target_delta`, `test_down_picks_a_put`, `test_expiry_shorter_than_horizon_is_skipped`, `test_expiry_day_excluded_unless_allowed`, `test_wide_spread_excluded`, `test_low_open_interest_excluded`, `test_zero_bid_is_excluded_not_divided_by`, `test_empty_chain_rejects`, `test_all_filtered_reports_why`, `test_pick_is_deterministic_on_ties` (lowest strike distance, then nearest expiry).
- [ ] **Step 2: Run.** Expected: FAIL.
- [ ] **Step 3: Implement** the types and picker (IV from mid, delta from our own greeks).
- [ ] **Step 4: Run tests.** Expected: PASS.
- [ ] **Step 5: Commit** `feat(options): contract types and a rule-based contract picker`.

---

### Task 10: Premium-at-risk sizing and exits for long options

**Files:**
- Create: `backend/app/options/sizing.py`, `backend/tests/options/test_sizing.py`

**Interfaces:**
- Produces: `size_long_option(premium_budget: float, entry_price: float, lot_size: int, max_lots: int) -> int` (whole lots, 0 if one lot exceeds the budget). `OptionExitPlan(premium_stop: float, underlying_invalidation: float, time_stop: datetime, direction: str)` built by `plan_exits(entry_price, direction, underlying_invalidation, entry_time, expiry, horizon_days, premium_stop_pct=0.35, expiry_buffer_hours=...)`. `exit_reason(plan, premium: float, underlying: float, now: datetime) -> str | None` returning `premium_stop`, `underlying_invalidation`, `time_stop` or `None`; invalidation direction depends on `UP` or `DOWN`.

- [ ] **Step 1: Write failing tests** `test_budget_rounds_down_to_whole_lots`, `test_one_lot_over_budget_gives_zero`, `test_max_lots_caps`, `test_zero_or_negative_inputs_raise`, `test_premium_stop_triggers`, `test_up_invalidation_below_level`, `test_down_invalidation_above_level`, `test_time_stop_before_expiry_buffer`, `test_no_exit_when_all_ok`.
- [ ] **Step 2: Run.** Expected: FAIL.
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run tests and the full suite.** Expected: PASS.
- [ ] **Step 5: Commit** `feat(options): premium-at-risk sizing and exit rules for long options`.

---

### Task 11: Collector restart with index-level labels

**Files:**
- Modify: `backend/spike/nifty50_symbols.yaml` (market-wide entries), `backend/spike/laya_shadow/fill.py`, `backend/spike/laya_shadow/scorer.py` (index wording), `backend/spike/tests/test_outcomes.py`, `backend/spike/tests/test_poller.py`

**Interfaces:**
- Produces: market-wide entries `{symbol: "MKT_NIFTY", ticker: "^NSEI", keywords: ["Nifty"], query: "Nifty OR Sensex"}` and similar for RBI, Fed, crude oil, rupee, budget. In `fill_pending`, an entry whose ticker is the index ticker is labeled with raw index returns (no index subtraction) and its materiality threshold comes from the index's own distribution.

- [ ] **Step 1: Write failing tests** `test_index_entry_label_is_raw_index_return`, `test_index_entry_threshold_uses_index_distribution`, `test_market_wide_entries_load_and_have_queries`.
- [ ] **Step 2: Run** from `backend/spike`: `.venv/Scripts/python -m pytest tests -q`. Expected: FAIL.
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run spike tests.** Expected: PASS (129 before).
- [ ] **Step 5: Restart the collector** in the Terminal panel (`python -m laya_shadow.poller --interval-seconds 900`) and confirm new rows arrive.
- [ ] **Step 6: Commit** `feat(spike): index-level market queries and labels`.

---

### Task 12: Correct the roadmap and record what was deferred

**Files:**
- Modify: `docs/ROADMAP.md`

- [ ] **Step 1: Edit** sub-project 2 and 3 text: LangGraph, pgvector and Redis agent messaging are not implemented; the Strategist is dormant by design (D10); add a pointer to the fleet roadmap and mark sub-projects 5 and 6 as absorbed by its phases.
- [ ] **Step 2: Commit** `docs: correct the roadmap and point to the fleet plan`.

---

## Deferred from Phase 0, with reasons

| Item | Why not now |
|---|---|
| Alembic | The only new table here is created by `create_all`. Set it up with the first ledger migration (Phase 3). |
| Real Zerodha/Groww adapter wiring in `main.py` | Needs live credentials and a supervised test; Phase 9 prerequisite. |
| Broker-side stop orders | Cannot be tested without a live broker session. |
| Hindsight for skipped trades | Needs a horizon decision and price history; schedule with the Phase 1 labeling work. |
| Live option quotes into the pod | Needs broker credentials and a data subscription (D13). |
| Wiring the picker and sizing into the pod/guardian/executor | Waits for live quotes and the quant gate (Phase 4). |
| NSE holiday data | Not verified; the file ships empty on purpose. |

## Self-review

- Spec coverage: Phase 0 items map to Tasks 1 to 11, with the deferrals above.
- Consistency: `AgentContext` gains `halted` (Task 2) and `now` (Task 5); `AgentPod` gains `clock` and `calendar` (Task 4) and `_trade_lock` (Task 3).
- Proportion: each task states interfaces and test names; bodies are left to the implementer.
