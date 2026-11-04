import math
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import pytest

from app.options.sizing import exit_reason, plan_exits, size_long_option

IST = ZoneInfo("Asia/Kolkata")
ENTRY = datetime(2026, 11, 4, 10, 0, tzinfo=IST)
EXPIRY = datetime(2026, 11, 10, 15, 30, tzinfo=IST)


def test_budget_rounds_down_to_whole_lots():
    assert size_long_option(100_000, 100.0, 75, 50) == 13  # 13 lots cost 97,500; 14 would cost 105,000


def test_one_lot_over_budget_gives_zero():
    assert size_long_option(5_000, 100.0, 75, 50) == 0


def test_max_lots_caps_the_size():
    assert size_long_option(1_000_000, 100.0, 75, 10) == 10


def test_a_zero_budget_buys_nothing():
    assert size_long_option(0.0, 100.0, 75, 10) == 0


@pytest.mark.parametrize("args", [(-1.0, 100.0, 75, 10), (1000.0, 0.0, 75, 10), (1000.0, -5.0, 75, 10), (1000.0, 100.0, 0, 10), (1000.0, 100.0, 75, -1)])
def test_invalid_sizing_inputs_raise(args):
    with pytest.raises(ValueError):
        size_long_option(*args)


def test_the_most_that_can_be_lost_never_exceeds_the_budget():
    for budget in (10_000, 55_555, 123_456):
        lots = size_long_option(budget, 87.35, 75, 100)
        assert lots * 87.35 * 75 <= budget


def make_plan(direction="UP", **kw):
    args = dict(
        entry_price=100.0, direction=direction, underlying_invalidation=24400.0 if direction == "UP" else 24600.0,
        entry_time=ENTRY, expiry=EXPIRY, horizon_days=2.0,
    )
    args.update(kw)
    return plan_exits(**args)


def test_the_premium_stop_is_a_fraction_below_the_entry():
    assert make_plan().premium_stop == pytest.approx(65.0)
    assert make_plan(premium_stop_pct=0.5).premium_stop == pytest.approx(50.0)


def test_premium_stop_triggers_at_or_below_the_stop():
    plan = make_plan()
    assert exit_reason(plan, 64.9, 24500.0, ENTRY) == "premium_stop"
    assert exit_reason(plan, 65.0, 24500.0, ENTRY) == "premium_stop"
    assert exit_reason(plan, 65.1, 24500.0, ENTRY) is None


def test_an_up_view_is_invalidated_at_or_below_the_level():
    plan = make_plan("UP")
    assert exit_reason(plan, 100.0, 24400.0, ENTRY) == "underlying_invalidation"
    assert exit_reason(plan, 100.0, 24401.0, ENTRY) is None


def test_a_down_view_is_invalidated_at_or_above_the_level():
    plan = make_plan("DOWN")
    assert exit_reason(plan, 100.0, 24600.0, ENTRY) == "underlying_invalidation"
    assert exit_reason(plan, 100.0, 24599.0, ENTRY) is None


def test_the_time_stop_is_the_horizon_when_it_comes_first():
    assert make_plan(horizon_days=1.0).time_stop == ENTRY + timedelta(days=1)


def test_the_time_stop_never_passes_the_expiry_buffer():
    plan = make_plan(horizon_days=30.0, expiry_buffer_hours=2.0)
    assert plan.time_stop == EXPIRY - timedelta(hours=2)


def test_time_stop_triggers_at_the_time():
    plan = make_plan(horizon_days=1.0)
    assert exit_reason(plan, 100.0, 24500.0, plan.time_stop - timedelta(seconds=1)) is None
    assert exit_reason(plan, 100.0, 24500.0, plan.time_stop) == "time_stop"


def test_a_broken_thesis_outranks_the_premium_stop_which_outranks_the_clock():
    plan = make_plan(horizon_days=1.0)
    late = plan.time_stop + timedelta(hours=1)
    assert exit_reason(plan, 10.0, 24000.0, late) == "underlying_invalidation"
    assert exit_reason(plan, 10.0, 24500.0, late) == "premium_stop"
    assert exit_reason(plan, 100.0, 24500.0, late) == "time_stop"


def test_missing_prices_neither_trigger_nor_crash():
    plan = make_plan()
    assert exit_reason(plan, None, None, ENTRY) is None
    assert exit_reason(plan, math.nan, math.nan, ENTRY) is None
    assert exit_reason(plan, 0.0, 24500.0, ENTRY) is None  # a zero premium is a missing quote, not a stop


def test_the_clock_may_be_in_any_time_zone():
    plan = make_plan(horizon_days=1.0)
    assert exit_reason(plan, 100.0, 24500.0, plan.time_stop.astimezone(timezone.utc)) == "time_stop"


@pytest.mark.parametrize(
    "changes",
    [
        {"entry_time": datetime(2026, 11, 4, 10, 0)},
        {"expiry": datetime(2026, 11, 10, 15, 30)},
        {"premium_stop_pct": 0.0},
        {"premium_stop_pct": 1.0},
        {"entry_price": 0.0},
        {"horizon_days": 0.0},
        {"direction": "SIDEWAYS"},
        {"entry_time": EXPIRY - timedelta(hours=1)},
    ],
)
def test_invalid_plans_raise(changes):
    with pytest.raises(ValueError):
        make_plan(**changes)
