# Laya Shadow-Mode Spike Implementation Plan (revised after Phase 0: poller-only venv)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Poll NIFTY 50 headlines, answer them with Laya and a FinBERT baseline in an isolated environment, fill realised forward returns, and report whether Laya predicts *materiality* better than the baseline.

**Architecture:** A self-contained package `backend/spike/laya_shadow/` with its own venv and SQLite file. A poller fetches headlines, scores them with Laya (GPU) and FinBERT, and writes `shadow_inference` rows. A fill script adds index-adjusted forward returns and the materiality label. An evaluation script computes metrics and a verdict. The app (`backend/app`, its torch, its requirements) is **not touched**; nothing here imports `app.*`.

**Tech Stack:** Python 3.12, torch 2.5.1+cu121, transformers 4.48-4.55, `laya==0.4.17`, SQLAlchemy 2, pandas/numpy, yfinance, gdelt-doc-api, pytest (+ pytest-asyncio if needed).

**Specs:** `docs/superpowers/specs/2026-10-28-laya-shadow-spike-design.md` (read Amendment 1 first) and `docs/superpowers/specs/2026-10-28-laya-phase0-findings.md`.

## Global Constraints

- Laya output never reaches any live decision path. The app is untouched.
- Primary target: materiality = |index-adjusted return at +1h| above the **75th percentile** of that symbol's last **60 trading days** of 1h bars (unconditional distribution). Index: **NIFTY 50 (`^NSEI`)**. Scope: **NIFTY 50 symbols only**.
- Primary horizon +1h. Also store +15m, EOD, +1d (robustness only). Chosen before data; never retuned after.
- t0 = source **publish time** (store `observed_at` too). Drop items with no publish time and report the drop rate. After-hours t0 = next market open; return measured open to open + 1h.
- Minimum **500** labeled headlines before any verdict; 95% bootstrap CIs on all comparisons.
- English checkpoint `convaiinnovations/laya` (`Router(device=...).predict({"message": text}, questions, model="english")`). Four questions: `event_type` (choice: earnings, macro_policy, regulatory, geopolitical, corporate_action, other_noise), `material_to_symbol` (noul), `bullish_for_symbol` (noul), `urgency` (score, 4 criteria 0-3).
- Kill: p50 Laya latency above **100 ms** on the 4070, or no lift (Task 6).
- Storage: SQLite, `SHADOW_DB_URL` env override, default `sqlite:///backend/spike/shadow.db`; DB file git-ignored.
- Time box 1-2 working days to build; collection time depends on volume. If NIFTY 50 volume projects past ~2 weeks to 500 labeled headlines, report back instead of extending silently.
- Run every command from the repo root with `backend/spike/.venv/Scripts/python` (call it `$PY`). Tests: `cd backend/spike && $PY -m pytest tests -v` with `PY=.venv/Scripts/python`.

## Review Focus

1. Headline with missing/empty/non-string title or no publish time: skipped and counted, never raises (Task 2).
2. Same headline from GDELT and yfinance: stored once per symbol (Tasks 2, 4).
3. Publish times in IST vs UTC vs naive vs epoch: normalized to tz-aware UTC before t0 alignment (Tasks 2, 5).
4. Laya or a news source raising / returning nothing / CUDA out-of-memory: the poll pass continues, errors counted (Tasks 3, 4).
5. Missing prices, holidays, weekend headlines: row retried then marked `unfillable` and excluded from metrics, never given a wrong return (Task 5).

---

## File Structure (all under `backend/spike/`)

- `requirements-spike.txt` (exists), `conftest.py` (empty; puts this dir on `sys.path`), `nifty50_symbols.yaml`
- `laya_shadow/__init__.py`, `models.py`, `headlines.py`, `recorder.py`, `scorer.py`, `baseline.py`, `poller.py`, `outcomes.py`, `fill.py`, `metrics.py`, `evaluate.py`
- `tests/__init__.py`, `tests/test_headlines.py`, `test_recorder.py`, `test_scorer.py`, `test_poller.py`, `test_outcomes.py`, `test_metrics.py`
- Add `backend/spike/shadow.db` to `.gitignore` (`.venv/` is already ignored).

---

### Task 1: Finish Phase 0 in the new venv (findings doc is the deliverable)

**Files:**
- Modify: `docs/superpowers/specs/2026-10-28-laya-phase0-findings.md` (append "Resolved in spike venv")
- Create: `backend/spike/conftest.py` (empty), update `.gitignore`

**Interfaces:**
- Produces: confirmation that the venv works, plus real item shapes, volume and drop rate that Tasks 2 and 4 depend on.

- [ ] **Step 1: Verify the venv.** `$PY -c "import torch,laya,transformers;print(torch.__version__,torch.cuda.is_available(),transformers.__version__)"`. Expected: torch 2.5.1+cu121, True, transformers 4.4x-4.55. Re-run the Phase 0 Laya probe **without** the `torch.compile` stub on 10 headlines; Expected: loads, p50 under 100 ms.
- [ ] **Step 2: Verify FinBERT** loads in this venv (`transformers.pipeline("sentiment-analysis", model="ProsusAI/finbert")` on one headline). Expected: a label and score.
- [ ] **Step 3: Read the Hugging Face model card** for `convaiinnovations/laya` (WebFetch `huggingface.co/convaiinnovations/laya`): record license and intended use.
- [ ] **Step 4: Record real item shapes.** For `GdeltDoc().article_search(Filters(keyword="Reliance Industries", timespan="1d"))` and `yfinance.Ticker("RELIANCE.NS").news`, print the keys of one item and where title / publish time live. Record whether either lacks a publish time.
- [ ] **Step 5: Measure volume and drop rate** for 5 NIFTY 50 names over one pass (headlines per symbol per day from each source; % without publish time).
- [ ] **Step 6: Append results to the findings doc** with GO/NO-GO: GO needs working venv, acceptable license, p50 under 100 ms, publish-time drop rate not "most". Commit `docs: laya phase 0 resolved in spike venv`. If NO-GO, stop and report.

---

### Task 2: Table, headline normalizer, recorder

**Files:**
- Create: `laya_shadow/__init__.py`, `models.py`, `headlines.py`, `recorder.py`; `tests/__init__.py`, `tests/test_headlines.py`, `tests/test_recorder.py`

**Interfaces:**
- Produces:
  - `models.py`: SQLAlchemy 2 `Base` and `ShadowInference`, table `shadow_inference`. Columns: `id` Integer PK; `observed_at` DateTime(tz) default now, indexed; `published_at` DateTime(tz) not null, indexed; `symbol` String not null, indexed; `headline` Text not null; `headline_hash` String(64) not null; `source` String; `model_name` String; `model_version` String; `answers` JSON; `latency_ms` Float; `finbert_label` String null; `finbert_score` Float null; `finbert_polarity` Float null; `ret_15m`, `ret_1h`, `ret_eod`, `ret_1d` Float null; `material` Boolean null; `fill_attempts` Integer default 0; `unfillable` Boolean default False; `outcome_filled_at` DateTime(tz) null. `UniqueConstraint("symbol", "headline_hash")`. `make_session_factory(url: str | None = None) -> Callable[[], Session]` creates tables if missing (uses `SHADOW_DB_URL` env or the default).
  - `headlines.py`: `normalize_headline(item: dict) -> tuple[str, datetime] | None` returning `(title, published_at_utc)` or `None` when title is missing/empty/non-string or no publish time. Handles top-level `title`, nested `content.title`; publish time from `published_at`, `pubDate`, `content.pubDate`, GDELT `seendate` (`%Y%m%dT%H%M%SZ`), epoch seconds, ISO strings; naive datetimes are IST (Asia/Kolkata) then converted; output is tz-aware UTC. `headline_hash(title: str) -> str`: sha256 hex of the lower-cased, whitespace-collapsed title.
  - `recorder.py`: `ShadowRecorder(session_factory)` with `record(symbol: str, title: str, published_at: datetime, source: str, scored: dict) -> bool` (False if `(symbol, headline_hash)` already exists). `scored` keys: `answers`, `latency_ms`, `model_name`, `model_version`, optional `finbert_label`, `finbert_score`, `finbert_polarity`.

- [ ] **Step 1: Write failing tests.** `test_headlines.py`: `test_gdelt_seendate_parsed_to_utc` (`"20261028T043000Z"` gives 04:30 UTC), `test_yfinance_nested_content_title_and_pubdate`, `test_naive_datetime_treated_as_ist` (naive 10:00 gives 04:30 UTC), `test_epoch_seconds_parsed`, `test_rfc822_pubdate_parsed_to_utc`, `test_trailing_publisher_suffix_stripped`, `test_missing_title_returns_none`, `test_empty_or_non_string_title_returns_none`, `test_missing_publish_time_returns_none`, `test_hash_ignores_case_and_whitespace`. `test_recorder.py` (in-memory SQLite): `test_record_inserts_row`, `test_duplicate_symbol_hash_returns_false_and_stores_once`, `test_same_headline_different_symbol_stored_twice`.
- [ ] **Step 2: Run** `cd backend/spike && $PY -m pytest tests -v`. Expected: FAIL (modules missing).
- [ ] **Step 3: Implement** the three modules per the signatures. Recorder uses a session per call and catches `IntegrityError` for the duplicate case.
- [ ] **Step 4: Run tests.** Expected: PASS.
- [ ] **Step 5: Commit** `feat(spike): shadow_inference table, headline normalizer, recorder`.

---

### Task 3: Laya scorer and FinBERT baseline

**Files:**
- Create: `laya_shadow/scorer.py`, `laya_shadow/baseline.py`; `tests/test_scorer.py`

**Interfaces:**
- Produces:
  - `LayaScorer(router_factory: Callable[[], Any] | None = None, device: str | None = None)` with `score(headline: str, symbol: str) -> dict` returning `{"answers": {"event_type": {label: p}, "material": float, "bullish": float, "urgency": {"0": p, "1": p, "2": p, "3": p}}, "latency_ms": float, "model_name": "convaiinnovations/laya", "model_version": str}`. `model_version` is Laya's pinned revision for the English repo (`laya.PINNED_REVISIONS["convaiinnovations/laya"]`). Lazy-loads on first `score`. Headline truncated to 512 characters. `symbol` is interpolated into the question instructions. Maps from Laya's output (`answers[q]["probabilities"]`, `["noul"]`) per `2026-10-28-laya-phase0-findings.md`.
  - `FinBertBaseline` with `score(headline: str) -> dict` returning `{"label": str, "score": float, "polarity": float}` where polarity = sign(label) * score (positive 1, negative -1, neutral 0), same convention as `app/intelligence/sentiment/finbert.py`. Lazy-loaded `ProsusAI/finbert`, 512-character truncation.

- [ ] **Step 1: Write failing tests** with a fake router: `test_maps_laya_answers_to_normalized_shape`, `test_latency_ms_measured_and_positive`, `test_lazy_load_only_on_first_score`, `test_long_headline_truncated_to_512_chars`, `test_router_exception_propagates` (the poller swallows it; Review Focus 4). Baseline test with a fake pipeline: `test_polarity_sign_follows_label`.
- [ ] **Step 2: Run.** Expected: FAIL.
- [ ] **Step 3: Implement** both modules.
- [ ] **Step 4: Run tests.** Expected: PASS.
- [ ] **Step 5: Real-model smoke** (not in the suite): score 3 headlines on the 4070 with `LayaScorer()` and `FinBertBaseline()`; print outputs and latency. Expected: valid probabilities, p50 under 100 ms.
- [ ] **Step 6: Commit** `feat(spike): Laya scorer and FinBERT baseline`.

---

### Task 4: Poller

**Files:**
- Create: `nifty50_symbols.yaml`, `laya_shadow/poller.py`; `tests/test_poller.py`

**Interfaces:**
- Consumes: `normalize_headline`, `LayaScorer.score`, `FinBertBaseline.score`, `ShadowRecorder.record`.
- Produces: `nifty50_symbols.yaml` as a list of `{symbol: "RELIANCE", ticker: "RELIANCE.NS", keywords: ["Reliance Industries"]}` for the 50 current constituents (verify against NSE; note the check date in a YAML comment). `NewsSource` protocol: `fetch(entry: dict) -> list[dict]` raw items; `GoogleNewsRss` (PRIMARY: `https://news.google.com/rss/search?q=<keywords[0]>+when:1d&hl=en-IN&gl=IN&ceid=IN:en`, returns dicts with `title`, `pubDate`, `link`, `source`), `YahooSearchNews` (`yf.Search(keywords[0]).news`, epoch `providerPublishTime`) and `GdeltNews` (`gdeltdoc`, skipped for the rest of the pass on `RateLimitError`, >=10 s between requests). `Ticker(...).news` is NOT used (returns nothing). `normalize_headline` strips a trailing ' - <publisher>' from titles and parses RFC 822 `pubDate`. `poll_once(symbols: list[dict], sources: list[NewsSource], scorer, baseline, recorder) -> dict` returning `{"fetched", "recorded", "duplicates", "dropped_no_time", "errors"}`. CLI `python -m laya_shadow.poller [--once] [--interval-seconds 900]`.

- [ ] **Step 1: Write failing tests** with fake sources/scorer/baseline/recorder: `test_poll_once_records_new_headlines`, `test_same_title_from_two_sources_recorded_once` (Review Focus 2), `test_items_without_publish_time_counted_not_recorded` (Review Focus 1), `test_failing_source_does_not_stop_pass` and `test_scorer_exception_counted_and_pass_continues` (Review Focus 4), `test_gdelt_uses_keywords_not_ticker`, `test_gdelt_rate_limit_skips_source_for_rest_of_pass`, `test_google_rss_item_parsed` (RFC 822 pubDate to UTC, publisher suffix stripped).
- [ ] **Step 2: Run.** Expected: FAIL.
- [ ] **Step 3: Implement** `poller.py` and fill `nifty50_symbols.yaml`. Skip scoring for titles already stored for that symbol (check hash first) so repeat passes are cheap.
- [ ] **Step 4: Run tests.** Expected: PASS.
- [ ] **Step 5: Live dry run** `$PY -m laya_shadow.poller --once` on 3 symbols (add a `--limit` flag for that). Expected: rows in the SQLite DB and a printed summary. Record headlines/day in the findings doc.
- [ ] **Step 6: Commit** `feat(spike): NIFTY 50 headline poller`.

---

### Task 5: Outcome fill

**Files:**
- Create: `laya_shadow/outcomes.py`, `laya_shadow/fill.py`; `tests/test_outcomes.py`

**Interfaces:**
- Produces:
  - `align_t0(published_at_utc: datetime) -> datetime`: unchanged if inside the NSE session (09:15-15:30 IST, Mon-Fri); otherwise the next session's 09:15 IST open (tz-aware UTC). Holidays are not modelled; the fill step marks them unfillable when no bar exists.
  - `forward_return(close: pandas.Series, t0: datetime, horizon: timedelta) -> float | None`: `close` has a tz-aware index; uses the first bar at or after `t0` and the first bar at or after `t0 + horizon`; `None` if either is missing or more than 2 bars from its target.
  - `adjusted_return(stock: Series, index: Series, t0, horizon) -> float | None`: stock minus index.
  - `materiality_threshold(stock: Series, index: Series, as_of: datetime) -> float | None`: 75th percentile of absolute adjusted 1h returns over the 60 trading days before `as_of`; `None` with fewer than 20 days.
  - `fill.py` CLI `python -m laya_shadow.fill`: for rows with `outcome_filled_at IS NULL AND unfillable = FALSE` whose +1d horizon has elapsed, fetch 1h bars (yfinance, ticker from the YAML, index `^NSEI`), cache per symbol per day, set the four returns and `material`, bump `fill_attempts`; after 3 failed attempts set `unfillable = True`. `ret_eod` = return to the last bar of t0's session day; `ret_1d` = return to the first bar at or after `t0 + 24h`.

- [ ] **Step 1: Write failing tests**: `test_align_t0_inside_session_unchanged`, `test_align_t0_after_close_moves_to_next_open`, `test_align_t0_friday_evening_moves_to_monday_open`, `test_align_t0_early_morning_moves_to_same_day_open`, `test_forward_return_basic`, `test_forward_return_missing_bar_returns_none` (Review Focus 5), `test_adjusted_return_subtracts_index`, `test_materiality_threshold_is_75th_percentile` (fixed synthetic series), `test_threshold_none_when_history_short`, and a DB test `test_fill_marks_unfillable_after_three_attempts` (fake price fetcher returning empty bars, in-memory SQLite).
- [ ] **Step 2: Run.** Expected: FAIL.
- [ ] **Step 3: Implement** `outcomes.py` pure functions, then `fill.py`.
- [ ] **Step 4: Run tests.** Expected: PASS.
- [ ] **Step 5: Commit** `feat(spike): outcome fill (index-adjusted forward returns, materiality label)`.

---

### Task 6: Metrics, evaluation, verdict

**Files:**
- Create: `laya_shadow/metrics.py`, `laya_shadow/evaluate.py`; `tests/test_metrics.py`

**Interfaces:**
- Produces:
  - `auroc(y_true, y_score) -> float` (rank-based, numpy only, ties averaged); `brier(y_true, p) -> float`; `ece(y_true, p, bins: int = 10) -> float`.
  - `paired_bootstrap_diff(y_true, score_a, score_b, metric: Callable, n: int = 2000, seed: int = 0) -> tuple[float, float, float]`: `(mean diff a minus b, ci_low, ci_high)` at 95%.
  - `verdict(n_labeled: int, auroc_diff_ci: tuple[float, float, float], urgency_auroc: float, latency_p50_ms: float) -> str` in `{"insufficient_data", "kill", "inconclusive_finetune", "adopt"}`. Rules (my reading of the spec; flag to the user): `insufficient_data` if `n_labeled < 500`; `kill` if `latency_p50_ms > 100`, or CI upper bound < 0 and `urgency_auroc <= 0.55`; `adopt` if CI lower bound > 0; else `inconclusive_finetune`.
  - `evaluate.py` CLI `python -m laya_shadow.evaluate`: reads filled, non-unfillable rows; label = `material`; compares `answers.material` (Laya) vs `abs(finbert_polarity)` (baseline) by AUROC with the paired bootstrap; Laya Brier/ECE; secondary directional hit rate of `bullish` vs sign of `ret_1h`; robustness AUROC at other horizons; prints a one-page report ending with the verdict.

- [ ] **Step 1: Write failing tests**: `test_auroc_perfect_random_inverse` (1.0, 0.5, 0.0), `test_auroc_ties_averaged`, `test_brier_known_value`, `test_ece_perfectly_calibrated_is_zero`, `test_bootstrap_ci_contains_zero_for_identical_scores`, `test_bootstrap_deterministic_with_seed`, `test_verdict_insufficient_data`, `test_verdict_kill_on_latency`, `test_verdict_adopt_when_ci_above_zero`, `test_verdict_inconclusive_when_ci_straddles_zero`.
- [ ] **Step 2: Run.** Expected: FAIL.
- [ ] **Step 3: Implement** `metrics.py`, then `evaluate.py`.
- [ ] **Step 4: Run tests.** Expected: PASS.
- [ ] **Step 5: Dry run** `evaluate` on a synthetic fixture DB; expect a readable report and a verdict string.
- [ ] **Step 6: Commit** `feat(spike): evaluation metrics and verdict`.

---

### Task 7: Collection run and report

**Files:**
- Modify: `docs/superpowers/specs/2026-10-28-laya-phase0-findings.md` (append results)

- [ ] **Step 1: Start the poller** on its schedule (`python -m laya_shadow.poller --interval-seconds 900`) and confirm rows appear.
- [ ] **Step 2: After the first day,** report headlines/day. If 500 labeled headlines projects past ~2 weeks, stop and report to the user.
- [ ] **Step 3: Run `python -m laya_shadow.fill`** daily.
- [ ] **Step 4: At 500 labeled rows,** run `evaluate`, append the report and verdict to the findings doc, commit `docs: laya shadow spike results`.
- [ ] **Step 5: Act on the verdict:** `kill` stops the poller; `inconclusive_finetune` and `adopt` each start a new design through brainstorming. Do not integrate Laya into live decisions inside this plan.
