#!/usr/bin/env python3
"""
Deep statistics for a specific Polymarket market.

Combines Gamma API, Data API, and CLOB to show:
  - Volume, liquidity, open interest, holder count
  - Price history summary (1h / 24h / 7d change)
  - Top holders
  - Recent trades
  - Order book depth summary

Usage:
  python market_stats.py --market-id CONDITION_ID_OR_SLUG
  python market_stats.py --token-id TOKEN_ID
"""
import sys, argparse, requests, json
from pathlib import Path
from datetime import datetime, timezone

sys.path.insert(0, str(Path(__file__).parent))
from _client import GAMMA_API, DATA_API, HOST, get_client


def fmt_usdc(v):
    try:
        return f"${float(v):>12,.2f}"
    except Exception:
        return "       N/A"


def price_change(token_id: str, hours: int) -> str:
    """Fetch price change over last N hours."""
    try:
        now_ts = int(datetime.now(timezone.utc).timestamp())
        start_ts = now_ts - hours * 3600
        resp = requests.get(
            f"{HOST}/prices-history",
            params={
                "token_id": token_id,
                "startTs": start_ts,
                "fidelity": 2,
                "interval": "max",
            },
            timeout=8,
        )
        if resp.ok:
            hist = resp.json().get("history", [])
            if len(hist) >= 2:
                p_first = float(hist[0]["p"])
                p_last = float(hist[-1]["p"])
                delta = p_last - p_first
                pct = (delta / p_first * 100) if p_first else 0
                arrow = "▲" if delta > 0.001 else ("▼" if delta < -0.001 else "→")
                sign = "+" if delta >= 0 else ""
                return f"{arrow} {sign}{delta:.4f}  ({sign}{pct:.1f}%)"
    except Exception:
        pass
    return "N/A"


def main():
    parser = argparse.ArgumentParser()
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--market-id", "-m", default="",
                       help="Condition ID, slug, or numeric market ID")
    group.add_argument("--token-id", "-t", default="",
                       help="CLOB token ID (YES or NO)")
    parser.add_argument("--holders", type=int, default=5,
                        help="Number of top holders to show (default 5)")
    parser.add_argument("--trades", type=int, default=5,
                        help="Number of recent trades to show (default 5)")
    args = parser.parse_args()

    market = None

    if args.market_id:
        # Try by ID / condition_id
        resp = requests.get(f"{GAMMA_API}/markets/{args.market_id}", timeout=8)
        if resp.ok:
            market = resp.json()
        else:
            # Try by slug
            resp = requests.get(f"{GAMMA_API}/markets",
                                params={"slug": args.market_id, "limit": 1},
                                timeout=8)
            if resp.ok:
                data = resp.json()
                market = data[0] if data else None

        if not market:
            # Try by condition_id via Data API
            resp = requests.get(f"{DATA_API}/markets",
                                params={"condition_ids": args.market_id},
                                timeout=8)
            if resp.ok:
                data = resp.json()
                if data:
                    cid = args.market_id

    elif args.token_id:
        resp = requests.get(f"{GAMMA_API}/markets",
                            params={"clob_token_ids": args.token_id, "limit": 1},
                            timeout=8)
        if resp.ok:
            data = resp.json()
            market = data[0] if data else None

    if not market:
        print(f"\n  Market not found. Try using --token-id instead.\n")
        sys.exit(1)

    question = market.get("question", "Unknown")
    condition_id = market.get("conditionId", market.get("id", ""))
    slug = market.get("slug", "")
    is_active = market.get("active", False)
    is_closed = market.get("closed", False)
    end_date = market.get("endDate", "?")
    description = market.get("description", "")
    tags = [t.get("label", t) if isinstance(t, dict) else t
            for t in market.get("tags", [])]
    volume_total = market.get("volume", 0)
    volume_24h = market.get("volume24hr", market.get("volumeClob", 0))
    liquidity = market.get("liquidity", market.get("liquidityClob", 0))
    tokens = market.get("tokens", [])

    print(f"\n{'='*70}")
    print(f"  MARKET STATS")
    print(f"{'='*70}")
    print(f"  {question}")
    if description:
        print(f"\n  {description[:200]}")
    print(f"\n  Status:      {'CLOSED' if is_closed else 'ACTIVE'}")
    print(f"  Closes:      {end_date[:10] if end_date != '?' else '?'}")
    if condition_id:
        print(f"  Condition:   {condition_id}")
    if slug:
        print(f"  URL:         https://polymarket.com/event/{slug}")
    if tags:
        print(f"  Tags:        {', '.join(str(t) for t in tags[:8])}")

    # Volume & Liquidity
    print(f"\n{'─'*70}")
    print(f"  VOLUME & LIQUIDITY")
    print(f"{'─'*70}")
    print(f"  Total volume:      {fmt_usdc(volume_total)}")
    print(f"  24h volume:        {fmt_usdc(volume_24h)}")
    print(f"  Liquidity:         {fmt_usdc(liquidity)}")

    # Live prices & order book summary per outcome
    client = get_client(authenticated=False)
    print(f"\n{'─'*70}")
    print(f"  LIVE PRICES")
    print(f"{'─'*70}")
    print(f"  {'OUTCOME':<8} {'PRICE':>7}  {'IMPL_PROB':>9}  {'1H':>18}  "
          f"{'24H':>18}  {'7D':>18}  {'TOKEN_ID'}")
    print(f"  {'-'*8} {'-'*7}  {'-'*9}  {'-'*18}  {'-'*18}  {'-'*18}  {'-'*20}")

    for tok in tokens:
        outcome = tok.get("outcome", "?")
        tid = tok.get("token_id", "")
        price_stored = float(tok.get("price", 0))

        try:
            mid = client.get_midpoint(tid)
            price_live = float(mid.get("mid", price_stored))
        except Exception:
            price_live = price_stored

        p1h = price_change(tid, 1) if tid else "N/A"
        p24h = price_change(tid, 24) if tid else "N/A"
        p7d = price_change(tid, 168) if tid else "N/A"

        print(f"  {outcome:<8} {price_live:7.4f}  {price_live*100:8.1f}%  "
              f"{p1h:>18}  {p24h:>18}  {p7d:>18}  {tid[:20]}")

    # Order book depth
    if tokens:
        print(f"\n{'─'*70}")
        print(f"  ORDERBOOK DEPTH")
        print(f"{'─'*70}")
        for tok in tokens:
            tid = tok.get("token_id", "")
            outcome = tok.get("outcome", "?")
            if not tid:
                continue
            try:
                book = client.get_order_book(tid)
                bids = sorted(book.bids or [], key=lambda x: float(x.price),
                              reverse=True)[:3]
                asks = sorted(book.asks or [], key=lambda x: float(x.price))[:3]
                bid_depth = sum(float(b.size) for b in bids)
                ask_depth = sum(float(a.size) for a in asks)
                spread_val = (float(asks[0].price) - float(bids[0].price)) if (bids and asks) else 0
                print(f"  [{outcome}]  bid depth: ${bid_depth:,.1f}  "
                      f"ask depth: ${ask_depth:,.1f}  "
                      f"spread: {spread_val:.4f} ({spread_val*100:.2f}%)")
            except Exception:
                pass

    # Holder / trader stats from Data API
    print(f"\n{'─'*70}")
    print(f"  HOLDER & ACTIVITY DATA")
    print(f"{'─'*70}")
    try:
        if condition_id:
            resp = requests.get(f"{DATA_API}/markets",
                                params={"condition_ids": condition_id},
                                timeout=8)
            if resp.ok:
                dm = resp.json()
                if dm:
                    dm = dm[0] if isinstance(dm, list) else dm
                    holders = dm.get("uniqueHolders", dm.get("holders", "N/A"))
                    oi = dm.get("openInterest", "N/A")
                    print(f"  Unique holders:    {holders}")
                    print(f"  Open interest:     {fmt_usdc(oi) if oi != 'N/A' else 'N/A'}")
    except Exception:
        pass

    # Recent trades
    try:
        if condition_id:
            resp = requests.get(f"{DATA_API}/trades",
                                params={"market": condition_id,
                                        "limit": args.trades},
                                timeout=8)
            trades = resp.json() if resp.ok else []
            if trades:
                print(f"\n{'─'*70}")
                print(f"  RECENT TRADES (last {len(trades)})")
                print(f"{'─'*70}")
                print(f"  {'DATE':<12} {'SIDE':<5} {'PRICE':>7}  "
                      f"{'SIZE':>9}  {'TOTAL':>9}")
                print(f"  {'-'*12} {'-'*5} {'-'*7}  {'-'*9}  {'-'*9}")
                for tr in trades:
                    date = str(tr.get("timestamp",
                                      tr.get("createdAt", "?")))[:10]
                    side = tr.get("side", tr.get("makerAction", "?")).upper()[:4]
                    tp = float(tr.get("price", 0))
                    ts = float(tr.get("size", tr.get("amount", 0)))
                    print(f"  {date:<12} {side:<5} {tp:7.4f}  "
                          f"${ts:>8,.2f}  ${tp*ts:>8,.2f}")
    except Exception:
        pass

    # Top holders
    try:
        if condition_id:
            resp = requests.get(f"{DATA_API}/holders",
                                params={"condition_id": condition_id,
                                        "limit": args.holders},
                                timeout=8)
            if resp.ok:
                holders_data = resp.json()
                if holders_data:
                    print(f"\n{'─'*70}")
                    print(f"  TOP {args.holders} HOLDERS")
                    print(f"{'─'*70}")
                    print(f"  {'ADDRESS':<20} {'OUTCOME':<8} {'SIZE':>10}  "
                          f"{'VALUE':>10}")
                    print(f"  {'-'*20} {'-'*8} {'-'*10}  {'-'*10}")
                    for h in holders_data[:args.holders]:
                        addr = str(h.get("holder", "?"))[:18] + ".."
                        out = h.get("outcome", "?")[:7]
                        sz = float(h.get("size", 0))
                        val = float(h.get("value", h.get("currentValue", 0)))
                        print(f"  {addr:<20} {out:<8} {sz:>10,.2f}  "
                              f"${val:>9,.2f}")
    except Exception:
        pass

    print(f"\n{'='*70}\n")


if __name__ == "__main__":
    main()
