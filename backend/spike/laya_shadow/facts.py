"""Pull hard numbers out of a document. This is all that is kept of publisher text."""
import re

MAX_FACTS = 12
_CONTEXT_CHARS = 40
_NUMBER = r"\d[\d,]*(?:\.\d+)?"
_MONEY = rf"(?:Rs\.?|INR|₹|US\$|\$|€|£)\s?{_NUMBER}(?:\s?(?:crore|cr|lakh|mn|million|bn|billion|trillion)\b)?"
_RATE = rf"{_NUMBER}\s?(?:%|(?:per cent|percent|bps|basis points)\b)"
_SCALED = rf"{_NUMBER}\s(?:crore|lakh|million|billion|trillion)\b"
_FACT = re.compile(rf"{_MONEY}|{_RATE}|{_SCALED}", re.IGNORECASE)


def extract_facts(text: str) -> list[dict]:
    """[{"value": "Rs 5,000 crore", "context": "...few words either side..."}], first mention of each value."""
    facts: list[dict] = []
    seen: set[str] = set()
    for match in _FACT.finditer(text):
        value = match.group(0)
        if value.lower() in seen:
            continue
        seen.add(value.lower())
        context = " ".join(text[max(0, match.start() - _CONTEXT_CHARS) : match.end() + _CONTEXT_CHARS].split())
        facts.append({"value": value, "context": context})
        if len(facts) == MAX_FACTS:
            break
    return facts
