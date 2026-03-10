"""
Tests for scripts/news/sources/rss.py

These tests are fully offline — no network calls.
"""
import sys, types, time
from pathlib import Path

# ── Stub out `requests` before importing rss so no real network calls happen
requests_stub = types.ModuleType("requests")
class _Resp:
    ok = False
    status_code = 503
    content = b""
    text = ""
    def raise_for_status(self): raise Exception("stubbed")
requests_stub.get = lambda *a, **kw: _Resp()
sys.modules.setdefault("requests", requests_stub)

sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))
from news.sources.rss import _strip_html, _parse_date, fetch_feed


# ── _strip_html ────────────────────────────────────────────────────────────────

def test_strip_html_plain():
    assert _strip_html("hello world") == "hello world"

def test_strip_html_removes_tags():
    result = _strip_html("<p>Hello <b>world</b></p>")
    assert "<" not in result
    assert "Hello" in result
    assert "world" in result

def test_strip_html_unescapes_entities():
    result = _strip_html("AT&amp;T earns &lt;$1B&gt;")
    assert "&amp;" not in result
    assert "AT&T" in result

def test_strip_html_nbsp():
    result = _strip_html("hello&nbsp;world")
    assert "&nbsp;" not in result
    assert "hello" in result and "world" in result

def test_strip_html_br_and_p():
    result = _strip_html("<p>Line 1</p><br/><p>Line 2</p>")
    assert "Line 1" in result
    assert "Line 2" in result
    assert "<" not in result

def test_strip_html_empty():
    assert _strip_html("") == ""

def test_strip_html_script_tag():
    result = _strip_html('<script>alert("xss")</script>actual content')
    assert "actual content" in result
    # script content may or may not remain; the tag itself must be gone
    assert "<script>" not in result

def test_strip_html_nested_entities():
    result = _strip_html("&lt;b&gt;bold&lt;/b&gt;")
    assert "&lt;" not in result

def test_strip_html_numeric_entity():
    result = _strip_html("caf&#233;")
    assert "&#233;" not in result


# ── _parse_date ────────────────────────────────────────────────────────────────

def test_parse_date_none_returns_recent():
    ts = _parse_date(None)
    assert abs(ts - time.time()) < 5

def test_parse_date_rfc2822():
    ts = _parse_date("Mon, 01 Jan 2024 12:00:00 GMT")
    assert 1704000000 < ts < 1704200000

def test_parse_date_iso8601_z():
    ts = _parse_date("2024-06-15T08:30:00Z")
    assert 1718000000 < ts < 1719000000

def test_parse_date_iso8601_offset():
    ts = _parse_date("2024-06-15T08:30:00+02:00")
    assert 1718000000 < ts < 1719000000

def test_parse_date_date_only():
    ts = _parse_date("2024-01-01")
    assert ts > 1700000000

def test_parse_date_garbage_returns_recent():
    ts = _parse_date("not a date at all!!")
    assert abs(ts - time.time()) < 5


# ── fetch_feed (offline: parse XML directly) ──────────────────────────────────

def _make_rss(items: list[tuple[str, str, str]]) -> bytes:
    """Build a minimal RSS 2.0 feed from (title, link, desc) tuples."""
    items_xml = ""
    for title, link, desc in items:
        items_xml += f"""
        <item>
            <title>{title}</title>
            <link>{link}</link>
            <description>{desc}</description>
            <pubDate>Mon, 10 Mar 2026 12:00:00 GMT</pubDate>
        </item>"""
    return f"""<?xml version="1.0" encoding="UTF-8"?>
    <rss version="2.0"><channel>
        <title>Test Feed</title>{items_xml}
    </channel></rss>""".encode()


def _make_atom(entries: list[tuple[str, str, str]]) -> bytes:
    """Build a minimal Atom feed from (title, link, summary) tuples."""
    entries_xml = ""
    for title, link, summary in entries:
        entries_xml += f"""
        <entry xmlns="http://www.w3.org/2005/Atom">
            <title>{title}</title>
            <link href="{link}"/>
            <published>2026-03-10T12:00:00Z</published>
            <summary>{summary}</summary>
        </entry>"""
    return f"""<?xml version="1.0" encoding="UTF-8"?>
    <feed xmlns="http://www.w3.org/2005/Atom">
        <title>Test Atom Feed</title>{entries_xml}
    </feed>""".encode()


def _fetch_feed_from_bytes(xml_bytes: bytes, label: str = "Test") -> list[dict]:
    """Call fetch_feed but stub requests to return our XML bytes."""
    import requests as _req
    class _FakeResp:
        ok = True
        status_code = 200
        content = xml_bytes
        text = xml_bytes.decode("utf-8", errors="replace")
        def raise_for_status(self): pass
    original_get = _req.get
    _req.get = lambda *a, **kw: _FakeResp()
    try:
        return fetch_feed("http://fake.feed/rss", label)
    finally:
        _req.get = original_get


def test_fetch_feed_rss_basic():
    stories = _fetch_feed_from_bytes(_make_rss([
        ("Trump wins election", "https://example.com/1", "Details here"),
        ("Fed raises rates", "https://example.com/2", "More details"),
    ]))
    assert len(stories) == 2
    titles = [s["title"] for s in stories]
    assert "Trump wins election" in titles
    assert "Fed raises rates" in titles

def test_fetch_feed_rss_html_description():
    stories = _fetch_feed_from_bytes(_make_rss([
        ("Test story", "https://example.com/1", "<p>A <b>bold</b> claim &amp; more</p>"),
    ]))
    assert len(stories) == 1
    body = stories[0]["body"]
    assert "<p>" not in body
    assert "<b>" not in body

def test_fetch_feed_rss_missing_link_skipped():
    xml = b"""<?xml version="1.0"?>
    <rss version="2.0"><channel>
        <item><title>No link</title><description>body</description></item>
        <item><title>Has link</title><link>https://x.com/1</link><description>b</description></item>
    </channel></rss>"""
    stories = _fetch_feed_from_bytes(xml)
    assert len(stories) == 1
    assert stories[0]["title"] == "Has link"

def test_fetch_feed_atom_basic():
    stories = _fetch_feed_from_bytes(_make_atom([
        ("Atom headline", "https://atom.com/1", "Summary text"),
    ]))
    assert len(stories) == 1
    assert stories[0]["title"] == "Atom headline"
    assert stories[0]["url"] == "https://atom.com/1"

def test_fetch_feed_malformed_xml_returns_empty():
    stories = _fetch_feed_from_bytes(b"<not valid xml <<< >>>")
    assert stories == []

def test_fetch_feed_empty_feed_returns_empty():
    stories = _fetch_feed_from_bytes(b"""<?xml version="1.0"?>
    <rss version="2.0"><channel><title>Empty</title></channel></rss>""")
    assert stories == []

def test_fetch_feed_trust_attached():
    stories = _fetch_feed_from_bytes(_make_rss([
        ("Story", "https://example.com/1", "body"),
    ]))
    assert "_trust" in stories[0]
    assert 0.0 <= stories[0]["_trust"] <= 1.0

def test_fetch_feed_source_label_attached():
    stories = _fetch_feed_from_bytes(_make_rss([
        ("Story", "https://example.com/1", "body"),
    ]), label="Reuters Top")
    assert stories[0]["source"] == "Reuters Top"

def test_fetch_feed_network_error_returns_empty(monkeypatch):
    """Network failure must not raise — returns empty list."""
    import requests as _req
    class _ErrResp:
        ok = False
        status_code = 503
        content = b""
        text = ""
        def raise_for_status(self): raise Exception("503")
    monkeypatch.setattr(_req, "get", lambda *a, **kw: _ErrResp())
    stories = fetch_feed("http://bad.url/rss", "Bad Feed")
    assert stories == []
