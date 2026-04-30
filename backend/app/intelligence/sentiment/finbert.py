"""FinBertSentiment — financial sentiment via ProsusAI/finbert (HuggingFace)."""
import logging

logger = logging.getLogger(__name__)


_POLARITY_MAP: dict[str, int] = {"positive": 1, "negative": -1, "neutral": 0}
_MAX_INPUT_LEN = 512


class FinBertSentiment:
    """Lazy-loading FinBERT classifier with polarity helpers."""

    def __init__(self, model_name: str = "ProsusAI/finbert"):
        self._model_name = model_name
        self._pipeline = None

    def _ensure_loaded(self) -> None:
        if self._pipeline is None:
            from transformers import pipeline
            logger.info(f"Loading FinBERT model: {self._model_name}")
            self._pipeline = pipeline("sentiment-analysis", model=self._model_name)

    def score(self, text: str) -> dict:
        """Classify a single text. Returns {label, score, polarity}."""
        self._ensure_loaded()
        truncated = text[:_MAX_INPUT_LEN]
        result = self._pipeline(truncated)[0]
        polarity = _POLARITY_MAP.get(result["label"], 0) * result["score"]
        return {
            "label": result["label"],
            "score": result["score"],
            "polarity": polarity,
        }

    def score_batch(self, texts: list[str]) -> list[dict]:
        """Batch classify multiple texts."""
        if not texts:
            return []
        self._ensure_loaded()
        truncated = [t[:_MAX_INPUT_LEN] for t in texts]
        results = self._pipeline(truncated)
        return [
            {
                "label": r["label"],
                "score": r["score"],
                "polarity": _POLARITY_MAP.get(r["label"], 0) * r["score"],
            }
            for r in results
        ]

    def aggregate_polarity(self, scores: list[dict]) -> float:
        """Mean polarity across a list of scored items."""
        if not scores:
            return 0.0
        return sum(s.get("polarity", 0) for s in scores) / len(scores)
