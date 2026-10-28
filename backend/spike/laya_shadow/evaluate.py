"""One-page evaluation report: does Laya predict materiality better than a FinBERT baseline?

Rows that share a symbol and an aligned t0 share one outcome, so confidence intervals resample whole
clusters and the sample-size gate also counts clusters. In-session and off-hours headlines are reported
separately (off-hours headlines are labeled from the volatile opening hour and miss the overnight gap).

Run:  python -m laya_shadow.evaluate
"""
import numpy as np

from laya_shadow.metrics import auroc, brier, ece, paired_bootstrap_diff, verdict

_HORIZONS = ("ret_15m", "ret_eod", "ret_1d")


def _urgency_expected(urgency: dict) -> float:
    return sum(int(k) * float(v) for k, v in urgency.items())


def _above_chance(y, score, clusters) -> tuple[float, float]:
    """(AUROC, lower 95% bound of AUROC - 0.5)."""
    _, lo, _ = paired_bootstrap_diff(y, score, np.zeros(len(score)), auroc, n=1000, clusters=clusters)
    return auroc(y, score), lo


def _baselines(rows: list[dict]) -> dict[str, np.ndarray]:
    out = {"|polarity|": np.array([abs(r["finbert_polarity"]) for r in rows])}
    if all(r.get("finbert_probs") for r in rows):
        out["1-P(neutral)"] = np.array([1.0 - r["finbert_probs"].get("neutral", 0.0) for r in rows])
    return out


def evaluate_rows(rows: list[dict]) -> tuple[str, str]:
    """rows: dicts with material, cluster, off_hours, answers, finbert_polarity (+ finbert_probs), latency_ms, ret_*."""
    n = len(rows)
    y = np.array([int(r["material"]) for r in rows])
    n_clusters = len({r.get("cluster", i) for i, r in enumerate(rows)})
    lines = [f"Labeled headlines: {n}   independent clusters: {n_clusters}   material rate: {y.mean():.3f}" if n else "Labeled headlines: 0"]
    if n == 0 or len(set(y)) < 2:
        lines += ["Only one class present: no AUROC possible.", "VERDICT: insufficient_data"]
        return "\n".join(lines), "insufficient_data"

    clusters = [r.get("cluster", i) for i, r in enumerate(rows)]
    laya = np.array([r["answers"]["material"] for r in rows])
    baselines = _baselines(rows)
    base_name = max(baselines, key=lambda k: auroc(y, baselines[k]))  # strongest baseline: the conservative one
    base = baselines[base_name]
    ci = paired_bootstrap_diff(y, laya, base, auroc, clusters=clusters)
    full_diff = auroc(y, laya) - auroc(y, base)
    urgency = np.array([_urgency_expected(r["answers"]["urgency"]) for r in rows])
    event = np.array([1.0 - r["answers"]["event_type"].get("other_noise", 0.0) for r in rows])
    a_urg, urg_lo = _above_chance(y, urgency, clusters)
    a_evt, evt_lo = _above_chance(y, event, clusters)
    has_promise = (urg_lo > 0) or (evt_lo > 0)
    latency_p50 = float(np.median([r["latency_ms"] for r in rows]))

    lines += [
        "Baselines tried: " + ", ".join(f"{k} AUROC {auroc(y, v):.3f}" for k, v in baselines.items()) + f"  -> using {base_name}",
        f"Materiality AUROC  Laya {auroc(y, laya):.3f}  baseline {auroc(y, base):.3f}",
        f"AUROC diff (Laya - baseline) {full_diff:+.3f}  95% cluster-bootstrap CI [{ci[1]:+.3f}, {ci[2]:+.3f}]",
        f"Laya material Brier {brier(y, laya):.3f}  ECE {ece(y, laya):.3f}",
        f"Promise checks vs materiality: urgency AUROC {a_urg:.3f} (CI lower bound over chance {urg_lo:+.3f}); "
        f"event_type 1-P(other_noise) AUROC {a_evt:.3f} (lower bound {evt_lo:+.3f})",
        f"Laya latency p50 {latency_p50:.1f} ms (median, robust to the cold first call)",
    ]
    for label, flag in (("in-session", False), ("off-hours", True)):
        idx = [i for i, r in enumerate(rows) if bool(r.get("off_hours")) is flag]
        ys = y[idx]
        if len(idx) < 50 or len(set(ys)) < 2:
            lines.append(f"{label}: fewer than 50 rows or one class, skipped (n={len(idx)})")
            continue
        lines.append(f"{label} (n={len(idx)}, material rate {ys.mean():.3f}): Laya AUROC {auroc(ys, laya[idx]):.3f}  baseline {auroc(ys, base[idx]):.3f}")

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
            f"{auroc(yh, [r['answers']['material'] for r in sub]):.3f}  FinBERT |polarity| "
            f"{auroc(yh, [abs(r['finbert_polarity']) for r in sub]):.3f}"
        )
    result = verdict(n, n_clusters, ci, has_promise, latency_p50)
    lines.append(f"VERDICT: {result}")
    return "\n".join(lines), result


def main() -> None:
    from laya_shadow.fill import _as_utc
    from laya_shadow.models import ShadowInference, make_session_factory
    from laya_shadow.outcomes import align_t0

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
                "finbert_probs": r.finbert_probs, "off_hours": bool(r.off_hours),
                "cluster": f"{r.symbol}|{align_t0(_as_utc(r.published_at)).isoformat()}",
                "latency_ms": r.latency_ms, "ret_15m": r.ret_15m, "ret_1h": r.ret_1h,
                "ret_eod": r.ret_eod, "ret_1d": r.ret_1d,
            }
            for r in db_rows
        ]
    print(evaluate_rows(rows)[0])


if __name__ == "__main__":
    main()
