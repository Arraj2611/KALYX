"""Tests for FinBertSentiment classifier wrapper."""
import pytest
from unittest.mock import MagicMock


def test_finbert_creation():
    from app.intelligence.sentiment.finbert import FinBertSentiment

    fb = FinBertSentiment()
    assert fb is not None


def test_finbert_lazy_load():
    from app.intelligence.sentiment.finbert import FinBertSentiment

    fb = FinBertSentiment()
    assert fb._pipeline is None


def test_finbert_score_positive():
    from app.intelligence.sentiment.finbert import FinBertSentiment

    fb = FinBertSentiment()
    fb._pipeline = MagicMock(return_value=[{"label": "positive", "score": 0.85}])

    result = fb.score("Stock surges on great earnings")
    assert result["label"] == "positive"
    assert result["score"] == 0.85
    assert result["polarity"] == pytest.approx(0.85)


def test_finbert_score_negative():
    from app.intelligence.sentiment.finbert import FinBertSentiment

    fb = FinBertSentiment()
    fb._pipeline = MagicMock(return_value=[{"label": "negative", "score": 0.92}])

    result = fb.score("Company files for bankruptcy")
    assert result["label"] == "negative"
    assert result["polarity"] == pytest.approx(-0.92)


def test_finbert_score_neutral():
    from app.intelligence.sentiment.finbert import FinBertSentiment

    fb = FinBertSentiment()
    fb._pipeline = MagicMock(return_value=[{"label": "neutral", "score": 0.7}])

    result = fb.score("Quarterly report released")
    assert result["label"] == "neutral"
    assert result["polarity"] == 0.0


def test_finbert_score_truncates_long_text():
    from app.intelligence.sentiment.finbert import FinBertSentiment

    fb = FinBertSentiment()
    long_text = "x" * 10000
    captured = {}

    def fake_pipeline(text):
        captured["len"] = len(text)
        return [{"label": "neutral", "score": 0.5}]

    fb._pipeline = fake_pipeline
    fb.score(long_text)
    assert captured["len"] <= 512


def test_finbert_score_batch():
    from app.intelligence.sentiment.finbert import FinBertSentiment

    fb = FinBertSentiment()
    fb._pipeline = MagicMock(return_value=[
        {"label": "positive", "score": 0.8},
        {"label": "negative", "score": 0.7},
        {"label": "neutral", "score": 0.6},
    ])

    results = fb.score_batch(["bull text", "bear text", "neutral text"])
    assert len(results) == 3
    assert results[0]["polarity"] == pytest.approx(0.8)
    assert results[1]["polarity"] == pytest.approx(-0.7)
    assert results[2]["polarity"] == 0.0


def test_finbert_aggregate_polarity_empty():
    from app.intelligence.sentiment.finbert import FinBertSentiment

    fb = FinBertSentiment()
    assert fb.aggregate_polarity([]) == 0.0


def test_finbert_aggregate_polarity_average():
    from app.intelligence.sentiment.finbert import FinBertSentiment

    fb = FinBertSentiment()
    scores = [
        {"polarity": 0.8},
        {"polarity": -0.4},
        {"polarity": 0.0},
    ]
    avg = fb.aggregate_polarity(scores)
    assert avg == pytest.approx((0.8 - 0.4 + 0.0) / 3)


def test_finbert_unknown_label_polarity_zero():
    from app.intelligence.sentiment.finbert import FinBertSentiment

    fb = FinBertSentiment()
    fb._pipeline = MagicMock(return_value=[{"label": "weird_label", "score": 0.5}])

    result = fb.score("text")
    assert result["polarity"] == 0.0
