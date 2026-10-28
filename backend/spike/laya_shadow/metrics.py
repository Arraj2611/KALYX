"""Metrics and the spike verdict (numpy/pandas only)."""
from typing import Callable, Sequence

import numpy as np
import pandas as pd


def auroc(y_true: Sequence[int], y_score: Sequence[float]) -> float:
    """Rank-based AUROC with tied scores averaged. NaN if only one class is present."""
    y = np.asarray(y_true, dtype=int)
    s = pd.Series(np.asarray(y_score, dtype=float))
    n_pos, n_neg = int(y.sum()), int(len(y) - y.sum())
    if n_pos == 0 or n_neg == 0:
        return float("nan")
    ranks = s.rank(method="average").to_numpy()
    return float((ranks[y == 1].sum() - n_pos * (n_pos + 1) / 2) / (n_pos * n_neg))


def brier(y_true: Sequence[int], p: Sequence[float]) -> float:
    return float(np.mean((np.asarray(p, dtype=float) - np.asarray(y_true, dtype=float)) ** 2))


def ece(y_true: Sequence[int], p: Sequence[float], bins: int = 10) -> float:
    """Expected calibration error with equal-width bins."""
    y, p = np.asarray(y_true, dtype=float), np.asarray(p, dtype=float)
    idx = np.minimum((p * bins).astype(int), bins - 1)
    total = 0.0
    for b in range(bins):
        mask = idx == b
        if mask.any():
            total += mask.mean() * abs(p[mask].mean() - y[mask].mean())
    return float(total)


def paired_bootstrap_diff(
    y_true, score_a, score_b, metric: Callable, n: int = 2000, seed: int = 0, clusters=None
) -> tuple[float, float, float]:
    """(mean, ci_low, ci_high) of metric(a) - metric(b) over paired resamples, 95% interval.

    With ``clusters`` (one id per row) whole clusters are resampled: rows that share an outcome
    (same symbol, same aligned t0) are not independent, and row-level resampling understates the CI.
    """
    y, a, b = np.asarray(y_true), np.asarray(score_a), np.asarray(score_b)
    rng = np.random.default_rng(seed)
    groups = None
    if clusters is not None:
        by_cluster: dict = {}
        for i, c in enumerate(clusters):
            by_cluster.setdefault(c, []).append(i)
        groups = [np.array(v) for v in by_cluster.values()]
    diffs = []
    for _ in range(n):
        if groups is None:
            idx = rng.integers(0, len(y), len(y))
        else:
            idx = np.concatenate([groups[g] for g in rng.integers(0, len(groups), len(groups))])
        d = metric(y[idx], a[idx]) - metric(y[idx], b[idx])
        if not np.isnan(d):
            diffs.append(d)
    if not diffs:
        return float("nan"), float("nan"), float("nan")
    return float(np.mean(diffs)), float(np.percentile(diffs, 2.5)), float(np.percentile(diffs, 97.5))


MIN_LABELED = 500
MIN_CLUSTERS = 150


def verdict(
    n_labeled: int, n_clusters: int, auroc_diff_ci: tuple[float, float, float], has_promise: bool, latency_p50_ms: float
) -> str:
    """insufficient_data | kill | inconclusive_finetune | adopt (rules: see the spike design doc).

    ``has_promise``: the lower CI bound of urgency or event_type AUROC against materiality is above 0.5.
    """
    _, lo, hi = auroc_diff_ci
    if n_labeled < MIN_LABELED or n_clusters < MIN_CLUSTERS:
        return "insufficient_data"
    if latency_p50_ms > 100 or (hi < 0 and not has_promise):
        return "kill"
    if lo > 0:
        return "adopt"
    return "inconclusive_finetune"
