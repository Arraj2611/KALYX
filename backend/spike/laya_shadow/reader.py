"""Read the full text of an article or filing, within what each site allows.

Only allowlisted hosts are fetched, with an honest User-Agent. robots.txt is honoured, including rules
aimed at AI agents, because this text is read by a model. Text is returned for scoring only: callers
must not store it (see Amendment 2 of the spike design).
"""
import io
import logging
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Callable
from urllib.parse import urlsplit
from urllib.robotparser import RobotFileParser

logger = logging.getLogger("laya_shadow.reader")
logging.getLogger("pypdf").setLevel(logging.ERROR)

USER_AGENT = "KALYX-research/0.1 (personal research, low volume)"
AGENT_TOKEN = "KALYX-research"
AI_AGENTS = ("GPTBot", "ClaudeBot")
FILING_HOST = "nsearchives.nseindia.com"
ALLOWED_HOSTS = {
    "economictimes.indiatimes.com",
    "www.livemint.com",
    "www.business-standard.com",
    FILING_HOST,
}
MAX_FEED_BYTES = 5_000_000
MAX_HTML_BYTES = 5_000_000
MAX_PDF_BYTES = 25_000_000
MAX_PDF_PAGES = 40
MIN_TEXT_CHARS = 200
MIN_GAP_S = 1.0
TIMEOUT_S = 30
_REFUSED = {401, 402, 403, 451}


class TooLarge(Exception):
    """The response is bigger than the caller's cap."""


class RedirectBlocked(Exception):
    """A redirect left the allowlisted hosts."""


def fetch_bytes(url: str, max_bytes: int) -> bytes:
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(request, timeout=TIMEOUT_S) as response:
        if urlsplit(response.geturl()).netloc not in ALLOWED_HOSTS:
            raise RedirectBlocked(response.geturl())
        body = response.read(max_bytes + 1)
    if len(body) > max_bytes:
        raise TooLarge(url)
    return body


@dataclass(frozen=True)
class ReadResult:
    """status: ok | blocked | no_text | too_large | unsupported | failed. text is set only when ok."""

    status: str
    text: str = ""


def _html_text(raw: bytes) -> str:
    import trafilatura

    return trafilatura.extract(raw.decode("utf-8", "ignore"), include_comments=False) or ""


def _pdf_text(raw: bytes) -> str:
    import pypdf

    pages = pypdf.PdfReader(io.BytesIO(raw)).pages[:MAX_PDF_PAGES]
    return "\n".join(page.extract_text() or "" for page in pages)


class ArticleReader:
    """One instance per poll pass, so robots.txt changes are picked up."""

    def __init__(self, fetch: Callable[[str, int], bytes] = fetch_bytes, sleep: Callable[[float], None] = time.sleep) -> None:
        self._fetch = fetch
        self._sleep = sleep
        self._robots: dict[str, RobotFileParser] = {}

    def _allowed_by_robots(self, url: str) -> bool:
        host = urlsplit(url).netloc
        if host not in self._robots:
            rules = RobotFileParser()
            try:
                rules.parse(self._fetch(f"https://{host}/robots.txt", MAX_HTML_BYTES).decode("utf-8", "ignore").splitlines())
            except urllib.error.HTTPError as exc:
                if exc.code != 404:
                    raise
                rules.parse([])
            self._robots[host] = rules
        return all(self._robots[host].can_fetch(agent, url) for agent in (AGENT_TOKEN, *AI_AGENTS))

    def read(self, url: str) -> ReadResult:
        parts = urlsplit(url)
        if parts.scheme != "https" or parts.netloc not in ALLOWED_HOSTS:
            return ReadResult("blocked")
        is_pdf = parts.path.lower().endswith(".pdf")
        if parts.netloc == FILING_HOST and not is_pdf:
            return ReadResult("unsupported")
        try:
            if not self._allowed_by_robots(url):
                return ReadResult("blocked")
            self._sleep(MIN_GAP_S)
            raw = self._fetch(url, MAX_PDF_BYTES if is_pdf else MAX_HTML_BYTES)
            text = (_pdf_text(raw) if is_pdf else _html_text(raw)).strip()
        except TooLarge:
            return ReadResult("too_large")
        except urllib.error.HTTPError as exc:
            logger.info("HTTP %s reading %s", exc.code, url)
            return ReadResult("blocked" if exc.code in _REFUSED else "failed")
        except RedirectBlocked:
            return ReadResult("blocked")
        except Exception as exc:  # any bad page or PDF must cost one row's body, never the pass
            logger.warning("could not read %s: %s", url, exc)
            return ReadResult("failed")
        if len(text) < MIN_TEXT_CHARS:
            return ReadResult("no_text")
        return ReadResult("ok", text)
