"""One-page evaluation report: does Laya predict materiality better than a FinBERT baseline?

Run:  python -m laya_shadow.evaluate
"""
import numpy as np

from laya_shadow.metrics import auroc, brier, ece, paired_bootstrap_diff, verdict

_HORIZONS = ("ret_15m", "ret_eod", "ret_1d")


def _urgency_expected(urgency: dict) -> float:
    return sum(int(k) * float(v) for k, v in urgency.items())


def evaluate_rows(rows: list[dict]) -> tuple[str, str]:
    """rows: dicts with material, answers, finbert_polarity, latency_ms, ret_* (filled, not unfillable)."""
    n = len(rows)
    y = np.array([int(r["material"]) for r in rows])
    laya = np.array([r["answers"]["material"] for r in rows])
    base = np.array([abs(r["finbert_polarity"]) for r in rows])
    urgency = np.array([_urgency_expected(r["answers"]["urgency"]) for r in rows])
    latency_p50 = float(np.median([r["latency_ms"] for r in rows])) if rows else float("nan")
    lines = [f"Labeled headlines: {n}   material rate: {y.mean():.3f}" if n else "Labeled headlines: 0"]
    if n == 0 or len(set(y)) < 2:
        lines.append("Only one class present: no AUROC possible.")
        result = "insufficient_data"
        lines.append(f"VERDICT: {result}")
        return "\n".join(lines), result

    a_laya, a_base, a_urg = auroc(y, laya), auroc(y, base), auroc(y, urgency)
    ci = paired_bootstrap_diff(y, laya, base, auroc)
    lines += [
        f"Materiality AUROC  Laya {a_laya:.3f}  FinBERT |polarity| {a_base:.3f}",
        f"AUROC diff (Laya - FinBERT) {ci[0]:+.3f}  95% CI [{ci[1]:+.3f}, {ci[2]:+.3f}]",
        f"Laya material Brier {brier(y, laya):.3f}  ECE {ece(y, laya):.3f}",
        f"Urgency (expected score) AUROC {a_urg:.3f}",
        f"Laya latency p50 {latency_p50:.1f} ms (median, robust to the cold first call)",
    ]
    dir_rows = [r for r in rows if r.get("ret_1h") is not None]
    if dir_rows:
        up = np.array([r["ret_1h"] > 0 for r in dir_rows])
        hit_laya = np.mean(np.array([r["answers"]["bullish"] > 0.5 for r in dir_rows]) == up)
        hit_fb = np.mean(np.array([r["finbert_polarity"] > 0 for r in dir_rows]) == up)
        lines.append(f"Direction hit rate (secondary, n={len(dir_rows)})  Laya {hit_laya:.3f}  FinBERT {hit_fb:.3f}")
    for h in _HORIZONS:
        sub = [r for r in rows if r.get(h) is not None]
        if len(sub) < 50:
            lines.append(f"Robustness {h}: fewer than 50 rows, skipped")
            continue
        mags = np.abs([r[h] for r in sub])
        yh = (mags > np.quantile(mags, 0.75)).astype(int)
        lines.append(
            f"Robustness {h} (sample 75th pct label, n={len(sub)})  Laya AUROC "
            f"{auroc(yh, [r['answers']['material'] for r in sub]):.3f}  FinBERT "
            f"{auroc(yh, [abs(r['finbert_polarity']) for r in sub]):.3f}"
        )
    result = verdict(n, ci, a_urg, latency_p50)
    lines.append(f"VERDICT: {result}")
    return "\n".join(lines), result


def main() -> None:
    from laya_shadow.models import ShadowInference, make_session_factory

    with make_session_factory()() as session:
        db_rows = (
            session.query(ShadowInference)
            .filter(
                ShadowInference.outcome_filled_at.is_not(None),
                ShadowInference.unfillable.is_(False),
                ShadowInference.material.is_not(None),
            )
            .all()
        )
        rows = [
            {
                "material": r.material, "answers": r.answers, "finbert_polarity": r.finbert_polarity or 0.0,
                "latency_ms": r.latency_ms, "ret_15m": r.ret_15m, "ret_1h": r.ret_1h,
                "ret_eod": r.ret_eod, "ret_1d": r.ret_1d,
            }
            for r in db_rows
        ]
    print(evaluate_rows(rows)[0])


if __name__ == "__main__":
    main()
