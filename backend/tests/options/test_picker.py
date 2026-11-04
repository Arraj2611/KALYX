from dataclasses import replace
from datetime import date, datetime, timezone

import pytest

from app.brokers.base import Instrument
from app.options.contracts import ChainRow, OptionContract, OptionQuote, contracts_from_instruments
from app.options.greeks import bs_price
from app.options.picker import PickRules, Pick, Rejection, pick_contract

SPOT, VOL, RATE, DIV = 24500.0, 0.15, 0.065, 0.013
NOW = datetime(2026, 11, 4, 4, 30, tzinfo=timezone.utc)  # Wednesday 10:00 IST
EXPIRIES = [date(2026, 11, 4), date(2026, 11, 10), date(2026, 11, 17), date(2026, 11, 26)]
STRIKES = list(range(23500, 25600, 100))


def years_to(expiry):
    close = datetime(expiry.year, expiry.month, expiry.day, 10, 0, tzinfo=timezone.utc)  # 15:30 IST
    return max((close - NOW).total_seconds(), 60.0) / (365 * 86400)


def row(kind, strike, expiry, spread_pct=1.0, bid_override=None, oi=50_000, volume=5_000):
    mid = bs_price(kind, SPOT, strike, years_to(expiry), RATE, DIV, VOL)
    half = mid * spread_pct / 200
    bid = max(mid - half, 0.05) if bid_override is None else bid_override
    contract = OptionContract("NIFTY", kind, float(strike), expiry, 75, f"NIFTY{expiry:%y%m%d}{strike}{kind}", "NFO")
    return ChainRow(contract, OptionQuote(bid=bid, ask=mid + half, ltp=mid, open_interest=oi, volume=volume))


def chain(expiries=EXPIRIES, **kw):
    return [row(kind, k, e, **kw) for e in expiries for k in STRIKES for kind in ("CE", "PE")]


def pick(rows, direction="UP", horizon=2.0, rules=None):
    return pick_contract(rows, direction, SPOT, NOW, horizon, rules or PickRules(), RATE, DIV)


def test_up_picks_a_call_near_the_target_delta():
    result = pick(chain())
    assert isinstance(result, Pick)
    assert result.contract.kind == "CE" and 0.30 <= result.delta <= 0.55
    assert abs(result.delta - 0.40) < 0.06
    assert result.entry_price > 0 and result.iv == pytest.approx(VOL, abs=0.01)


def test_down_picks_a_put():
    result = pick(chain(), direction="DOWN")
    assert result.contract.kind == "PE" and -0.55 <= result.delta <= -0.30


def test_an_expiry_shorter_than_the_horizon_is_skipped():
    result = pick(chain(), horizon=10.0)
    assert result.contract.expiry >= date(2026, 11, 17)


def test_expiry_day_is_excluded_unless_allowed():
    same_day = chain(expiries=[date(2026, 11, 4)])
    rejected = pick(same_day, horizon=0.1)
    assert isinstance(rejected, Rejection) and rejected.reason == "expiry_too_close"
    allowed = pick(same_day, horizon=0.1, rules=PickRules(allow_expiry_day=True))
    assert isinstance(allowed, Pick)


def test_a_contract_that_expires_before_the_horizon_ends_is_rejected_even_when_expiry_day_is_allowed():
    result = pick(chain(expiries=[date(2026, 11, 4)]), horizon=3.0, rules=PickRules(allow_expiry_day=True))
    assert isinstance(result, Rejection) and result.reason == "expiry_too_close"


def test_wide_spreads_are_excluded():
    result = pick(chain(spread_pct=25.0))
    assert isinstance(result, Rejection) and result.reason == "spread_too_wide"


def test_low_open_interest_and_volume_are_excluded():
    assert pick(chain(oi=10)).reason == "no_liquid_contract"
    assert pick(chain(volume=1)).reason == "no_liquid_contract"


def test_a_zero_bid_is_excluded_and_never_divided_by():
    result = pick(chain(bid_override=0.0))
    assert isinstance(result, Rejection) and result.reason == "no_usable_quote"


def test_an_empty_chain_is_rejected():
    assert pick([]).reason == "empty_chain"


def test_a_chain_with_only_the_wrong_side_is_rejected():
    calls_only = [r for r in chain() if r.contract.kind == "CE"]
    assert pick(calls_only, direction="DOWN").reason == "empty_chain"


def test_a_rejection_says_how_far_each_stage_got():
    result = pick(chain(oi=10))
    assert result.detail["considered"] > 0 and result.detail["after_expiry"] > 0
    assert result.detail["after_liquidity"] == 0


def test_the_delta_band_can_exclude_everything():
    far_otm = [row("CE", strike, expiry) for expiry in EXPIRIES[1:] for strike in (25400, 25500)]
    result = pick(far_otm)
    assert isinstance(result, Rejection) and result.reason == "no_contract_in_delta_band"
    assert result.detail["after_spread"] > 0 and result.detail["after_delta"] == 0


def test_the_pick_does_not_depend_on_row_order():
    rows = chain()
    assert pick(rows).contract == pick(list(reversed(rows))).contract


def test_exact_ties_break_on_the_symbol():
    rows = chain(expiries=[date(2026, 11, 10)])
    twins = [replace(r, contract=replace(r.contract, symbol="Z" + r.contract.symbol)) for r in rows]
    assert not pick(rows + twins).contract.symbol.startswith("Z")
    assert not pick(twins + rows).contract.symbol.startswith("Z")


def test_naive_time_and_bad_inputs_raise():
    with pytest.raises(ValueError):
        pick_contract(chain(), "UP", SPOT, datetime(2026, 11, 4, 10), 2.0, PickRules())
    with pytest.raises(ValueError):
        pick(chain(), horizon=0)
    with pytest.raises(ValueError):
        pick(chain(), direction="SIDEWAYS")
    with pytest.raises(ValueError):
        pick_contract(chain(), "UP", 0.0, NOW, 2.0, PickRules())


def instrument(symbol, kind="CE", expiry="2026-11-26", strike=24500.0, lot=75):
    return Instrument(symbol, "NFO", "NFO-OPT", kind, lot, 0.05, "zerodha", expiry=expiry, strike=strike)


def test_contracts_come_from_the_instrument_list():
    found = contracts_from_instruments(
        [
            instrument("NIFTY26NOV24500CE"),
            instrument("NIFTY26NOV24500PE", kind="PE"),
            instrument("NIFTY2611324500CE", expiry="2026-11-13"),  # weekly naming
            instrument("BANKNIFTY26NOV52000CE"),
            instrument("NIFTYNXT5026NOV70000CE"),
            instrument("NIFTY26NOVFUT", kind="FUT", strike=None),
            instrument("NIFTY26NOV99999CE", strike=None),
            instrument("NIFTY26NOV24600CE", expiry="soon"),
        ],
        "NIFTY",
    )
    assert sorted(c.symbol for c in found) == ["NIFTY2611324500CE", "NIFTY26NOV24500CE", "NIFTY26NOV24500PE"]
    first = next(c for c in found if c.symbol == "NIFTY26NOV24500CE")
    assert (first.kind, first.strike, first.expiry, first.lot_size, first.exchange) == ("CE", 24500.0, date(2026, 11, 26), 75, "NFO")
