"""Black-Scholes pricing for European options on an index with a continuous dividend yield.

NIFTY options are European and cash-settled, so this is the right model for them. It is used to
compute greeks and implied volatility from quotes and to choose contracts; it never places an order.
Everything is plain arithmetic with no dependency beyond the standard library.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Optional

_SQRT2 = math.sqrt(2.0)
_SQRT2PI = math.sqrt(2.0 * math.pi)
_DAYS_PER_YEAR = 365.0
_VOL_FLOOR, _VOL_CEILING = 1e-4, 5.0  # implied volatility search range: 0.01% to 500%


@dataclass(frozen=True)
class Greeks:
    delta: float
    gamma: float
    theta_per_day: float  # change in value per calendar day; negative for a long option
    vega_per_vol_point: float  # change in value for one percentage point of volatility


def _cdf(x: float) -> float:
    return 0.5 * (1.0 + math.erf(x / _SQRT2))


def _pdf(x: float) -> float:
    return math.exp(-0.5 * x * x) / _SQRT2PI


def _check(kind: str, spot: float, strike: float, t_years: float, vol: float) -> None:
    if kind not in ("CE", "PE"):
        raise ValueError(f"kind must be 'CE' or 'PE', got {kind!r}")
    if spot <= 0 or strike <= 0:
        raise ValueError("spot and strike must be positive")
    if t_years < 0:
        raise ValueError("time to expiry cannot be negative")
    if vol < 0:
        raise ValueError("volatility cannot be negative")


def _intrinsic(kind: str, spot: float, strike: float) -> float:
    return max(spot - strike, 0.0) if kind == "CE" else max(strike - spot, 0.0)


def _d1_d2(spot: float, strike: float, t: float, rate: float, q: float, vol: float) -> tuple[float, float]:
    spread = vol * math.sqrt(t)
    d1 = (math.log(spot / strike) + (rate - q + 0.5 * vol * vol) * t) / spread
    return d1, d1 - spread


def bs_price(kind: str, spot: float, strike: float, t_years: float, rate: float, div_yield: float, vol: float) -> float:
    """Option value. At expiry it is intrinsic; at zero volatility it is the discounted forward intrinsic."""
    _check(kind, spot, strike, t_years, vol)
    if t_years == 0:
        return _intrinsic(kind, spot, strike)
    disc_spot = spot * math.exp(-div_yield * t_years)
    disc_strike = strike * math.exp(-rate * t_years)
    if vol == 0:
        return max(disc_spot - disc_strike, 0.0) if kind == "CE" else max(disc_strike - disc_spot, 0.0)
    d1, d2 = _d1_d2(spot, strike, t_years, rate, div_yield, vol)
    if kind == "CE":
        return disc_spot * _cdf(d1) - disc_strike * _cdf(d2)
    return disc_strike * _cdf(-d2) - disc_spot * _cdf(-d1)


def greeks(kind: str, spot: float, strike: float, t_years: float, rate: float, div_yield: float, vol: float) -> Greeks:
    """Delta, gamma, theta and vega. At expiry or zero volatility: a delta step and zero for the rest."""
    _check(kind, spot, strike, t_years, vol)
    if t_years == 0 or vol == 0:
        in_the_money = spot > strike if kind == "CE" else spot < strike
        step = (1.0 if kind == "CE" else -1.0) if in_the_money else 0.0
        return Greeks(delta=step, gamma=0.0, theta_per_day=0.0, vega_per_vol_point=0.0)
    d1, d2 = _d1_d2(spot, strike, t_years, rate, div_yield, vol)
    root_t = math.sqrt(t_years)
    disc_spot = spot * math.exp(-div_yield * t_years)
    disc_strike = strike * math.exp(-rate * t_years)
    density = _pdf(d1)
    decay = -disc_spot * density * vol / (2.0 * root_t)
    if kind == "CE":
        delta = math.exp(-div_yield * t_years) * _cdf(d1)
        theta_year = decay - rate * disc_strike * _cdf(d2) + div_yield * disc_spot * _cdf(d1)
    else:
        delta = -math.exp(-div_yield * t_years) * _cdf(-d1)
        theta_year = decay + rate * disc_strike * _cdf(-d2) - div_yield * disc_spot * _cdf(-d1)
    return Greeks(
        delta=delta,
        gamma=math.exp(-div_yield * t_years) * density / (spot * vol * root_t),
        theta_per_day=theta_year / _DAYS_PER_YEAR,
        vega_per_vol_point=disc_spot * density * root_t / 100.0,
    )


def implied_vol(
    kind: str, price: float, spot: float, strike: float, t_years: float, rate: float, div_yield: float
) -> Optional[float]:
    """Volatility that reproduces ``price``, by bisection; None when no such volatility exists.

    None means: no time left, a non-positive price, a price at or below the zero-volatility value, or a
    price above what 500% volatility would give.
    """
    if kind not in ("CE", "PE") or spot <= 0 or strike <= 0 or t_years <= 0 or price <= 0:
        return None
    low, high = _VOL_FLOOR, _VOL_CEILING
    if price <= bs_price(kind, spot, strike, t_years, rate, div_yield, low):
        return None
    if price >= bs_price(kind, spot, strike, t_years, rate, div_yield, high):
        return None
    for _ in range(100):
        mid = 0.5 * (low + high)
        if bs_price(kind, spot, strike, t_years, rate, div_yield, mid) < price:
            low = mid
        else:
            high = mid
        if high - low < 1e-9:
            break
    return 0.5 * (low + high)
