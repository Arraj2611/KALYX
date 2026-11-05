from laya_shadow.facts import MAX_FACTS, extract_facts


def values(text):
    return [fact["value"] for fact in extract_facts(text)]


def test_rupee_amounts_with_units():
    assert values("Net profit rose to Rs 5,000 crore this quarter") == ["Rs 5,000 crore"]
    assert values("declared a dividend of Rs. 5 per share") == ["Rs. 5"]
    assert values("revenue of ₹1,250.5 crore") == ["₹1,250.5 crore"]


def test_dollar_amounts():
    assert values("won a $1 billion deal") == ["$1 billion"]


def test_percent_and_basis_points():
    assert values("margin fell 240 bps while sales grew 18%") == ["240 bps", "18%"]
    assert values("up 11.5 per cent on year") == ["11.5 per cent"]


def test_plain_numbers_and_dates_are_not_facts():
    assert values("In 2026 the 3 directors met on October 30") == []


def test_repeated_value_kept_once():
    assert values("profit 18% and revenue 18%") == ["18%"]


def test_context_is_short_and_whitespace_collapsed():
    fact = extract_facts("word " * 50 + "grew\n  18%   in the " + "quarter " * 50)[0]
    assert "grew 18% in the" in fact["context"]
    assert len(fact["context"]) <= 100


def test_fact_count_is_capped():
    text = " ".join(f"{n}%" for n in range(1, 100))
    assert len(extract_facts(text)) == MAX_FACTS


def test_empty_text_gives_no_facts():
    assert extract_facts("") == []
