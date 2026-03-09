"""
rss.py — RSS 2.0 / Atom feed fetcher

Handles both RSS 2.0 and Atom 1.0.
No external deps beyond the stdlib xml.etree.ElementTree + requests.

DEFAULT_FEEDS covers high-value public feeds for Polymarket-relevant categories:
  • US politics / government
  • Central banks / macro
  • Courts / regulation
  • Crypto / DeFi
  • Wire services

Add custom feeds via the caller or news_sources.json.
"""
import hashlib
import logging
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from urllib.parse import urlparse
from xml.etree import ElementTree as ET

import requests

log = logging.getLogger(__name__)

_TIMEOUT = 15
_ATOM = "http://www.w3.org/2005/Atom"

# ---------------------------------------------------------------------------
# Default high-value RSS feeds for Polymarket signal hunting
# ---------------------------------------------------------------------------
DEFAULT_FEEDS: list[dict] = [
    # --- US Government / Official ---
    {"url": "https://www.whitehouse.gov/feed/", "label": "White House", "trust": 0.95},
    {"url": "https://www.sec.gov/cgi-bin/browse-edgar?action=getcurrent&type=8-K&dateb=&owner=include&count=20&output=atom", "label": "SEC 8-K", "trust": 0.90},
    {"url": "https://www.federalreserve.gov/feeds/press_all.xml", "label": "Federal Reserve", "trust": 0.95},
    {"url": "https://www.supremecourt.gov/rss/orders/ordersofthecourt.xml", "label": "SCOTUS Orders", "trust": 0.95},
    {"url": "https://www.justice.gov/feeds/opa/justice-news.xml", "label": "DOJ", "trust": 0.90},
    # --- Wire services ---
    {"url": "https://feeds.reuters.com/reuters/topNews", "label": "Reuters Top", "trust": 0.85},
    {"url": "https://feeds.reuters.com/Reuters/worldNews", "label": "Reuters World", "trust": 0.85},
    {"url": "https://apnews.com/rss/apf-topnews", "label": "AP Top News", "trust": 0.85},
    # --- Politics ---
    {"url": "https://rss.politico.com/politics-news.xml", "label": "Politico", "trust": 0.80},
    {"url": "https://thehill.com/feed/", "label": "The Hill", "trust": 0.75},
    # --- Macro / Finance ---
    {"url": "https://feeds.bloomberg.com/markets/news.rss", "label": "Bloomberg Markets", "trust": 0.85},
    {"url": "https://www.ft.com/?format=rss", "label": "FT", "trust": 0.85},
    # --- Crypto ---
    {"url": "https://www.coindesk.com/arc/outboundfeeds/rss/", "label": "CoinDesk", "trust": 0.72},
    {"url": "https://decrypt.co/feed", "label": "Decrypt", "trust": 0.68},
    {"url": "https://theblock.co/rss.xml", "label": "The Block", "trust": 0.70},
]


def _parse_date(s: str | None) -> float:
    """Parse RFC 2822 or ISO 8601 date → UTC unix timestamp."""
    if not s:
        return time.time()
    # Try RFC 2822 (RSS pubDate)
    try:
        return parsedate_to_datetime(s).timestamp()
    except Exception:
        pass
    # Try ISO 8601 (Atom updated/published)
    for fmt in ("%Y-%m-%dT%H:%M:%SZ", "%Y-%m-%dT%H:%M:%S%z", "%Y-%m-%d"):
        try:
            dt = datetime.strptime(s[:25], fmt)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt.timestamp()
        except Exception:
            continue
    return time.time()


def _text(el: ET.Element | None, *tags: str, ns: str = "") -> str:
    if el is None:
        return ""
    for tag in tags:
        child = el.find(f"{{{ns}}}{tag}" if ns else tag)
        if child is not None and child.text:
            return child.text.strip()
    return ""


def fetch_feed(url: str, label: str, trust: float = 0.6) -> list[dict]:
    """Fetch a single RSS/Atom feed and return story dicts."""
    try:
        resp = requests.get(url, timeout=_TIMEOUT, headers={"User-Agent": "OpenPoly/1.0"})
        resp.raise_for_status()
        xml_text = resp.text
    except Exception as exc:
        log.debug("RSS fetch failed [%s]: %s", label, exc)
        return []

    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError as exc:
        log.debug("RSS parse error [%s]: %s", label, exc)
        return []

    stories: list[dict] = []
    domain = urlparse(url).netloc.lstrip("www.")

    # --- Atom 1.0 ---
    if root.tag == f"{{{_ATOM}}}feed" or "Atom" in root.tag:
        for entry in root.findall(f"{{{_ATOM}}}entry"):
            title = _text(entry, "title", ns=_ATOM)
            link_el = entry.find(f"{{{_ATOM}}}link")
            link = (link_el.get("href") if link_el is not None else "") or ""
            pub = _text(entry, "published", "updated", ns=_ATOM)
            summary = _text(entry, "summary", "content", ns=_ATOM)
            if not title or not link:
                continue
            stories.append({
                "id": "",
                "title": title,
                "url": link,
                "domain": domain,
                "pub_ts": _parse_date(pub),
                "body": summary[:400],
                "source": label,
                "lang": "en",
                "_trust": trust,
            })
        if stories:
            return stories

    # --- RSS 2.0 (also RSS 1.0 / RDF) ---
    for item in root.iter("item"):
        title = _text(item, "title")
        link = _text(item, "link", "guid")
        pub = _text(item, "pubDate", "dc:date", "date")
        desc = _text(item, "description", "summary")
        if not title or not link:
            continue
        # Strip HTML from description
        desc = ET.tostring(ET.fromstring(f"<x>{desc}</x>"), encoding="unicode", method="text") if "<" in desc else desc
        stories.append({
            "id": "",
            "title": title,
            "url": link.strip(),
            "domain": domain,
            "pub_ts": _parse_date(pub),
            "body": desc[:400],
            "source": label,
            "lang": "en",
            "_trust": trust,
        })

    log.debug("RSS[%s] → %d stories", label, len(stories))
    return stories


def fetch_all(feeds: list[dict] | None = None, max_workers: int = 8) -> list[dict]:
    """Fetch all feeds in parallel.

    Args:
        feeds: List of {"url": …, "label": …, "trust": …} dicts.
               Defaults to DEFAULT_FEEDS.
        max_workers: Thread pool size.

    Returns:
        Combined, URL-deduplicated list of story dicts.
    """
    if feeds is None:
        feeds = DEFAULT_FEEDS

    seen_urls: set[str] = set()
    results: list[dict] = []

    with ThreadPoolExecutor(max_workers=max_workers) as ex:
        futures = {
            ex.submit(fetch_feed, f["url"], f.get("label", f["url"]), f.get("trust", 0.6)): f
            for f in feeds
        }
        for fut in as_completed(futures):
            for story in fut.result():
                if story["url"] not in seen_urls:
                    seen_urls.add(story["url"])
                    results.append(story)

    return results
