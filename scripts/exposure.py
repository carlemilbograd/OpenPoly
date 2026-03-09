#!/usr/bin/env python3
"""
Portfolio risk and exposure analysis.

Shows:
  - Capital at risk per market and as % of portfolio
  - USDC cash vs deployed capital ratio
  - Largest single-market concentration
  - Correlated positions (markets sharing the same tag/topic)
  - Kelly-suggested position cap vs actual size

Usage:
  python exposure.py
  python exposure.py --warn-threshold 0.20   # warn if >20% in one market
"""
import sys, os, argparse, requests
from pathlib import Path
from collections import defaultdict

sys.path.insert(0, str(Path(__file__).parent))
from _client import get_client, DATA_API, GAMMA_API


def fmt_usdc(v: float) -> str:
    return f"${v:>10,.2f}"


def fmt_pct(v: float) -> str:
    return f"{v*100:6.1f}%"


def bar(pct: float, width: int = 20) -> str:
    filled = int(pct * width)
    return "█" * filled + "░" * (width - filled)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--warn-threshold", type=float, default=0.25,
                        help="Warn if single market > this %% of total "
                             "(default 0.25 = 25%%)")
    args = parser.parse_args()

    client = get_client(authenticated=True)

    try:
        address = client.get_address()
    except Exception:
        address = os.getenv("POLYMARKET_FUNDER_ADDRESS", "")

    if not address:
        print("ERROR: Could not determine wallet address.")
        sys.exit(1)

    # Fetch positions
    try:
        resp = requests.get(
            f"{DATA_API}/positions",
            params={"user": address, "sizeThreshold": "0.001"},
            timeout=10,
        )
        positions = resp.json() if resp.ok else []
    except Exception as e:
        print(f"Error: {e}")
        sys.exit(1)

    # Fetch USDC balance
    try:
        from py_clob_client.clob_types import AssetType, BalanceAllowanceParams
        bal = client.get_balance_allowance(
            params=BalanceAllowanceParams(asset_type=AssetType.COLLATERAL)
        )
        usdc_cash = float(bal.get("balance", 0)) / 1e6
    except Exception:
        usdc_cash = 0.0

    if not positions and usdc_cash == 0:
        print("\n  No positions or balance found.\n")
        return

    # Build enriched position data
    enriched = []
    tag_groups: dict = defaultdict(list)

    for pos in positions:
        try:
            size = float(pos.get("size", 0))
            cur_price = float(pos.get("curPrice", pos.get("currentPrice", 0)))
            value = size * cur_price
            if value < 0.01:
                continue

            title = pos.get("title", pos.get("market", "?"))[:45]
            outcome = pos.get("outcome", "?")
            condition_id = pos.get("conditionId", pos.get("market", ""))

            # Get market tags for correlation detection
            tags = []
            if condition_id:
                try:
                    r = requests.get(
                        f"{GAMMA_API}/markets",
                        params={"condition_id": condition_id, "limit": 1},
                        timeout=5,
                    )
                    if r.ok:
                        mkt_data = r.json()
                        if mkt_data:
                            raw_tags = mkt_data[0].get("tags", [])
                            tags = [
                                t.get("label", t) if isinstance(t, dict) else t
                                for t in raw_tags
                            ]
                except Exception:
                    pass

            enriched.append({
                "title": title,
                "outcome": outcome,
                "size": size,
                "price": cur_price,
                "value": value,
                "condition_id": condition_id,
                "tags": tags,
            })

            for tag in tags:
                tag_groups[str(tag)].append(title)

        except Exception:
            continue

    if not enriched:
        print("\n  No open positions with value found.\n")
        return

    total_position_value = sum(p["value"] for p in enriched)
    total_portfolio = total_position_value + usdc_cash
    enriched.sort(key=lambda x: x["value"], reverse=True)

    print(f"\n{'='*70}")
    print(f"  PORTFOLIO EXPOSURE ANALYSIS")
    print(f"  Wallet: {address[:10]}...{address[-6:]}")
    print(f"{'='*70}")

    # Summary
    print(f"\n  USDC cash:          {fmt_usdc(usdc_cash)}")
    print(f"  Deployed capital:   {fmt_usdc(total_position_value)}  "
          f"({total_position_value/total_portfolio*100:.1f}% of portfolio)")
    print(f"  Total portfolio:    {fmt_usdc(total_portfolio)}")
    print(f"  Open positions:     {len(enriched)}")

    cash_ratio = usdc_cash / total_portfolio if total_portfolio else 0
    if cash_ratio < 0.10:
        print(f"\n  ⚠️  Only {cash_ratio*100:.0f}% cash — limited dry powder for new trades.")
    elif cash_ratio > 0.80:
        print(f"\n  ℹ️  {cash_ratio*100:.0f}% cash — large amount undeployed.")

    # Position detail
    print(f"\n{'─'*70}")
    print(f"  POSITIONS BY SIZE")
    print(f"{'─'*70}")
    print(f"  {'MARKET':<45} {'OUT':<5} {'SIZE':>8}  {'PRICE':>6}  "
          f"{'VALUE':>9}  {'%PORT':>6}  {'BAR'}")
    print(f"  {'-'*45} {'-'*5} {'-'*8}  {'-'*6}  {'-'*9}  {'-'*6}  {'-'*20}")

    warnings = []
    for p in enriched:
        pct = p["value"] / total_portfolio
        concentration_bar = bar(min(pct * 4, 1.0))  # scale: 25% = full bar
        flag = "  ⚠️  HIGH" if pct >= args.warn_threshold else ""
        print(f"  {p['title']:<45} {p['outcome']:<5} "
              f"{p['size']:>8.2f}  {p['price']:>6.3f}  "
              f"${p['value']:>8.2f}  {fmt_pct(pct)}  "
              f"{concentration_bar}{flag}")
        if pct >= args.warn_threshold:
            warnings.append(p["title"])

    # Correlated / clustered positions
    correlated = {tag: titles for tag, titles in tag_groups.items()
                  if len(titles) > 1}
    if correlated:
        print(f"\n{'─'*70}")
        print(f"  CORRELATED POSITIONS (same category)")
        print(f"{'─'*70}")
        for tag, titles in correlated.items():
            tag_value = sum(
                p["value"] for p in enriched
                if tag in p.get("tags", [])
            )
            tag_pct = tag_value / total_portfolio
            print(f"  [{tag}]  {len(titles)} positions  "
                  f"total value: ${tag_value:,.2f}  ({tag_pct*100:.1f}%)")
            for t in titles:
                print(f"    • {t}")

    # Largest position concentration warning
    if enriched:
        largest = enriched[0]
        largest_pct = largest["value"] / total_portfolio
        print(f"\n{'─'*70}")
        print(f"  CONCENTRATION CHECK")
        print(f"{'─'*70}")
        print(f"  Largest position:  {largest['title'][:40]}")
        print(f"  Value:             {fmt_usdc(largest['value'])}  "
              f"({largest_pct*100:.1f}% of portfolio)")
        if largest_pct > args.warn_threshold:
            print(f"  ⚠️  Above {args.warn_threshold*100:.0f}% threshold — "
                  f"consider reducing.")
        else:
            print(f"  ✅ Within {args.warn_threshold*100:.0f}% concentration limit.")

    # Unrealized P&L estimate (cost basis not always available, so cost ≈ mid)
    print(f"\n{'─'*70}")
    print(f"  RISK SUMMARY")
    print(f"{'─'*70}")
    max_loss = total_position_value   # worst case: all markets resolve against you
    print(f"  Max possible loss:  {fmt_usdc(max_loss)}  "
          f"(all positions resolve to 0)")
    print(f"  Max possible gain:  {fmt_usdc(sum(p['size'] for p in enriched) - total_position_value)}"
          f"  (all positions resolve to 1.0)")
    if warnings:
        print(f"\n  ⚠️  Over-concentrated positions ({args.warn_threshold*100:.0f}% limit):")
        for w in warnings:
            print(f"     • {w}")

    print(f"\n{'='*70}\n")


if __name__ == "__main__":
    main()
