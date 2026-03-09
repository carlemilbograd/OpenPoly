#!/usr/bin/env python3
"""
news_trader.py — Real-time news monitor that detects probability-shifting
events and automatically trades on Polymarket before the crowd reacts.

Sources monitored:
  • RSS feeds (configurable list in news_sources.json)
  • Nitter (Twitter/X via public RSS — no API key needed)
  • Government announcements (whitehouse.gov, SEC, Fed, SCOTUS)
  • Custom keyword watchlist

Workflow:
  1. Poll all sources for new stories
  2. Score each story's relevance to active Polymarket questions
  3. Estimate probability shift implied by the news
  4. Compare estimate to current market price
  5. If gap > min_edge: execute trade (BUY the underpriced side)
  6. Save seen story IDs to avoid duplicate trades

Usage:
  python scripts/news_trader.py --once                         # single scan + trade cycle
  python scripts/news_trader.py --loop --interval 3            # run every 3 minutes
  python scripts/news_trader.py --loop --interval 5 --dry-run  # simulate only
  python scripts/news_trader.py --sources                       # list configured sources
  python scripts/news_trader.py --add-source "https://..."      # add RSS feed
  python scripts/news_trader.py --history --limit 20            # show recent news matches
"""
import sys, os, json, time, argparse, hashlib, requests, re
from pathlib import Path
from datetime import datetime, timezone, timedelta
from xml.etree import ElementTree as ET

sys.path.insert(0, str(Path(__file__).parent))
from _client import GAMMA_API, get_client

SKILL_DIR    = Path(__file__).parent.parent
LOG_DIR      = SKILL_DIR / "logs"
STATE_FILE   = SKILL_DIR / "news_trader_state.json"
SOURCES_FILE = SKILL_DIR / "news_sources.json"
LOG_DIR.mkdir(exist_ok=True)

FEE      = 0.02   # round-trip fee estimate
MAX_AGE  = 43200  # ignore stories older than 12 hours (seconds)

# ── Default news source catalogue ─────────────────────────────────────────────
DEFAULT_SOURCES = [
    # Government / Policy
    {"label": "White House",      "url": "https://www.whitehouse.gov/feed/", "type": "rss"},
    {"label": "SEC News",         "url": "https://www.sec.gov/cgi-bin/browse-edgar?action=getcurrent&type=8-K&dateb=&owner=include&count=10&search_text=&output=atom", "type": "rss"},
    {"label": "Federal Reserve",  "url": "https://www.federalreserve.gov/feeds/press_all.xml", "type": "rss"},
    {"label": "SCOTUS SCOTUSblog","url": "https://www.scotusblog.com/feed/", "type": "rss"},
    # Finance / Crypto
    {"label": "CoinDesk",         "url": "https://www.coindesk.com/arc/outboundfeeds/rss/", "type": "rss"},
    {"label": "Reuters Business", "url": "https://feeds.reuters.com/reuters/businessNews", "type": "rss"},
    {"label": "Reuters Politics", "url": "https://feeds.reuters.com/Reuters/PoliticsNews",  "type": "rss"},
    {"label": "AP Top News",      "url": "https://rsshub.app/apnews/topics/apf-topnews", "type": "rss"},
    {"label": "Politico",         "url": "https://www.politico.com/rss/politics08.xml", "type": "rss"},
    # Crypto / Market
    {"label": "The Block",        "url": "https://www.theblock.co/rss.xml", "type": "rss"},
    {"label": "Decrypt",          "url": "https://decrypt.co/feed", "type": "rss"},
    # Nitter (Twitter/X public RSS for key accounts — no API key)
    {"label": "Nitter: Trump",    "url": "https://nitter.privacyredirect.com/realDonaldTrump/rss", "type": "nitter"},
    {"label": "Nitter: FedReserve","url": "https://nitter.privacyredirect.com/federalreserve/rss", "type": "nitter"},
    {"label": "Nitter: SECGov",   "url": "https://nitter.privacyredirect.com/SECGov/rss", "type": "nitter"},
    {"label": "Nitter: POTUS",    "url": "https://nitter.privacyredirect.com/POTUS/rss", "type": "nitter"},
]

# ── Category keyword → probability shift magnitude ────────────────────────────
# Higher value = larger expected market move when this keyword fires.
KEYWORD_SIGNALS = [
    {"keywords": ["wins", "elected", "victory", "won the"],          "magnitude": 0.20, "bullish": True},
    {"keywords": ["loses", "defeated", "concedes", "lost"],           "magnitude": 0.20, "bullish": False},
    {"keywords": ["arrest", "indicted", "charged", "convicted"],      "magnitude": 0.15, "bullish": False},
    {"keywords": ["resign", "steps down", "withdraws", "drops out"],  "magnitude": 0.15, "bullish": False},
    {"keywords": ["rate hike", "raises rates", "tightening"],         "magnitude": 0.08, "bullish": True},  # for "rate hike" markets
    {"keywords": ["rate cut", "cuts rates", "easing", "dovish"],      "magnitude": 0.08, "bullish": True},
    {"keywords": ["ceasefire", "peace deal", "agreement signed"],     "magnitude": 0.15, "bullish": True},
    {"keywords": ["war declared", "invasion", "military strikes"],    "magnitude": 0.15, "bullish": False},
    {"keywords": ["etf approved", "sec approves", "approved bitcoin"],"magnitude": 0.12, "bullish": True},
    {"keywords": ["ban", "crackdown", "sanctions", "seized"],         "magnitude": 0.10, "bullish": False},
    {"keywords": ["breakthrough", "cure", "vaccine", "fda approves"], "magnitude": 0.10, "bullish": True},
    {"keywords": ["bankruptcy", "collapse", "default", "insolvency"], "magnitude": 0.15, "bullish": False},
    {"keywords": ["ipo", "merger", "acquisition", "takeover"],        "magnitude": 0.06, "bullish": True},
    {"keywords": ["earthquake", "hurricane", "disaster"],             "magnitude": 0.05, "bullish": False},
]

# ── State ─────────────────────────────────────────────────────────────────────
def load_state() -> dict:
    if STATE_FILE.exists():
        try:
            return json.loads(STATE_FILE.read_text())
        except Exception:
            pass
    return {"seen_ids": [], "trade_log": [], "last_run": None}


def save_state(state: dict):
    STATE_FILE.write_text(json.dumps(state, indent=2))


def story_id(title: str, url: str) -> str:
    return hashlib.sha256(f"{title}{url}".encode()).hexdigest()[:16]


def load_sources() -> list:
    if SOURCES_FILE.exists():
        try:
            return json.loads(SOURCES_FILE.read_text())
        except Exception:
            pass
    sources = DEFAULT_SOURCES[:]
    SOURCES_FILE.write_text(json.dumps(sources, indent=2))
    return sources


def save_sources(sources: list):
    SOURCES_FILE.write_text(json.dumps(sources, indent=2))


# ── RSS / Nitter fetching ─────────────────────────────────────────────────────
def fetch_rss(url: str, label: str) -> list:
    """Return list of {"title", "link", "published", "summary"} from RSS."""
    try:
        resp = requests.get(url, timeout=10, headers={"User-Agent": "Mozilla/5.0"})
        if not resp.ok:
            return []
        root = ET.fromstring(resp.text)
        ns   = {"atom": "http://www.w3.org/2005/Atom"}
        items = []

        # RSS 2.0
        for item in root.findall(".//item"):
            title   = (item.findtext("title") or "").strip()
            link    = item.findtext("link") or ""
            pub     = item.findtext("pubDate") or ""
            summary = (item.findtext("description") or "").strip()[:500]
            if title:
                items.append({"title": title, "link": link, "published": pub,
                               "summary": summary, "source": label})
        # Atom
        for entry in root.findall("atom:entry", ns) or root.findall(".//entry"):
            title   = (entry.findtext("atom:title", namespaces=ns) or
                       entry.findtext("title") or "").strip()
            link    = ""
            for lnk in entry.findall("atom:link", ns) or entry.findall("link"):
                href = lnk.get("href", "")
                if href:
                    link = href
                    break
            pub     = (entry.findtext("atom:updated", namespaces=ns) or
                       entry.findtext("atom:published", namespaces=ns) or
                       entry.findtext("updated") or "")
            summary = (entry.findtext("atom:summary", namespaces=ns) or
                       entry.findtext("summary") or "").strip()[:500]
            if title:
                items.append({"title": title, "link": link, "published": pub,
                               "summary": summary, "source": label})
        return items[:20]   # cap at 20 per source
    except Exception:
        return []


def fetch_all_stories(sources: list) -> list:
    all_stories = []
    for src in sources:
        stories = fetch_rss(src["url"], src["label"])
        all_stories.extend(stories)
    return all_stories


# ── Score stories against Polymarket questions ────────────────────────────────
def score_story(story: dict, market_question: str) -> tuple[float, dict | None]:
    """
    Returns (relevance_score 0–1, signal_dict or None).
    relevance_score: how closely this story relates to the market question.
    signal: the detected keyword signal if any.
    """
    combined = (story["title"] + " " + story.get("summary", "")).lower()
    question = market_question.lower()

    # Split question into key words (3+ chars, not stopwords)
    stopwords = {"the", "a", "an", "is", "are", "will", "would", "who", "what",
                 "when", "where", "why", "how", "by", "in", "to", "of", "for",
                 "and", "or", "not", "yes", "no", "at", "on", "with", "that"}
    q_words = [w for w in re.findall(r'\b[a-z]{3,}\b', question) if w not in stopwords]

    if not q_words:
        return 0.0, None

    # Count how many key question words appear in the story
    hits = sum(1 for w in q_words if w in combined)
    relevance = hits / len(q_words)

    # Check for a keyword signal
    detected_signal = None
    for sig in KEYWORD_SIGNALS:
        if any(kw in combined for kw in sig["keywords"]):
            detected_signal = sig
            break

    return min(1.0, relevance), detected_signal


def find_matching_markets(story: dict, min_relevance: float = 0.25) -> list:
    """Search Gamma API for markets related to this story's content."""
    search_text = story["title"][:60]
    try:
        resp = requests.get(
            f"{GAMMA_API}/markets",
            params={"search": search_text, "active": "true", "limit": 10},
            timeout=10,
        )
        if not resp.ok:
            return []
        markets = resp.json()
    except Exception:
        return []

    results = []
    for m in (markets if isinstance(markets, list) else []):
        q = m.get("question", "")
        relevance, signal = score_story(story, q)
        if relevance >= min_relevance and signal:
            tokens = m.get("tokens", [])
            yes_token = tokens[0].get("token_id", "") if tokens else ""
            no_token  = tokens[1].get("token_id", "") if len(tokens) > 1 else ""
            results.append({
                "market_id":    m.get("id", ""),
                "question":     q,
                "yes_token":    yes_token,
                "no_token":     no_token,
                "relevance":    round(relevance, 3),
                "signal":       signal,
            })

    results.sort(key=lambda x: x["relevance"], reverse=True)
    return results[:5]


# ── Estimate probability shift ────────────────────────────────────────────────
def estimate_shift(match: dict, current_price: float) -> dict | None:
    """
    Given a signal and current YES price, estimate whether there's an edge.
    Returns trade instruction or None.
    """
    signal = match["signal"]
    mag    = signal["magnitude"]
    bullish = signal["bullish"]

    # Estimate where price SHOULD be after market digests this news
    if bullish:
        target = min(0.97, current_price + mag)
        side   = "BUY_YES"  # underpriced YES
        edge   = target - current_price
    else:
        target = max(0.03, current_price - mag)
        side   = "BUY_NO"   # overpriced YES → buy the NO
        edge   = current_price - target

    net = edge - FEE
    if net <= 0:
        return None

    return {
        "side":          side,
        "current_price": round(current_price, 4),
        "target_price":  round(target, 4),
        "edge":          round(edge, 4),
        "net_edge":      round(net, 4),
        "signal_kw":     signal["keywords"][0],
    }


# ── Execute trade ──────────────────────────────────────────────────────────────
def execute_trade(match: dict, instruction: dict, budget: float,
                  client, dry_run: bool) -> dict:
    from py_clob_client.clob_types import OrderArgs, OrderType
    from py_clob_client.order_builder.constants import BUY

    token_id = match["yes_token"] if instruction["side"] == "BUY_YES" else match["no_token"]
    price    = instruction["current_price"]
    if instruction["side"] == "BUY_NO":
        price = 1.0 - price   # NO price = 1 - YES price

    label  = "YES" if instruction["side"] == "BUY_YES" else "NO"
    result = {
        "market":    match["question"][:60],
        "side":      instruction["side"],
        "price":     price,
        "budget":    budget,
        "net_edge":  instruction["net_edge"],
        "dry_run":   dry_run,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }

    if dry_run:
        print(f"    [DRY-RUN] Would BUY {label} {match['question'][:50]} @ {price:.4f} "
              f"(${budget:.2f}, net edge {instruction['net_edge']*100:.1f}%)")
        result["status"] = "dry_run"
        return result

    try:
        o_args = OrderArgs(token_id=token_id, price=round(price, 4),
                           size=round(budget, 2), side=BUY)
        signed = client.create_order(o_args)
        resp   = client.post_order(signed, OrderType.GTC)
        oid    = (resp or {}).get("orderID") or (resp or {}).get("id", "?")
        print(f"    ✅ Placed {label} order {str(oid)[:20]}  ${budget:.2f}  @ {price:.4f}")
        result["status"]   = "placed"
        result["order_id"] = str(oid)
    except Exception as e:
        print(f"    ❌ Order failed: {e}")
        result["status"] = "error"
        result["error"]  = str(e)
    return result


# ── Get current mid price ─────────────────────────────────────────────────────
def get_mid(client, token_id: str) -> float | None:
    try:
        r = client.get_midpoint(token_id)
        v = r.get("mid")
        return float(v) if v else None
    except Exception:
        return None


# ── Main cycle ────────────────────────────────────────────────────────────────
def run_cycle(args, client, state: dict) -> dict:
    sources    = load_sources()
    print(f"\n  [{datetime.now().strftime('%H:%M:%S')}] Fetching stories from {len(sources)} sources...")
    all_stories = fetch_all_stories(sources)
    print(f"  Fetched {len(all_stories)} total stories")

    new_stories = [s for s in all_stories if story_id(s["title"], s["link"]) not in state["seen_ids"]]
    print(f"  New (unseen): {len(new_stories)}")

    actions_taken = 0
    for story in new_stories:
        sid = story_id(story["title"], story["link"])
        state["seen_ids"].append(sid)
        # Keep seen_ids from growing unbounded
        if len(state["seen_ids"]) > 5000:
            state["seen_ids"] = state["seen_ids"][-3000:]

        matches = find_matching_markets(story, min_relevance=args.min_relevance)
        if not matches:
            continue

        print(f"\n  📰 [{story['source']}] {story['title'][:80]}")
        for match in matches:
            token_id = match["yes_token"]
            if not token_id:
                continue

            current_price = get_mid(client, token_id)
            if current_price is None:
                continue

            instruction = estimate_shift(match, current_price)
            if not instruction or instruction["net_edge"] < args.min_edge:
                continue

            print(f"  🎯 Signal '{instruction['signal_kw']}'  |  "
                  f"relevance {match['relevance']:.0%}  |  "
                  f"net edge {instruction['net_edge']*100:.1f}%")
            print(f"     Market: {match['question'][:65]}")
            print(f"     Price now: {instruction['current_price']:.3f} → est. after: {instruction['target_price']:.3f}")

            logged = execute_trade(match, instruction, args.budget, client, args.dry_run)
            state["trade_log"].append(logged)
            if len(state["trade_log"]) > 500:
                state["trade_log"] = state["trade_log"][-500:]
            actions_taken += 1

    state["last_run"] = datetime.now(timezone.utc).isoformat()
    print(f"\n  Cycle complete — {actions_taken} trade action(s) taken.\n")
    return state


# ── CLI ────────────────────────────────────────────────────────────────────────
def main():
    parser = argparse.ArgumentParser(description="News-driven Polymarket trader")
    parser.add_argument("--once",          action="store_true", help="Run a single cycle then exit")
    parser.add_argument("--loop",          action="store_true", help="Run continuously")
    parser.add_argument("--interval",      type=float, default=5.0, help="Minutes between cycles (default 5)")
    parser.add_argument("--dry-run",       action="store_true", help="Analyse but do not place orders")
    parser.add_argument("--budget",        type=float, default=25.0, help="USDC per trade (default 25)")
    parser.add_argument("--min-edge",      type=float, default=0.04, help="Min net edge to trade (0.04=4%%)")
    parser.add_argument("--min-relevance", type=float, default=0.30, help="Min relevance score (0.30=30%%)")
    parser.add_argument("--sources",       action="store_true", help="List configured news sources")
    parser.add_argument("--add-source",    metavar="URL", help="Add an RSS feed URL")
    parser.add_argument("--source-label",  default="Custom", help="Label for --add-source")
    parser.add_argument("--history",       action="store_true", help="Show recent trade history")
    parser.add_argument("--limit",         type=int, default=20, help="Lines for --history")
    args = parser.parse_args()

    state = load_state()

    if args.history:
        log = state.get("trade_log", [])
        print(f"\n  Last {args.limit} trades:\n")
        for t in log[-args.limit:]:
            status = "DRY" if t.get("dry_run") else t.get("status","?").upper()
            print(f"  [{t['timestamp'][:19]}] {status:8}  {t['side']:<10}  "
                  f"{t.get('net_edge',0)*100:>5.1f}%  {t['market'][:55]}")
        print()
        return

    if args.sources:
        sources = load_sources()
        print(f"\n  Configured news sources ({len(sources)}):\n")
        for i, s in enumerate(sources, 1):
            print(f"  {i:>3}.  {s['label']:<25}  {s['type']:<8}  {s['url'][:60]}")
        print()
        return

    if args.add_source:
        sources = load_sources()
        sources.append({"label": args.source_label, "url": args.add_source, "type": "rss"})
        save_sources(sources)
        print(f"  ✅ Added: [{args.source_label}] {args.add_source}")
        return

    authenticated = not args.dry_run
    client = get_client(authenticated=authenticated)

    if args.once or args.loop:
        try:
            while True:
                state = run_cycle(args, client, state)
                save_state(state)
                if args.once:
                    break
                print(f"  Sleeping {args.interval:.1f} min...")
                time.sleep(args.interval * 60)
        except KeyboardInterrupt:
            save_state(state)
            print("\n  Stopped.\n")
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
