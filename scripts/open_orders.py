#!/usr/bin/env python3
"""
List open (unfilled/partially filled) orders for the account.

Usage:
  python open_orders.py                        # all open orders
  python open_orders.py --market-id TOKEN_ID   # orders for one market
  python open_orders.py --side BUY             # filter by side
  python open_orders.py --json                 # machine-readable output
"""
import sys, argparse, json
from pathlib import Path
from datetime import datetime, timezone

sys.path.insert(0, str(Path(__file__).parent))
from _client import get_client, GAMMA_API

try:
    import requests
except ImportError:
    import os; os.system("pip install requests --quiet --break-system-packages")
    import requests


def ts_to_age(ts_str: str) -> str:
    """Convert an ISO or unix timestamp string to a human-readable age."""
    try:
        if ts_str and ts_str.isdigit():
            dt = datetime.fromtimestamp(int(ts_str), tz=timezone.utc)
        elif ts_str:
            dt = datetime.fromisoformat(ts_str.replace("Z", "+00:00"))
        else:
            return "?"
        age = datetime.now(timezone.utc) - dt
        s = int(age.total_seconds())
        if s < 60:
            return f"{s}s"
        if s < 3600:
            return f"{s//60}m"
        if s < 86400:
            return f"{s//3600}h {(s%3600)//60}m"
        return f"{s//86400}d {(s%86400)//3600}h"
    except Exception:
        return "?"


def resolve_market_question(token_id: str) -> str:
    """Best-effort lookup of a market question from a token_id."""
    try:
        resp = requests.get(
            f"{GAMMA_API}/markets",
            params={"clob_token_ids": token_id},
            timeout=5,
        )
        if resp.ok:
            markets = resp.json()
            if markets:
                return markets[0].get("question", "")[:50]
    except Exception:
        pass
    return ""


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--market-id", "-m", default="",
                        help="Filter by market token ID")
    parser.add_argument("--side", "-s", default="",
                        choices=["", "BUY", "SELL"],
                        help="Filter by side")
    parser.add_argument("--json", dest="as_json", action="store_true",
                        help="Output raw JSON")
    args = parser.parse_args()

    client = get_client(authenticated=True)

    try:
        from py_clob_client.clob_types import OpenOrderParams
        params = OpenOrderParams(
            market=args.market_id if args.market_id else None,
            asset_id=args.market_id if args.market_id else None,
        )
        orders = client.get_orders(params=params) or []
    except Exception as e:
        print(f"Error fetching orders: {e}")
        sys.exit(1)

    # Filter by side
    if args.side:
        orders = [o for o in orders if o.get("side", "").upper() == args.side]

    if args.as_json:
        print(json.dumps(orders, indent=2))
        return

    if not orders:
        print("\n  No open orders found.\n")
        return

    print(f"\n{'='*90}")
    print(f"  OPEN ORDERS  ({len(orders)} total)")
    print(f"{'='*90}")
    print(f"  {'ORDER ID':<14} {'SIDE':<5} {'PRICE':>7}  {'SIZE':>8}  "
          f"{'FILLED':>8}  {'REMAIN':>8}  {'TYPE':<5}  {'AGE':>8}  {'MARKET'}")
    print(f"  {'-'*14} {'-'*5} {'-'*7}  {'-'*8}  {'-'*8}  {'-'*8}  {'-'*5}  "
          f"{'-'*8}  {'-'*40}")

    total_exposure = 0.0
    for o in orders:
        oid = str(o.get("id", o.get("orderID", "?")))[:13]
        side = o.get("side", "?").upper()[:4]
        price = float(o.get("price", 0))
        size_orig = float(o.get("original_size", o.get("size", 0)))
        size_filled = float(o.get("size_matched", o.get("filled", 0)))
        size_remain = float(o.get("size_open", size_orig - size_filled))
        order_type = str(o.get("type", o.get("orderType", "GTC")))[:5]
        created = o.get("created_at", o.get("createdAt", ""))
        age = ts_to_age(str(created))
        token_id = o.get("asset_id", o.get("token_id", o.get("tokenID", "")))
        question = resolve_market_question(token_id)[:40] if token_id else ""
        exposure = size_remain * price if side == "BUY" else size_remain
        total_exposure += exposure

        pct_filled = (size_filled / size_orig * 100) if size_orig > 0 else 0
        filled_str = f"{size_filled:.2f} ({pct_filled:.0f}%)"

        print(f"  {oid:<14} {side:<5} {price:7.4f}  {size_orig:8.2f}  "
              f"{filled_str:>8}  {size_remain:8.2f}  {order_type:<5}  "
              f"{age:>8}  {question}")

    print(f"\n  Total open orders: {len(orders)}")
    print(f"  Total USDC exposure (approx): ${total_exposure:,.2f}")
    print(f"\n  To cancel:  python scripts/cancel.py --order-id ORDER_ID")
    print(f"  Cancel all: python scripts/cancel.py --all")
    print(f"{'='*90}\n")


if __name__ == "__main__":
    main()
