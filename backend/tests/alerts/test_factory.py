from types import SimpleNamespace

from app.alerts.factory import build_alert_service
from app.alerts.telegram import TelegramAlertService


def test_returns_none_without_a_token():
    assert build_alert_service(SimpleNamespace(TELEGRAM_BOT_TOKEN=None, TELEGRAM_CHAT_ID="1")) is None


def test_returns_none_without_a_chat_id():
    assert build_alert_service(SimpleNamespace(TELEGRAM_BOT_TOKEN="abc", TELEGRAM_CHAT_ID=None)) is None


def test_empty_strings_count_as_unset():
    assert build_alert_service(SimpleNamespace(TELEGRAM_BOT_TOKEN="", TELEGRAM_CHAT_ID="")) is None


def test_returns_the_service_when_both_are_set():
    service = build_alert_service(SimpleNamespace(TELEGRAM_BOT_TOKEN="abc", TELEGRAM_CHAT_ID="42"))
    assert isinstance(service, TelegramAlertService)
