"""Tests for AgentStreamPublisher and AgentStreamSubscriber — Redis Streams pub/sub."""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.agents.streams import AgentStreamPublisher, AgentStreamSubscriber


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def mock_redis():
    r = MagicMock()
    r.xadd = AsyncMock(return_value="1234567890-0")
    r.xread = AsyncMock(return_value=[])
    return r


@pytest.fixture
def publisher(mock_redis):
    return AgentStreamPublisher(redis_client=mock_redis)


# ---------------------------------------------------------------------------
# Publisher tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_publish_signal(publisher, mock_redis):
    """publish_signal() calls xadd with stream_name=='stream:signals:<account>'."""
    await publisher.publish_signal("paper_test", {"signal": "BUY"})

    mock_redis.xadd.assert_called_once()
    call_args = mock_redis.xadd.call_args
    assert call_args[0][0] == "stream:signals:paper_test"


@pytest.mark.asyncio
async def test_publish_decision(publisher, mock_redis):
    """publish_decision() calls xadd with stream_name=='stream:decisions:<account>'."""
    await publisher.publish_decision("paper_test", {"decision": "EXECUTE"})

    mock_redis.xadd.assert_called_once()
    call_args = mock_redis.xadd.call_args
    assert call_args[0][0] == "stream:decisions:paper_test"


@pytest.mark.asyncio
async def test_publish_alert(publisher, mock_redis):
    """publish_alert() calls xadd with stream_name=='stream:alerts:<account>'."""
    await publisher.publish_alert("paper_test", {"alert": "RISK_LIMIT"})

    mock_redis.xadd.assert_called_once()
    call_args = mock_redis.xadd.call_args
    assert call_args[0][0] == "stream:alerts:paper_test"


@pytest.mark.asyncio
async def test_publish_serializes_data(publisher, mock_redis):
    """publish_signal() JSON-serializes nested dict under 'data' key in xadd payload."""
    nested = {"signal": "BUY", "meta": {"confidence": 0.9, "symbol": "NIFTY"}}
    await publisher.publish_signal("paper_test", nested)

    mock_redis.xadd.assert_called_once()
    call_args = mock_redis.xadd.call_args
    payload = call_args[0][1]  # second positional arg is the fields dict
    assert "data" in payload
    parsed = json.loads(payload["data"])
    assert parsed == nested


# ---------------------------------------------------------------------------
# Subscriber tests
# ---------------------------------------------------------------------------


def test_subscriber_creation():
    """AgentStreamSubscriber can be created without error."""
    subscriber = AgentStreamSubscriber(redis_client=MagicMock())
    assert subscriber is not None
