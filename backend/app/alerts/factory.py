"""Build the alert service from settings."""

from typing import Any, Optional

from app.alerts.telegram import TelegramAlertService


def build_alert_service(settings: Any) -> Optional[TelegramAlertService]:
    """A Telegram service when both the bot token and the chat id are set, otherwise None.

    None means alerts only reach the log, which nobody reads at 3 a.m.; main.py logs that fact at startup.
    """
    token = getattr(settings, "TELEGRAM_BOT_TOKEN", None)
    chat_id = getattr(settings, "TELEGRAM_CHAT_ID", None)
    if not token or not chat_id:
        return None
    return TelegramAlertService(token, chat_id)
