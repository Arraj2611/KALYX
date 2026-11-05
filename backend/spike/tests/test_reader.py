import io
import urllib.error

import pypdf
import pytest

import laya_shadow.reader as reader_module
from laya_shadow.reader import ArticleReader, RedirectBlocked, TooLarge, fetch_bytes

ARTICLE_URL = "https://economictimes.indiatimes.com/markets/stocks/news/results.cms"
PDF_URL = "https://nsearchives.nseindia.com/corporate/RELIANCE_outcome.pdf"
ZIP_URL = "https://nsearchives.nseindia.com/corporate/RELIANCE_outcome.zip"
ROBOTS_OPEN = b"User-agent: *\nAllow: /\n"
SENTENCE = "Reliance Industries reported a strong quarter as retail and digital revenue grew in every segment. "
HTML = (
    "<html><head><title>Results</title></head><body><nav>Home Markets News</nav><article><h1>Results</h1>"
    + "".join(f"<p>{SENTENCE * 3}</p>" for _ in range(4))
    + "</article></body></html>"
).encode()


def pdf_with_text(text: str) -> bytes:
    stream = f"BT /F1 10 Tf 40 720 Td ({text}) Tj ET".encode()
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Contents 4 0 R "
        b"/Resources << /Font << /F1 5 0 R >> >> >>",
        b"<< /Length %d >>\nstream\n%s\nendstream" % (len(stream), stream),
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
    ]
    out, offsets = b"%PDF-1.4\n", []
    for number, body in enumerate(objects, 1):
        offsets.append(len(out))
        out += b"%d 0 obj\n%s\nendobj\n" % (number, body)
    start = len(out)
    out += b"xref\n0 %d\n0000000000 65535 f \n" % (len(objects) + 1)
    out += b"".join(b"%010d 00000 n \n" % offset for offset in offsets)
    return out + b"trailer\n<< /Size %d /Root 1 0 R >>\nstartxref\n%d\n%%%%EOF" % (len(objects) + 1, start)


def blank_pdf() -> bytes:
    writer = pypdf.PdfWriter()
    writer.add_blank_page(width=612, height=792)
    buffer = io.BytesIO()
    writer.write(buffer)
    return buffer.getvalue()


def make_reader(pages, robots=ROBOTS_OPEN):
    fetched = []

    def fetch(url, max_bytes):
        fetched.append(url)
        if url.endswith("/robots.txt"):
            if isinstance(robots, Exception):
                raise robots
            return robots
        value = pages[url]
        if isinstance(value, Exception):
            raise value
        return value

    reader = ArticleReader(fetch=fetch, sleep=lambda _: None)
    reader.fetched = fetched
    return reader


def http_error(code):
    return urllib.error.HTTPError("https://x", code, "nope", {}, None)


def test_html_article_body_extracted_without_page_furniture():
    result = make_reader({ARTICLE_URL: HTML}).read(ARTICLE_URL)
    assert result.status == "ok"
    assert "Reliance Industries reported" in result.text
    assert "Home Markets News" not in result.text


def test_pdf_filing_text_extracted():
    result = make_reader({PDF_URL: pdf_with_text("Board approved results " * 12)}).read(PDF_URL)
    assert result.status == "ok" and "Board approved results" in result.text


def test_scanned_pdf_reports_no_text():
    result = make_reader({PDF_URL: blank_pdf()}).read(PDF_URL)
    assert result.status == "no_text" and result.text == ""


def test_zip_filing_is_unsupported_and_not_downloaded():
    reader = make_reader({})
    assert reader.read(ZIP_URL).status == "unsupported"
    assert reader.fetched == []


def test_host_outside_allowlist_blocked_without_any_fetch():
    reader = make_reader({})
    assert reader.read("https://evil.example.com/a").status == "blocked"
    assert reader.fetched == []


def test_plain_http_blocked():
    assert make_reader({}).read(ARTICLE_URL.replace("https", "http")).status == "blocked"


@pytest.mark.parametrize("code", [401, 402, 403, 451])
def test_refusal_status_reports_blocked(code):
    assert make_reader({ARTICLE_URL: http_error(code)}).read(ARTICLE_URL).status == "blocked"


def test_server_error_reports_failed():
    assert make_reader({ARTICLE_URL: http_error(500)}).read(ARTICLE_URL).status == "failed"


def test_network_error_reports_failed():
    assert make_reader({ARTICLE_URL: OSError("timed out")}).read(ARTICLE_URL).status == "failed"


def test_oversized_document_reports_too_large():
    assert make_reader({ARTICLE_URL: TooLarge("big")}).read(ARTICLE_URL).status == "too_large"


def test_unparseable_pdf_reports_failed():
    assert make_reader({PDF_URL: b"this is not a pdf"}).read(PDF_URL).status == "failed"


def test_short_extract_reports_no_text():
    page = b"<html><body><p>Subscribe to read.</p></body></html>"
    assert make_reader({ARTICLE_URL: page}).read(ARTICLE_URL).status == "no_text"


def test_robots_disallow_blocks_without_fetching_article():
    reader = make_reader({ARTICLE_URL: HTML}, robots=b"User-agent: *\nDisallow: /markets/\n")
    assert reader.read(ARTICLE_URL).status == "blocked"
    assert ARTICLE_URL not in reader.fetched


def test_robots_refusing_ai_agents_blocks_us_too():
    reader = make_reader({ARTICLE_URL: HTML}, robots=b"User-agent: GPTBot\nDisallow: /\n\nUser-agent: *\nAllow: /\n")
    assert reader.read(ARTICLE_URL).status == "blocked"


def test_missing_robots_file_allows_reading():
    reader = make_reader({PDF_URL: pdf_with_text("Board approved results " * 12)}, robots=http_error(404))
    assert reader.read(PDF_URL).status == "ok"


def test_robots_read_once_per_host():
    other = ARTICLE_URL.replace("results", "other")
    reader = make_reader({ARTICLE_URL: HTML, other: HTML})
    reader.read(ARTICLE_URL)
    reader.read(other)
    assert sum(url.endswith("/robots.txt") for url in reader.fetched) == 1


class FakeResponse:
    def __init__(self, body, final_url):
        self.body, self.final_url = body, final_url

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def read(self, size):
        return self.body[:size]

    def geturl(self):
        return self.final_url


def test_fetch_bytes_rejects_body_over_cap(monkeypatch):
    monkeypatch.setattr(reader_module.urllib.request, "urlopen", lambda *a, **k: FakeResponse(b"x" * 11, ARTICLE_URL))
    with pytest.raises(TooLarge):
        fetch_bytes(ARTICLE_URL, 10)


def test_fetch_bytes_rejects_redirect_off_allowlist(monkeypatch):
    monkeypatch.setattr(
        reader_module.urllib.request, "urlopen", lambda *a, **k: FakeResponse(b"ok", "https://evil.example.com/x")
    )
    with pytest.raises(RedirectBlocked):
        fetch_bytes(ARTICLE_URL, 10)


def test_fetch_bytes_sends_honest_user_agent(monkeypatch):
    seen = {}

    def urlopen(request, timeout):
        seen["agent"] = request.get_header("User-agent")
        return FakeResponse(b"ok", ARTICLE_URL)

    monkeypatch.setattr(reader_module.urllib.request, "urlopen", urlopen)
    assert fetch_bytes(ARTICLE_URL, 10) == b"ok"
    assert seen["agent"].startswith("KALYX-research") and "Mozilla" not in seen["agent"]
