#!/usr/bin/env python3
"""
Browse and search Polymarket markets.
Usage:
  python markets.py                        # top markets by volume
  python markets.py --query "US election"  # search
  python markets.py --tag politics --limit 20
  python markets.py --market-id SLUG_OR_ID # single market detail
"""
import sys, requests, argparse, json
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))
from _client import GAMMA_API

def format_price(p):
    if p is None:
        return "  N/A "
    return f"{float(p)*100:5.1f}%"

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--query", "-q", default="")
    parser.add_argument("--tag", "-t", default="")
    parser.add_argument("--limit", "-n", type=int, default=15)
    parser.add_argument("--market-id", "-m", default="")
    parser.add_argument("--active", action="store_true", default=True)
    args = parser.parse_args()

    if args.market_id:
        # Single market detail
        url = f"{GAMMA_API}/markets/{args.market_id}"
        resp = requests.get(url)
        if not resp.ok:
            # try slug
            resp = requests.get(f"{GAMMA_API}/markets", params={"slug": args.market_id})
            data = resp.json()
            market = data[0] if data else None
        else:
            market = resp.json()

        if not market:
            print(f"Market '{args.market_id}' not found.")
            sys.exit(1)

        print(f"\n{'='*60}")
        print(f"  {market.get('question', 'Unknown')}")
        print(f"{'='*60}")
        print(f"  ID:          {market.get('id','')}")
        print(f"  Slug:        {market.get('slug','')}")
        print(f"  Status:      {'Active' if market.get('active') else 'Closed'}")
        print(f"  Close date:  {market.get('endDate','?')}")
        print(f"  Volume:      ${float(market.get('volume',0)):,.0f}")
        print(f"  Liquidity:   ${float(market.get('liquidity',0)):,.0f}")

        outcomes = market.get("outcomes", [])
        tokens = market.get("tokens", [])
        if tokens:
            print(f"\n  Outcomes:")
            for t in tokens:
                print(f"    [{t.get('outcome','?')}]  token_id: {t.get('token_id','')}")
        print()
        return

    # List markets
    params = {"limit": args.limit, "active": "true" if args.active else "false"}
    if args.query:
        # Use search endpoint
        resp = requests.get(f"{GAMMA_API}/events", params={"q": args.query, "limit": args.limit})
        events = resp.json() if resp.ok else []
        markets = []
        for ev in events:
            markets.extend(ev.get("markets", []))
        markets = markets[:args.limit]
    else:
        if args.tag:
            params["tag"] = args.tag
        params["order"] = "volume24hr"
        params["ascending"] = "false"
        resp = requests.get(f"{GAMMA_API}/markets", params=params)
        markets = resp.json() if resp.ok else []

    if not markets:
        print("No markets found.")
        return

    print(f"\n{'='*90}")
    print(f"  {'MARKET':<52} {'YES':>6}  {'NO':>6}  {'VOL 24h':>10}  {'CLOSE':>10}")
    print(f"  {'-'*52} {'-'*6}  {'-'*6}  {'-'*10}  {'-'*10}")

    for m in markets:
        question = m.get("question", "?")[:51]
        tokens = m.get("tokens", [])
        yes_price = no_price = None
        for t in tokens:
            if t.get("outcome", "").upper() == "YES":
                yes_price = t.get("price")
            elif t.get("outcome", "").upper() == "NO":
                no_price = t.get("price")

        vol = float(m.get("volume24hr", m.get("volume", 0)) or 0)
        close = (m.get("endDate") or "?")[:10]

        print(f"  {question:<52} {format_price(yes_price):>6}  {format_price(no_price):>6}  ${vol:>9,.0f}  {close:>10}")
        # Print token IDs for easy copy
        for t in tokens:
            tid = t.get("token_id", "")
            out = t.get("outcome", "?")
            if tid:
                print(f"    → {out} token_id: {tid}")

    print(f"\n  Showing {len(markets)} markets")
    print(f"{'='*90}\n")

if __name__ == "__main__":
    main()
