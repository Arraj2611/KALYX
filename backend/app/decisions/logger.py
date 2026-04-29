"""DecisionLogger — writes every trading decision to PostgreSQL and per-account log files.

Usage
-----
    logger = DecisionLogger(db=session, log_base_dir="logs", alert_service=telegram)
    decision_id = await logger.log_decision(
        account_name="paper_test",
        symbol="NIFTY25JANFUT",
        signal="LONG",
        action=DecisionAction.EXECUTED,
        confidence=0.87,
        reasoning="RSI oversold + breakout confirmed",
        market_state={"rsi": 26},
    )
    # Later, after the position closes:
    await logger.fill_hindsight(decision_id, outcome_if_taken=200.0, outcome_actual=185.0)
"""

import dataclasses
import json
import logging
import os
from datetime import date, datetime, timezone
from typing import Any, Optional

from sqlalchemy.orm import Session

from app.decisions.models import DecisionAction, DecisionLog

logger = logging.getLogger(__name__)


class DecisionLogger:
    """Logs every trading decision to the database and per-account log files.

    Args:
        db: Active SQLAlchemy session.
        log_base_dir: Root directory for file-based logs (default: "logs").
        alert_service: Optional TelegramAlertService instance.  When supplied,
            FAILED and REJECTED decisions trigger a Telegram alert.
    """

    def __init__(
        self,
        db: Session,
        log_base_dir: str = "logs",
        alert_service=None,
    ) -> None:
        self._db = db
        self._log_base_dir = log_base_dir
        self._alert_service = alert_service

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def log_decision(
        self,
        account_name: str,
        symbol: str,
        signal: str,
        action: DecisionAction,
        confidence: float,
        reasoning: str,
        market_state: dict,
        strategy_id: Optional[int] = None,
        skip_reason: Optional[str] = None,
        trade_id: Optional[int] = None,
        context=None,
    ) -> int:
        """Persist a decision and write a JSON log line.

        Returns
        -------
        int
            The ``id`` of the newly created ``DecisionLog`` row.
        """
        entry = DecisionLog(
            account_name=account_name,
            symbol=symbol,
            signal=signal,
            strategy_id=strategy_id,
            confidence=confidence,
            market_state=market_state,
            action=action,
            reasoning=reasoning,
            skip_reason=skip_reason,
            trade_id=trade_id,
            trade_context=self._serialize_context(context),
        )

        self._db.add(entry)
        self._db.commit()
        self._db.refresh(entry)

        log_entry = {
            "id": entry.id,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "account_name": account_name,
            "symbol": symbol,
            "signal": signal,
            "action": str(action.value) if hasattr(action, "value") else str(action),
            "confidence": confidence,
            "reasoning": reasoning,
            "skip_reason": skip_reason,
            "strategy_id": strategy_id,
            "trade_id": trade_id,
        }
        self._write_log_file(account_name, log_entry)

        # Telegram alert for critical actions
        if self._alert_service and action in (
            DecisionAction.FAILED,
            DecisionAction.REJECTED,
        ):
            try:
                msg = f"{action.value.upper()}: {symbol} — {reasoning}"
                await self._alert_service.send_warning(account_name, msg)
            except Exception as exc:  # noqa: BLE001
                logger.warning("Failed to send Telegram alert: %s", exc)

        return entry.id

    async def fill_hindsight(
        self,
        decision_id: int,
        outcome_if_taken: float,
        outcome_actual: float,
    ) -> None:
        """Update a decision with post-session outcome data and compute correctness.

        Correctness rules
        -----------------
        - EXECUTED and ``outcome_actual > 0``  → was_correct = True
        - EXECUTED and ``outcome_actual <= 0`` → was_correct = False
        - Not EXECUTED and ``outcome_if_taken <= 0`` → was_correct = True
          (we were right to stay out)
        - Not EXECUTED and ``outcome_if_taken > 0``  → was_correct = False
          (missed a profitable trade)
        """
        entry: Optional[DecisionLog] = (
            self._db.query(DecisionLog)
            .filter(DecisionLog.id == decision_id)
            .first()
        )
        if entry is None:
            logger.warning("fill_hindsight: decision_id=%d not found", decision_id)
            return

        entry.outcome_if_taken = outcome_if_taken
        entry.outcome_actual = outcome_actual

        if entry.action == DecisionAction.EXECUTED:
            entry.was_correct = outcome_actual > 0
        else:
            # Skipped / blocked / rejected — correct if the trade would have lost
            entry.was_correct = outcome_if_taken <= 0

        self._db.commit()

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _write_log_file(self, account_name: str, entry: dict) -> None:
        """Append a JSON line to the per-account daily log file."""
        today = date.today().strftime("%Y-%m-%d")
        log_dir = os.path.join(self._log_base_dir, "accounts", account_name)
        os.makedirs(log_dir, exist_ok=True)
        log_path = os.path.join(log_dir, f"decisions-{today}.log")
        try:
            with open(log_path, "a", encoding="utf-8") as fh:
                fh.write(json.dumps(entry, default=str) + "\n")
        except OSError as exc:
            logger.error("Failed to write decision log file %s: %s", log_path, exc)

    def _serialize_context(self, context: Any) -> Optional[dict]:
        """Convert a TradeContext dataclass (or any object) to a JSON-safe dict.

        Handles datetime values by converting them to ISO-format strings.
        Returns ``None`` when ``context`` is ``None``.
        """
        if context is None:
            return None

        if dataclasses.is_dataclass(context) and not isinstance(context, type):
            raw = dataclasses.asdict(context)
        elif isinstance(context, dict):
            raw = context
        else:
            try:
                raw = vars(context)
            except TypeError:
                return {"_repr": repr(context)}

        # Recursively convert datetime objects
        return _sanitize_for_json(raw)


# ---------------------------------------------------------------------------
# Module-level helper
# ---------------------------------------------------------------------------


def _sanitize_for_json(obj: Any) -> Any:
    """Recursively convert datetime/date values to ISO strings."""
    if isinstance(obj, dict):
        return {k: _sanitize_for_json(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_sanitize_for_json(v) for v in obj]
    if isinstance(obj, (datetime, date)):
        return obj.isoformat()
    return obj
