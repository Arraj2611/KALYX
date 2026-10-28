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
    y_true, score_a, score_b, metric: Callable, n: int = 2000, seed: int = 0
) -> tuple[float, float, float]:
    """(mean, ci_low, ci_high) of metric(a) - metric(b) over paired resamples, 95% interval."""
    y, a, b = np.asarray(y_true), np.asarray(score_a), np.asarray(score_b)
    rng = np.random.default_rng(seed)
    diffs = []
    for _ in range(n):
        idx = rng.integers(0, len(y), len(y))
        d = metric(y[idx], a[idx]) - metric(y[idx], b[idx])
        if not np.isnan(d):
            diffs.append(d)
    if not diffs:
        return float("nan"), float("nan"), float("nan")
    return float(np.mean(diffs)), float(np.percentile(diffs, 2.5)), float(np.percentile(diffs, 97.5))


def verdict(n_labeled: int, auroc_diff_ci: tuple[float, float, float], urgency_auroc: float, latency_p50_ms: float) -> str:
    """insufficient_data | kill | inconclusive_finetune | adopt (rules: see the spike design doc)."""
    _, lo, hi = auroc_diff_ci
    if n_labeled < 500:
        return "insufficient_data"
    if latency_p50_ms > 100 or (hi < 0 and urgency_auroc <= 0.55):
        return "kill"
    if lo > 0:
        return "adopt"
    return "inconclusive_finetune"
