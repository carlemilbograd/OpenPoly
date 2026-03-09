#!/usr/bin/env python3
"""
Show orderbook for a market token.
Usage: python orderbook.py --token-id TOKEN_ID [--depth 10]
"""
import sys, argparse
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))
from _client import get_client

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--token-id", "-t", required=True)
    parser.add_argument("--depth", "-d", type=int, default=5)
    args = parser.parse_args()

    client = get_client(authenticated=False)

    try:
        mid = client.get_midpoint(args.token_id)
        price_buy = client.get_price(args.token_id, side="BUY")
        price_sell = client.get_price(args.token_id, side="SELL")
        book = client.get_order_book(args.token_id)
    except Exception as e:
        print(f"Error fetching orderbook: {e}")
        sys.exit(1)

    mid_val = float(mid.get("mid", 0))
    spread = float(price_sell.get("price", 0)) - float(price_buy.get("price", 0))

    print(f"\n{'='*45}")
    print(f"  TOKEN: {args.token_id[:16]}...")
    print(f"  Mid price: {mid_val:.4f}  ({mid_val*100:.1f}%)")
    print(f"  Spread:    {spread:.4f}  ({spread*100:.2f}%)")
    print(f"{'='*45}")

    asks = sorted(book.asks, key=lambda x: float(x.price))[:args.depth]
    bids = sorted(book.bids, key=lambda x: float(x.price), reverse=True)[:args.depth]

    print(f"\n  {'ASKS (SELL)'}")
    print(f"  {'Price':>8}  {'Size':>10}  {'Total':>10}")
    print(f"  {'-'*8}  {'-'*10}  {'-'*10}")
    for ask in reversed(asks):
        p = float(ask.price)
        s = float(ask.size)
        print(f"  {p:8.4f}  {s:10.2f}  ${p*s:9.2f}")

    print(f"\n  --- MID: {mid_val:.4f} ---")

    print(f"\n  {'BIDS (BUY)'}")
    print(f"  {'Price':>8}  {'Size':>10}  {'Total':>10}")
    print(f"  {'-'*8}  {'-'*10}  {'-'*10}")
    for bid in bids:
        p = float(bid.price)
        s = float(bid.size)
        print(f"  {p:8.4f}  {s:10.2f}  ${p*s:9.2f}")

    print()

if __name__ == "__main__":
    main()
