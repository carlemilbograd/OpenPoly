#!/usr/bin/env python3
"""
Show trade history for the account.
Usage: python history.py [--limit 20] [--market-id TOKEN_ID]
"""
import sys, os, requests, argparse
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))
from _client import get_client, DATA_API

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=20)
    parser.add_argument("--market-id", default="")
    args = parser.parse_args()

    client = get_client(authenticated=True)

    # For type 1/2 wallets the maker address in CLOB trades is the
    # funder/proxy address, NOT the derived signing key address.
    # Always prefer POLYMARKET_FUNDER_ADDRESS; fall back to signer.
    address = os.getenv("POLYMARKET_FUNDER_ADDRESS", "")
    if not address:
        try:
            address = client.get_address()
        except Exception:
            pass
    if not address:
        print("ERROR: set POLYMARKET_FUNDER_ADDRESS in .env")
        return

    params = {"user": address, "limit": args.limit}
    if args.market_id:
        params["market"] = args.market_id

    resp = requests.get(f"{DATA_API}/trades", params=params)
    if resp.ok:
        body = resp.json()
        # data-api returns paginated {"data": [...], "count": N, "next_cursor": "..."}
        # but fall back to bare-list format just in case
        trades = body.get("data", body) if isinstance(body, dict) else body
        if not isinstance(trades, list):
            trades = []
    else:
        trades = []

    if not trades:
        # CLOB fallback — authenticated request already scoped to your account
        try:
            clob_trades = client.get_trades() or []
            trades = clob_trades if isinstance(clob_trades, list) else []
        except Exception:
            trades = []

    if not trades:
        print(f"\n  No trades found for {address[:10]}...\n")
        return

    print(f"\n{'='*80}")
    print(f"  TRADE HISTORY  —  {address[:10]}...{address[-6:]}")
    print(f"{'='*80}")
    print(f"  {'DATE':<12} {'MARKET':<35} {'SIDE':<5} {'PRICE':>7}  {'SIZE':>8}  {'TOTAL':>8}")
    print(f"  {'-'*12} {'-'*35} {'-'*5} {'-'*7}  {'-'*8}  {'-'*8}")

    total_spent = 0
    for t in trades:
        # data-api uses unix ms or ISO timestamp
        ts = t.get("timestamp", t.get("createdAt", ""))
        if ts:
            try:
                ts_int = int(float(str(ts)))
                # unix ms if > 1e10, else unix s
                if ts_int > 1_000_000_000_000:
                    ts_int //= 1000
                from datetime import datetime, timezone
                date = datetime.fromtimestamp(ts_int, tz=timezone.utc).strftime("%Y-%m-%d")
            except Exception:
                date = str(ts)[:10]
        else:
            date = "?"

        market = str(t.get("title", t.get("market", t.get("conditionId", "?"))))[:34]
        # side: data-api uses "BUY"/"SELL"; also check outcome "Yes"/"No"
        side = (t.get("side") or t.get("makerAction") or t.get("type") or "?").upper()[:4]
        if side not in ("BUY", "SELL"):
            outcome = str(t.get("outcome", "")).upper()
            side = "BUY" if outcome in ("YES", "1") else ("SELL" if outcome in ("NO", "0") else side)
        price = float(t.get("price", 0))
        size = float(t.get("size", t.get("usdcSize", t.get("amount", 0))))
        total = price * size
        total_spent += total if side == "BUY" else -total
        print(f"  {date:<12} {market:<35} {side:<5} {price:7.4f}  {size:8.2f}  ${total:7.2f}")

    print(f"\n  Net flow: ${total_spent:+.2f} USDC ({len(trades)} trades)")
    print(f"{'='*80}\n")

if __name__ == "__main__":
    main()
