"""
mapper.py — Layer 3: map a news story to one or more Polymarket markets

Strategy:
  1. Extract keywords from story title + body
  2. Search Gamma API using best keyword(s)
  3. Score each returned market on keyword overlap + category match
  4. Return top matches above min_relevance threshold

The mapper is CLOB-unauthenticated — it only reads from Gamma API.
"""
from __future__ import annotations

import logging
import re
import time
from urllib.parse import urlparse

import requests

log = logging.getLogger(__name__)

_GAMMA = "https://gamma-api.polymarket.com"
_TIMEOUT = 20

# ---------------------------------------------------------------------------
# Category / tag keywords → Polymarket tags  (used to narrow API search)
# ---------------------------------------------------------------------------
_TAG_MAP: dict[str, list[str]] = {
    "politics": ["federal reserve", "interest rate", "rate cut", "rate hike",
                 "election", "president", "congress", "senate", "vote",
                 "democrat", "republican", "biden", "trump", "harris",
                 "supreme court", "scotus"],
    "crypto":   ["bitcoin", "btc", "ethereum", "eth", "crypto", "blockchain",
                 "sec crypto", "defi", "coinbase", "binance"],
    "finance":  ["gdp", "inflation", "cpi", "pce", "unemployment", "jobs",
                 "earnings", "ipo", "merger", "acquisition", "fed", "fomc",
                 "treasury", "yield", "recession"],
    "sports":   ["nba", "nfl", "mlb", "nhl", "world cup", "olympics",
                 "championship", "super bowl", "final"],
    "geopolitics": ["ukraine", "russia", "china", "taiwan", "nato", "iran",
                    "north korea", "israel", "gaza", "war", "sanctions"],
}

_STOPWORDS = frozenset(
    "a an the and or but in on at to for of with by from is are was were "
    "be been being have has had do does did will would could should may "
    "might can must this that these those it its says said report reports "
    "new latest breaking update after following amid over as".split()
)


def _extract_keywords(story: dict, top_n: int = 5) -> list[str]:
    """Extract the most meaningful keywords from title + body."""
    text = f"{story.get('title', '')} {story.get('body', '')}".lower()
    text = re.sub(r"[^\w\s]", " ", text)
    words = [w for w in text.split() if len(w) > 3 and w not in _STOPWORDS]
    # Score by frequency * length (longer words tend to be more specific)
    freq: dict[str, int] = {}
    for w in words:
        freq[w] = freq.get(w, 0) + 1
    scored = sorted(freq.items(), key=lambda x: x[1] * len(x[0]), reverse=True)
    return [w for w, _ in scored[:top_n]]


def _fetch_markets(query: str, limit: int = 30) -> list[dict]:
    """Search Gamma API for active markets matching *query*."""
    try:
        params = {
            "active": "true",
            "closed": "false",
            "limit": str(limit),
            "search": query,
        }
        resp = requests.get(f"{_GAMMA}/markets", params=params, timeout=_TIMEOUT)
        resp.raise_for_status()
        return resp.json() if isinstance(resp.json(), list) else []
    except Exception as exc:
        log.debug("Gamma search failed (%s): %s", query, exc)
        return []


def _token_overlap(text_a: str, text_b: str) -> float:
    """Normalised token overlap between two strings."""
    a = frozenset(re.sub(r"[^\w\s]", " ", text_a.lower()).split()) - _STOPWORDS
    b = frozenset(re.sub(r"[^\w\s]", " ", text_b.lower()).split()) - _STOPWORDS
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


def _relevance(story: dict, market: dict) -> float:
    """Compute 0..1 relevance of a market to a story."""
    question = market.get("question", market.get("title", ""))
    event_title = market.get("groupItemTitle", "")
    tags = " ".join(t.get("label", "") if isinstance(t, dict) else str(t)
                    for t in (market.get("tags") or []))

    combined_market = f"{question} {event_title} {tags}"

    story_text = f"{story.get('title', '')} {story.get('body', '')}"

    return _token_overlap(story_text, combined_market)


def map_story(
    story: dict,
    min_relevance: float = 0.15,
    top_k: int = 5,
    fetch_limit: int = 30,
) -> list[dict]:
    """Map a story to the most relevant active Polymarket markets.

    Args:
        story:         Normalised story dict.
        min_relevance: Minimum token-overlap score to include a market.
        top_k:         Maximum number of markets to return.
        fetch_limit:   How many Gamma API results to retrieve per keyword.

    Returns:
        List of dicts with keys: market (full Gamma dict) + relevance (float).
        Sorted by relevance descending.
    """
    keywords = _extract_keywords(story)
    if not keywords:
        return []

    # Build search query: use top 2–3 keywords
    query = " ".join(keywords[:3])

    seen_ids: set[str] = set()
    candidates: list[dict] = []

    for market in _fetch_markets(query, limit=fetch_limit):
        mid = market.get("id", market.get("conditionId", ""))
        if mid in seen_ids:
            continue
        seen_ids.add(mid)
        rel = _relevance(story, market)
        if rel >= min_relevance:
            candidates.append({"market": market, "relevance": rel})

    # If few results, try individual keywords
    if len(candidates) < 3 and len(keywords) > 1:
        for kw in keywords[1:3]:
            for market in _fetch_markets(kw, limit=fetch_limit):
                mid = market.get("id", market.get("conditionId", ""))
                if mid in seen_ids:
                    continue
                seen_ids.add(mid)
                rel = _relevance(story, market)
                if rel >= min_relevance:
                    candidates.append({"market": market, "relevance": rel})

    candidates.sort(key=lambda x: x["relevance"], reverse=True)
    return candidates[:top_k]
