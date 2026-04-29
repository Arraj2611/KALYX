"""
ZerodhaFeed — KiteTicker wrapper for live market data.

This is a stub implementation. The full WebSocket-based feed handler
(with reconnect logic, instrument token resolution, and tick callbacks)
will be fleshed out in a follow-up task that migrates app.auth.websocket_client.
"""

from __future__ import annotations

import logging
from typing import Callable, Optional

logger = logging.getLogger(__name__)

TickCallback = Callable[[dict], None]


class ZerodhaFeed:
    """Thin async wrapper around KiteTicker.

    Parameters
    ----------
    api_key : str
        Zerodha API key.
    access_token : str
        Valid access token obtained via ZerodhaAdapter.login().
    """

    def __init__(self, api_key: str, access_token: str) -> None:
        self._api_key = api_key
        self._access_token = access_token
        self._ticker: Optional[object] = None
        self._callbacks: dict[int, list[TickCallback]] = {}

    async def connect(self) -> None:
        """Initialize KiteTicker and open the WebSocket connection."""
        try:
            from kiteconnect import KiteTicker  # noqa: PLC0415

            self._ticker = KiteTicker(self._api_key, self._access_token)
            # In the full implementation:
            #   self._ticker.on_ticks = self._on_ticks
            #   self._ticker.on_connect = self._on_connect
            #   self._ticker.on_close = self._on_close
            #   self._ticker.connect(threaded=True)
            logger.info("ZerodhaFeed: ticker initialized (connect stub).")
        except ImportError:
            logger.warning(
                "kiteconnect not installed — ZerodhaFeed.connect() is a no-op."
            )

    def subscribe(
        self, instrument_tokens: list[int], callback: TickCallback
    ) -> None:
        """Register *callback* for each instrument token in *instrument_tokens*."""
        for token in instrument_tokens:
            self._callbacks.setdefault(token, []).append(callback)
        if self._ticker is not None:
            # self._ticker.subscribe(instrument_tokens)
            # self._ticker.set_mode(self._ticker.MODE_FULL, instrument_tokens)
            logger.debug(
                "ZerodhaFeed.subscribe: %d tokens (stub — not sending to ticker).",
                len(instrument_tokens),
            )

    def unsubscribe(self, instrument_tokens: list[int]) -> None:
        """Stop delivering ticks for the given instrument tokens."""
        for token in instrument_tokens:
            self._callbacks.pop(token, None)
        if self._ticker is not None:
            # self._ticker.unsubscribe(instrument_tokens)
            logger.debug(
                "ZerodhaFeed.unsubscribe: %d tokens (stub).",
                len(instrument_tokens),
            )

    async def disconnect(self) -> None:
        """Close the WebSocket connection and release resources."""
        if self._ticker is not None:
            try:
                # self._ticker.close()
                pass
            except Exception as exc:
                logger.warning("ZerodhaFeed.disconnect error: %s", exc)
            finally:
                self._ticker = None
        self._callbacks.clear()
        logger.info("ZerodhaFeed disconnected.")
