import itertools
import math

import pytest

from app.options.greeks import Greeks, bs_price, greeks, implied_vol

S, K, T, R, Q, V = 100.0, 100.0, 1.0, 0.05, 0.0, 0.20


def test_textbook_values():
    assert bs_price("CE", S, K, T, R, Q, V) == pytest.approx(10.4506, abs=5e-4)
    assert bs_price("PE", S, K, T, R, Q, V) == pytest.approx(5.5735, abs=5e-4)
    assert greeks("CE", S, K, T, R, Q, V).delta == pytest.approx(0.6368, abs=5e-4)


@pytest.mark.parametrize("spot,strike,t,q", itertools.product([80, 100, 125], [90, 100, 120], [0.05, 0.5, 2.0], [0.0, 0.013]))
def test_put_call_parity_with_dividends(spot, strike, t, q):
    call = bs_price("CE", spot, strike, t, R, q, V)
    put = bs_price("PE", spot, strike, t, R, q, V)
    assert call - put == pytest.approx(spot * math.exp(-q * t) - strike * math.exp(-R * t), abs=1e-9)


@pytest.mark.parametrize("kind", ["CE", "PE"])
@pytest.mark.parametrize("strike", [85, 100, 115])
@pytest.mark.parametrize("t", [0.02, 0.25, 1.5])
@pytest.mark.parametrize("vol", [0.08, 0.2, 0.6])
def test_implied_vol_round_trip(kind, strike, t, vol):
    price = bs_price(kind, 100, strike, t, R, 0.013, vol)
    time_value = price - bs_price(kind, 100, strike, t, R, 0.013, 0.0)
    if time_value < 1e-6:  # deep in the money: the price carries no information about volatility
        pytest.skip("price is indistinguishable from the forward intrinsic value")
    assert implied_vol(kind, price, 100, strike, t, R, 0.013) == pytest.approx(vol, abs=1e-5)


def test_implied_vol_is_none_below_intrinsic_and_above_any_vol():
    assert implied_vol("CE", 10.0, 120, 100, 0.5, R, Q) is None  # intrinsic is about 22.5
    assert implied_vol("CE", 119.9, 120, 100, 0.5, R, Q) is None  # above the price at 500% vol
    assert implied_vol("PE", 0.0, 100, 100, 0.5, R, Q) is None
    assert implied_vol("PE", -1.0, 100, 100, 0.5, R, Q) is None


def test_implied_vol_is_none_at_or_after_expiry():
    assert implied_vol("CE", 5.0, 105, 100, 0.0, R, Q) is None
    assert implied_vol("CE", 5.0, 105, 100, -0.1, R, Q) is None


def test_at_expiry_the_price_is_intrinsic():
    assert bs_price("CE", 105, 100, 0.0, R, Q, V) == 5.0
    assert bs_price("PE", 105, 100, 0.0, R, Q, V) == 0.0
    assert bs_price("PE", 95, 100, 0.0, R, Q, V) == 5.0


def test_zero_volatility_is_the_discounted_forward_intrinsic():
    expected = max(S - K * math.exp(-R * T), 0.0)
    assert bs_price("CE", S, K, T, R, Q, 0.0) == pytest.approx(expected)


def test_deep_out_of_the_money_is_tiny_and_finite():
    price = bs_price("CE", 100, 1000, 0.01, R, Q, V)
    assert 0.0 <= price < 1e-12 and math.isfinite(price)
    g = greeks("CE", 100, 1000, 0.01, R, Q, V)
    assert all(math.isfinite(x) for x in (g.delta, g.gamma, g.theta_per_day, g.vega_per_vol_point))


def test_long_atm_options_lose_value_with_time():
    assert greeks("CE", S, K, T, R, Q, V).theta_per_day < 0
    assert greeks("PE", S, K, T, R, Q, V).theta_per_day < 0


def test_put_delta_is_call_delta_minus_one_when_no_dividend():
    call = greeks("CE", S, K, T, R, Q, V).delta
    put = greeks("PE", S, K, T, R, Q, V).delta
    assert put == pytest.approx(call - 1.0)


@pytest.mark.parametrize("kind", ["CE", "PE"])
def test_greeks_match_finite_differences(kind):
    q = 0.013
    g = greeks(kind, S, 105, 0.4, R, q, V)
    h = 0.01
    up, mid, down = (bs_price(kind, S + d, 105, 0.4, R, q, V) for d in (h, 0, -h))
    assert g.delta == pytest.approx((up - down) / (2 * h), rel=1e-4)
    assert g.gamma == pytest.approx((up - 2 * mid + down) / h**2, rel=1e-3)
    dv = 1e-4
    vega = (bs_price(kind, S, 105, 0.4, R, q, V + dv) - bs_price(kind, S, 105, 0.4, R, q, V - dv)) / (2 * dv)
    assert g.vega_per_vol_point == pytest.approx(vega / 100, rel=1e-4)
    dt = 1e-5
    theta_year = -(bs_price(kind, S, 105, 0.4 + dt, R, q, V) - bs_price(kind, S, 105, 0.4 - dt, R, q, V)) / (2 * dt)
    assert g.theta_per_day == pytest.approx(theta_year / 365, rel=1e-3)


def test_greeks_at_expiry_are_step_and_zero():
    assert greeks("CE", 105, 100, 0.0, R, Q, V) == Greeks(delta=1.0, gamma=0.0, theta_per_day=0.0, vega_per_vol_point=0.0)
    assert greeks("PE", 105, 100, 0.0, R, Q, V).delta == 0.0
    assert greeks("PE", 95, 100, 0.0, R, Q, V).delta == -1.0


@pytest.mark.parametrize(
    "args",
    [("XX", S, K, T, R, Q, V), ("CE", 0.0, K, T, R, Q, V), ("CE", S, -1.0, T, R, Q, V), ("CE", S, K, T, R, Q, -0.1), ("CE", S, K, -1.0, R, Q, V)],
)
def test_invalid_inputs_raise(args):
    with pytest.raises(ValueError):
        bs_price(*args)


def test_implied_vol_is_none_when_the_price_is_only_intrinsic():
    deep = bs_price("CE", 100, 85, 0.02, R, 0.013, 0.08)
    assert deep == pytest.approx(bs_price("CE", 100, 85, 0.02, R, 0.013, 0.0), abs=1e-9)
    assert implied_vol("CE", deep, 100, 85, 0.02, R, 0.013) is None
