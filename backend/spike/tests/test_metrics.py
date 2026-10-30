import numpy as np
import pytest

from laya_shadow.evaluate import evaluate_rows
from laya_shadow.metrics import auroc, brier, ece, paired_bootstrap_diff, verdict


def test_auroc_perfect_random_inverse():
    y = [0, 0, 1, 1]
    assert auroc(y, [0.1, 0.2, 0.8, 0.9]) == 1.0
    assert auroc(y, [0.9, 0.8, 0.2, 0.1]) == 0.0
    assert auroc([0, 1, 0, 1], [0.5, 0.5, 0.5, 0.5]) == 0.5


def test_auroc_ties_averaged():
    # positives {0.5, 0.9}, negatives {0.5, 0.1}: pairs 0.5>0.5 tie(0.5), 0.5>0.1, 0.9>0.5, 0.9>0.1
    assert auroc([1, 1, 0, 0], [0.5, 0.9, 0.5, 0.1]) == pytest.approx(0.875)


def test_brier_known_value():
    assert brier([1, 0], [0.8, 0.3]) == pytest.approx((0.04 + 0.09) / 2)


def test_ece_perfectly_calibrated_is_zero():
    y = [1] * 5 + [0] * 5
    assert ece(y, [0.5] * 10) == pytest.approx(0.0)
    assert ece([1, 1, 1, 1], [0.0] * 4) == pytest.approx(1.0)


def test_bootstrap_ci_contains_zero_for_identical_scores():
    rng = np.random.default_rng(1)
    y = rng.integers(0, 2, 200)
    s = rng.random(200)
    mean, lo, hi = paired_bootstrap_diff(y, s, s, auroc, n=300)
    assert mean == 0.0 and lo <= 0.0 <= hi


def test_bootstrap_deterministic_with_seed():
    rng = np.random.default_rng(2)
    y = rng.integers(0, 2, 100)
    a, b = rng.random(100), rng.random(100)
    assert paired_bootstrap_diff(y, a, b, auroc, n=200, seed=7) == paired_bootstrap_diff(y, a, b, auroc, n=200, seed=7)


def test_verdict_insufficient_data():
    assert verdict(100, 80, (0.05, 0.02, 0.08), True, 40.0) == "insufficient_data"


def test_verdict_insufficient_when_few_independent_clusters():
    assert verdict(900, 40, (0.05, 0.02, 0.08), True, 40.0) == "insufficient_data"


def test_verdict_kill_on_latency():
    assert verdict(600, 300, (0.05, 0.02, 0.08), True, 120.0) == "kill"


def test_verdict_kill_when_clearly_worse_and_no_promise():
    assert verdict(600, 300, (-0.05, -0.08, -0.02), False, 40.0) == "kill"


def test_verdict_not_kill_when_worse_but_promising():
    assert verdict(600, 300, (-0.05, -0.08, -0.02), True, 40.0) == "inconclusive_finetune"


def test_verdict_adopt_when_ci_above_zero():
    assert verdict(600, 300, (0.05, 0.02, 0.08), False, 40.0) == "adopt"


def test_verdict_inconclusive_when_ci_straddles_zero():
    assert verdict(600, 300, (0.01, -0.02, 0.04), False, 40.0) == "inconclusive_finetune"


def test_cluster_bootstrap_ci_wider_than_row_bootstrap_when_labels_cluster():
    rng = np.random.default_rng(5)
    n_clusters, per = 60, 10
    y_c = rng.integers(0, 2, n_clusters)
    a_c = y_c + rng.normal(0, 1.0, n_clusters)
    b_c = rng.normal(0, 1.0, n_clusters)
    y, a, b = (np.repeat(v, per) for v in (y_c, a_c, b_c))
    clusters = np.repeat(np.arange(n_clusters), per)
    _, lo_r, hi_r = paired_bootstrap_diff(y, a, b, auroc, n=400, seed=1)
    _, lo_c, hi_c = paired_bootstrap_diff(y, a, b, auroc, n=400, seed=1, clusters=clusters)
    assert (hi_c - lo_c) > 1.5 * (hi_r - lo_r)


def test_evaluate_rows_produces_report_and_verdict():
    rng = np.random.default_rng(3)
    rows = []
    for i in range(600):
        material = bool(rng.random() < 0.25)
        rows.append({
            "material": material, "cluster": f"S|{i // 4}", "off_hours": bool(i % 3 == 0),
            "finbert_probs": {"positive": 0.3, "neutral": 0.4, "negative": 0.3},
            "answers": {"material": float(rng.random()), "bullish": float(rng.random()), "event_type": {"other_noise": float(rng.random())},
                        "urgency": {"0": 0.25, "1": 0.25, "2": 0.25, "3": 0.25}},
            "finbert_polarity": float(rng.normal()),
            "latency_ms": 50.0,
            "ret_15m": float(rng.normal(0, .002)), "ret_1h": float(rng.normal(0, .003)),
            "ret_eod": float(rng.normal(0, .005)), "ret_1d": float(rng.normal(0, .01)),
        })
    text, result = evaluate_rows(rows)
    assert result in {"insufficient_data", "kill", "inconclusive_finetune", "adopt"}
    assert "AUROC" in text and result in text
    assert "off-hours" in text and "clusters" in text


def _rows(n, with_body):
    rng = np.random.default_rng(4)
    rows = []
    for i in range(n):
        material = bool(i % 4 == 0)
        row = {
            "material": material, "cluster": f"S|{i}", "off_hours": False, "latency_ms": 50.0,
            "finbert_polarity": float(rng.normal()), "finbert_probs": None, "ret_1h": 0.01,
            "ret_15m": None, "ret_eod": None, "ret_1d": None,
            "answers": {"material": float(rng.random()), "bullish": 0.5, "event_type": {"other_noise": 0.5},
                        "urgency": {"0": 1.0}},
        }
        if with_body:
            row["body_answers"] = {"material": 0.9 if material else 0.1}
        rows.append(row)
    return rows


def test_report_shows_what_reading_the_full_text_adds():
    text, _ = evaluate_rows(_rows(200, with_body=True))
    line = next(line for line in text.splitlines() if line.startswith("Reading gain"))
    assert "n=200" in line and "full text AUROC 1.000" in line


def test_report_skips_reading_gain_when_too_few_bodies():
    text, _ = evaluate_rows(_rows(200, with_body=False))
    assert "Reading gain: fewer than 50 rows" in text
