import pytest

from laya_shadow.baseline import FinBertBaseline
from laya_shadow.scorer import BODY_MAX_CHARS, BODY_MAX_TOKENS, LayaScorer

LAYA_RESULT = {
    "model": "english",
    "usage": {"state_tokens": 1000, "state_tokens_dropped": 40},
    "answers": {
        "event_type": {
            "type": "choice",
            "choice": "earnings",
            "probabilities": {"earnings": 0.9, "macro_policy": 0.02, "regulatory": 0.02,
                              "geopolitical": 0.02, "corporate_action": 0.02, "other_noise": 0.02},
        },
        "material_to_symbol": {"type": "noul", "noul": 0.7},
        "bullish_for_symbol": {"type": "noul", "noul": 0.2},
        "urgency": {"type": "score", "score": 2.0,
                    "probabilities": {"0": 0.1, "1": 0.2, "2": 0.5, "3": 0.2}},
    },
}


class FakeRouter:
    def __init__(self, error=None):
        self.calls = []
        self.error = error

    def predict(self, state, questions, model=None, **kw):
        self.calls.append((state, questions, model))
        self.kwargs = kw
        if self.error:
            raise self.error
        return LAYA_RESULT


def test_maps_laya_answers_to_normalized_shape():
    scorer = LayaScorer(router_factory=lambda: FakeRouter())
    out = scorer.score("Reliance profit beats estimates", "RELIANCE")
    assert out["answers"]["event_type"]["earnings"] == 0.9
    assert out["answers"]["material"] == 0.7
    assert out["answers"]["bullish"] == 0.2
    assert out["answers"]["urgency"] == {"0": 0.1, "1": 0.2, "2": 0.5, "3": 0.2}
    assert out["model_name"] == "convaiinnovations/laya"
    assert out["model_version"]


def test_latency_ms_measured_and_positive():
    scorer = LayaScorer(router_factory=lambda: FakeRouter())
    assert scorer.score("headline", "TCS")["latency_ms"] > 0


def test_lazy_load_only_on_first_score():
    built = []

    def factory():
        built.append(1)
        return FakeRouter()

    scorer = LayaScorer(router_factory=factory)
    assert built == []
    scorer.score("a", "TCS")
    scorer.score("b", "TCS")
    assert built == [1]


def test_long_headline_truncated_to_512_chars():
    router = FakeRouter()
    scorer = LayaScorer(router_factory=lambda: router)
    scorer.score("x" * 2000, "TCS")
    state, questions, model = router.calls[0]
    assert len(state["message"]) == 512
    assert model == "english"
    assert "TCS" in questions["material_to_symbol"]["instructions"]


def test_router_exception_propagates():
    scorer = LayaScorer(router_factory=lambda: FakeRouter(error=RuntimeError("cuda oom")))
    with pytest.raises(RuntimeError):
        scorer.score("headline", "TCS")


def test_baseline_stores_all_probabilities_and_continuous_polarity():
    probs = [{"label": "positive", "score": 0.7}, {"label": "neutral", "score": 0.2}, {"label": "negative", "score": 0.1}]
    baseline = FinBertBaseline(pipeline_factory=lambda: (lambda texts, top_k=None: [probs]))
    out = baseline.score("some headline")
    assert out["label"] == "positive" and out["score"] == 0.7
    assert out["probs"] == {"positive": 0.7, "neutral": 0.2, "negative": 0.1}
    assert out["polarity"] == pytest.approx(0.6)


def test_score_body_reads_a_wide_window_not_the_default():
    router = FakeRouter()
    scorer = LayaScorer(router_factory=lambda: router)
    out = scorer.score_body("full article text", "TCS")
    assert router.kwargs["max_len"] == BODY_MAX_TOKENS
    assert out["answers"]["material"] == 0.7 and out["latency_ms"] > 0
    assert out["tokens_read"] == 960 and out["tokens_dropped"] == 40


def test_score_body_passes_long_text_past_the_headline_cut():
    router = FakeRouter()
    LayaScorer(router_factory=lambda: router).score_body("x" * 2000, "TCS")
    assert len(router.calls[0][0]["message"]) == 2000


def test_score_body_caps_huge_documents():
    router = FakeRouter()
    LayaScorer(router_factory=lambda: router).score_body("x" * (BODY_MAX_CHARS + 500), "TCS")
    assert len(router.calls[0][0]["message"]) == BODY_MAX_CHARS
