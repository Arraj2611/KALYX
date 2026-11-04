"""Choose which option contract to buy for a directional view. Plain rules, no model.

The council decides *what* to expect (direction, horizon, invalidation); this module decides *which
contract* expresses it. Each stage narrows the chain and, if nothing is left, the rejection says which
stage emptied it, so a "no trade" is never a mystery.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Union
from zoneinfo import ZoneInfo

from app.options.contracts import ChainRow, OptionContract
from app.options.greeks import greeks, implied_vol

_IST = ZoneInfo("Asia/Kolkata")
_SESSION_CLOSE_HOUR, _SESSION_CLOSE_MINUTE = 15, 30  # options expire at the 15:30 close


@dataclass(frozen=True)
class PickRules:
    min_days_to_expiry: float = 2.0
    allow_expiry_day: bool = False
    delta_low: float = 0.30
    delta_high: float = 0.55
    target_delta: float = 0.40
    max_spread_pct: float = 5.0
    min_open_interest: float = 1000
    min_volume: float = 100


@dataclass(frozen=True)
class Pick:
    contract: OptionContract
    entry_price: float  # the ask: what buying right now costs
    delta: float  # signed: positive for calls, negative for puts
    iv: float
    spread_pct: float
    reasons: tuple[str, ...] = ()


@dataclass(frozen=True)
class Rejection:
    reason: str
    detail: dict = field(default_factory=dict)


def _expiry_moment(contract: OptionContract) -> datetime:
    day = contract.expiry
    return datetime(day.year, day.month, day.day, _SESSION_CLOSE_HOUR, _SESSION_CLOSE_MINUTE, tzinfo=_IST)


def pick_contract(
    chain: list[ChainRow],
    direction: str,
    spot: float,
    now: datetime,
    horizon_days: float,
    rules: PickRules,
    rate: float = 0.065,
    div_yield: float = 0.013,
) -> Union[Pick, Rejection]:
    """The best long call (direction "UP") or put ("DOWN") in the chain, or the reason there is none."""
    if now.tzinfo is None:
        raise ValueError("now must be timezone-aware")
    if direction not in ("UP", "DOWN"):
        raise ValueError(f"direction must be 'UP' or 'DOWN', got {direction!r}")
    if horizon_days <= 0:
        raise ValueError("horizon_days must be positive")
    if spot <= 0:
        raise ValueError("spot must be positive")

    kind = "CE" if direction == "UP" else "PE"
    rows = [r for r in chain if r.contract.kind == kind]
    detail: dict = {"considered": len(rows)}
    if not rows:
        return Rejection("empty_chain", detail)

    today = now.astimezone(_IST).date()
    after_expiry: list[tuple[ChainRow, float]] = []
    for r in rows:
        days_left = (_expiry_moment(r.contract) - now).total_seconds() / 86400.0
        if days_left < horizon_days:
            continue  # it would expire before the view plays out
        if r.contract.expiry == today:
            if not rules.allow_expiry_day:
                continue
        elif days_left < rules.min_days_to_expiry:
            continue
        after_expiry.append((r, days_left))
    detail["after_expiry"] = len(after_expiry)
    if not after_expiry:
        return Rejection("expiry_too_close", detail)

    liquid = [
        (r, d) for r, d in after_expiry
        if r.quote.open_interest >= rules.min_open_interest and r.quote.volume >= rules.min_volume
    ]
    detail["after_liquidity"] = len(liquid)
    if not liquid:
        return Rejection("no_liquid_contract", detail)

    quoted = [(r, d) for r, d in liquid if r.quote.bid > 0 and r.quote.ask >= r.quote.bid]
    detail["after_quote"] = len(quoted)
    if not quoted:
        return Rejection("no_usable_quote", detail)

    tight = []
    for r, d in quoted:
        mid = (r.quote.bid + r.quote.ask) / 2.0
        spread_pct = (r.quote.ask - r.quote.bid) / mid * 100.0
        if spread_pct <= rules.max_spread_pct:
            tight.append((r, d, mid, spread_pct))
    detail["after_spread"] = len(tight)
    if not tight:
        return Rejection("spread_too_wide", detail)

    candidates = []
    for r, days_left, mid, spread_pct in tight:
        t_years = max(days_left, 1e-6) / 365.0
        iv = implied_vol(kind, mid, spot, r.contract.strike, t_years, rate, div_yield)
        if iv is None:
            continue
        delta = greeks(kind, spot, r.contract.strike, t_years, rate, div_yield, iv).delta
        if rules.delta_low <= abs(delta) <= rules.delta_high:
            candidates.append((r, delta, iv, spread_pct))
    detail["after_delta"] = len(candidates)
    if not candidates:
        return Rejection("no_contract_in_delta_band", detail)

    best = min(
        candidates,
        key=lambda c: (
            round(abs(abs(c[1]) - rules.target_delta), 9),
            round(abs(c[0].contract.strike - spot), 9),
            c[0].contract.expiry,
            c[0].contract.strike,
            c[0].contract.symbol,
        ),
    )
    row, delta, iv, spread_pct = best
    return Pick(
        contract=row.contract,
        entry_price=row.quote.ask,
        delta=delta,
        iv=iv,
        spread_pct=spread_pct,
        reasons=(
            f"delta {delta:+.2f} is closest to the {rules.target_delta:.2f} target inside "
            f"[{rules.delta_low:.2f}, {rules.delta_high:.2f}]",
            f"spread {spread_pct:.2f}% within {rules.max_spread_pct:.1f}%",
        ),
    )
