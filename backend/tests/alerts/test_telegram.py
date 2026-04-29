"""Tests for TelegramAlertService.

TDD: these tests are written before the implementation.
Mock _send_message to avoid real HTTP calls; verify message content and retry
behaviour only.
"""

import pytest
from unittest.mock import AsyncMock, patch, call

from app.alerts.telegram import TelegramAlertService


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def service():
    """Enabled TelegramAlertService with dummy credentials."""
    return TelegramAlertService(bot_token="test-token", chat_id="12345")


@pytest.fixture
def disabled_service():
    """Disabled TelegramAlertService — empty token."""
    return TelegramAlertService(bot_token="", chat_id="")


# ---------------------------------------------------------------------------
# Test 1: send_critical formats and sends the correct message
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_send_critical(service):
    """send_critical should include 🔴 CRITICAL prefix, account name, and message."""
    with patch.object(service, "_send_message", new_callable=AsyncMock) as mock_send:
        await service.send_critical("ZERODHA_1", "Margin call triggered")
        mock_send.assert_called_once()
        text = mock_send.call_args[0][0]
        assert "🔴" in text
        assert "CRITICAL" in text
        assert "ZERODHA_1" in text
        assert "Margin call triggered" in text


# ---------------------------------------------------------------------------
# Test 2: send_warning formats and sends the correct message
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_send_warning(service):
    """send_warning should include 🟡 WARNING prefix, account name, and message."""
    with patch.object(service, "_send_message", new_callable=AsyncMock) as mock_send:
        await service.send_warning("PAPER_1", "Drawdown approaching limit")
        mock_send.assert_called_once()
        text = mock_send.call_args[0][0]
        assert "🟡" in text
        assert "WARNING" in text
        assert "PAPER_1" in text
        assert "Drawdown approaching limit" in text


# ---------------------------------------------------------------------------
# Test 3: send_info formats and sends the correct message
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_send_info(service):
    """send_info should include 🟢 INFO prefix, account name, and message."""
    with patch.object(service, "_send_message", new_callable=AsyncMock) as mock_send:
        await service.send_info("IBKR_1", "Daily session started")
        mock_send.assert_called_once()
        text = mock_send.call_args[0][0]
        assert "🟢" in text
        assert "INFO" in text
        assert "IBKR_1" in text
        assert "Daily session started" in text


# ---------------------------------------------------------------------------
# Test 4: send_daily_summary uses 📈 for positive P&L and 📉 for negative
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_send_daily_summary_profit(service):
    """📈 emoji when total P&L is positive."""
    summary = {
        "total_pnl": 12500.0,
        "total_trades": 8,
        "winning_trades": 5,
        "losing_trades": 3,
    }
    with patch.object(service, "_send_message", new_callable=AsyncMock) as mock_send:
        await service.send_daily_summary(summary)
        mock_send.assert_called_once()
        text = mock_send.call_args[0][0]
        assert "📈" in text
        assert "12500" in text or "12,500" in text


@pytest.mark.asyncio
async def test_send_daily_summary_loss(service):
    """📉 emoji when total P&L is negative."""
    summary = {
        "total_pnl": -3200.0,
        "total_trades": 4,
        "winning_trades": 1,
        "losing_trades": 3,
    }
    with patch.object(service, "_send_message", new_callable=AsyncMock) as mock_send:
        await service.send_daily_summary(summary)
        mock_send.assert_called_once()
        text = mock_send.call_args[0][0]
        assert "📉" in text


# ---------------------------------------------------------------------------
# Test 5: disabled mode — all sends are no-ops (no HTTP calls at all)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_disabled_mode_no_send(disabled_service):
    """When token is empty, _send_message must never be called."""
    with patch.object(disabled_service, "_send_message", new_callable=AsyncMock) as mock_send:
        await disabled_service.send_critical("ACC", "msg")
        await disabled_service.send_warning("ACC", "msg")
        await disabled_service.send_info("ACC", "msg")
        await disabled_service.send_daily_summary({"total_pnl": 0.0, "total_trades": 0})
        mock_send.assert_not_called()


# ---------------------------------------------------------------------------
# Test 6: retry — fails twice, succeeds on third call; total 3 invocations
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_retry_succeeds_on_third_attempt(service):
    """_send_with_retry should retry on failure; succeed on 3rd call."""
    call_count = 0

    async def flaky_send(text):
        nonlocal call_count
        call_count += 1
        if call_count < 3:
            raise RuntimeError("Telegram API error")

    with patch.object(service, "_send_message", side_effect=flaky_send):
        # Patch asyncio.sleep to avoid real delays in tests
        with patch("app.alerts.telegram.asyncio.sleep", new_callable=AsyncMock):
            await service._send_with_retry("test message", max_retries=3)

    assert call_count == 3
