#!/usr/bin/env python3
"""
Show portfolio: USDC balance + open positions.
Usage: python portfolio.py
"""
import sys, os, requests, json
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))
from _client import get_client, DATA_API, GAMMA_API

def fmt_usdc(v):
    return f"${float(v):,.2f}"

def main():
    client = get_client(authenticated=True)

    # Derive wallet address from signer
    try:
        address = client.get_address()
    except Exception:
        address = os.getenv("POLYMARKET_FUNDER_ADDRESS") or "unknown"

    print(f"\n{'='*55}")
    print(f"  POLYMARKET PORTFOLIO  —  {address[:10]}...{address[-6:]}")
    print(f"{'='*55}")

    # Open positions
    try:
        resp = requests.get(f"{DATA_API}/positions", params={"user": address, "sizeThreshold": "0.01"})
        positions = resp.json() if resp.ok else []
    except Exception as e:
        positions = []
        print(f"Warning: could not fetch positions: {e}")

    if not positions:
        print("\n  No open positions found.\n")
    else:
        print(f"\n  {'MARKET':<45} {'SIDE':<5} {'SIZE':>8}  {'PRICE':>7}  {'VALUE':>8}")
        print(f"  {'-'*45} {'-'*5} {'-'*8}  {'-'*7}  {'-'*8}")
        total_value = 0.0
        for pos in positions:
            question = pos.get("title", pos.get("market", "Unknown"))[:44]
            outcome = pos.get("outcome", "?")
            size = float(pos.get("size", 0))
            cur_price = float(pos.get("curPrice", pos.get("currentPrice", 0)))
            value = size * cur_price
            total_value += value
            print(f"  {question:<45} {outcome:<5} {size:>8.2f}  {cur_price:>7.3f}  {fmt_usdc(value):>8}")
        print(f"\n  Total position value: {fmt_usdc(total_value)}")

    # USDC balance via CLOB
    try:
        bal = client.get_balance_allowance(asset_type=1)  # 1 = USDC
        usdc = float(bal.get("balance", 0)) / 1e6
        print(f"  USDC cash balance:    {fmt_usdc(usdc)}")
    except Exception as e:
        print(f"  (Could not fetch USDC balance: {e})")

    print(f"\n{'='*55}\n")

if __name__ == "__main__":
    main()
