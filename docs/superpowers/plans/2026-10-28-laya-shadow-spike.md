# Laya Shadow-Mode Spike Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Run Laya beside FinBERT on live NIFTY 50 headlines, log every answer, fill realised forward returns, and report whether Laya predicts *materiality* better than a FinBERT baseline.

**Architecture:** A `ShadowDispatcher` hooked into `IntelligenceContextBuilder.build()` hands headlines to a single-worker thread that runs `LayaShadowScorer` and writes `shadow_inference` rows. A standalone poller feeds the same scorer and table for volume. A separate outcome-fill script and an evaluation script turn rows into a verdict. Nothing Laya produces ever reaches a live decision path.

**Tech Stack:** Python 3.12, SQLAlchemy (existing `Base`, `SessionLocal`), pytest (+ `pytest.mark.asyncio` as in `tests/intelligence/test_context_builder.py`), numpy/pandas (already present via yfinance/transformers stack; add nothing else except `laya`), `laya` (added only after Task 1 passes).

**Spec:** `docs/superpowers/specs/2026-10-28-laya-shadow-spike-design.md`

## Global Constraints

- FinBERT's output remains the only value the system uses; Laya is observe-only.
- Guardian stays math-only; no model call anywhere near it.
- Shadow hook is OFF by default (config flag); any Laya exception or timeout is logged at warning and swallowed.
- Shadow work runs on a **single-worker executor with skip-if-busy**; dropped calls are counted and reported.
- Primary target: materiality = |index-adjusted return at +1h| above the **75th percentile** of that symbol's last **60 trading days** of 1h bars (unconditional distribution). Index: **NIFTY 50 (`^NSEI`)**. Scope: **NIFTY 50 symbols only**.
- Primary horizon +1h. Also store +15m, EOD, +1d (robustness only). Chosen before data; never retuned after.
- t0 = source **publish time** (store `observed_at` too). Drop items with no publish time and report the drop rate. After-hours t0 = next market open; return measured open to open + 1h.
- "No measurable slowdown" = `build()` p95 with flag on within **5%** of flag off over at least **200** runs.
- Minimum **500** labeled headlines before any verdict; 95% bootstrap CIs on all comparisons.
- English checkpoint (ModernBERT-large) first; four questions: `event_type` (choice: earnings, macro/policy, regulatory, geopolitical, corporate action, other/noise), `material_to_symbol` (noul), `bullish_for_symbol` (noul), `urgency` (score 0-3).
- Kill: p50 latency above **100 ms** on the 4070, or measurable `build()` slowdown, or no lift (see Task 7).
- If Laya cannot coexist with the project's torch/transformers: **stop and report**. No separate inference process.
- Time box 1-2 working days; do not extend silently. If NIFTY 50 volume projects past ~2 weeks to 500 labeled headlines, report back.
- Tables are created by `Base.metadata.create_all` (no migration tool). Same DB and `SessionLocal` as `DecisionLogger`.

## Review Focus

1. Headline item with missing/empty/non-string title or no publish time: skipped and counted, never raises (Task 2).
2. Same headline arriving via both the `build()` hook and the poller: stored once per symbol (Task 2).
3. Publish times in IST vs UTC vs naive: normalized to tz-aware UTC before t0 alignment (Tasks 2, 6).
4. Laya raising, hanging, or CUDA out-of-memory: `build()` result is unchanged and unblocked (Tasks 3, 4).
5. Missing prices, exchange holidays, or a weekend headline: row retried then marked `unfillable` and excluded from metrics, never filled with a wrong return (Task 6).

---

## File Structure

- Create `backend/app/intelligence/decision/__init__.py`
- Create `backend/app/intelligence/decision/models.py` — `ShadowInference` table.
- Create `backend/app/intelligence/decision/headlines.py` — `normalize_headline`, `headline_hash`.
- Create `backend/app/intelligence/decision/recorder.py` — `ShadowRecorder` (dedupe + write).
- Create `backend/app/intelligence/decision/laya_shadow.py` — `LayaShadowScorer`.
- Create `backend/app/intelligence/decision/dispatch.py` — `ShadowDispatcher`.
- Create `backend/app/intelligence/decision/outcomes.py` — t0 alignment, forward returns, materiality threshold.
- Create `backend/app/intelligence/decision/metrics.py` — AUROC, Brier, ECE, paired bootstrap, verdict.
- Create `backend/scripts/__init__.py`, `poll_headlines.py`, `fill_outcomes.py`, `shadow_eval.py`, `shadow_overhead_bench.py`
- Create `backend/config/nifty50_symbols.yaml` — ticker (`.NS`) + news keywords per symbol.
- Modify `backend/app/intelligence/context.py` (optional `shadow` ctor arg; one submit call after FinBERT scoring).
- Modify `backend/app/config.py` (two settings), `backend/app/main.py` (wiring), `backend/requirements.txt` (add `laya` after Task 1).
- Tests under `backend/tests/intelligence/decision/` (create `__init__.py`).

Run all tests from `backend/` with `python -m pytest tests/intelligence/decision -v`.

---

### Task 1: Phase 0 feasibility gate (throwaway; findings doc is the deliverable)

**Files:**
- Create: `docs/superpowers/specs/2026-10-28-laya-phase0-findings.md`
- Scratch only (NOT in repo): venv and a script in the session scratchpad directory.

**Interfaces:**
- Produces: a go/no-go decision plus facts later tasks need: exact `laya` output shape, English checkpoint name, license, p50/p95 latency, real headline item shapes per source, publish-time drop rate, NIFTY 50 headline volume per day.

- [ ] **Step 1: Create a scratch venv** with the project's `backend/requirements.txt` plus `pip install laya`. Expected: resolves, or note the conflict. If it forces a torch/transformers change that breaks FinBERT, STOP and report to the user (spec: no separate process).
- [ ] **Step 2: Read the Hugging Face model card** for Laya (English checkpoint). Record license, checkpoint name, intended use. If the license restricts this use, STOP and report.
- [ ] **Step 3: Load Laya on the RTX 4070** (`torch.cuda.is_available()` is True on this machine) and run ~20 real headlines through the four questions. Record p50/p95 latency and GPU memory, and the exact `router.predict(...)` result shape (the DataCamp write-up shows `result["answers"][question][type]`; confirm).
- [ ] **Step 4: Record real news item shapes.** Live `build()` news comes from the registry chain `scrapling,trafilatura,gdelt` (`backend/config/data_sources.yaml`); of those only `GdeltSource` declares `get_news`, and it passes the symbol as the GDELT *keyword* (`gdelt_source.py`), so a futures symbol like `NIFTY25JANFUT` will match nothing useful. For GDELT (`article_search` records: expect `title`, `seendate`, `url`, `domain`) and `YFinanceSource.get_news` (expect nested `content.title` / `content.pubDate` in recent yfinance), log the keys of one real item each and whether `title` is present at the top level. Also state whether live FinBERT is therefore scoring empty strings (report as a finding; do not fix).
- [ ] **Step 5: Measure volume and publish-time drop rate** for 5 NIFTY 50 names (ticker `.NS` via yfinance; company-name keyword via GDELT) over one polling pass: headlines/day/symbol and % lacking a publish time.
- [ ] **Step 6: Write the findings doc and commit it.** State GO/NO-GO against: install ok, license ok, p50 under 100 ms, publish-time drop rate not "most". Commit message: `docs: laya phase 0 feasibility findings`. If NO-GO, stop; remaining tasks do not run.

---

### Task 2: ShadowInference table, headline normalization, recorder

**Files:**
- Create: `backend/app/intelligence/decision/__init__.py`, `models.py`, `headlines.py`, `recorder.py`
- Test: `backend/tests/intelligence/decision/__init__.py`, `test_headlines.py`, `test_recorder.py`

**Interfaces:**
- Produces:
  - `ShadowInference(Base)`, table `shadow_inference`. Columns: `id` Integer PK; `observed_at` DateTime(tz) server_default now, indexed; `published_at` DateTime(tz) not null, indexed; `symbol` String not null, indexed; `headline` Text not null; `headline_hash` String(64) not null; `source` String; `model_name` String; `model_version` String; `answers` JSON; `latency_ms` Float; `finbert_label` String null; `finbert_score` Float null; `finbert_polarity` Float null; `ret_15m`, `ret_1h`, `ret_eod`, `ret_1d` Float null; `material` Boolean null; `fill_attempts` Integer default 0; `unfillable` Boolean default False; `outcome_filled_at` DateTime(tz) null. `UniqueConstraint("symbol", "headline_hash")`.
  - `normalize_headline(item: dict, source: str) -> tuple[str, datetime] | None`: returns `(title, published_at_utc)` or `None` when title is missing/empty/non-string or no publish time. Handles top-level `title`, nested `content.title`, publish time from `published_at`/`pubDate`/`content.pubDate`/GDELT `seendate` (`%Y%m%dT%H%M%SZ`), epoch seconds, and ISO strings; naive datetimes are treated as IST (Asia/Kolkata) then converted; output is tz-aware UTC.
  - `headline_hash(title: str) -> str`: sha256 hex of the lower-cased, whitespace-collapsed title.
  - `ShadowRecorder(session_factory: Callable[[], Session])` with `record(symbol: str, title: str, published_at: datetime, source: str, scored: dict) -> bool` (True if inserted, False if a duplicate `(symbol, headline_hash)` already exists). `scored` carries `answers`, `latency_ms`, `model_name`, `model_version`, and optional `finbert_label/score/polarity`.

- [ ] **Step 1: Write failing tests** in `test_headlines.py`: `test_gdelt_seendate_parsed_to_utc` (`seendate="20261028T043000Z"` gives `2026-10-28 04:30 UTC`), `test_yfinance_nested_content_title_and_pubdate`, `test_naive_datetime_treated_as_ist` (naive 10:00 gives 04:30 UTC), `test_missing_title_returns_none`, `test_empty_or_non_string_title_returns_none`, `test_missing_publish_time_returns_none`, `test_hash_ignores_case_and_whitespace`.
- [ ] **Step 2: Write failing tests** in `test_recorder.py` using an in-memory SQLite engine (`ShadowInference.__table__.create(engine)` only, so Postgres-only models are not needed): `test_record_inserts_row`, `test_duplicate_symbol_hash_returns_false_and_stores_once`, `test_same_headline_different_symbol_stored_twice`.
- [ ] **Step 3: Run** `python -m pytest tests/intelligence/decision -v`. Expected: FAIL (modules missing).
- [ ] **Step 4: Implement** `models.py`, `headlines.py`, `recorder.py` per the signatures above. Recorder uses `session_factory()` per call and catches `IntegrityError` for the duplicate case.
- [ ] **Step 5: Run tests.** Expected: PASS.
- [ ] **Step 6: Commit** `feat(intelligence): shadow_inference table, headline normalizer, recorder`.

---

### Task 3: LayaShadowScorer

**Files:**
- Create: `backend/app/intelligence/decision/laya_shadow.py`
- Modify: `backend/requirements.txt` (add `laya` at the version proven in Task 1)
- Test: `backend/tests/intelligence/decision/test_laya_shadow.py`

**Interfaces:**
- Consumes: Task 1's recorded `laya` result shape and English checkpoint name.
- Produces: `LayaShadowScorer(router_factory: Callable[[], Any] | None = None, device: str | None = None)` with `score(headlines: list[str], symbol: str) -> list[dict]`. Each dict: `{"answers": {"event_type": {label: prob}, "material": float, "bullish": float, "urgency": {"0": p, "1": p, "2": p, "3": p}}, "latency_ms": float, "model_name": str, "model_version": str}`. Lazy-loads on first call (like `FinBertSentiment._ensure_loaded`). `router_factory` exists so tests inject a fake; default builds the real `laya` Router. `symbol` is interpolated into the question instructions (e.g. "material to <symbol>").

- [ ] **Step 1: Write failing tests** with a fake router: `test_maps_laya_answers_to_normalized_shape`, `test_latency_ms_measured_and_positive`, `test_lazy_load_only_on_first_score` (factory not called at construction), `test_empty_list_returns_empty_without_loading`, `test_long_headline_truncated_to_512_chars` (match FinBERT's `_MAX_INPUT_LEN`), `test_router_exception_propagates` (the dispatcher, not the scorer, swallows it; Review Focus 4).
- [ ] **Step 2: Run** the file. Expected: FAIL.
- [ ] **Step 3: Implement `LayaShadowScorer`** in `laya_shadow.py` following `finbert.py`'s lazy-load style. Question definitions are module-level constants carrying the exact option sets from Global Constraints.
- [ ] **Step 4: Run tests.** Expected: PASS.
- [ ] **Step 5: Real-model smoke check** (not in the test suite): a short script in the scratchpad calls the default factory on 3 headlines on the 4070 and prints answers and latency. Expected: valid probabilities, p50 under 100 ms.
- [ ] **Step 6: Commit** `feat(intelligence): LayaShadowScorer for shadow-mode decisions`.

---

### Task 4: ShadowDispatcher and the build() hook

**Files:**
- Create: `backend/app/intelligence/decision/dispatch.py`
- Modify: `backend/app/intelligence/context.py` (constructor + one call after the FinBERT block at ~line 80), `backend/app/config.py`, `backend/app/main.py` (~line 128-136)
- Create: `backend/scripts/__init__.py`, `backend/scripts/shadow_overhead_bench.py`
- Test: `backend/tests/intelligence/decision/test_dispatch.py`, extend `backend/tests/intelligence/test_context_builder.py`

**Interfaces:**
- Consumes: `LayaShadowScorer.score`, `ShadowRecorder.record`, `normalize_headline`.
- Produces:
  - `ShadowDispatcher(scorer, recorder, timeout_s: float = 2.0)` with `submit(symbol: str, items: list[dict], finbert: list[dict], source: str) -> bool` (non-blocking; True if accepted, False if busy/degraded/disabled-after-timeout), `stats() -> dict` with `submitted`, `dropped`, `errors`, `timeouts`, and `shutdown() -> None`. Single worker thread. A job running longer than `timeout_s` marks the dispatcher *degraded*: further submits are dropped (counted) until the job returns; the thread cannot be killed.
  - Settings: `SHADOW_LAYA_ENABLED: bool = False`, `SHADOW_LAYA_TIMEOUT_S: float = 2.0`.
  - `IntelligenceContextBuilder.__init__(..., shadow: ShadowDispatcher | None = None)`. Existing callers and tests unchanged when omitted.

- [ ] **Step 1: Write failing tests** in `test_dispatch.py`: `test_submit_returns_immediately_while_worker_busy` (fake scorer sleeps 0.3 s; `submit` returns in under 10 ms), `test_second_submit_while_busy_is_dropped_and_counted`, `test_scorer_exception_is_swallowed_and_counted` (Review Focus 4), `test_job_longer_than_timeout_marks_degraded_and_drops_later_submits`, `test_items_without_title_or_publish_time_are_skipped_not_recorded` (Review Focus 1), `test_scored_rows_include_finbert_fields`.
- [ ] **Step 2: Write failing tests** appended to `test_context_builder.py`: `test_build_result_identical_with_shadow_enabled` (shadow stub that records calls; `IntelligenceContext` equal to the flag-off result) and `test_build_unaffected_when_shadow_submit_raises` (stub `submit` raises; `build()` still returns).
- [ ] **Step 3: Run** both files. Expected: FAIL.
- [ ] **Step 4: Implement** `dispatch.py`, add the two settings, and in `build()` call `self._shadow.submit(...)` inside its own try/except right after the FinBERT block (only when `self._shadow` is set and `news_items` is non-empty). Source label comes from `sources_used` (the winning vendor).
- [ ] **Step 5: Wire in `main.py`:** when `settings.SHADOW_LAYA_ENABLED`, construct `LayaShadowScorer`, `ShadowRecorder(SessionLocal)`, `ShadowDispatcher`, and pass `shadow=` to the builder; otherwise pass nothing. Also ensure the model module is imported so `create_all` creates `shadow_inference`.
- [ ] **Step 6: Run tests.** Expected: PASS.
- [ ] **Step 7: Overhead bench.** `shadow_overhead_bench.py` runs `build()` 200 times each with the flag off and on (fake registry returning fixed headlines, fake Redis returning `None`, real `FinBertSentiment`, real scorer if CUDA is available), prints p95 for each and the ratio, and exits non-zero if the ratio exceeds 1.05. Run it. Expected: exit 0. Record the numbers in the Phase 0 findings doc appendix.
- [ ] **Step 8: Commit** `feat(intelligence): shadow dispatcher and build() hook behind SHADOW_LAYA_ENABLED`.

---

### Task 5: Headline poller

**Files:**
- Create: `backend/config/nifty50_symbols.yaml`, `backend/scripts/poll_headlines.py`
- Test: `backend/tests/intelligence/decision/test_poller.py`

**Interfaces:**
- Consumes: `normalize_headline`, `LayaShadowScorer.score`, `ShadowRecorder.record`, `YFinanceSource.fetch("get_news", symbol=...)`, `GdeltSource.fetch("get_news", keyword=...)`.
- Produces: `nifty50_symbols.yaml` as a list of `{symbol: "RELIANCE", ticker: "RELIANCE.NS", keywords: ["Reliance Industries"]}` for all 50 names; `poll_once(symbols: list[dict], sources: list, scorer, recorder, finbert) -> dict` returning `{"fetched": int, "recorded": int, "duplicates": int, "dropped_no_time": int}`; a `main()` with `--interval-seconds` (default 900) and `--once`, run as `python -m scripts.poll_headlines`.

- [ ] **Step 1: Write failing tests** with fake sources/scorer/recorder: `test_poll_once_records_new_headlines`, `test_poll_once_counts_duplicates_across_sources` (same title from two sources recorded once; Review Focus 2), `test_items_without_publish_time_counted_not_recorded`, `test_one_failing_source_does_not_stop_the_pass`, `test_symbol_keywords_used_for_gdelt_not_ticker`.
- [ ] **Step 2: Run.** Expected: FAIL.
- [ ] **Step 3: Implement** `poll_once` and `main`. Use the same `FinBertSentiment` instance for the baseline so rows carry `finbert_*`. Fill `nifty50_symbols.yaml` with the real NIFTY 50 constituents (verify the list against NSE's current index composition; note the date checked in a YAML comment).
- [ ] **Step 4: Run tests.** Expected: PASS.
- [ ] **Step 5: Live dry run** `python -m scripts.poll_headlines --once` against 3 symbols; expect rows in `shadow_inference` and a printed summary. Record headlines/day in the findings doc.
- [ ] **Step 6: Commit** `feat(intelligence): standalone NIFTY 50 headline poller for shadow data`.

---

### Task 6: Outcome fill

**Files:**
- Create: `backend/app/intelligence/decision/outcomes.py`, `backend/scripts/fill_outcomes.py`
- Test: `backend/tests/intelligence/decision/test_outcomes.py`

**Interfaces:**
- Produces:
  - `align_t0(published_at_utc: datetime) -> datetime`: returns `published_at_utc` if it falls inside the NSE session (09:15-15:30 IST, Mon-Fri); otherwise the next session's 09:15 IST open (UTC-aware). Holidays are not modelled here; the fill step marks them unfillable when no bar exists.
  - `forward_return(close: pandas.Series, t0: datetime, horizon: timedelta) -> float | None`: `close` indexed by tz-aware timestamps; uses the first bar at or after `t0` and the first bar at or after `t0 + horizon`; `None` if either is missing or more than 2 bars away from its target.
  - `adjusted_return(stock: Series, index: Series, t0, horizon) -> float | None`: stock return minus index return.
  - `materiality_threshold(stock: Series, index: Series, as_of: datetime) -> float | None`: 75th percentile of absolute adjusted 1h returns over the 60 trading days before `as_of`; `None` if fewer than 20 days of bars.
  - `fill_outcomes.py` `main()`: for rows with `outcome_filled_at IS NULL AND unfillable = FALSE` whose +1d horizon has elapsed, fetch bars (yfinance, `interval="1h"`, ticker from `nifty50_symbols.yaml`, index `^NSEI`), cache per symbol per day in-process, set the four returns and `material`, bump `fill_attempts`; after 3 failed attempts set `unfillable = True`.

- [ ] **Step 1: Write failing tests**: `test_align_t0_inside_session_unchanged`, `test_align_t0_after_close_moves_to_next_open`, `test_align_t0_friday_evening_moves_to_monday_open`, `test_align_t0_early_morning_moves_to_same_day_open`, `test_forward_return_basic`, `test_forward_return_missing_bar_returns_none` (Review Focus 5), `test_adjusted_return_subtracts_index`, `test_materiality_threshold_is_75th_percentile` (fixed synthetic series), `test_threshold_none_when_history_short`.
- [ ] **Step 2: Run.** Expected: FAIL.
- [ ] **Step 3: Implement** `outcomes.py` pure functions, then `fill_outcomes.py` using them. `ret_eod` = return to the last bar of t0's session day; `ret_1d` = return to the first bar at or after `t0 + 24h`.
- [ ] **Step 4: Run tests.** Expected: PASS.
- [ ] **Step 5: Add a DB-level test** `test_fill_marks_unfillable_after_three_attempts` with a fake price fetcher returning empty bars (in-memory SQLite).
- [ ] **Step 6: Commit** `feat(intelligence): outcome-fill for shadow_inference (index-adjusted forward returns)`.

---

### Task 7: Metrics, evaluation script, verdict

**Files:**
- Create: `backend/app/intelligence/decision/metrics.py`, `backend/scripts/shadow_eval.py`
- Test: `backend/tests/intelligence/decision/test_metrics.py`

**Interfaces:**
- Produces:
  - `auroc(y_true: Sequence[int], y_score: Sequence[float]) -> float` (rank-based, numpy only; ties averaged).
  - `brier(y_true, p) -> float`; `ece(y_true, p, bins: int = 10) -> float`.
  - `paired_bootstrap_diff(y_true, score_a, score_b, metric: Callable, n: int = 2000, seed: int = 0) -> tuple[float, float, float]`: `(mean diff a minus b, ci_low, ci_high)` at 95%.
  - `verdict(n_labeled: int, auroc_diff_ci: tuple[float, float, float], urgency_auroc: float, latency_p50_ms: float, overhead_ratio: float) -> str` returning one of `"insufficient_data"`, `"kill"`, `"inconclusive_finetune"`, `"adopt"`. Rules (my interpretation of the spec's decision rule, flag to the user): `insufficient_data` if `n_labeled < 500`; `kill` if `latency_p50_ms > 100` or `overhead_ratio > 1.05`, or CI upper bound < 0 and `urgency_auroc <= 0.55`; `adopt` if CI lower bound > 0; otherwise `inconclusive_finetune`.
  - `shadow_eval.py`: reads filled rows with `unfillable = FALSE`, builds the label from `material`, compares `answers.material` (Laya) vs `abs(finbert_polarity)` (baseline) via AUROC, Brier/ECE for Laya, secondary directional hit rate for `bullish` vs sign of `ret_1h`, robustness AUROC at other horizons, prints a one-page report ending in the `verdict(...)` string.

- [ ] **Step 1: Write failing tests**: `test_auroc_perfect_and_random_and_inverse` (1.0, 0.5, 0.0 on constructed data), `test_auroc_ties_averaged`, `test_brier_known_value`, `test_ece_perfectly_calibrated_is_zero`, `test_bootstrap_ci_contains_zero_for_identical_scores`, `test_bootstrap_deterministic_with_seed`, and one test per verdict branch: `test_verdict_insufficient_data`, `test_verdict_kill_on_latency`, `test_verdict_kill_on_overhead`, `test_verdict_adopt_when_ci_above_zero`, `test_verdict_inconclusive_when_ci_straddles_zero`.
- [ ] **Step 2: Run.** Expected: FAIL.
- [ ] **Step 3: Implement** `metrics.py` (numpy only), then `shadow_eval.py`.
- [ ] **Step 4: Run tests.** Expected: PASS.
- [ ] **Step 5: Dry run `shadow_eval.py`** against the shadow table once rows exist (or against a synthetic fixture); expect a readable report and a verdict string.
- [ ] **Step 6: Commit** `feat(intelligence): shadow evaluation metrics and verdict`.

---

### Task 8: Collection run and report

**Files:**
- Modify: `docs/superpowers/specs/2026-10-28-laya-phase0-findings.md` (append results)

**Interfaces:**
- Consumes: everything above.

- [ ] **Step 1: Enable** `SHADOW_LAYA_ENABLED=true` in the local `.env`, start the poller on its schedule and the app as usual. Confirm rows appear.
- [ ] **Step 2: After the first day,** report headlines/day. If 500 labeled headlines projects past ~2 weeks, STOP and report to the user.
- [ ] **Step 3: Schedule `fill_outcomes.py`** (daily is enough) and let it run.
- [ ] **Step 4: At 500 labeled rows, run `shadow_eval.py`,** append the report and verdict to the findings doc, and commit `docs: laya shadow spike results`.
- [ ] **Step 5: Act on the verdict:** `kill` removes the hook (flag off, code left or reverted per the user); `inconclusive_finetune` and `adopt` each start a new design through brainstorming. Do not integrate Laya into live decisions inside this plan.
