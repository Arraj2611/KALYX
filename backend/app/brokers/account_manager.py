"""AccountManager — multi-account broker registry for KALYX.

Registers multiple BrokerAdapter instances by account name and provides
cross-account queries for positions, margins, and total exposure.
Per-adapter failures are caught and logged so one bad account never
blocks results from healthy ones.
"""

from __future__ import annotations

import logging
from typing import Any

from app.brokers.base import BrokerAdapter, MarginInfo, Position

logger = logging.getLogger(__name__)


class AccountManager:
    """Registry of named broker adapters.

    Usage::

        mgr = AccountManager()
        mgr.register("zerodha_fno", ZerodhaAdapter(cfg), cfg)
        mgr.register("paper_test", PaperAdapter(cfg), cfg)

        positions = await mgr.get_all_positions()
        margins   = await mgr.get_all_margins()
        exposure  = await mgr.get_total_exposure()
    """

    def __init__(self) -> None:
        # account_name -> adapter
        self._adapters: dict[str, BrokerAdapter] = {}
        # account_name -> config dict
        self._configs: dict[str, dict[str, Any]] = {}

    # ------------------------------------------------------------------
    # Registry operations
    # ------------------------------------------------------------------

    def register(
        self,
        account_name: str,
        adapter: BrokerAdapter,
        config: dict[str, Any],
    ) -> None:
        """Register a broker adapter under the given account name.

        Raises
        ------
        ValueError
            If *account_name* is already registered.
        """
        if account_name in self._adapters:
            raise ValueError(
                f"Account '{account_name}' is already registered. "
                "Use a unique name or deregister the existing adapter first."
            )
        self._adapters[account_name] = adapter
        self._configs[account_name] = config
        logger.info("Registered account '%s' (broker=%s)", account_name, adapter.name)

    def get_adapter(self, account_name: str) -> BrokerAdapter:
        """Return the adapter registered under *account_name*.

        Raises
        ------
        KeyError
            If no adapter is registered with that name.
        """
        if account_name not in self._adapters:
            raise KeyError(f"No account registered with name '{account_name}'.")
        return self._adapters[account_name]

    def get_all_adapters(self) -> dict[str, BrokerAdapter]:
        """Return a shallow copy of the name -> adapter mapping."""
        return dict(self._adapters)

    def get_adapters_by_broker(self, broker_name: str) -> list[BrokerAdapter]:
        """Return all adapters whose ``adapter.name`` matches *broker_name*.

        Returns an empty list when no matches are found.
        """
        return [
            adapter
            for adapter in self._adapters.values()
            if adapter.name == broker_name
        ]

    def get_account_names(self) -> list[str]:
        """Return a list of all registered account names."""
        return list(self._adapters.keys())

    # ------------------------------------------------------------------
    # Cross-account async queries
    # ------------------------------------------------------------------

    async def get_all_positions(self) -> dict[str, list[Position]]:
        """Fetch open positions from every registered adapter.

        Returns a mapping of account_name -> list[Position].
        Adapters that raise are logged and skipped (empty list returned
        for that account).
        """
        result: dict[str, list[Position]] = {}
        for account_name, adapter in self._adapters.items():
            try:
                positions = await adapter.get_positions()
                result[account_name] = positions
            except Exception as exc:  # noqa: BLE001
                logger.error(
                    "get_positions failed for account '%s': %s",
                    account_name,
                    exc,
                )
                result[account_name] = []
        return result

    async def get_all_margins(self) -> dict[str, MarginInfo]:
        """Fetch margin info from every registered adapter.

        Returns a mapping of account_name -> MarginInfo.
        Adapters that raise are logged and omitted from the result.
        """
        result: dict[str, MarginInfo] = {}
        for account_name, adapter in self._adapters.items():
            try:
                margin = await adapter.get_margins()
                result[account_name] = margin
            except Exception as exc:  # noqa: BLE001
                logger.error(
                    "get_margins failed for account '%s': %s",
                    account_name,
                    exc,
                )
        return result

    async def get_total_exposure(self) -> float:
        """Sum of used_margin across all accounts that respond successfully.

        Returns 0.0 when no accounts have open positions or all fail.
        """
        all_margins = await self.get_all_margins()
        return sum(m.used_margin for m in all_margins.values())
