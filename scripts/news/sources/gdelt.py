"""
gdelt.py — GDELT DOC 2.0 API client (no API key required)

GDELT DOC 2.0 endpoint:
  https://api.gdeltproject.org/api/v2/doc/doc
  ?query=<keywords>&mode=artlist&maxrecords=25&format=json&timespan=15m

timespan values: 15m, 1h, 3h, 6h, 24h, 1w
maxrecords: 1-250

Returns story dicts matching the common schema from news/sources/__init__.py.
GDELT updates its index roughly every 15 minutes; poll interval ≤ 15 min is fine.
"""
import hashlib
import logging
import time
from datetime import datetime, timezone
from urllib.parse import urlparse

import requests

log = logging.getLogger(__name__)

_BASE = "https://api.gdeltproject.org/api/v2/doc/doc"
_TIMEOUT = 20
_MAX_RETRIES = 2


def _parse_gdelt_date(s: str) -> float:
    """GDELT seendate format: YYYYMMDDHHmmSS"""
    try:
        dt = datetime.strptime(s, "%Y%m%d%H%M%S")
        return dt.replace(tzinfo=timezone.utc).timestamp()
    except Exception:
        return time.time()


def fetch(
    query: str,
    timespan: str = "1h",
    maxrecords: int = 50,
    language: str = "English",
) -> list[dict]:
    """Fetch articles from GDELT DOC 2.0 matching *query*.

    Args:
        query:      GDELT query string (supports boolean, e.g. 'Fed AND "rate cut"')
        timespan:   How far back to search.  One of: 15m 1h 3h 6h 12h 24h 1w
        maxrecords: 1–250.
        language:   GDELT language filter (English, Spanish, …) or "" for all.

    Returns:
        List of story dicts (common schema).
    """
    params: dict = {
        "query": query,
        "mode": "artlist",
        "maxrecords": str(maxrecords),
        "format": "json",
        "timespan": timespan,
    }
    if language:
        params["query"] = f"{query} sourcelang:{language.lower()}"

    for attempt in range(_MAX_RETRIES + 1):
        try:
            resp = requests.get(_BASE, params=params, timeout=_TIMEOUT)
            resp.raise_for_status()
            data = resp.json()
            break
        except Exception as exc:
            if attempt == _MAX_RETRIES:
                log.warning("GDELT fetch failed (%s): %s", query, exc)
                return []
            time.sleep(2 ** attempt)

    articles = data.get("articles") or []
    stories: list[dict] = []
    for art in articles:
        url = art.get("url", "")
        title = art.get("title", "").strip()
        if not title or not url:
            continue
        domain = urlparse(url).netloc.lstrip("www.")
        pub_ts = _parse_gdelt_date(art.get("seendate", ""))
        stories.append(
            {
                "id": "",  # filled by normalize layer
                "title": title,
                "url": url,
                "domain": domain,
                "pub_ts": pub_ts,
                "body": "",
                "source": f"gdelt:{query[:30]}",
                "lang": art.get("language", "English")[:2].lower() or "en",
            }
        )
    log.debug("GDELT[%s] → %d stories", query, len(stories))
    return stories


def fetch_multi(queries: list[str], **kwargs) -> list[dict]:
    """Fetch GDELT for multiple queries; deduplicate by URL."""
    seen: set[str] = set()
    results: list[dict] = []
    for q in queries:
        for s in fetch(q, **kwargs):
            if s["url"] not in seen:
                seen.add(s["url"])
                results.append(s)
    return results
