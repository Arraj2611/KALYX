"""FinBERT baseline: same polarity convention as the app's FinBertSentiment."""
from typing import Any, Callable, Optional

_POLARITY = {"positive": 1, "negative": -1, "neutral": 0}
MAX_INPUT_LEN = 512


def _default_pipeline_factory() -> Callable[[list[str]], list[dict]]:
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
        result = self._pipe([headline[:MAX_INPUT_LEN]])[0]
        label, score = result["label"], float(result["score"])
        return {"label": label, "score": score, "polarity": _POLARITY.get(label, 0) * score}
