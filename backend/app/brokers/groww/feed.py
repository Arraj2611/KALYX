"""GrowwFeed — stub WebSocket feed handler for Groww.

Full implementation pending official Groww WebSocket SDK support.
"""

from __future__ import annotations


class GrowwFeed:
    """Stub live feed handler for Groww."""

    def __init__(self, access_token: str) -> None:
        self._access_token = access_token

    async def connect(self) -> None:
        """Connect to the Groww live feed (stub)."""

    async def disconnect(self) -> None:
        """Disconnect from the Groww live feed (stub)."""
