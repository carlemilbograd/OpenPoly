#!/usr/bin/env python3
"""
Execute an arbitrage opportunity on Polymarket.

Finds or accepts a specific arbitrage opportunity, calculates optimal
position sizes for all outcome legs, shows the trade plan, and executes
with a single confirmation.

Math (binary):
  Buy S shares of YES at p_yes  +  S shares of NO at p_no
  Cost  = S * (p_yes + p_no)
  Payoff = S  (whichever outcome wins pays 1.0)
  Profit = S * (1 - p_yes - p_no)
  ROI    = (1 - sum) / sum

Usage:
  python arbitrage_execute.py --market-id MARKET_ID    # execute for specific market
  python arbitrage_execute.py --scan                   # scan & pick the best arb
  python arbitrage_execute.py --scan --min-gap 0.04 --budget 100
"""
import sys, argparse, requests, json
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from _client import GAMMA_API, get_client

FEE_ESTIMATE = 0.02   # ~2% round-trip
MIN_LIQUIDITY = 10.0  # minimum USDC depth per leg


def get_live_prices(client, token_ids: list) -> dict:
    prices = {}
    for tid in token_ids:
        try:
            resp = client.get_midpoint(tid)
            prices[tid] = float(resp.get("mid", 0))
        except Exception:
            prices[tid] = None
    return prices


def get_depth(client, token_id: str, side: str, target_size: float) -> float:
    """
    Return depth available at or better than the market price for `target_size`.
    Returns how many shares are available within 2% of mid.
    """
    try:
        book = client.get_order_book(token_id)
        if side == "BUY":
            levels = sorted(book.asks or [], key=lambda x: float(x.price))
        else:
            levels = sorted(book.bids or [], key=lambda x: float(x.price),
                            reverse=True)
        mid_resp = client.get_midpoint(token_id)
        mid = float(mid_resp.get("mid", 0))
        threshold = mid * 1.02 if side == "BUY" else mid * 0.98
        total = 0.0
        for level in levels:
            p = float(level.price)
            if (side == "BUY" and p <= threshold) or (side == "SELL" and p >= threshold):
                total += float(level.size)
        return total
    except Exception:
        return 0.0


def scan_for_arb(client, limit: int, min_gap: float, tag: str) -> list:
    """Scan markets and return arbitrage opportunities sorted by profit."""
    params = {
        "limit": limit,
        "active": "true",
        "order": "volume24hr",
        "ascending": "false",
    }
    if tag:
        params["tag"] = tag

    resp = requests.get(f"{GAMMA_API}/markets", params=params, timeout=15)
    markets = resp.json() if resp.ok else []

    opportunities = []
    for market in markets:
        tokens = market.get("tokens", [])
        if len(tokens) < 2:
            continue

        token_ids = [t.get("token_id", "") for t in tokens if t.get("token_id")]
        live_prices = get_live_prices(client, token_ids)

        outcome_prices = []
        for t in tokens:
            tid = t.get("token_id", "")
            price = live_prices.get(tid) or float(t.get("price", 0) or 0)
            if price > 0:
                outcome_prices.append({
                    "outcome": t.get("outcome", "?"),
                    "token_id": tid,
                    "price": price,
                })

        if len(outcome_prices) < 2:
            continue

        total = sum(o["price"] for o in outcome_prices)
        gap = 1.0 - total
        net_profit_pct = gap - FEE_ESTIMATE

        if gap < min_gap or net_profit_pct <= 0:
            continue

        opportunities.append({
            "question": market.get("question", "?"),
            "market_id": market.get("id", ""),
            "outcomes": outcome_prices,
            "total": total,
            "gap": gap,
            "net_profit_pct": net_profit_pct,
            "volume_24h": float(market.get("volume24hr", 0) or 0),
        })

    opportunities.sort(key=lambda x: x["net_profit_pct"], reverse=True)
    return opportunities


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--market-id", "-m", default="",
                        help="Market ID to execute arb on")
    parser.add_argument("--scan", action="store_true",
                        help="Auto-scan and pick the best arb opportunity")
    parser.add_argument("--budget", "-b", type=float, default=50.0,
                        help="Total USDC budget to deploy (default 50)")
    parser.add_argument("--min-gap", type=float, default=0.03,
                        help="Minimum arb gap required (default 0.03 = 3%%)")
    parser.add_argument("--scan-limit", type=int, default=100,
                        help="Markets to scan (default 100)")
    parser.add_argument("--tag", default="",
                        help="Filter scan by tag")
    parser.add_argument("--confirm", action="store_true",
                        help="Skip interactive confirmation")
    args = parser.parse_args()

    if not args.market_id and not args.scan:
        print("Provide --market-id or --scan")
        sys.exit(1)

    client = get_client(authenticated=True)

    opportunity = None

    if args.scan:
        print(f"\n  Scanning for arbitrage (min gap {args.min_gap*100:.0f}%)...")
        opps = scan_for_arb(client, args.scan_limit, args.min_gap, args.tag)
        if not opps:
            print(f"  No arbitrage opportunities found above "
                  f"{args.min_gap*100:.0f}% gap.\n")
            sys.exit(0)
        opportunity = opps[0]
        print(f"  Best opportunity: {opportunity['question'][:60]}")
        print(f"  Net profit: {opportunity['net_profit_pct']*100:.2f}%  "
              f"(gap {opportunity['gap']*100:.2f}%)\n")

    elif args.market_id:
        resp = requests.get(f"{GAMMA_API}/markets/{args.market_id}", timeout=8)
        if not resp.ok:
            resp = requests.get(f"{GAMMA_API}/markets",
                                params={"slug": args.market_id, "limit": 1},
                                timeout=8)
            data = resp.json() if resp.ok else []
            market = data[0] if data else None
        else:
            market = resp.json()

        if not market:
            print(f"  Market '{args.market_id}' not found.")
            sys.exit(1)

        tokens = market.get("tokens", [])
        token_ids = [t.get("token_id", "") for t in tokens if t.get("token_id")]
        live_prices = get_live_prices(client, token_ids)

        outcome_prices = []
        for t in tokens:
            tid = t.get("token_id", "")
            price = live_prices.get(tid) or float(t.get("price", 0) or 0)
            if price > 0:
                outcome_prices.append({
                    "outcome": t.get("outcome", "?"),
                    "token_id": tid,
                    "price": price,
                })

        total = sum(o["price"] for o in outcome_prices)
        gap = 1.0 - total
        net_profit_pct = gap - FEE_ESTIMATE

        opportunity = {
            "question": market.get("question", "?"),
            "market_id": market.get("id", ""),
            "outcomes": outcome_prices,
            "total": total,
            "gap": gap,
            "net_profit_pct": net_profit_pct,
        }

        if gap < args.min_gap:
            print(f"\n  Gap is {gap*100:.2f}% — below min-gap "
                  f"({args.min_gap*100:.0f}%).")
            print(f"  Use --min-gap {gap:.3f} to force execution.\n")
            sys.exit(0)

        if net_profit_pct <= 0:
            print(f"\n  Gap ({gap*100:.2f}%) is smaller than estimated fees "
                  f"({FEE_ESTIMATE*100:.0f}%). Not profitable after fees.\n")
            sys.exit(0)

    # ── Plan the trade ────────────────────────────────────────────────────────
    opp = opportunity
    n = len(opp["outcomes"])
    total_price = opp["total"]

    # Shares: S = budget / total_price (same S for all outcomes)
    # Each leg costs S * price_i USDC
    # After resolution: get back S USDC (profit = S - budget)
    shares = args.budget / total_price
    profit = shares - args.budget
    roi = profit / args.budget * 100

    print(f"\n{'='*65}")
    print(f"  ARB TRADE PLAN")
    print(f"{'='*65}")
    print(f"  Market:   {opp['question'][:62]}")
    print(f"  Gap:      {opp['gap']*100:.3f}%  |  "
          f"Net after fees: ~{opp['net_profit_pct']*100:.2f}%")
    print(f"  Budget:   ${args.budget:.2f} USDC")
    print(f"  Shares:   {shares:.4f} per outcome")
    print(f"  Profit:   +${profit:.4f} USDC  ({roi:.2f}% ROI)")
    print(f"\n  {'OUTCOME':<8} {'TOKEN_ID':<22} {'PRICE':>7}  "
          f"{'SHARES':>10}  {'COST':>9}")
    print(f"  {'-'*8} {'-'*22} {'-'*7}  {'-'*10}  {'-'*9}")

    legs = []
    for o in opp["outcomes"]:
        cost = shares * o["price"]
        depth = get_depth(client, o["token_id"], "BUY", cost)
        depth_warn = "  ⚠️ LOW LIQUIDITY" if depth < cost * 0.9 else ""
        print(f"  {o['outcome']:<8} {o['token_id'][:20]:<22} "
              f"{o['price']:7.4f}  {shares:>10.4f}  ${cost:>8.2f}"
              f"{depth_warn}")
        legs.append({
            "token_id": o["token_id"],
            "side": "BUY",
            "price": o["price"],
            "size": cost,
        })

    print(f"\n  Total cost:    ${sum(l['size'] for l in legs):.4f} USDC")
    print(f"  (sum should ≈ budget: ${args.budget:.2f})")
    print(f"{'='*65}")

    if not args.confirm:
        confirm = input("\n  Execute all legs? (yes/no): ").strip().lower()
        if confirm not in ("yes", "y"):
            print("  Cancelled.\n")
            sys.exit(0)

    # ── Execute legs ─────────────────────────────────────────────────────────
    from py_clob_client.clob_types import OrderArgs, OrderType
    from py_clob_client.order_builder.constants import BUY

    print(f"\n  Placing {len(legs)} orders...")
    order_ids = []
    for i, leg in enumerate(legs, 1):
        o_args = OrderArgs(
            token_id=leg["token_id"],
            price=leg["price"],
            size=leg["size"],
            side=BUY,
        )
        try:
            signed = client.create_order(o_args)
            resp = client.post_order(signed, OrderType.GTC)
            oid = (resp or {}).get("orderID", (resp or {}).get("id", "?"))
            print(f"  [{i}] ✅ {opp['outcomes'][i-1]['outcome']}  "
                  f" order {str(oid)[:16]}...")
            order_ids.append(oid)
        except Exception as e:
            print(f"  [{i}] ❌ {opp['outcomes'][i-1]['outcome']} FAILED: {e}")

    print(f"\n  {len([x for x in order_ids if x != '?'])}/{len(legs)} "
          f"orders submitted successfully.")
    print(f"  Monitor: python scripts/open_orders.py")
    print(f"  Cancel:  python scripts/cancel.py --all\n")


if __name__ == "__main__":
    main()
