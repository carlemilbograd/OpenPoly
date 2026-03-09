"""
newsapi.py — NewsAPI.org client (requires free API key)

Free tier: 100 requests/day, articles from the past 30 days.
Set NEWSAPI_KEY in .env or pass explicitly.

Endpoint used: GET https://newsapi.org/v2/everything
Docs: https://newsapi.org/docs/endpoints/everything
"""
import logging
import os
import time
from urllib.parse import urlparse

import requests

log = logging.getLogger(__name__)

_BASE = "https://newsapi.org/v2/everything"
_TIMEOUT = 20


def fetch(
    query: str,
    api_key: str | None = None,
    page_size: int = 20,
    sort_by: str = "publishedAt",
    language: str = "en",
) -> list[dict]:
    """Fetch articles from NewsAPI matching *query*.

    Args:
        query:     Boolean keyword string (e.g. 'Fed "rate cut"')
        api_key:   NewsAPI key.  Falls back to NEWSAPI_KEY env var.
        page_size: 1–100.
        sort_by:   "publishedAt" | "relevancy" | "popularity"
        language:  ISO 639-1 code or "" for all.

    Returns:
        List of story dicts (common schema).  Empty if no key available.
    """
    key = api_key or os.environ.get("NEWSAPI_KEY", "")
    if not key:
        log.debug("NEWSAPI_KEY not set — skipping NewsAPI for query: %s", query)
        return []

    params: dict = {
        "q": query,
        "sortBy": sort_by,
        "pageSize": str(page_size),
        "apiKey": key,
    }
    if language:
        params["language"] = language

    try:
        resp = requests.get(_BASE, params=params, timeout=_TIMEOUT)
        resp.raise_for_status()
        data = resp.json()
    except Exception as exc:
        log.warning("NewsAPI fetch failed (%s): %s", query, exc)
        return []

    if data.get("status") != "ok":
        log.warning("NewsAPI error: %s", data.get("message", "unknown"))
        return []

    stories: list[dict] = []
    for art in data.get("articles") or []:
        url = art.get("url", "")
        title = (art.get("title") or "").strip()
        if not title or not url or title == "[Removed]":
            continue
        domain = urlparse(url).netloc.lstrip("www.")
        # publishedAt is ISO 8601: "2024-11-10T14:35:00Z"
        pub_ts: float = time.time()
        try:
            from datetime import datetime, timezone
            pub_ts = datetime.fromisoformat(
                art["publishedAt"].replace("Z", "+00:00")
            ).timestamp()
        except Exception:
            pass

        body = art.get("description") or art.get("content") or ""
        # NewsAPI appends "[+N chars]" to content — strip it
        body = body.split("[+")[0].strip()

        stories.append(
            {
                "id": "",
                "title": title,
                "url": url,
                "domain": domain,
                "pub_ts": pub_ts,
                "body": body,
                "source": f"newsapi:{query[:30]}",
                "lang": language or "en",
            }
        )
    log.debug("NewsAPI[%s] → %d stories", query, len(stories))
    return stories


def fetch_multi(queries: list[str], **kwargs) -> list[dict]:
    """Fetch NewsAPI for multiple queries; deduplicate by URL."""
    seen: set[str] = set()
    results: list[dict] = []
    for q in queries:
        for s in fetch(q, **kwargs):
            if s["url"] not in seen:
                seen.add(s["url"])
                results.append(s)
    return results
