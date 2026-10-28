# Laya Phase 0 — Findings (2026-10-28)

Scratch venv (`--system-site-packages`) on the dev machine: Windows 11, Python 3.12.3,
RTX 4070 Laptop GPU, global torch 2.3.1+cu118, global transformers 4.41.2.

## Verdict: BLOCKED — needs a decision (spec says stop and report)

Laya works, but not in the project's current environment.

### Dependency conflict (the stop condition)
- `pip install laya` (0.4.17) pulled `transformers 5.21`, which requires torch >= 2.6.
  With torch 2.3.1 it fails on import (`NameError: name 'nn' is not defined`).
- Pinning `transformers>=4.48,<5` (tested 4.55.4, `huggingface_hub<1`, `tokenizers<0.22`)
  fixes that, but ModernBERT then fails to import: it uses `@torch.compile`, and
  torch 2.3.1 raises `RuntimeError: Dynamo is not supported on Python 3.12+`.
- Probe that worked: with `torch.compile` replaced by a no-op **before** importing
  transformers, Laya loads and runs on the 4070. That is a hack, not a fix. The real fix
  is torch >= 2.4 (Dynamo on 3.12), which is a bigger change to the shared environment.
- The project's `transformers>=4.40.0` is already too loose: ModernBERT needs >= 4.48.
- Separately, the global Python has Keras 3 installed, so a plain `transformers` FinBERT
  pipeline fails there ("install tf-keras"). Unrelated to Laya, but it means FinBERT could
  not be re-tested in the scratch venv. Needs tf-keras or `USE_TF=0`.

### Facts (for later tasks)
- License: PyPI metadata says Apache-2.0 (author Convai Innovations). The Hugging Face
  model card has not been read yet. Package pins model revisions and supports sha256
  digests, which is good practice. A proper supply-chain review of `laya` is still
  recommended before adding it to `requirements.txt`.
- English checkpoint: `convaiinnovations/laya` (pinned revision `55cf4c4e...`).
  Weights download ~100 s on first use; cold load + first call 11.3 s.
- API: `Router(device="cuda").predict({"message": text}, questions, model="english")`
  returns `{"model", "answers", "usage", "routing"}`. Per question:
  - `choice`: `{"choice": label, "probabilities": {label: p}, "confidence", "answer_confidence"}`
  - `noul`: `{"noul": p, "confidence", "answer_confidence"}`
  - `score`: `{"score": float, "probabilities": {"0": p, ...}, "confidence", "answer_confidence"}`
  Note: **the Router.predict signature has no per-headline batching**; one call per headline
  with all four questions answered in one forward pass.
- Latency on the 4070 (4 questions, 20 calls, 2 runs): p50 40-46 ms, p95 64-75 ms,
  max 98 ms. GPU memory ~2.4 GB. Under the 100 ms kill threshold.

### Zero-shot quality: a warning sign
Ten NIFTY-style headlines, English checkpoint, zero-shot:
- `event_type` looks good (earnings headline: `earnings` 0.988).
- `bullish_for_symbol` is badly wrong and very confident: "Reliance Q2 profit beats
  estimates" 0.0001, "TCS wins $1 billion deal" 0.0002, "L&T bags large order" 0.0001, yet
  "RBI imposes penalty on HDFC Bank" 0.94.
- `material_to_symbol` is low for nearly every headline (0.03-0.13) except the crude
  oil one (0.89).
This matches the earlier warning that un-tuned base weights are near chance for domain
tasks. It is 10 samples, not evidence, but it is a strong prior that the spike's likely
outcome is "inconclusive, fine-tune", and that the directional question is unusable
zero-shot.

### Not done (blocked behind the decision)
- Step 4 (real GDELT / yfinance item shapes) and Step 5 (volume, publish-time drop rate):
  `yfinance` is not installed in the global Python; needs the same environment decision.
- Reading the Hugging Face model card.

## Options

1. **Poller-only, separate venv (recommended).** Drop the `build()` hook. Run the poller
   (and Laya, and FinBERT baseline) in its own venv. The app and its torch/transformers are
   untouched, the 5% overhead risk disappears, and the question the spike asks (does Laya
   predict materiality?) does not need the live path. Cost: no shadowing of the live
   `build()` path; we only see what the poller fetches.
2. **Upgrade the project environment** (torch >= 2.4, transformers 4.48-4.55) so the hook
   can live in-app. Wider blast radius, tested against everything else in this repo.
3. **Keep torch 2.3.1, upgrade transformers, no-op `torch.compile` in app code.** Works
   today, but ships a monkeypatch in the app. Not recommended.
4. **Stop here** given the weak zero-shot results, or narrow to `event_type` + `urgency`
   triage only.

---

## Resolved in spike venv (2026-10-28, later)

**Verdict: GO** (conditional on the source change below).

### Environment
- `backend/spike/.venv`: torch 2.5.1+cu121 (CUDA True on the 4070), transformers 4.55.4,
  `laya==0.4.17`, SQLAlchemy 2.1, yfinance 1.7.0, `gdeltdoc` (the PyPI name is `gdeltdoc`;
  `gdelt-doc-api`, which the app's requirements list, does not resolve from the spike venv).
- Laya runs **without** the `torch.compile` hack. English checkpoint, 4 questions, 20 calls:
  cold load + first 9.9 s, **p50 49.7 ms**, p95 94.5 ms, max 98.6 ms, 2.4 GB GPU. The kill
  criterion is p50 over 100 ms, so it passes, but p95 is close to the line.
- FinBERT (`ProsusAI/finbert`) loads on the GPU in the same venv.

### Model card (convaiinnovations/laya)
- Apache 2.0, open weights. Confirmed.
- The card itself says: base checkpoints are **near chance on typed-decisions zero-shot**
  (0.362 vs a 0.461 majority baseline); probabilities ship **over-confident** (per-type
  temperature refit cut mean ECE 0.466 to 0.081); `noul` answers **can follow the option
  labels rather than the input**; choice questions with more than ~20 options perform poorly;
  ordinal `score` is the weakest type; `action.act_probability` has no usable signal; no
  finance validation. Fine-tuning on domain decisions is the stated main route to accuracy.
- This matches what we saw in the 10-headline probe. Treat the expected verdict as
  `inconclusive_finetune`; the spike's real product is a labeled dataset plus a measured
  baseline. Any use of Laya probabilities needs temperature refit on our own data.

### News sources (real behaviour from this machine today)
- `yf.Ticker(sym).news` returns **0 items for every symbol tested, including AAPL**. This
  is what the app's `YFinanceSource.get_news` calls, so it is effectively dead here.
- `yf.Search(name).news` works but is flat and tiny: ~1 item per query. Fields: `title`,
  `providerPublishTime` (epoch), `link`, `publisher`, `relatedTickers`.
- GDELT (`gdeltdoc`) returned `RateLimitError` on every request, including single requests
  8 s apart. The app's `get_news` chain (`scrapling,trafilatura,gdelt`) falls through to
  GDELT, so **live `build()` news is probably empty right now**, meaning live FinBERT may
  be scoring nothing. Out of scope for this spike; worth a separate look.
- **Google News RSS** (`news.google.com/rss/search?q=<name>+when:1d&hl=en-IN&gl=IN&ceid=IN:en`)
  works: 27 to 100 items per name per day (Reliance 100, Infosys 49, HDFC Bank 27, SBI 44,
  Tata Motors 53), **every item has `pubDate`** (RFC 822, GMT), plus `title`, `link`, `source`.
  Titles carry a trailing " - <publisher>" suffix to strip, and some items are stock-quote
  pages, not news. Publish-time drop rate: **0%**. Estimated volume across NIFTY 50 is on
  the order of 1,000+ headlines/day, so 500 labeled headlines is reachable in days.
  Caveat: it is an unofficial public feed; check its terms before anything beyond personal
  research.

### Decision for the plan
Primary poller source is Google News RSS; `yf.Search` and GDELT (with a >=10 s spacing and
backoff, skipped on `RateLimitError`) are optional secondaries. Item shapes recorded above
feed `normalize_headline` (handle RFC 822 `pubDate` strings, epoch `providerPublishTime`,
and strip the " - <publisher>" suffix).
