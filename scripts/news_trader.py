#!/usr/bin/env python3
"""
news_trader.py — News-driven Polymarket trader (pipeline edition)

Sources: GDELT (no key) + NewsAPI (optional) + RSS (configurable)

Pipeline layers
  L1  Ingest     GDELT broad-sweep + NewsAPI articles + RSS feeds
  L2  Normalize  fingerprint, dedup, age-filter, source-trust weight
  L2b Cluster    group near-identical stories -> one representative
  L3  Map        story -> active Polymarket markets (Gamma API)
  L4  Score      5-factor impact (trust x novelty x relevance x specificity x urgency)
      Gate       edge vs current orderbook (slippage + fees + safety buffer)

Usage:
  python scripts/news_trader.py --once                         # single scan + trade cycle
  python scripts/news_trader.py --loop --interval 3            # run every 3 minutes
  python scripts/news_trader.py --loop --interval 5 --dry-run  # simulate only
  python scripts/news_trader.py --sources                      # list configured RSS sources
  python scripts/news_trader.py --add-source "https://..."     # add RSS feed
  python scripts/news_trader.py --history --limit 20           # show recent news matches
"""
import sys, json, time, argparse, logging
from pathlib import Path
from datetime import datetime, timezone

sys.path.insert(0, str(Path(__file__).parent))
from _client import get_client
from _utils  import SKILL_DIR, LOG_DIR, load_json, save_json

from news.sources.rss import DEFAULT_FEEDS
from news.pipeline     import run_pipeline, PipelineResult

# -- Logging ------------------------------------------------------------------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-7s  %(name)s -- %(message)s",
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler(LOG_DIR / "news_trader.log"),
    ],
)
log = logging.getLogger("news_trader")

# -- State --------------------------------------------------------------------
STATE_FILE   = SKILL_DIR / "news_trader_state.json"
SOURCES_FILE = SKILL_DIR / "news_sources.json"

_DEFAULT_STATE = {"seen_ids": [], "trade_log": [], "last_run": None}


def load_state() -> dict:
    return load_json(STATE_FILE, _DEFAULT_STATE)

def save_state(s: dict):
    save_json(STATE_FILE, s)

def load_sources() -> list:
    saved = load_json(SOURCES_FILE, [])
    return saved if saved else list(DEFAULT_FEEDS)

def save_sources(feeds: list):
    save_json(SOURCES_FILE, feeds)


# -- Execute a PipelineResult -------------------------------------------------
def execute_result(pr: PipelineResult, budget: float, client, dry_run: bool) -> dict:
    market    = pr.market
    shift     = pr.shift or {}
    token_ids = market.get("clobTokenIds") or []
    token_id  = token_ids[0] if token_ids else None
    direction = shift.get("direction", "YES")
    price     = pr.current_price if direction == "YES" else round(1.0 - pr.current_price, 4)

    record = {
        "market":    market.get("question", "")[:70],
        "market_id": market.get("id", ""),
        "direction": direction,
        "price":     price,
        "edge":      pr.edge,
        "impact":    pr.scores.get("impact"),
        "budget":    budget,
        "dry_run":   dry_run,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }

    if not token_id:
        record.update({"status": "skip", "reason": "no clobTokenId"})
        return record

    if dry_run:
        print(f"      [DRY-RUN] BUY {direction} {market.get('question','')[:55]}")
        print(f"               @ {price:.4f}  |  ${budget:.2f}  |  "
              f"edge {pr.edge:.1%}  |  impact {pr.scores.get('impact',0):.3f}")
        record["status"] = "dry_run"
        return record

    try:
        from py_clob_client.clob_types import OrderArgs, OrderType
        from py_clob_client.order_builder.constants import BUY
        o_args = OrderArgs(token_id=token_id, price=round(price, 4),
                           size=round(budget, 2), side=BUY)
        signed = client.create_order(o_args)
        resp   = client.post_order(signed, OrderType.GTC)
        oid    = (resp or {}).get("orderID") or (resp or {}).get("id", "?")
        print(f"      OK Placed {direction} order {str(oid)[:20]}  ${budget:.2f}  @ {price:.4f}")
        record.update({"status": "placed", "order_id": str(oid)})
        # ── Notify OpenClaw ──────────────────────────────────────────────────
        try:
            from notifier import notify_trade_opened
            notify_trade_opened(
                bot="news_trader",
                market=record["market"],
                market_id=record.get("market_id", ""),
                direction=direction,
                amount_usd=round(budget, 2),
                price=price,
                order_ids=[str(oid)],
                extras={
                    "edge":   record.get("edge"),
                    "impact": record.get("impact"),
                },
            )
        except Exception:
            pass
    except Exception as exc:
        print(f"      FAIL Order failed: {exc}")
        record.update({"status": "error", "error": str(exc)})

    return record


# -- One scan + trade cycle ---------------------------------------------------
def run_cycle(args, client, state: dict) -> dict:
    seen_ids = set(state.get("seen_ids") or [])
    sources  = load_sources()

    print(f"\n  [{datetime.now().strftime('%H:%M:%S')}] Starting pipeline  "
          f"({len(sources)} RSS feeds + GDELT + NewsAPI)...")

    results, new_seen = run_pipeline(
        client=client,
        rss_feeds=sources,
        newsapi_key=args.newsapi_key or None,
        max_age_secs=args.max_age * 60,
        seen_ids=seen_ids,
        min_impact=args.min_impact,
        min_relevance=args.min_relevance,
        min_edge=args.min_edge,
        budget_per_trade=args.budget,
        safety_buffer=args.safety_buffer,
        skip_slippage=args.skip_slippage,
        dry_run=args.dry_run,
    )

    actionable = [r for r in results if r.actionable]
    print(f"  Pipeline: {len(results)} signal(s) mapped, {len(actionable)} actionable")

    trades_taken = 0
    for pr in actionable:
        story  = pr.story
        market = pr.market
        print(f"\n  NEWS  [{story.get('source','?')}] {story['title'][:80]}")
        print(f"        Market  : {market.get('question','')[:65]}")
        print(f"        Price   : {pr.current_price:.3f}  ->  est. {pr.shift['target_price']:.3f}"
              f"  (edge {pr.edge:.1%})")
        print(f"        Scores  : impact={pr.scores['impact']:.3f}  "
              f"trust={pr.scores['trust']:.2f}  novelty={pr.scores['novelty']:.2f}  "
              f"relevance={pr.scores['relevance']:.2f}  "
              f"specificity={pr.scores['specificity']:.2f}")

        record = execute_result(pr, args.budget, client, args.dry_run)
        state["trade_log"].append(record)
        if len(state["trade_log"]) > 500:
            state["trade_log"] = state["trade_log"][-500:]
        trades_taken += 1

    # Persist seen IDs (cap at 10 000)
    full_seen = list(new_seen)
    if len(full_seen) > 10_000:
        full_seen = full_seen[-8_000:]
    state["seen_ids"] = full_seen
    state["last_run"] = datetime.now(timezone.utc).isoformat()
    print(f"\n  Cycle complete -- {trades_taken} trade action(s).\n")
    return state


# -- CLI ----------------------------------------------------------------------
def main():
    p = argparse.ArgumentParser(
        description="News-driven Polymarket trader (pipeline edition)")

    # Run modes
    p.add_argument("--once",          action="store_true",
                   help="Run one cycle then exit")
    p.add_argument("--loop",          action="store_true",
                   help="Run continuously")
    p.add_argument("--interval",      type=float, default=5.0,
                   help="Minutes between cycles (default 5)")

    # Trade settings
    p.add_argument("--dry-run",       action="store_true",
                   help="Analyse only; no orders placed")
    p.add_argument("--budget",        type=float, default=25.0,
                   help="USDC per trade (default 25)")
    p.add_argument("--min-edge",      type=float, default=0.06,
                   help="Min estimated edge (default 0.06)")
    p.add_argument("--min-relevance", type=float, default=0.15,
                   help="Min story-market relevance (default 0.15)")
    p.add_argument("--min-impact",    type=float, default=0.15,
                   help="Min pipeline impact score (default 0.15)")
    p.add_argument("--safety-buffer", type=float, default=0.02,
                   help="Extra edge over fees+slippage (default 0.02)")
    p.add_argument("--max-age",       type=float, default=60.0,
                   help="Max story age in minutes (default 60)")

    # Source overrides
    p.add_argument("--newsapi-key",   default="",
                   help="NewsAPI.org key (or set NEWSAPI_KEY env var)")
    p.add_argument("--skip-slippage", action="store_true",
                   help="Skip execution_simulator gate")

    # Management commands
    p.add_argument("--sources",       action="store_true",
                   help="List configured RSS sources")
    p.add_argument("--add-source",    metavar="URL",
                   help="Add an RSS feed URL")
    p.add_argument("--source-label",  default="Custom",
                   help="Label for --add-source")
    p.add_argument("--source-trust",  type=float, default=0.6,
                   help="Trust score for --add-source (0-1)")
    p.add_argument("--history",       action="store_true",
                   help="Show recent trade + signal history")
    p.add_argument("--limit",         type=int, default=20,
                   help="Rows for --history")
    p.add_argument("--json",          action="store_true",
                   help="Output --history as JSON")

    args  = p.parse_args()

    # ── Hard limits (cannot be overridden by user flags) ────────────────────
    from _guards import enforce_min_interval, check_min_order
    if args.once or args.loop:
        args.interval = enforce_min_interval(args.interval, bot="news_trader")
        if not args.dry_run:
            check_min_order(args.budget, flag="--budget",
                            bot="news_trader", exit_on_fail=True)

    state = load_state()

    # Info commands
    if args.history:
        entries = state.get("trade_log", [])[-args.limit:]
        if args.json:
            print(json.dumps(entries, indent=2))
        else:
            print(f"\n  Last {len(entries)} trade/signal records:\n")
            for t in entries:
                tag = "DRY" if t.get("dry_run") else t.get("status", "?").upper()
                print(f"  [{t['timestamp'][:19]}]  {tag:<8}  "
                      f"{t.get('direction',''):<4}  "
                      f"edge {t.get('edge',0):.1%}  "
                      f"{t.get('market','')[:55]}")
            print()
        return

    if args.sources:
        feeds = load_sources()
        print(f"\n  Configured RSS sources ({len(feeds)}):\n")
        for i, f in enumerate(feeds, 1):
            print(f"  {i:>3}.  {f.get('label','?'):<28}  "
                  f"trust={f.get('trust',0.6):.2f}  {f['url'][:60]}")
        print()
        return

    if args.add_source:
        feeds = load_sources()
        feeds.append({"url": args.add_source,
                      "label": args.source_label,
                      "trust": args.source_trust})
        save_sources(feeds)
        print(f"  Added [{args.source_label}]  "
              f"trust={args.source_trust}  {args.add_source}")
        return

    # Trading loop
    if not (args.once or args.loop):
        p.print_help()
        return

    client = get_client(authenticated=not args.dry_run)

    try:
        while True:
            state = run_cycle(args, client, state)
            save_state(state)
            if args.once:
                break
            print(f"  Sleeping {args.interval:.1f} min ...")
            time.sleep(args.interval * 60)
    except KeyboardInterrupt:
        save_state(state)
        print("\n  Stopped.\n")


if __name__ == "__main__":
    main()
