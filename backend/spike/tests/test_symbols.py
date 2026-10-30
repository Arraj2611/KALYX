import yaml

from laya_shadow.poller import load_symbols
from laya_shadow.symbols import SymbolMatcher

ENTRIES = [
    {"symbol": "RELIANCE", "keywords": ["Reliance Industries"], "aliases": ["Reliance Industries", "RIL"]},
    {"symbol": "TCS", "keywords": ["Tata Consultancy Services"], "aliases": ["TCS"]},
    {"symbol": "SBIN", "keywords": ["State Bank of India"], "aliases": ["State Bank of India", "SBI"]},
    {"symbol": "SBILIFE", "keywords": ["SBI Life Insurance Company"], "aliases": ["SBI Life"]},
    {"symbol": "LT", "keywords": ["Larsen & Toubro"], "aliases": ["Larsen & Toubro", "L&T"]},
    {"symbol": "ITC", "keywords": ["ITC"], "aliases": ["ITC"]},
    {"symbol": "ONGC", "keywords": ["Oil & Natural Gas Corporation"], "aliases": ["ONGC"]},
    {"symbol": "DRREDDY", "keywords": ["Dr. Reddy's Laboratories"], "aliases": ["Dr Reddy's"]},
]
matcher = SymbolMatcher(ENTRIES)


def test_alias_found_in_title():
    assert matcher.in_title("TCS wins $1 billion deal") == ["TCS"]


def test_match_is_case_sensitive():
    assert matcher.in_title("tcs of the town") == []


def test_longest_alias_wins_so_sbi_life_is_not_sbi():
    assert matcher.in_title("SBI Life posts record premium") == ["SBILIFE"]


def test_both_found_when_both_named():
    assert sorted(matcher.in_title("SBI Life and SBI lead gains")) == ["SBILIFE", "SBIN"]


def test_ampersand_alias_found():
    assert matcher.in_title("L&T bags large order") == ["LT"]


def test_no_match_inside_a_longer_word():
    assert matcher.in_title("Pakistan ITCHY rally on TCSL news") == []


def test_possessive_still_matches():
    assert matcher.in_title("Reliance Industries' profit jumps") == ["RELIANCE"]


def test_several_symbols_in_one_title():
    assert sorted(matcher.in_title("RIL, TCS and ITC drag Sensex")) == ["ITC", "RELIANCE", "TCS"]


def test_company_name_found_from_nse_form():
    assert matcher.company("Reliance Industries Limited") == "RELIANCE"
    assert matcher.company("Dr. Reddy's Laboratories Ltd.") == "DRREDDY"


def test_company_name_treats_and_as_ampersand():
    assert matcher.company("Oil And Natural Gas Corporation Limited") == "ONGC"


def test_unknown_company_not_found():
    assert matcher.company("Tempsens Instruments (India) Limited") is None


def test_every_real_symbol_has_aliases_and_none_are_shared():
    entries = load_symbols()
    assert len(entries) == 50
    seen = {}
    for entry in entries:
        assert entry.get("aliases"), entry["symbol"]
        for alias in entry["aliases"]:
            assert alias not in seen, alias
            seen[alias] = entry["symbol"]
