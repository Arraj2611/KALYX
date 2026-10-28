# Laya Shadow-Mode Spike — Design

Date: 2026-10-28 | Branch context: `feat/broker-abstraction` | Status: approved, amended after Phase 0

## Amendment 1 (after Phase 0, user decision: poller-only venv)

Phase 0 (`2026-10-28-laya-phase0-findings.md`) showed Laya cannot run in the app's
environment (torch 2.3.1 on Python 3.12 cannot import ModernBERT). The user chose to run
the spike in its own isolated environment. These changes **supersede** conflicting text below:

- **No `build()` hook, no `ShadowDispatcher`, no changes to `context.py`, `config.py`,
  `main.py` or the app's `requirements.txt`.** The app and its torch are untouched.
- The spike lives in `backend/spike/` with its own venv (`backend/spike/.venv`, git-ignored),
  its own `requirements-spike.txt` (torch 2.5.1+cu121, transformers 4.48-4.55, `laya==0.4.17`),
  and a self-contained package `backend/spike/laya_shadow/`. It imports nothing from `app.*`
  (the app's `Settings` requires Zerodha env vars at import time).
- **Storage:** a local SQLite file (`backend/spike/shadow.db`, git-ignored; override with
  `SHADOW_DB_URL`), not the app's Postgres. My call: zero risk to production data, no
  Postgres needed to run the spike.
- **Data source is the poller only.** FinBERT baseline is computed inside the poller in the
  same venv. Consequence: the spike does not observe the live `build()` news path; it
  observes what the poller fetches. The "no measurable slowdown of build()" criterion and
  the 5% overhead benchmark are **removed** (nothing to slow down).
- **Kill criteria now:** p50 latency above 100 ms on the 4070, or no lift (see Decision rule).
- Phase 0 still owes: real GDELT / yfinance item shapes, headline volume, publish-time drop
  rate, and the Hugging Face model card read. They are done in the new venv before Phase 1.
- Early warning from Phase 0 (10 headlines, zero-shot): `event_type` looked right, but
  `bullish_for_symbol` and `material_to_symbol` were confidently wrong. Expect
  "inconclusive, fine-tune" as the most likely verdict.

## Intent and why

KALYX scores news with FinBERT (`intelligence/sentiment/finbert.py`), called from
`IntelligenceContextBuilder.build()` (`intelligence/context.py`, the
`self._sentiment.score_batch(...)` call). FinBERT gives one sentiment label per
headline. It cannot say what *kind* of event a headline is, whether it matters to a
given symbol, or how urgent it is.

Laya (ConvAI, open weights, ModernBERT-large, ~421M params) is a non-autoregressive
"System One" decision model. It answers typed questions (`choice`, `score`, `noul` =
calibrated P(true)) about a piece of text in one forward pass. We want to find out,
cheaply and without risk to trading, whether Laya adds real predictive value over
FinBERT, mainly for **materiality triage**: does this headline move this symbol?

Why Laya and not Jev (TypeSafe AI): Laya is self-hostable and fine-tunable; Jev is a
closed, cloud-only, waitlisted API that would add a network and vendor dependency
and send trade context to a third party. This choice is the user's, made on
2026-10-28. All published speed/accuracy numbers for both models are vendor-claimed
and unverified, which is the reason this is a measured spike and not an integration.

## Goals

- Run Laya in **shadow mode** next to FinBERT on live headlines. FinBERT's output
  stays the only value the system uses.
- Log every Laya answer, with FinBERT's output for the same headline, to a new table.
- Fill in realised forward returns later and compute whether Laya's answers predict
  outcomes better than FinBERT-derived baselines.
- End with one of three explicit outcomes (see Decision rule).

## Non-goals

- No change to trade execution, signals, sizing, or the Guardian. Guardian stays
  math-only and never calls a model.
- No Jev integration.
- No fine-tuning in phase 1. The shadow table is designed so it can later serve as
  the training set.
- No new long-running service, queue, or DB. The one allowed addition is a small
  standalone poller script (see Components, item 6), approved by the user.

## Anti-goals (failure even if it "works")

- Any measurable slowdown or new failure mode in `IntelligenceContextBuilder.build()`.
- Judging success on a horizon or metric chosen after seeing the results.
- Laya output leaking into any live decision path.

## Constraints (verified against the repo and machine, 2026-10-28)

- Machine: NVIDIA RTX 4070 Laptop GPU; torch 2.3.1+cu118, `cuda.is_available()` True.
- `backend/requirements.txt` has `transformers>=4.40.0` and `torch>=2.2.0` unpinned.
  ModernBERT needs a newer transformers than 4.40; compatibility with torch 2.3.1 is
  **unverified**. Settled by the feasibility gate below.
- DB tables are created with `Base.metadata.create_all` (`app/data/database.py`); there
  is no migration tool. A new SQLAlchemy model creates its own table.
- Laya license: one source says Apache 2.0, another does not state it. Verify on the
  Hugging Face model card before adding any dependency.
- Python 3.12 (pycache evidence); Windows 11 dev machine.

## Phase 0 — Feasibility gate (about 30 minutes, throwaway, nothing committed)

Run in a scratch venv or the scratchpad, not in the project environment:

1. `pip install laya` resolves with a working torch/transformers combination.
2. Weights download and load on the 4070.
3. Run ~20 real headlines (taken from the news sources KALYX already uses) through the
   four questions below. Record p50/p95 latency, GPU memory.
4. Read the Hugging Face model card: license, intended use, English checkpoint name.

Stop and report if: install cannot coexist with the project's dependencies without
breaking FinBERT, license is restrictive for this use, or p50 latency on the 4070 is
above 100 ms. Otherwise proceed to Phase 1.

## Phase 1 — Shadow mode (the spike proper)

### Components

1. **`LayaShadowScorer`** (`backend/app/intelligence/decision/laya_shadow.py`).
   Lazy-loaded like `FinBertSentiment`; uses the GPU if available, otherwise CPU.
   One method taking a list of headlines plus a symbol and returning per-headline
   answers to the questions below, plus measured latency.
2. **Shadow hook in `build()`.** After FinBERT scoring, schedule the Laya call as a
   background task with a timeout. The result is never awaited on the build path.
   Any exception or timeout is logged at warning level and swallowed. A config flag
   (default off) enables it, so the spike can be switched off without a code change.
3. **`ShadowInference` model + table** (`shadow_inference`), separate from
   `DecisionLog` (which records trade decisions, not model observations). Columns:
   id, timestamp (UTC), symbol, headline (text) and headline hash (dedupe), source,
   model name and version, answers (JSON: every question's probabilities), latency_ms,
   finbert_label, finbert_score, finbert_polarity, and nullable outcome columns
   `ret_15m`, `ret_1h`, `ret_eod`, `ret_1d` (index-adjusted), `outcome_filled_at`.
4. **Outcome-fill job.** Periodically finds rows whose horizons have elapsed, fetches
   prices (existing yfinance source), writes index-adjusted forward returns. Headlines
   arriving outside market hours use the return from the next open. Mirrors the
   `fill_hindsight` pattern in `decisions/logger.py`.
6. **Headline poller** (standalone script, run on a schedule, not part of the app
   process). Polls news for the in-scope symbols so volume does not depend on how often
   the analyst runs, runs the same Laya scorer, and writes `shadow_inference` rows.
   The `build()` hook and the poller share the scorer and table; dedupe by headline
   hash so a headline seen by both is stored once. Scope is **NIFTY 50 symbols only**
   (user decision); this also settles the index for the "material" label (NIFTY 50).
   Poll interval, source selection, and symbol list file are left to the builder.
5. **Evaluation script** (`backend/scripts/` or a notebook; builder's choice) that
   computes the metrics below and prints a one-page report.

### Questions asked per headline (my call; kept under 20 options because Laya
degrades on large label sets)

- `choice` **event_type**: earnings, macro/policy, regulatory, geopolitical,
  corporate action, other/noise.
- `noul` **material_to_symbol**: will this plausibly move this symbol?
- `noul` **bullish_for_symbol**: is this positive for this symbol?
- `score` **urgency**: 0–3.

Use the English checkpoint (ModernBERT-large) first. The multilingual router is out
of scope unless Phase 0 shows the news feeds contain non-English headlines.

### Ground truth and metrics (set before any result is seen)

- **Primary target: materiality.** A headline is "material" if the absolute
  index-adjusted return at **+1h** (primary horizon, chosen for intraday NIFTY
  futures) is in the top quartile of the trailing distribution for that symbol
  (threshold choice is mine; builder may tune it before collecting data, not after).
- **Primary metrics:** AUROC and Brier/ECE of `material_to_symbol` against that
  label.
- **Baseline:** FinBERT absolute polarity (`abs(polarity)`) against the same label,
  on the same headlines (paired comparison).
- **Secondary:** directional hit rate and Brier of `bullish_for_symbol` vs sign of
  the +1h return, against FinBERT polarity sign. Expected to be weak for both;
  reported but not decisive.
- Other horizons (+15m, EOD, +1d) are stored and reported as robustness checks only.
- Report 95% bootstrap confidence intervals on every comparison.

### Sample size

Minimum 500 labeled headlines before any verdict. Because direction is a weak signal,
the directional comparison is expected to stay inconclusive at that size; that is
acceptable because it is secondary. If the primary comparison's interval still
overlaps zero at 500, the outcome is "inconclusive" (below), not "fail".

## Decision rule (agreed up front)

- **Kill:** p50 latency above 100 ms on the 4070; or any measurable slowdown of
  `build()`; or Laya's materiality AUROC is not above the FinBERT baseline's with the
  interval excluding zero **and** also shows no promise in the event_type/urgency
  checks. Remove the hook; keep the notes.
- **Inconclusive, fine-tune:** zero-shot is near chance or the interval overlaps the
  baseline (one source reports ~0.35, near chance, for un-tuned base weights).
  Next phase is fine-tuning on the collected, outcome-labeled headlines. That is a
  new design, back through this process.
- **Adopt as a feature:** Laya beats the baseline with the interval excluding zero.
  Next phase is feeding materiality/urgency into composite scoring
  (`intelligence/scoring/composite.py`) as an additional input behind a flag. Also a
  new design. Even then it never feeds the Guardian.

## Time box

One to two working days for Phase 0 + Phase 1 build. Data collection time depends on
headline volume (unknown; one measured fact the builder should report after Phase 0
or the first day of shadowing). Sub-projects 4 and 5 on the roadmap are not started,
so this must not grow beyond the time box without a new decision.

## Decisions made by the user

- Laya over Jev; self-hosted; shadow mode; FinBERT stays live.
- Primary target is materiality, not direction; primary horizon +1h; decided before
  seeing data.
- Feasibility gate before building; kill criteria as stated above.
- Scope is NIFTY 50 symbols only; a small standalone headline-poller script is allowed
  to feed the spike.

## My calls (change freely)

- Separate `shadow_inference` table rather than extending `DecisionLog`.
- Feature flag default off; background task with timeout.
- The four questions and their option sets.
- Top-quartile threshold for "material".
- English checkpoint first.
- Minimum 500 labeled headlines; bootstrap CIs.
- Not committing this document yet.

## Left to the builder

- Exact background-task mechanism (asyncio task vs thread executor) given how `build()`
  and the GPU call interact.
- Module and script layout, test strategy, config key names.
- Whether to also expose Laya behind a small `DecisionModel` protocol now or wait until
  a second model exists. (Recommendation was an interface; for the spike, a thin
  protocol is fine but not required.)
- Dedupe and batching policy for repeated headlines.

## Clarifications from the builder check (my calls, fixed before data collection)

- **Clock (t0).** Forward returns are measured from the source's **publish time**, not
  observation time. Store both. Drop items with no publish time and report the drop
  rate after Phase 0; if most items lack one, the spike's data is unusable and we stop
  and report.
- **Headline text.** `build()` reads `n.get("title", "")` from raw source dicts. Newer
  yfinance versions nest the title under `content`, so FinBERT may already be scoring
  empty strings in live use (yfinance is not installed in the current Python, so this
  is unverified). Phase 0 logs the real item shape per source. The FinBERT baseline
  uses exactly what the live system feeds it; Laya uses the correctly extracted
  headline. If the live title is empty, that is reported as a finding and **not**
  silently fixed in this spike.
- **Materiality label.** For each symbol, take the last 60 trading days of 1h bars and
  compute the distribution of absolute index-adjusted 1h returns (unconditional, not
  headline-conditional). A headline is "material" if its +1h absolute adjusted return
  exceeds the 75th percentile of that distribution. Index: NIFTY 50 for Indian
  symbols; other symbols are out of scope until a matching index is chosen.
- **Off-hours headlines.** t0 becomes the next market open; the return is open to
  open + 1h.
- **Performance rule.** Shadow work runs on a single-worker executor with
  skip-if-busy (dropped calls are counted and reported). "No measurable slowdown"
  means `build()` p95 with the flag on is within 5% of flag off over at least 200
  runs on the same machine.
- **Dependency conflict.** If Laya cannot coexist with the project's torch/transformers,
  stop and report. No separate inference process; that would be new infrastructure.
- **Persistence.** The shadow table uses the same DB and session factory as
  `DecisionLogger`. The outcome-fill job is a standalone script run on a schedule,
  not inside the app process. Prices are cached per symbol per day to respect yfinance
  limits; rows with missing prices are retried a few times, then marked unfillable
  and excluded from metrics.

## Open items

- Laya license and exact English checkpoint name (Phase 0).
- Torch/transformers compatibility (Phase 0).
- Headline volume per day for NIFTY 50 symbols: unmeasured. The builder reports it after
  the first day of polling. If it projects past about two weeks to 500 labeled
  headlines, report back instead of extending the time box silently.
