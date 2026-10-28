from datetime import datetime, timezone

from laya_shadow.headlines import headline_hash, normalize_headline

UTC = timezone.utc


def test_gdelt_seendate_parsed_to_utc():
    title, ts = normalize_headline({"title": "RBI holds rates", "seendate": "20261028T043000Z"})
    assert title == "RBI holds rates"
    assert ts == datetime(2026, 10, 28, 4, 30, tzinfo=UTC)


def test_yfinance_nested_content_title_and_pubdate():
    item = {"content": {"title": "Infosys wins deal", "pubDate": "2026-10-28T04:30:00Z"}}
    title, ts = normalize_headline(item)
    assert title == "Infosys wins deal"
    assert ts == datetime(2026, 10, 28, 4, 30, tzinfo=UTC)


def test_naive_datetime_treated_as_ist():
    title, ts = normalize_headline({"title": "x news", "published_at": datetime(2026, 10, 28, 10, 0)})
    assert ts == datetime(2026, 10, 28, 4, 30, tzinfo=UTC)


def test_epoch_seconds_parsed():
    title, ts = normalize_headline({"title": "TCS results", "providerPublishTime": 1788169009})
    assert ts == datetime.fromtimestamp(1788169009, tz=UTC)


def test_rfc822_pubdate_parsed_to_utc():
    title, ts = normalize_headline({"title": "Tata Motors up", "pubDate": "Wed, 28 Oct 2026 04:55:35 GMT"})
    assert ts == datetime(2026, 10, 28, 4, 55, 35, tzinfo=UTC)


def test_trailing_publisher_suffix_stripped():
    title, _ = normalize_headline(
        {"title": "Reliance profit beats estimates - Economic Times", "source": "Economic Times", "pubDate": "Wed, 28 Oct 2026 04:55:35 GMT"}
    )
    assert title == "Reliance profit beats estimates"


def test_missing_title_returns_none():
    assert normalize_headline({"pubDate": "Wed, 28 Oct 2026 04:55:35 GMT"}) is None


def test_empty_or_non_string_title_returns_none():
    assert normalize_headline({"title": "   ", "seendate": "20261028T043000Z"}) is None
    assert normalize_headline({"title": 123, "seendate": "20261028T043000Z"}) is None
    assert normalize_headline({"title": None, "seendate": "20261028T043000Z"}) is None


def test_missing_publish_time_returns_none():
    assert normalize_headline({"title": "No time here"}) is None
    assert normalize_headline({"title": "Bad time", "pubDate": "not a date"}) is None


def test_hash_ignores_case_and_whitespace():
    assert headline_hash("  Reliance  Q2 Beats ") == headline_hash("reliance q2 beats")
