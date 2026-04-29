"""Telegram alerting service for KALYX trading system.

Sends critical/warning/info trade alerts and daily summaries via the
Telegram Bot API. Gracefully disables itself when no token is configured.
"""

import asyncio
import logging
from datetime import datetime, timezone
from typing import Any

import httpx

logger = logging.getLogger(__name__)


class TelegramAlertService:
    """Send structured trade alerts to a Telegram chat.

    Args:
        bot_token: Telegram bot token from BotFather.
        chat_id: Target chat or channel ID.

    If either ``bot_token`` or ``chat_id`` is empty the service is disabled
    and all send methods become no-ops — no exceptions are raised.
    """

    _TELEGRAM_API = "https://api.telegram.org/bot{token}/sendMessage"

    def __init__(self, bot_token: str, chat_id: str) -> None:
        self._bot_token = bot_token
        self._chat_id = chat_id
        self._enabled = bool(bot_token and chat_id)
        if not self._enabled:
            logger.info("TelegramAlertService disabled — no token/chat_id configured.")

    # ------------------------------------------------------------------
    # Internal HTTP
    # ------------------------------------------------------------------

    async def _send_message(self, text: str) -> None:
        """POST ``text`` to the Telegram Bot API (single attempt).

        Raises:
            httpx.HTTPError: on any network or API-level failure.
        """
        url = self._TELEGRAM_API.format(token=self._bot_token)
        payload = {
            "chat_id": self._chat_id,
            "text": text,
            "parse_mode": "HTML",
        }
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.post(url, json=payload)
            response.raise_for_status()

    async def _send_with_retry(self, text: str, max_retries: int = 3) -> None:
        """Send ``text`` with exponential backoff on failure.

        Retry schedule: attempt 1 immediately, then sleep 2s, then sleep 4s.
        Raises the last exception if all retries are exhausted.

        Args:
            text: Message text to send.
            max_retries: Maximum total attempts (default 3).
        """
        last_exc: Exception | None = None
        for attempt in range(max_retries):
            if attempt > 0:
                delay = 2 ** attempt  # 2, 4, 8, …
                await asyncio.sleep(delay)
            try:
                await self._send_message(text)
                return
            except Exception as exc:  # noqa: BLE001
                last_exc = exc
                logger.warning(
                    "Telegram send failed (attempt %d/%d): %s",
                    attempt + 1,
                    max_retries,
                    exc,
                )
        logger.error("Telegram send failed after %d attempts.", max_retries)
        if last_exc is not None:
            raise last_exc

    # ------------------------------------------------------------------
    # Public alert methods
    # ------------------------------------------------------------------

    def _timestamp(self) -> str:
        return datetime.now(tz=timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")

    async def send_critical(self, account_name: str, msg: str) -> None:
        """Send a 🔴 CRITICAL alert.

        Args:
            account_name: The trading account identifier.
            msg: Alert body text.
        """
        if not self._enabled:
            return
        text = (
            f"🔴 CRITICAL [{account_name}] {self._timestamp()}\n"
            f"{msg}"
        )
        await _send_with_retry_or_log(self, text)

    async def send_warning(self, account_name: str, msg: str) -> None:
        """Send a 🟡 WARNING alert.

        Args:
            account_name: The trading account identifier.
            msg: Alert body text.
        """
        if not self._enabled:
            return
        text = (
            f"🟡 WARNING [{account_name}] {self._timestamp()}\n"
            f"{msg}"
        )
        await _send_with_retry_or_log(self, text)

    async def send_info(self, account_name: str, msg: str) -> None:
        """Send a 🟢 INFO alert.

        Args:
            account_name: The trading account identifier.
            msg: Alert body text.
        """
        if not self._enabled:
            return
        text = (
            f"🟢 INFO [{account_name}] {self._timestamp()}\n"
            f"{msg}"
        )
        await _send_with_retry_or_log(self, text)

    async def send_daily_summary(self, summary_dict: dict[str, Any]) -> None:
        """Send a daily P&L summary.

        Selects 📈 for positive (or zero) P&L and 📉 for negative.

        Args:
            summary_dict: Must contain ``total_pnl`` (float) and
                ``total_trades`` (int). May also contain
                ``winning_trades`` and ``losing_trades``.
        """
        if not self._enabled:
            return

        total_pnl: float = float(summary_dict.get("total_pnl", 0.0))
        total_trades: int = int(summary_dict.get("total_trades", 0))
        winning: int = int(summary_dict.get("winning_trades", 0))
        losing: int = int(summary_dict.get("losing_trades", 0))

        emoji = "📈" if total_pnl >= 0 else "📉"
        pnl_sign = "+" if total_pnl >= 0 else ""

        lines = [
            f"{emoji} Daily Summary — {self._timestamp()}",
            f"P&L: {pnl_sign}{total_pnl:,.2f}",
            f"Trades: {total_trades} (W: {winning} / L: {losing})",
        ]
        text = "\n".join(lines)
        await _send_with_retry_or_log(self, text)


# ---------------------------------------------------------------------------
# Module-level helper (keeps public methods clean)
# ---------------------------------------------------------------------------


async def _send_with_retry_or_log(service: TelegramAlertService, text: str) -> None:
    """Attempt to send; swallow exceptions so alerts never crash the caller."""
    try:
        await service._send_with_retry(text)
    except Exception as exc:  # noqa: BLE001
        logger.error("TelegramAlertService: failed to deliver message: %s", exc)
