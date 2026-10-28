"""FinBERT baseline: all three class probabilities and a continuous polarity.

Polarity here is P(positive) - P(negative). The app's FinBertSentiment uses sign(label) * top score,
which is 0 for every neutral headline and makes a heavily tied baseline; this one does not.
"""
from typing import Any, Callable, Optional

MAX_INPUT_LEN = 512


def _default_pipeline_factory() -> Callable[..., list]:
    import torch
    from transformers import pipeline

    return pipeline("sentiment-analysis", model="ProsusAI/finbert", device=0 if torch.cuda.is_available() else -1)


class FinBertBaseline:
    def __init__(self, pipeline_factory: Optional[Callable[[], Any]] = None) -> None:
        self._factory = pipeline_factory or _default_pipeline_factory
        self._pipe = None

    def score(self, headline: str) -> dict:
        if self._pipe is None:
            self._pipe = self._factory()
        result = self._pipe([headline[:MAX_INPUT_LEN]], top_k=None)[0]
        probs = {d["label"]: float(d["score"]) for d in result}
        top = max(probs, key=probs.get)
        return {
            "label": top,
            "score": probs[top],
            "polarity": probs.get("positive", 0.0) - probs.get("negative", 0.0),
            "probs": probs,
        }
