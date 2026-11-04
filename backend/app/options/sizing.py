"""Position size and exits for a long option. Plain arithmetic, no model.

A bought option can lose at most the premium paid, so size is premium at risk: how many whole lots fit
inside a budget. Each position carries three exits, checked in priority order: the thesis broke on the
underlying, the premium fell to its stop, or time ran out (a long option also loses value as time passes).
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Optional


def size_long_option(premium_budget: float, entry_price: float, lot_size: int, max_lots: int) -> int:
    """Whole lots that fit in the budget, never more than ``max_lots``. 0 when one lot costs more."""
    if premium_budget < 0:
        raise ValueError("premium_budget cannot be negative")
    if entry_price <= 0:
        raise ValueError("entry_price must be positive")
    if lot_size <= 0:
        raise ValueError("lot_size must be positive")
    if max_lots < 0:
        raise ValueError("max_lots cannot be negative")
    return min(int(premium_budget // (entry_price * lot_size)), max_lots)


@dataclass(frozen=True)
class OptionExitPlan:
    premium_stop: float
    underlying_invalidation: float
    time_stop: datetime
    direction: str  # "UP" (long call) or "DOWN" (long put)


def plan_exits(
    entry_price: float,
    direction: str,
    underlying_invalidation: float,
    entry_time: datetime,
    expiry: datetime,
    horizon_days: float,
    premium_stop_pct: float = 0.35,
    expiry_buffer_hours: float = 2.0,
) -> OptionExitPlan:
    """The three exits for a new long option. The time stop is the horizon or the expiry buffer, whichever is first."""
    if direction not in ("UP", "DOWN"):
        raise ValueError(f"direction must be 'UP' or 'DOWN', got {direction!r}")
    if entry_price <= 0:
        raise ValueError("entry_price must be positive")
    if not 0 < premium_stop_pct < 1:
        raise ValueError("premium_stop_pct must be between 0 and 1")
    if horizon_days <= 0:
        raise ValueError("horizon_days must be positive")
    if entry_time.tzinfo is None or expiry.tzinfo is None:
        raise ValueError("entry_time and expiry must be timezone-aware")
    time_stop = min(entry_time + timedelta(days=horizon_days), expiry - timedelta(hours=expiry_buffer_hours))
    if time_stop <= entry_time:
        raise ValueError("no time left before the expiry buffer")
    return OptionExitPlan(
        premium_stop=entry_price * (1.0 - premium_stop_pct),
        underlying_invalidation=underlying_invalidation,
        time_stop=time_stop,
        direction=direction,
    )


def _usable(value: Optional[float]) -> bool:
    return value is not None and math.isfinite(value) and value > 0


def exit_reason(plan: OptionExitPlan, premium: Optional[float], underlying: Optional[float], now: datetime) -> Optional[str]:
    """Why to exit now, or None. A missing, zero or non-finite price never triggers an exit by itself."""
    if _usable(underlying):
        broke = underlying <= plan.underlying_invalidation if plan.direction == "UP" else underlying >= plan.underlying_invalidation
        if broke:
            return "underlying_invalidation"
    if _usable(premium) and premium <= plan.premium_stop:
        return "premium_stop"
    if now >= plan.time_stop:
        return "time_stop"
    return None
