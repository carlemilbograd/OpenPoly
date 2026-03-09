#!/usr/bin/env python3
"""
Place orders on Polymarket.
⚠️  ALWAYS confirm with user before running.

Usage:
  # Limit order (GTC):
  python trade.py --token-id TOKEN_ID --side BUY --price 0.55 --size 10

  # Market order (FOK):
  python trade.py --token-id TOKEN_ID --side BUY --size 25 --type FOK

  # Limit with expiry (GTD):
  python trade.py --token-id TOKEN_ID --side SELL --price 0.70 --size 5 --type GTD --expiry 3600
"""
import sys, argparse
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))
from _client import get_client

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--token-id", "-t", required=True)
    parser.add_argument("--side", "-s", required=True, choices=["BUY", "SELL"])
    parser.add_argument("--price", "-p", type=float, default=None,
                        help="Limit price (0.01-0.99). Omit for market orders.")
    parser.add_argument("--size", "-z", type=float, required=True,
                        help="Size in USDC")
    parser.add_argument("--type", dest="order_type", default="GTC",
                        choices=["GTC", "GTD", "FOK"],
                        help="GTC=limit, FOK=market fill-or-kill, GTD=limit with expiry")
    parser.add_argument("--expiry", type=int, default=3600,
                        help="GTD expiry in seconds (default 3600)")
    parser.add_argument("--confirm", action="store_true",
                        help="Skip interactive confirmation (use only from trusted automation)")
    args = parser.parse_args()

    from py_clob_client.clob_types import OrderArgs, MarketOrderArgs, OrderType
    from py_clob_client.order_builder.constants import BUY, SELL

    side_const = BUY if args.side == "BUY" else SELL

    order_type_map = {
        "GTC": OrderType.GTC,
        "GTD": OrderType.GTD,
        "FOK": OrderType.FOK,
    }
    order_type = order_type_map[args.order_type]

    # Preview
    print(f"\n{'='*50}")
    print(f"  📋 ORDER PREVIEW")
    print(f"{'='*50}")
    print(f"  Token ID:   {args.token_id}")
    print(f"  Side:       {args.side}")
    print(f"  Type:       {args.order_type}")
    if args.price:
        print(f"  Price:      {args.price:.4f}  ({args.price*100:.1f}%)")
    else:
        print(f"  Price:      MARKET")
    print(f"  Size:       ${args.size:.2f} USDC")
    if args.price:
        shares = args.size / args.price
        print(f"  Shares:     ~{shares:.2f}")
        print(f"  Max profit: ~${shares - args.size:.2f}")
    if args.order_type == "GTD":
        print(f"  Expiry:     {args.expiry}s ({args.expiry//60} min)")
    print(f"{'='*50}")

    if not args.confirm:
        confirm = input("\n  ⚠️  Confirm order? (yes/no): ").strip().lower()
        if confirm not in ("yes", "y"):
            print("  Order cancelled.")
            sys.exit(0)

    client = get_client(authenticated=True)

    try:
        if args.order_type == "FOK":
            # Market order
            mo_args = MarketOrderArgs(
                token_id=args.token_id,
                amount=args.size,
                side=side_const,
                order_type=order_type,
            )
            signed = client.create_market_order(mo_args)
            resp = client.post_order(signed, order_type)
        else:
            # Limit order
            o_args = OrderArgs(
                token_id=args.token_id,
                price=args.price,
                size=args.size,
                side=side_const,
            )
            signed = client.create_order(o_args)
            resp = client.post_order(signed, order_type)

        print(f"\n  ✅ Order submitted!")
        print(f"  Response: {resp}")
        if isinstance(resp, dict):
            order_id = resp.get("orderID") or resp.get("id") or ""
            if order_id:
                print(f"  Order ID: {order_id}")
                print(f"  Cancel with: python cancel.py --order-id {order_id}")
        print()

    except Exception as e:
        print(f"\n  ❌ Order failed: {e}")
        print("  Check credentials, balance, and token ID.")
        sys.exit(1)

if __name__ == "__main__":
    main()
