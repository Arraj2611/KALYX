"""
Redis Streams pub/sub infrastructure for cross-agent and cross-pod communication.

AgentStreamPublisher  — publish signals, decisions, and alerts per account.
AgentStreamSubscriber — register callbacks and poll streams for new messages.

Stream naming convention:
  stream:signals:<account_name>
  stream:decisions:<account_name>
  stream:alerts:<account_name>

The SP5 Orchestrator will use AgentStreamSubscriber to coordinate agents
across pods without direct in-process coupling.
"""

from __future__ import annotations

import json
import logging
from typing import Callable

logger = logging.getLogger(__name__)


class AgentStreamPublisher:
    """Publish agent events to Redis Streams.

    Each publish method targets a dedicated stream per account so consumers
    can subscribe only to the channels they care about.
    """

    def __init__(self, redis_client) -> None:
        self._redis = redis_client

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def publish_signal(self, account_name: str, signal_data: dict) -> str:
        """Publish a trading signal to the signals stream for this account."""
        return await self._publish(f"stream:signals:{account_name}", signal_data)

    async def publish_decision(self, account_name: str, decision_data: dict) -> str:
        """Publish a final decision to the decisions stream for this account."""
        return await self._publish(f"stream:decisions:{account_name}", decision_data)

    async def publish_alert(self, account_name: str, alert_data: dict) -> str:
        """Publish a risk or system alert to the alerts stream for this account."""
        return await self._publish(f"stream:alerts:{account_name}", alert_data)

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    async def _publish(self, stream_name: str, data: dict) -> str:
        """Serialize data and write a single entry to a Redis Stream.

        Args:
            stream_name: Full Redis key for the target stream.
            data: Arbitrary dict to publish; stored as a JSON string under
                  the ``"data"`` field so consumers get a single parseable blob.

        Returns:
            The Redis message ID assigned by xadd (e.g. ``"1234567890-0"``).

        Raises:
            Exception: Re-raises any Redis error after logging it so callers
                       can decide whether to retry or skip.
        """
        try:
            msg_id = await self._redis.xadd(stream_name, {"data": json.dumps(data)})
            return msg_id
        except Exception as exc:
            logger.error(
                "AgentStreamPublisher failed to publish to %s: %s",
                stream_name,
                exc,
                exc_info=True,
            )
            raise


class AgentStreamSubscriber:
    """Subscribe to Redis Streams and dispatch messages to registered callbacks.

    Usage::

        sub = AgentStreamSubscriber(redis_client=redis)
        await sub.subscribe("stream:signals:paper_test", my_handler)
        messages = await sub.poll()

    Wildcard subscriptions (``subscribe_all_signals``) are stored but NOT
    polled via xread — they are reserved for pattern-based fanout that the
    SP5 Orchestrator will wire up separately.
    """

    def __init__(self, redis_client) -> None:
        self._redis = redis_client
        self._callbacks: dict[str, Callable] = {}

    # ------------------------------------------------------------------
    # Subscription management
    # ------------------------------------------------------------------

    async def subscribe(self, stream_name: str, callback: Callable) -> None:
        """Register a callback for a specific stream name."""
        self._callbacks[stream_name] = callback

    async def subscribe_all_signals(self, callback: Callable) -> None:
        """Register a callback for all signal streams (wildcard entry).

        Note: wildcard keys are stored but not polled directly by ``poll()``.
        The SP5 Orchestrator is responsible for resolving them.
        """
        self._callbacks["stream:signals:*"] = callback

    async def unsubscribe(self, stream_name: str) -> None:
        """Remove the callback for a stream, no-op if not registered."""
        self._callbacks.pop(stream_name, None)

    # ------------------------------------------------------------------
    # Polling
    # ------------------------------------------------------------------

    async def poll(self, block_ms: int = 1000) -> list[dict]:
        """Read new messages from all concrete (non-wildcard) streams.

        Args:
            block_ms: How long (ms) to block waiting for new messages.
                      Passed directly to ``xread``.

        Returns:
            List of parsed message dicts from all active streams. Each dict
            is the deserialized ``"data"`` field written by the publisher.
            Returns ``[]`` on error to keep the poll loop alive.
        """
        concrete = {
            name: "0"
            for name in self._callbacks
            if "*" not in name
        }
        if not concrete:
            return []

        try:
            raw_result = await self._redis.xread(concrete, block=block_ms, count=10)
            messages: list[dict] = []
            for stream_name, stream_messages in (raw_result or []):
                callback = self._callbacks.get(stream_name)
                for _msg_id, fields in stream_messages:
                    try:
                        parsed = json.loads(fields.get("data", "{}"))
                    except json.JSONDecodeError:
                        parsed = dict(fields)
                    if callback is not None:
                        await callback(parsed) if callable(callback) else None
                    messages.append(parsed)
            return messages
        except Exception as exc:
            logger.error(
                "AgentStreamSubscriber poll error: %s", exc, exc_info=True
            )
            return []
