"""Option contract and quote types, and conversion from the broker's instrument list."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date
from typing import Iterable

from app.brokers.base import Instrument


@dataclass(frozen=True)
class OptionContract:
    underlying: str
    kind: str  # "CE" (call) or "PE" (put)
    strike: float
    expiry: date
    lot_size: int
    symbol: str
    exchange: str


@dataclass(frozen=True)
class OptionQuote:
    bid: float
    ask: float
    ltp: float
    open_interest: float
    volume: float


@dataclass(frozen=True)
class ChainRow:
    contract: OptionContract
    quote: OptionQuote


def contracts_from_instruments(instruments: Iterable[Instrument], underlying: str) -> list[OptionContract]:
    """Option contracts on ``underlying`` from a broker instrument list.

    Broker symbols look like NIFTY26NOV24500CE or NIFTY2611324500CE. The character after the
    underlying name must be a digit, so BANKNIFTY and NIFTYNXT50 are never mistaken for NIFTY.
    Futures, rows without a strike, and rows with an unreadable expiry are skipped.
    """
    pattern = re.compile(rf"^{re.escape(underlying)}\d")
    found: list[OptionContract] = []
    for item in instruments:
        if item.instrument_type not in ("CE", "PE") or item.strike is None or not item.expiry:
            continue
        if not pattern.match(item.symbol):
            continue
        try:
            expiry = date.fromisoformat(str(item.expiry)[:10])
        except ValueError:
            continue
        found.append(
            OptionContract(
                underlying=underlying,
                kind=item.instrument_type,
                strike=float(item.strike),
                expiry=expiry,
                lot_size=int(item.lot_size),
                symbol=item.symbol,
                exchange=item.exchange,
            )
        )
    return found
