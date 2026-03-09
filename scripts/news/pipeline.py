"""
pipeline.py — Full 4-layer news→signal pipeline

Flow:
  L1  Ingest     sources/gdelt, sources/newsapi, sources/rss
  L2  Normalize  deduplicate, age-filter, trust-weight
  L2b Cluster    group near-identical stories → one representative per event
  L3  Map        story → active Polymarket markets (Gamma API)
  L4  Score      5-factor impact score
      Gate       current market price vs estimated shift; edge > fees + slippage

Returns a list of PipelineResult objects ready for execution or dry-run logging.
"""
from __future__ import annotations

import logging
import os
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path

# Allow imports from parent scripts/ dir when called with -m or directly
sys.path.insert(0, str(Path(__file__).parent.parent))

from news.sources import gdelt as _gdelt
from news.sources import newsapi as _newsapi
from news.sources import rss as _rss
from news import normalize as _norm
from news import cluster as _cluster
from news import mapper as _mapper
from news import score as _score

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Default GDELT / NewsAPI query strings covering Polymarket-relevant topics
# ---------------------------------------------------------------------------
DEFAULT_QUERIES: list[str] = [
    "Federal Reserve interest rate decision",
    "Supreme Court ruling decision",
    "election results president",
    "Bitcoin ETF SEC approval",
    "GDP inflation unemployment report",
    "geopolitical war sanctions",
    "Congress bill signed law",
    "FDA drug approval",
]

# ---------------------------------------------------------------------------
# Probability shift estimation  (keyword → (direction, magnitude))
# Higher magnitude = bigger implied probability move
# ---------------------------------------------------------------------------
_SHIFT_SIGNALS: list[dict] = [
    # Court / regulatory
    {"words": ["ruled", "ruling", "verdict", "convicted", "acquitted"],   "magnitude": 0.30, "bullish": True},
    {"words": ["appealed", "appeal", "overturned"],                        "magnitude": 0.20, "bullish": None},
    # Elections / votes
    {"words": ["elected", "won", "wins", "defeated", "lost"],             "magnitude": 0.40, "bullish": True},
    {"words": ["leads", "ahead", "polling"],                               "magnitude": 0.12, "bullish": True},
    {"words": ["trails", "behind", "losing"],                              "magnitude": 0.12, "bullish": False},
    # Central bank
    {"words": ["rate cut", "cuts rates", "lower rates"],                   "magnitude": 0.25, "bullish": True},
    {"words": ["rate hike", "raises rates", "higher rates"],               "magnitude": 0.25, "bullish": False},
    {"words": ["rate hold", "holds rates", "unchanged"],                   "magnitude": 0.15, "bullish": None},
    # Crypto / SEC
    {"words": ["approves", "approved", "approval"],                        "magnitude": 0.28, "bullish": True},
    {"words": ["rejects", "rejected", "denial", "denied"],                 "magnitude": 0.28, "bullish": False},
    {"words": ["charges", "indicts", "lawsuit"],                           "magnitude": 0.22, "bullish": False},
    # Macro data
    {"words": ["beats", "beat", "exceeds", "stronger than"],               "magnitude": 0.10, "bullish": True},
    {"words": ["misses", "miss", "weaker than", "disappoints"],            "magnitude": 0.10, "bullish": False},
    # Breaking urgency
    {"words": ["breaking", "flash", "just in", "developing"],             "magnitude": 0.05, "bullish": None},
]


def _estimate_shift(story: dict, current_price: float) -> dict | None:
    """Estimate implied probability shift from story text.

    Returns dict with keys: direction (YES/NO), magnitude, target_price
    or None if no recognisable signal found.
    """
    text = (story.get("title", "") + " " + story.get("body", "")).lower()

    best: dict | None = None
    for sig in _SHIFT_SIGNALS:
        for word in sig["words"]:
            if word in text:
                if best is None or sig["magnitude"] > best["magnitude"]:
                    best = sig
                break

    if best is None:
        return None

    if best["bullish"] is True:
        direction = "YES"
        target = min(0.98, current_price + best["magnitude"])
    elif best["bullish"] is False:
        direction = "NO"
        target = max(0.02, current_price - best["magnitude"])
    else:
        # Ambiguous — small default shift toward 0.5
        direction = "YES" if current_price < 0.50 else "NO"
        target = 0.50
    edge = abs(target - current_price)
    return {"direction": direction, "magnitude": best["magnitude"], "target_price": round(target, 3), "edge": round(edge, 3)}


# ---------------------------------------------------------------------------
# PipelineResult
# ---------------------------------------------------------------------------
@dataclass
class PipelineResult:
    story:          dict
    market:         dict
    relevance:      float
    scores:         dict
    shift:          dict | None
    current_price:  float
    edge:           float             # estimated price gap
    actionable:     bool              # edge > min_edge threshold
    reason:         str               # why actionable or not
    # Populated after slippage gate
    sim_result:     object | None = field(default=None, repr=False)


def _get_yes_price(client, token_id: str) -> float | None:
    """Fetch current YES price from CLOB. Returns None on failure."""
    try:
        mp = client.get_midpoint(token_id)
        return float(mp) if mp else None
    except Exception:
        return None


# ---------------------------------------------------------------------------
# Gate: slippage check via execution_simulator
# ---------------------------------------------------------------------------
def _slippage_gate(
    result: PipelineResult,
    usd_size: float,
    client,
    safety_buffer: float = 0.02,
) -> tuple[bool, str]:
    """Return (pass, reason) after checking slippage + fees."""
    try:
        from execution_simulator import simulate_order, is_viable, FEE
    except ImportError:
        return True, "slippage check skipped (execution_simulator not found)"

    direction = result.shift.get("direction", "YES") if result.shift else "YES"
    side = "BUY"  # we always buy the underpriced side
    token_id = result.market.get("clobTokenIds", [None])[0]
    if not token_id:
        return False, "no clobTokenId on market"

    try:
        sim = simulate_order(client, token_id, side, usd_size)
        result.sim_result = sim
        viable, net = is_viable(sim, result.edge, min_net_profit=0.0)
        if not viable:
            return False, f"slippage too high ({sim.slippage_pct:.2%} vs edge {result.edge:.2%})"
        if net < safety_buffer:
            return False, f"net edge {net:.2%} below safety buffer {safety_buffer:.2%}"
        return True, f"slippage ok (net edge {net:.2%})"
    except Exception as exc:
        return True, f"slippage check error ({exc}); proceeding"


# ---------------------------------------------------------------------------
# Main pipeline entry point
# ---------------------------------------------------------------------------
def run_pipeline(
    client=None,
    rss_feeds: list[dict] | None = None,
    gdelt_queries: list[str] | None = None,
    newsapi_key: str | None = None,
    max_age_secs: float = 3600.0,
    seen_ids: set[str] | None = None,
    min_impact: float = 0.15,
    min_relevance: float = 0.15,
    min_edge: float = 0.06,
    budget_per_trade: float = 50.0,
    safety_buffer: float = 0.02,
    skip_slippage: bool = False,
    dry_run: bool = False,
) -> tuple[list[PipelineResult], set[str]]:
    """Run the full news→signal pipeline.

    Args:
        client:           Authenticated or read-only CLOB client (None → use mid from Gamma).
        rss_feeds:        Override list of RSS feed dicts.  None → DEFAULT_FEEDS.
        gdelt_queries:    Override GDELT query list.  None → DEFAULT_QUERIES.
        newsapi_key:      NewsAPI.org API key.  Falls back to NEWSAPI_KEY env var.
        max_age_secs:     Discard stories older than this.
        seen_ids:         Set of already-processed story fingerprints (for dedup).
        min_impact:       Minimum aggregate impact score to proceed to market mapping.
        min_relevance:    Minimum story↔market relevance to include a match.
        min_edge:         Minimum estimated price gap to mark a result actionable.
        budget_per_trade: USD size for slippage simulation.
        safety_buffer:    Extra edge required above fees + slippage.
        skip_slippage:    If True, skip execution_simulator gate.
        dry_run:          If True, mark results actionable but don't actually trade.

    Returns:
        (results, updated_seen_ids)
        results is sorted by edge descending.
    """
    t0 = time.time()
    if seen_ids is None:
        seen_ids = set()

    # ── Layer 1: Ingest ──────────────────────────────────────────────────
    log.info("L1: ingesting news sources …")
    raw: list[dict] = []

    # RSS (always)
    raw += _rss.fetch_all(rss_feeds)

    # GDELT (no API key needed)
    queries = gdelt_queries or DEFAULT_QUERIES
    raw += _gdelt.fetch_multi(queries, timespan="1h", maxrecords=25)

    # NewsAPI (optional, key required)
    key = newsapi_key or os.environ.get("NEWSAPI_KEY", "")
    if key:
        raw += _newsapi.fetch_multi(queries[:4], api_key=key, page_size=20)

    log.info("L1: %d raw stories collected", len(raw))

    # ── Layer 2: Normalize + dedup ───────────────────────────────────────
    log.info("L2: normalising …")
    fresh, updated_seen = _norm.normalize_batch(raw, max_age_secs=max_age_secs, seen_ids=seen_ids)
    log.info("L2: %d new stories after dedup+age filter", len(fresh))

    # ── Layer 2b: Cluster ────────────────────────────────────────────────
    log.info("L2b: clustering …")
    clustered = _cluster.cluster_stories(fresh, threshold=0.40)
    log.info("L2b: %d clusters from %d stories", len(clustered), len(fresh))

    # ── Layer 3 + 4: Map & Score ─────────────────────────────────────────
    results: list[PipelineResult] = []

    for story in clustered:
        # Quick impact pre-filter (trust × novelty ≥ min_impact / 2)
        pre_score = _score.source_trust_score(story) * _score.novelty_score(story)
        if pre_score < min_impact / 2:
            continue

        matches = _mapper.map_story(story, min_relevance=min_relevance)
        if not matches:
            continue

        for match in matches:
            market = match["market"]
            rel    = match["relevance"]

            scores = _score.impact_score(story, market, rel)
            if scores["impact"] < min_impact:
                continue

            # Get current YES price
            current_price: float | None = None
            token_ids = market.get("clobTokenIds") or []
            if client and token_ids:
                current_price = _get_yes_price(client, token_ids[0])
            if current_price is None:
                # Fall back to Gamma last_trade_price
                try:
                    current_price = float(market.get("lastTradePrice", 0.5) or 0.5)
                except Exception:
                    current_price = 0.5

            shift = _estimate_shift(story, current_price)
            edge  = shift["edge"] if shift else 0.0

            if edge < min_edge:
                reason = f"edge {edge:.2%} < min_edge {min_edge:.2%}"
                actionable = False
            else:
                actionable = True
                reason = f"edge {edge:.2%} > min_edge {min_edge:.2%}"

            pr = PipelineResult(
                story=story,
                market=market,
                relevance=rel,
                scores=scores,
                shift=shift,
                current_price=current_price,
                edge=edge,
                actionable=actionable,
                reason=reason,
            )

            # ── Slippage gate ─────────────────────────────────────────
            if actionable and not skip_slippage and client:
                ok, gate_reason = _slippage_gate(pr, budget_per_trade, client, safety_buffer)
                if not ok:
                    pr.actionable = False
                    pr.reason = gate_reason

            results.append(pr)

    results.sort(key=lambda r: r.edge, reverse=True)
    log.info(
        "Pipeline done in %.1fs: %d matches, %d actionable",
        time.time() - t0,
        len(results),
        sum(1 for r in results if r.actionable),
    )
    return results, updated_seen
