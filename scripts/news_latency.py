#!/usr/bin/env python3
"""
news_latency.py — Speed-first news trading for Polymarket.

Goal: news-to-order in under 10 seconds.

Design principles (vs full news_trader):
  • RSS-only feed polling — no GDELT/NewsAPI overhead
  • No clustering pass — single-story keywords match directly to market IDs
  • No detailed impact scoring — accept broad keyword match if edge > threshold
  • No slippage gate — use an edge buffer instead
  • Market list pre-cached and refreshed every 5 minutes (separate background job)
  • Poll interval: 10 seconds (hard-coded minimum)

Speed path: RSS story → keyword match → mid-price check → order placed in ~3 s

KNOWN_MARKET_KEYWORDS dict maps keyword phrase → token_id for instant matching.
  (Populate by running  --build-map  which saves to news_latency_map.json)

Usage:
  python scripts/news_latency.py --build-map
  python scripts/news_latency.py --loop
  python scripts/news_latency.py --loop --budget 20 --dry-run
"""
from __future__ import annotations

import sys, json, time, argparse, hashlib, logging
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from _client import get_client
from _utils  import SKILL_DIR, LOG_DIR, FEE, load_json, save_json, get_mid, fetch_markets
from _guards import check_min_order, enforce_min_interval, gamma_rate_wait

# ── Constants ──────────────────────────────────────────────────────────────────
POLL_INTERVAL    = 10          # seconds — absolute minimum
MAX_STORY_AGE    = 30          # seconds — ignore stories older than this
MIN_EDGE         = 0.05        # higher than news_trader (no slippage gate)
CACHE_TTL        = 300         # 5 min market cache refresh
STATE_FILE       = SKILL_DIR / "news_latency_state.json"
MAP_FILE         = SKILL_DIR / "news_latency_map.json"
LOG_FILE         = LOG_DIR   / f"news_latency_{datetime.now().strftime('%Y-%m-%d')}.log"

_DEFAULT_STATE: dict = {
    "runs": 0, "signals_found": 0, "trades_executed": 0,
    "total_spent": 0.0, "total_profit_est": 0.0,
    "seen_guids": [], "history": [],
}

LOG_DIR.mkdir(exist_ok=True)
logging.basicConfig(level=logging.INFO,
    format="%(asctime)s  %(levelname)-7s  %(message)s",
    handlers=[logging.StreamHandler(), logging.FileHandler(LOG_FILE)],
)
log = logging.getLogger("news_latency")


# ── Fast RSS polling ───────────────────────────────────────────────────────────
_RSS_FAST = [
    "https://feeds.reuters.com/reuters/topNews",
    "https://feeds.bbci.co.uk/news/rss.xml",
    "https://rss.ap.org/category/top-news",
    "https://feeds.npr.org/1001/rss.xml",
]

def _poll_rss() -> list[dict]:
    """
    Return fresh story items from fast RSS feeds (stdlib-only, no feedparser).
    Only returns items published within MAX_STORY_AGE seconds of now.
    Uses the project's own news/sources/rss.py fetch_all() helper.
    """
    from news.sources.rss import fetch_all
    now_ts = time.time()
    fresh: list[dict] = []

    feed_cfgs = [{"url": u, "label": u, "trust": 0.7} for u in _RSS_FAST]
    try:
        stories = fetch_all(feeds=feed_cfgs, max_workers=len(_RSS_FAST))
    except Exception as exc:
        log.debug(f"RSS poll error: {exc}")
        return fresh

    for story in stories:
        entry_ts: float = story.get("pub_ts") or 0.0
        if entry_ts == 0.0:
            continue
        age = now_ts - entry_ts
        if age < 0 or age > MAX_STORY_AGE:
            continue

        guid = (story.get("id") or story.get("url") or
                hashlib.md5(story.get("title", "").encode()).hexdigest())
        fresh.append({
            "guid":   guid,
            "title":  story.get("title", ""),
            "url":    story.get("url", ""),
            "source": story.get("source", ""),
            "age_s":  round(age, 1),
        })

    return fresh

    return fresh


# ── Market keyword map ─────────────────────────────────────────────────────────
def build_keyword_map(limit: int = 600) -> dict[str, list[str]]:
    """
    Scan Gamma for active markets and return a dict:
      keyword_phrase  →  [yes_token_id, no_token_id]

    Key-phrase extraction: just lowercase question words ≥ 4 chars, deduped.
    """
    log.info("Building keyword map from Gamma …")
    markets  = fetch_markets(limit=limit, active=True)
    kw_map: dict[str, list[str]] = {}

    for m in markets:
        q = (m.get("question") or "").lower()
        tokens = m.get("tokens") or []
        if len(tokens) < 2:
            continue
        yes_tid = tokens[0].get("token_id", "")
        no_tid  = tokens[1].get("token_id", "")
        if not yes_tid or not no_tid:
            continue
        # 2-3 word n-grams as keys for faster look-up
        words = [w.strip("'\".,?!") for w in q.split() if len(w) >= 4]
        for i in range(len(words)):
            for n in (2, 3):
                phrase = " ".join(words[i:i+n])
                if len(phrase) >= 8:
                    kw_map.setdefault(phrase, [yes_tid, no_tid])

    log.info(f"Keyword map: {len(kw_map)} entries from {len(markets)} markets")
    return kw_map


def _score_story(title: str, kw_map: dict[str, list[str]]
                 ) -> tuple[float, list[str]] | None:
    """
    Match story title against keyword map.
    Returns (match_count / total_checked, [yes_tid, no_tid]) or None.
    """
    tl = title.lower()
    best_phrase = ""
    best_tids: list[str] = []
    best_len = 0

    for phrase, tids in kw_map.items():
        if phrase in tl and len(phrase) > best_len:
            best_phrase = phrase
            best_tids   = tids
            best_len    = len(phrase)

    if not best_tids:
        return None
    log.debug(f"Matched '{best_phrase}' in: {title[:60]}")
    return best_len / max(len(tl), 1), best_tids


# ── Signal processing ──────────────────────────────────────────────────────────
YES_KEYWORDS = {
    "win", "wins", "won", "pass", "passes", "approved", "agrees",
    "confirm", "confirmed", "elect", "elected", "signs",
    "launches", "announces", "increases", "rises", "surges",
    "record", "first", "achieves", "completes",
}
NO_KEYWORDS = {
    "lose", "lost", "fails", "failed", "reject", "rejected", "refuses",
    "crash", "crashes", "drops", "falls", "declines", "cancels",
    "postpones", "suspends", "blocks",
}

def _direction(title: str) -> str:
    tl_set = set(title.lower().split())
    yes_hits = len(tl_set & YES_KEYWORDS)
    no_hits  = len(tl_set & NO_KEYWORDS)
    if yes_hits > no_hits:
        return "YES"
    if no_hits > yes_hits:
        return "NO"
    return "YES"  # default: buy YES (event likely positive)


def _process_stories(stories: list[dict], kw_map: dict,
                     client, min_edge: float, budget: float,
                     dry_run: bool, state: dict) -> int:
    """Process fresh stories. Returns number of signals found."""
    seen: set[str] = set(state.get("seen_guids", []) or [])
    found = 0

    for story in stories:
        if story["guid"] in seen:
            continue

        result = _score_story(story["title"], kw_map)
        if result is None:
            continue

        _, tids = result
        yes_tid, no_tid = tids[0], tids[1]

        direction = _direction(story["title"])
        target_tid = yes_tid if direction == "YES" else no_tid

        gamma_rate_wait()
        price = get_mid(client, target_tid)
        if price is None:
            continue

        # Edge check: only buy at meaningful discount
        fair_price = 0.65 if direction == "YES" else 0.35
        edge = abs(fair_price - price) - FEE
        if edge < min_edge:
            log.debug(f"Edge too thin: {edge:.3f} for {story['title'][:50]}")
            continue

        log.info(f"SIGNAL  [{direction}]  age={story['age_s']}s  "
                 f"price={price:.4f}  edge={edge:.3f}  {story['title'][:60]}")
        found += 1
        state["signals_found"] = state.get("signals_found", 0) + 1

        if dry_run:
            seen.add(story["guid"])
            print(f"  DRY-RUN  {direction}  ${budget:.2f}  "
                  f"price={price:.4f}  {story['title'][:55]}")
            state.setdefault("history", []).append({
                "ts": datetime.now(timezone.utc).isoformat(),
                "title": story["title"][:70], "direction": direction,
                "price": price, "edge": edge, "status": "dry_run",
            })
            continue

        # ── Place order ──────────────────────────────────────────────────────
        try:
            from py_clob_client.clob_types import OrderArgs, OrderType
            from py_clob_client.order_builder.constants import BUY
            o_args = OrderArgs(token_id=target_tid, price=price, size=budget, side=BUY)
            signed = client.create_order(o_args)
            resp   = client.post_order(signed, OrderType.GTC)
            oid    = (resp or {}).get("orderID") or str((resp or {}).get("id", "?"))
            print(f"  ORDER  {direction}  ${budget:.2f}  @ {price:.4f}  "
                  f"id={str(oid)[:20]}  '{story['title'][:45]}'")
            seen.add(story["guid"])
            state["trades_executed"] = state.get("trades_executed", 0) + 1
            state["total_spent"]     = state.get("total_spent", 0.0) + budget
            state.setdefault("history", []).append({
                "ts": datetime.now(timezone.utc).isoformat(),
                "title": story["title"][:70], "direction": direction,
                "price": price, "edge": edge, "status": "placed",
                "order_id": str(oid),
            })
            try:
                from notifier import notify_trade_opened
                notify_trade_opened(
                    bot="news_latency",
                    market=story["title"][:70],
                    direction=direction,
                    amount_usd=budget,
                    order_ids=[str(oid)],
                    extras={"age_s": story["age_s"], "edge": edge},
                )
            except Exception:
                pass
        except Exception as exc:
            log.warning(f"Order failed: {exc}")
            seen.add(story["guid"])   # don't retry failed story

    # Trim seen set
    seen_list = list(seen)
    if len(seen_list) > 2000:
        seen_list = seen_list[-2000:]
    state["seen_guids"] = seen_list
    return found


# ── Entry point ────────────────────────────────────────────────────────────────
def main():
    p = argparse.ArgumentParser(description="Speed-first RSS news trading")
    mode = p.add_mutually_exclusive_group()
    mode.add_argument("--loop",         action="store_true",
                      help="Continuous loop (default mode)")
    mode.add_argument("--once",         action="store_true",
                      help="Single poll cycle then exit")
    mode.add_argument("--build-map",    action="store_true",
                      help="Rebuild keyword-market map and exit")
    p.add_argument("--interval",    type=int,   default=POLL_INTERVAL,
                   help=f"Poll interval in seconds (min {POLL_INTERVAL}, default {POLL_INTERVAL})")
    p.add_argument("--budget",      type=float, default=1.0,
                   help="USDC per trade (default 1)")
    p.add_argument("--min-edge",    type=float, default=MIN_EDGE,
                   help=f"Min directional edge (default {MIN_EDGE})")
    p.add_argument("--dry-run",     action="store_true")
    p.add_argument("--status",      action="store_true")
    args = p.parse_args()

    interval = max(POLL_INTERVAL, args.interval)
    if interval != args.interval:
        print(f"  [INFO] Interval clamped to {POLL_INTERVAL}s minimum.")

    if (args.loop or args.once) and not args.dry_run:
        check_min_order(args.budget, flag="--budget", bot="news_latency",
                        exit_on_fail=True)

    state  = load_json(STATE_FILE, _DEFAULT_STATE)
    client = get_client(authenticated=bool((args.loop or args.once) and not args.dry_run))

    if args.status:
        print(f"\n  News-Latency Status\n  {'─'*40}")
        print(f"  Runs:          {state.get('runs', 0)}")
        print(f"  Signals found: {state.get('signals_found', 0)}")
        print(f"  Trades placed: {state.get('trades_executed', 0)}")
        print(f"  USDC deployed: ${state.get('total_spent', 0):.2f}")
        for r in state.get("history", [])[-8:]:
            tag = "DRY" if r.get("status") == "dry_run" else r.get("status","?").upper()
            print(f"  [{r['ts'][:19]}]  {tag:<8}  {r.get('direction','?')}  "
                  f"edge={r.get('edge',0):.3f}  {r.get('title','')[:45]}")
        print()
        return

    if args.build_map:
        kw_map = build_keyword_map()
        save_json(MAP_FILE, kw_map)
        print(f"  Saved {len(kw_map)} keyword entries → {MAP_FILE}")
        return

    if not (args.loop or args.once):
        p.print_help()
        return

    # Load keyword map (or build on first run)
    if not MAP_FILE.exists():
        log.info("No map found — building now (first run)…")
        kw_map = build_keyword_map()
        save_json(MAP_FILE, kw_map)
    else:
        kw_map = load_json(MAP_FILE, {})

    _map_last_refresh = time.monotonic()

    state["runs"] = state.get("runs", 0) + 1
    log.info(f"news_latency starting  interval={interval}s  budget=${args.budget}"
             f"  dry_run={args.dry_run}  map_entries={len(kw_map)}")

    try:
        while True:
            # Refresh keyword map every CACHE_TTL seconds
            if time.monotonic() - _map_last_refresh > CACHE_TTL:
                log.info("Refreshing keyword map…")
                kw_map = build_keyword_map()
                save_json(MAP_FILE, kw_map)
                _map_last_refresh = time.monotonic()

            stories = _poll_rss()
            if stories:
                _process_stories(stories, kw_map, client,
                                args.min_edge, args.budget, args.dry_run, state)

            save_json(STATE_FILE, state)

            if args.once:
                break
            time.sleep(interval)
    except KeyboardInterrupt:
        log.info("news_latency stopped")

    save_json(STATE_FILE, state)


if __name__ == "__main__":
    main()
