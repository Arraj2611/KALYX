"""Find which in-scope companies an item is about."""
import re
from typing import Optional


def _company_key(name: str) -> str:
    key = re.sub(r"\s+(limited|ltd\.?)$", "", name.strip(), flags=re.IGNORECASE).lower()
    return " ".join(key.replace(" and ", " & ").replace(".", " ").split())


class SymbolMatcher:
    """Case-sensitive alias matching on titles, longest alias first so "SBI Life" is never read as "SBI"."""

    def __init__(self, entries: list[dict]) -> None:
        pairs = [(alias, entry["symbol"]) for entry in entries for alias in entry.get("aliases") or entry["keywords"]]
        pairs.sort(key=lambda pair: -len(pair[0]))
        self._patterns = [(re.compile(rf"(?<![\w&]){re.escape(alias)}(?![\w&])"), symbol) for alias, symbol in pairs]
        self._companies = {_company_key(entry["keywords"][0]): entry["symbol"] for entry in entries}

    def in_title(self, title: str) -> list[str]:
        found: list[str] = []
        remaining = title
        for pattern, symbol in self._patterns:
            if pattern.search(remaining):
                remaining = pattern.sub(" ", remaining)
                if symbol not in found:
                    found.append(symbol)
        return found

    def company(self, name: str) -> Optional[str]:
        return self._companies.get(_company_key(name))
