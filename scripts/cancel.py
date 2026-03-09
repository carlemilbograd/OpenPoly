#!/usr/bin/env python3
"""
Cancel Polymarket orders.
Usage:
  python cancel.py --order-id ORDER_ID
  python cancel.py --all
  python cancel.py --market-id TOKEN_ID
"""
import sys, argparse
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))
from _client import get_client

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--order-id", default="")
    parser.add_argument("--all", action="store_true")
    parser.add_argument("--market-id", default="",
                        help="Cancel all orders for a specific market token ID")
    args = parser.parse_args()

    if not (args.order_id or args.all or args.market_id):
        parser.print_help()
        sys.exit(1)

    client = get_client(authenticated=True)

    try:
        if args.all:
            confirm = input("Cancel ALL open orders? (yes/no): ").strip().lower()
            if confirm not in ("yes", "y"):
                print("Cancelled.")
                sys.exit(0)
            resp = client.cancel_all()
            print(f"✅ All orders cancelled: {resp}")

        elif args.market_id:
            resp = client.cancel_market_orders(market=args.market_id)
            print(f"✅ Market orders cancelled: {resp}")

        else:
            resp = client.cancel(order_id=args.order_id)
            print(f"✅ Order {args.order_id} cancelled: {resp}")

    except Exception as e:
        print(f"❌ Cancel failed: {e}")
        sys.exit(1)

if __name__ == "__main__":
    main()
