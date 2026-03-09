#!/usr/bin/env python3
"""
Scan Polymarket for arbitrage opportunities.

For binary markets: YES price + NO price should sum to ~1.0 (minus ~2% fees).
  If sum < 0.97 → buy both → guaranteed profit at resolution.
  If sum > 1.03 → sell both → guaranteed profit.

For multi-outcome markets: all outcome prices should sum to 1.0.
  If sum < 0.97 → buy all outcomes.

Usage:
  python arbitrage.py
  python arbitrage.py --min-gap 0.02 --limit 100 --tag politics
"""
import sys, requests, argparse, json
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))
from _client import GAMMA_API, get_client

FEE_ESTIMATE = 0.02  # ~2% round-trip fee estimate

def get_live_prices(client, token_ids: list[str]) -> dict:
    """Fetch live midpoint prices for a list of token IDs."""
    prices = {}
    for tid in token_ids:
        try:
            resp = client.get_midpoint(tid)
            prices[tid] = float(resp.get("mid", 0))
        except Exception:
            prices[tid] = None
    return prices

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--min-gap", type=float, default=0.03,
                        help="Minimum arb gap to report (default 0.03 = 3%%)")
    parser.add_argument("--limit", type=int, default=50,
                        help="Number of markets to scan (default 50)")
    parser.add_argument("--tag", default="",
                        help="Filter by tag (e.g. politics, crypto, sports)")
    parser.add_argument("--live", action="store_true",
                        help="Fetch live CLOB prices (slower but accurate)")
    args = parser.parse_args()

    print(f"\n🔍 Scanning {args.limit} markets for arbitrage opportunities (min gap: {args.min_gap*100:.0f}%)...")

    params = {
        "limit": args.limit,
        "active": "true",
        "order": "volume24hr",
        "ascending": "false",
    }
    if args.tag:
        params["tag"] = args.tag

    resp = requests.get(f"{GAMMA_API}/markets", params=params)
    markets = resp.json() if resp.ok else []

    if not markets:
        print("No markets found.")
        return

    client = get_client(authenticated=False) if args.live else None

    opportunities = []

    for market in markets:
        tokens = market.get("tokens", [])
        if not tokens:
            continue

        question = market.get("question", "?")
        market_id = market.get("id", "")

        if args.live and client:
            token_ids = [t.get("token_id", "") for t in tokens if t.get("token_id")]
            live_prices = get_live_prices(client, token_ids)
            for t in tokens:
                tid = t.get("token_id", "")
                if tid in live_prices and live_prices[tid] is not None:
                    t["_live_price"] = live_prices[tid]

        # Collect prices
        outcome_prices = []
        for t in tokens:
            price = t.get("_live_price") if args.live else t.get("price")
            if price is not None:
                try:
                    outcome_prices.append((t.get("outcome", "?"), t.get("token_id", ""), float(price)))
                except (ValueError, TypeError):
                    pass

        if len(outcome_prices) < 2:
            continue

        total = sum(p for _, _, p in outcome_prices)

        # Arb if sum significantly != 1.0
        gap = abs(1.0 - total)
        if gap < args.min_gap:
            continue

        direction = "BUY ALL" if total < 1.0 else "SELL ALL"
        expected_profit = abs(1.0 - total) - FEE_ESTIMATE

        if expected_profit > 0:
            opportunities.append({
                "question": question,
                "market_id": market_id,
                "total": total,
                "gap": gap,
                "direction": direction,
                "profit_pct": expected_profit * 100,
                "outcomes": outcome_prices,
            })

    opportunities.sort(key=lambda x: x["profit_pct"], reverse=True)

    if not opportunities:
        print(f"\n  ✅ No arbitrage opportunities found above {args.min_gap*100:.0f}% gap.\n")
        return

    print(f"\n  🎯 Found {len(opportunities)} arbitrage opportunities!\n")
    print(f"  {'MARKET':<50} {'SUM':>6}  {'GAP':>6}  {'NET PROFIT':>10}  {'ACTION'}")
    print(f"  {'-'*50} {'-'*6}  {'-'*6}  {'-'*10}  {'-'*10}")

    for opp in opportunities[:20]:
        q = opp["question"][:49]
        print(f"  {q:<50} {opp['total']:6.3f}  {opp['gap']*100:5.1f}%  {opp['profit_pct']:9.1f}%  {opp['direction']}")
        for outcome, token_id, price in opp["outcomes"]:
            print(f"      [{outcome}]  price={price:.3f}  token_id={token_id[:20]}...")

    print(f"\n  ⚠️  Estimates exclude fees (~{FEE_ESTIMATE*100:.0f}%). Verify live liquidity before trading.")
    print(f"     Use orderbook.py to check depth before placing orders.\n")

if __name__ == "__main__":
    main()
