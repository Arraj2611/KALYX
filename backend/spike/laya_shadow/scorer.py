"""Laya typed-decision scorer for NIFTY headlines (English checkpoint)."""
import time
from typing import Any, Callable, Optional

MODEL_NAME = "convaiinnovations/laya"
MAX_INPUT_LEN = 512
_EVENT_TYPES = {
    "earnings": "quarterly results, guidance, profit or revenue",
    "macro_policy": "interest rates, inflation, budget, central bank",
    "regulatory": "regulator action, approval, penalty, court",
    "geopolitical": "war, sanctions, trade tensions",
    "corporate_action": "merger, dividend, buyback, stake sale, leadership change",
    "other_noise": "none of the above or generic commentary",
}
_URGENCY = ["old or routine", "minor", "important today", "breaking, act now"]


def build_questions(symbol: str) -> dict:
    return {
        "event_type": {
            "type": "choice",
            "instructions": f"What kind of event does `message` describe for {symbol}?",
            "criteria": dict(_EVENT_TYPES),
        },
        "material_to_symbol": {
            "type": "noul",
            "instructions": f"Is `message` likely to move the share price of {symbol}?",
        },
        "bullish_for_symbol": {
            "type": "noul",
            "instructions": f"Is `message` positive news for {symbol} shareholders?",
        },
        "urgency": {
            "type": "score",
            "instructions": "How time-sensitive is `message` for a trader?",
            "criteria": list(_URGENCY),
        },
    }


def _default_router_factory(device: Optional[str]) -> Callable[[], Any]:
    def factory():
        import torch
        from laya import Router

        return Router(device=device or ("cuda" if torch.cuda.is_available() else "cpu"))

    return factory


def _model_version() -> str:
    try:
        from laya import PINNED_REVISIONS

        return PINNED_REVISIONS.get(MODEL_NAME, "unknown")
    except ImportError:
        return "unknown"


class LayaScorer:
    """Lazy-loaded Laya wrapper. Exceptions from the model propagate; the poller handles them."""

    def __init__(self, router_factory: Optional[Callable[[], Any]] = None, device: Optional[str] = None) -> None:
        self._factory = router_factory or _default_router_factory(device)
        self._router = None

    def _ensure_loaded(self) -> None:
        if self._router is None:
            self._router = self._factory()

    def score(self, headline: str, symbol: str) -> dict:
        self._ensure_loaded()
        text = headline[:MAX_INPUT_LEN]
        start = time.perf_counter()
        result = self._router.predict({"message": text}, build_questions(symbol), model="english")
        latency_ms = (time.perf_counter() - start) * 1000
        a = result["answers"]
        return {
            "answers": {
                "event_type": dict(a["event_type"]["probabilities"]),
                "material": float(a["material_to_symbol"]["noul"]),
                "bullish": float(a["bullish_for_symbol"]["noul"]),
                "urgency": {str(k): float(v) for k, v in a["urgency"]["probabilities"].items()},
            },
            "latency_ms": latency_ms,
            "model_name": MODEL_NAME,
            "model_version": _model_version(),
        }
