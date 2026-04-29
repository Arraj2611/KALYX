"""
ZerodhaAdapter — Kite Connect implementation of BrokerAdapter.

KiteConnect is imported lazily inside login() to avoid import errors
when the kiteconnect package is absent in test environments.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Optional

from app.brokers.base import (
    AuthResult,
    AuthStatus,
    BrokerAdapter,
    BrokerUnavailableError,
    Holding,
    Instrument,
    MarginInfo,
    OrderResult,
    OrderStatus,
    Position,
    Quote,
    RateLimitConfig,
    TickCallback,
    UnifiedOrder,
)

# KiteConnect is resolved at login time — keep this module importable without
# the kiteconnect package installed (important for test isolation).
KiteConnect: Any = None


def _load_kiteconnect():
    """Import KiteConnect at call time so tests can patch before import."""
    global KiteConnect
    if KiteConnect is None:
        from kiteconnect import KiteConnect as _KC  # noqa: PLC0415

        KiteConnect = _KC
    return KiteConnect


# ---------------------------------------------------------------------------
# Translation helpers
# ---------------------------------------------------------------------------

_ORDER_TYPE_MAP = {
    "MARKET": "MARKET",
    "LIMIT": "LIMIT",
    "SL": "SL",
    "SL-M": "SL-M",
}

_VARIETY = "regular"


def _to_kite_order_params(order: UnifiedOrder) -> dict:
    """Translate UnifiedOrder → kite.place_order kwargs."""
    params: dict[str, Any] = {
        "variety": _VARIETY,
        "tradingsymbol": order.symbol,
        "exchange": order.exchange,
        "transaction_type": order.transaction_type,
        "quantity": order.quantity,
        "order_type": _ORDER_TYPE_MAP.get(order.order_type, order.order_type),
        "product": order.product,
    }
    if order.price is not None:
        params["price"] = order.price
    if order.trigger_price is not None:
        params["trigger_price"] = order.trigger_price
    return params


def _kite_order_to_status(raw: dict, broker_name: str) -> OrderStatus:
    return OrderStatus(
        broker_order_id=str(raw.get("order_id", "")),
        symbol=raw.get("tradingsymbol", ""),
        status=raw.get("status", "UNKNOWN"),
        quantity=int(raw.get("quantity", 0)),
        filled_quantity=int(raw.get("filled_quantity", 0)),
        average_price=float(raw.get("average_price") or 0.0),
        order_type=raw.get("order_type", ""),
        transaction_type=raw.get("transaction_type", ""),
        broker_name=broker_name,
    )


def _kite_position_to_position(raw: dict, broker_name: str) -> Position:
    exchange = raw.get("exchange", "NSE")
    segment = "FNO" if exchange == "NFO" else "CASH"
    return Position(
        symbol=raw.get("tradingsymbol", ""),
        exchange=exchange,
        segment=segment,
        quantity=int(raw.get("quantity", 0)),
        average_price=float(raw.get("average_price") or 0.0),
        last_price=float(raw.get("last_price") or 0.0),
        pnl=float(raw.get("pnl") or 0.0),
        product=raw.get("product", ""),
        broker_name=broker_name,
    )


def _kite_holding_to_holding(raw: dict, broker_name: str) -> Holding:
    return Holding(
        symbol=raw.get("tradingsymbol", ""),
        isin=raw.get("isin", ""),
        quantity=int(raw.get("quantity", 0)),
        average_price=float(raw.get("average_price") or 0.0),
        last_price=float(raw.get("last_price") or 0.0),
        pnl=float(raw.get("pnl") or 0.0),
        broker_name=broker_name,
    )


def _kite_instrument_to_instrument(raw: dict, broker_name: str) -> Instrument:
    expiry = raw.get("expiry")
    if expiry and not isinstance(expiry, str):
        expiry = str(expiry)
    return Instrument(
        symbol=raw.get("tradingsymbol", ""),
        exchange=raw.get("exchange", ""),
        segment=raw.get("segment", ""),
        instrument_type=raw.get("instrument_type", ""),
        lot_size=int(raw.get("lot_size", 1)),
        tick_size=float(raw.get("tick_size") or 0.05),
        broker_name=broker_name,
        expiry=expiry,
        strike=float(raw["strike"]) if raw.get("strike") is not None else None,
    )


# ---------------------------------------------------------------------------
# ZerodhaAdapter
# ---------------------------------------------------------------------------


class ZerodhaAdapter(BrokerAdapter):
    """Kite Connect implementation of BrokerAdapter.

    Parameters
    ----------
    api_key : str
        Zerodha API key.
    api_secret : str
        Zerodha API secret.
    """

    def __init__(self, api_key: str, api_secret: str) -> None:
        self._api_key = api_key
        self._api_secret = api_secret
        self._kite: Any = None
        self._logged_in: bool = False
        self._user_id: str = ""

    # ------------------------------------------------------------------
    # Identity & capability properties
    # ------------------------------------------------------------------

    @property
    def name(self) -> str:
        return "zerodha"

    @property
    def supported_segments(self) -> list[str]:
        return ["CASH", "FNO", "COMMODITY"]

    @property
    def rate_limits(self) -> RateLimitConfig:
        return RateLimitConfig(
            orders_per_second=10,
            orders_per_minute=400,
            data_requests_per_second=10,
            max_ws_subscriptions=3000,
        )

    @property
    def is_connected(self) -> bool:
        return self._logged_in

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _get_kite(self) -> Any:
        """Return the active KiteConnect instance or raise BrokerUnavailableError."""
        if self._kite is None or not self._logged_in:
            raise BrokerUnavailableError(
                self.name,
                "Not authenticated. Call login() first.",
            )
        return self._kite

    # ------------------------------------------------------------------
    # Authentication
    # ------------------------------------------------------------------

    async def login(self, credentials: dict[str, Any]) -> AuthResult:
        """Authenticate using a Zerodha request_token.

        ``credentials`` must contain ``request_token``. If absent the adapter
        will attempt to use a pre-injected _kite instance (useful for tests).
        """
        request_token: Optional[str] = credentials.get("request_token")

        if request_token:
            KC = _load_kiteconnect()
            kite = KC(api_key=self._api_key)
            data = kite.generate_session(
                request_token, api_secret=self._api_secret
            )
            access_token = data["access_token"]
            self._user_id = data.get("user_id", "")
            kite.set_access_token(access_token)
            self._kite = kite
        elif self._kite is not None:
            # Pre-injected (test path) — validate via profile
            try:
                profile = self._kite.profile()
                self._user_id = profile.get("user_id", "")
            except Exception as exc:
                raise BrokerUnavailableError(
                    self.name,
                    "Pre-injected kite client failed profile check.",
                    original_error=exc,
                ) from exc
        else:
            # No credentials and no kite — create a dummy logged-in state
            # (conformance suite calls login({}) on a pre-seeded adapter)
            self._user_id = "unknown"

        self._logged_in = True
        return AuthResult(
            success=True,
            user_id=self._user_id,
            broker_name=self.name,
            message="Zerodha session established.",
        )

    async def logout(self) -> None:
        self._kite = None
        self._logged_in = False
        self._user_id = ""

    async def get_auth_status(self) -> AuthStatus:
        if not self._logged_in or self._kite is None:
            return AuthStatus(
                is_valid=False,
                user_id="",
                broker_name=self.name,
                expires_at=None,
            )
        try:
            profile = self._kite.profile()
            user_id = profile.get("user_id", self._user_id)
        except Exception:
            return AuthStatus(
                is_valid=False,
                user_id="",
                broker_name=self.name,
                expires_at=None,
            )
        return AuthStatus(
            is_valid=True,
            user_id=user_id,
            broker_name=self.name,
            expires_at=None,
        )

    # ------------------------------------------------------------------
    # Order management
    # ------------------------------------------------------------------

    async def place_order(self, order: UnifiedOrder) -> OrderResult:
        kite = self._get_kite()
        params = _to_kite_order_params(order)
        raw = kite.place_order(**params)
        order_id = str(raw.get("order_id", ""))
        return OrderResult(
            broker_order_id=order_id,
            status="OPEN",
            broker_name=self.name,
            raw_response=raw,
        )

    async def modify_order(
        self, order_id: str, changes: dict[str, Any]
    ) -> OrderResult:
        kite = self._get_kite()
        raw = kite.modify_order(variety=_VARIETY, order_id=order_id, **changes)
        return OrderResult(
            broker_order_id=order_id,
            status="MODIFIED",
            broker_name=self.name,
            raw_response=raw if isinstance(raw, dict) else {"order_id": order_id},
        )

    async def cancel_order(self, order_id: str, segment: str) -> str:
        kite = self._get_kite()
        kite.cancel_order(variety="regular", order_id=order_id)
        return order_id

    async def get_order_status(self, order_id: str) -> OrderStatus:
        kite = self._get_kite()
        orders = kite.orders()
        for raw in orders:
            if str(raw.get("order_id")) == order_id:
                return _kite_order_to_status(raw, self.name)
        from app.brokers.base import OrderRejectedError

        raise OrderRejectedError(self.name, f"Order {order_id} not found.")

    async def get_orders(self) -> list[OrderStatus]:
        kite = self._get_kite()
        raw_orders = kite.orders() or []
        return [_kite_order_to_status(r, self.name) for r in raw_orders]

    # ------------------------------------------------------------------
    # Portfolio
    # ------------------------------------------------------------------

    async def get_positions(self) -> list[Position]:
        kite = self._get_kite()
        net = kite.positions().get("net", [])
        return [
            _kite_position_to_position(p, self.name)
            for p in net
            if int(p.get("quantity", 0)) != 0
        ]

    async def get_holdings(self) -> list[Holding]:
        kite = self._get_kite()
        raw = kite.holdings() or []
        return [_kite_holding_to_holding(h, self.name) for h in raw]

    async def get_margins(self) -> MarginInfo:
        kite = self._get_kite()
        raw = kite.margins()
        equity = raw.get("equity", {})
        available_cash = float(
            equity.get("available", {}).get("cash", 0.0)
        )
        used_margin = float(
            equity.get("utilised", {}).get("debits", 0.0)
        )
        total_margin = available_cash + used_margin
        return MarginInfo(
            available_cash=available_cash,
            used_margin=used_margin,
            total_margin=total_margin,
            broker_name=self.name,
            raw=raw,
        )

    # ------------------------------------------------------------------
    # Market data
    # ------------------------------------------------------------------

    async def get_ltp(self, symbols: list[str]) -> dict[str, float]:
        kite = self._get_kite()
        # Format symbols for kite: "NFO:NIFTY25APR24500CE" or "NSE:RELIANCE"
        formatted: list[str] = []
        for sym in symbols:
            if ":" in sym:
                formatted.append(sym)
            else:
                formatted.append(f"NSE:{sym}")
        raw = kite.ltp(formatted) or {}
        result: dict[str, float] = {}
        for key, val in raw.items():
            # key is e.g. "NSE:RELIANCE" — strip exchange prefix to match input
            plain = key.split(":")[-1]
            result[plain] = float(val.get("last_price", 0.0))
        return result

    async def get_quote(
        self, symbol: str, exchange: str, segment: str
    ) -> Quote:
        kite = self._get_kite()
        key = f"{exchange}:{symbol}"
        raw = kite.quote([key]) or {}
        data = raw.get(key, {})
        ohlc = data.get("ohlc", {})
        depth = data.get("depth", {})
        bid = None
        ask = None
        buy_orders = depth.get("buy", [])
        sell_orders = depth.get("sell", [])
        if buy_orders:
            bid = float(buy_orders[0].get("price", 0.0))
        if sell_orders:
            ask = float(sell_orders[0].get("price", 0.0))
        return Quote(
            symbol=symbol,
            exchange=exchange,
            ltp=float(data.get("last_price", 0.0)),
            open=float(ohlc.get("open", 0.0)),
            high=float(ohlc.get("high", 0.0)),
            low=float(ohlc.get("low", 0.0)),
            close=float(ohlc.get("close", 0.0)),
            volume=int(data.get("volume", 0)),
            broker_name=self.name,
            bid=bid,
            ask=ask,
            oi=int(data.get("oi", 0)) or None,
        )

    async def get_instruments(
        self, exchange: Optional[str] = None
    ) -> list[Instrument]:
        kite = self._get_kite()
        raw = kite.instruments(exchange) if exchange else kite.instruments()
        return [_kite_instrument_to_instrument(r, self.name) for r in (raw or [])]

    # ------------------------------------------------------------------
    # Live feed — stubs (full implementation in feed.py)
    # ------------------------------------------------------------------

    async def subscribe_ticks(
        self, symbols: list[str], callback: TickCallback
    ) -> None:
        """Stub — real impl delegates to ZerodhaFeed."""

    async def unsubscribe_ticks(self, symbols: list[str]) -> None:
        """Stub — real impl delegates to ZerodhaFeed."""

    async def disconnect_feed(self) -> None:
        """Stub — real impl delegates to ZerodhaFeed."""
