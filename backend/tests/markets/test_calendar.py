from datetime import date, datetime, timezone

import pytest

from app.markets.calendar import MarketCalendar, load_holidays

UTC = timezone.utc
cal = MarketCalendar()


def utc(y, m, d, h, mi=0, s=0):
    return datetime(y, m, d, h, mi, s, tzinfo=UTC)


# 2026-11-04 is a Wednesday. NSE 09:15 IST = 03:45 UTC, 15:30 IST = 10:00 UTC.
def test_nse_is_closed_just_before_0915_and_open_at_0915():
    assert cal.is_open("NSE", utc(2026, 11, 4, 3, 44, 59)) is False
    assert cal.is_open("NSE", utc(2026, 11, 4, 3, 45)) is True


def test_nse_is_open_just_before_1530_and_closed_at_1530():
    assert cal.is_open("NSE", utc(2026, 11, 4, 9, 59, 59)) is True
    assert cal.is_open("NSE", utc(2026, 11, 4, 10, 0)) is False


def test_weekend_is_closed():
    assert cal.is_open("NSE", utc(2026, 11, 7, 5)) is False  # Saturday
    assert cal.is_open("NSE", utc(2026, 11, 8, 5)) is False  # Sunday


def test_listed_holiday_is_closed_and_other_days_are_not():
    calendar = MarketCalendar({"NSE": {date(2026, 11, 4)}})
    assert calendar.is_open("NSE", utc(2026, 11, 4, 5)) is False
    assert calendar.is_open("NSE", utc(2026, 11, 5, 5)) is True
    assert calendar.is_open("NYSE", utc(2026, 11, 4, 15)) is True  # holidays are per exchange


def test_the_exchange_local_date_decides_not_the_utc_date():
    # 2026-11-08 22:00 UTC is already Monday 03:30 in India, but the session has not opened yet
    assert cal.is_open("NSE", utc(2026, 11, 8, 22)) is False
    # 2026-11-09 04:00 UTC is Monday 09:30 IST
    assert cal.is_open("NSE", utc(2026, 11, 9, 4)) is True
    # Friday 22:00 UTC is Saturday 03:30 IST
    assert cal.is_open("NSE", utc(2026, 11, 6, 22)) is False


def test_naive_datetime_is_rejected():
    with pytest.raises(ValueError):
        cal.is_open("NSE", datetime(2026, 11, 4, 5))


def test_nyse_follows_daylight_saving():
    assert cal.is_open("NYSE", utc(2026, 7, 6, 13, 29)) is False  # summer: 09:30 EDT = 13:30 UTC
    assert cal.is_open("NYSE", utc(2026, 7, 6, 13, 30)) is True
    assert cal.is_open("NYSE", utc(2026, 11, 9, 14, 29)) is False  # winter: 09:30 EST = 14:30 UTC
    assert cal.is_open("NYSE", utc(2026, 11, 9, 14, 30)) is True
    assert cal.is_open("NYSE", utc(2026, 11, 9, 20, 59)) is True  # 16:00 EST is 21:00 UTC
    assert cal.is_open("NYSE", utc(2026, 11, 9, 21, 0)) is False


def test_unknown_exchange_raises():
    with pytest.raises(ValueError):
        cal.is_open("LSE", utc(2026, 11, 4, 10))


def test_empty_holiday_file_loads(tmp_path):
    path = tmp_path / "holidays.yaml"
    path.write_text("# nothing filled in\nNSE: []\nNYSE:\n")
    assert load_holidays(str(path)) == {"NSE": set(), "NYSE": set()}


def test_holiday_file_parses_dates(tmp_path):
    path = tmp_path / "holidays.yaml"
    path.write_text('NSE: ["2026-01-26", "2026-08-15"]\n')
    assert load_holidays(str(path)) == {"NSE": {date(2026, 1, 26), date(2026, 8, 15)}}


def test_missing_holiday_file_loads_as_empty(tmp_path):
    assert load_holidays(str(tmp_path / "nope.yaml")) == {}
