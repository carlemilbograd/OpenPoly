#!/usr/bin/env python3
"""
execution_simulator.py — Orderbook simulation, slippage estimation, and
optimal order sizing for Polymarket.

The key decision rule:
    net_profit = edge - slippage - fees
    if net_profit > min_threshold: TRADE
    else: SKIP

Slippage is estimated by walking the live orderbook and simulating fills
at each price level until the requested USD size is consumed.

Usage (standalone):
  python scripts/execution_simulator.py --token-id TOKEN --size 50 --edge 0.07
  python scripts/execution_simulator.py --token-id TOKEN --size 50 --edge 0.07 --json
  python scripts/execution_simulator.py --token-id TOKEN --optimal-size --edge 0.06 --budget 200

Usage (as imported module):
  from execution_simulator import simulate_order, is_viable, optimal_size
"""
import sys, json, argparse, requests
from pathlib import Path
from dataclasses import dataclass, asdict
from typing import Optional

sys.path.insert(0, str(Path(__file__).parent))
from _client import GAMMA_API, get_client

FEE = 0.02          # ~2% round-trip Polymarket fee estimate
MIN_LIQUIDITY = 5   # warn if best-level size < $5


@dataclass
class SimResult:
    token_id:         str
    side:             str           # "BUY" | "SELL"
    requested_usd:    float
    fills:            list          # [{"price": float, "size_usd": float, "cumulative": float}]
    avg_fill_price:   float
    best_price:       float         # top-of-book price (what you'd hope to pay)
    slippage_pct:     float         # (avg_fill - best) / best  [for BUY; inverted for SELL]
    total_filled_usd: float
    unfilled_usd:     float
    depth_warning:    bool          # True if book didn't have enough liquidity
    viable:           bool          # True if slippage_pct < some caller-supplied threshold

    def summary(self) -> str:
        warn = "  ⚠️  DEPTH WARNING — insufficient liquidity" if self.depth_warning else ""
        return (
            f"  Side:          {self.side}\n"
            f"  Requested:     ${self.requested_usd:.2f}\n"
            f"  Best price:    {self.best_price:.4f}\n"
            f"  Avg fill:      {self.avg_fill_price:.4f}\n"
            f"  Slippage:      {self.slippage_pct:.2f}%\n"
            f"  Filled:        ${self.total_filled_usd:.2f}"
            + (f"  (unfilled: ${self.unfilled_usd:.2f})" if self.unfilled_usd > 0 else "")
            + (f"\n{warn}" if warn else "")
        )


def _get_book_levels(client, token_id: str) -> tuple[list, list]:
    """
    Return (asks, bids) as sorted lists of {"price": float, "size": float}.
    Asks sorted ascending (cheapest first), bids sorted descending (highest first).
    """
    try:
        book = client.get_order_book(token_id)
        asks = sorted(
            [{"price": float(l.price), "size": float(l.size)} for l in (book.asks or [])],
            key=lambda x: x["price"],
        )
        bids = sorted(
            [{"price": float(l.price), "size": float(l.size)} for l in (book.bids or [])],
            key=lambda x: x["price"], reverse=True,
        )
        return asks, bids
    except Exception:
        return [], []


def simulate_order(
    client,
    token_id: str,
    side: str,
    usd_size: float,
) -> SimResult:
    """
    Walk the live orderbook and simulate fills until usd_size is consumed.

    BUY  → walks asks (cheapest first): you pay ask prices
    SELL → walks bids (highest first):  you receive bid prices

    Returns a SimResult with slippage, fills, and depth info.
    """
    asks, bids = _get_book_levels(client, token_id)
    levels = asks if side.upper() == "BUY" else bids

    if not levels:
        # No book data — return worst-case: assume 5% slippage, depth warning
        return SimResult(
            token_id=token_id, side=side,
            requested_usd=usd_size, fills=[],
            avg_fill_price=0.0, best_price=0.0,
            slippage_pct=5.0, total_filled_usd=0.0,
            unfilled_usd=usd_size, depth_warning=True, viable=False,
        )

    best_price     = levels[0]["price"]
    remaining      = usd_size
    fills          = []
    total_shares   = 0.0
    total_cost_usd = 0.0

    for level in levels:
        if remaining <= 0:
            break
        level_shares    = level["size"]                   # shares available at this price
        level_usd_value = level_shares * level["price"]   # USD cost to buy all of them

        take_usd = min(remaining, level_usd_value)
        take_shares = take_usd / level["price"]

        fills.append({
            "price":       level["price"],
            "shares":      round(take_shares, 6),
            "size_usd":    round(take_usd, 4),
            "cumulative":  round(total_cost_usd + take_usd, 4),
        })
        total_cost_usd += take_usd
        total_shares   += take_shares
        remaining      -= take_usd

    unfilled        = max(0.0, remaining)
    total_filled    = usd_size - unfilled
    avg_fill        = total_cost_usd / total_shares if total_shares > 0 else best_price
    depth_warning   = unfilled > 0.01

    # Slippage: how much worse than the best price?
    if side.upper() == "BUY":
        slippage_pct = ((avg_fill - best_price) / best_price * 100) if best_price > 0 else 0.0
    else:
        slippage_pct = ((best_price - avg_fill) / best_price * 100) if best_price > 0 else 0.0

    return SimResult(
        token_id=token_id, side=side,
        requested_usd=usd_size, fills=fills,
        avg_fill_price=round(avg_fill, 6),
        best_price=round(best_price, 6),
        slippage_pct=round(max(0.0, slippage_pct), 4),
        total_filled_usd=round(total_filled, 4),
        unfilled_usd=round(unfilled, 4),
        depth_warning=depth_warning,
        viable=True,   # caller decides viability with is_viable()
    )


def is_viable(
    sim: SimResult,
    edge_pct: float,
    min_net_profit: float = 0.01,
) -> tuple[bool, float]:
    """
    Decide whether a trade is worth executing.

    net = edge - slippage_pct/100 - FEE
    Returns (viable: bool, net_profit: float)

    edge_pct is the raw probability edge as a fraction (e.g. 0.07 for 7%).
    """
    net = edge_pct - (sim.slippage_pct / 100.0) - FEE
    return net >= min_net_profit, round(net, 6)


def optimal_size(
    client,
    token_id: str,
    side: str,
    edge_pct: float,
    budget: float,
    min_net: float = 0.01,
    step_pct: float = 0.1,
) -> tuple[float, Optional[SimResult]]:
    """
    Binary-search for the largest order size where trade remains viable.
    
    Returns (optimal_usd_size, simulation_at_that_size).
    Returns (0.0, None) if even the minimum feasible size is not viable.
    """
    low, high = 1.0, budget
    best_size = 0.0
    best_sim  = None

    # Quick check: is the trade viable at minimum size?
    min_sim = simulate_order(client, token_id, side, low)
    ok, _   = is_viable(min_sim, edge_pct, min_net)
    if not ok:
        return 0.0, None

    # Binary search
    for _ in range(15):
        mid = (low + high) / 2.0
        sim = simulate_order(client, token_id, side, mid)
        ok, net = is_viable(sim, edge_pct, min_net)
        if ok:
            best_size = mid
            best_sim  = sim
            low = mid
        else:
            high = mid
        if high - low < 0.50:
            break

    return round(best_size, 2), best_sim


# ── Main ───────────────────────────────────────────────────────────────────────
def main():
    parser = argparse.ArgumentParser(description="Orderbook simulation and slippage estimator")
    parser.add_argument("--token-id",     required=True,              help="Polymarket token ID to simulate")
    parser.add_argument("--side",         default="BUY",              help="BUY or SELL (default BUY)")
    parser.add_argument("--size",         type=float, default=50.0,   help="USDC order size to simulate")
    parser.add_argument("--edge",         type=float, default=0.05,   help="Your edge as fraction (e.g. 0.07 = 7%%)")
    parser.add_argument("--min-profit",   type=float, default=0.01,   help="Min acceptable net profit (0.01 = 1%%)")
    parser.add_argument("--optimal-size", action="store_true",        help="Find optimal order size for given budget")
    parser.add_argument("--budget",       type=float, default=200.0,  help="Max budget for optimal sizing (default 200)")
    parser.add_argument("--json",         action="store_true",        help="Output raw JSON")
    args = parser.parse_args()

    client = get_client(authenticated=False)

    if args.optimal_size:
        print(f"\n  Finding optimal order size for ${args.budget:.2f} budget...")
        size, sim = optimal_size(
            client, args.token_id, args.side.upper(),
            args.edge, args.budget, args.min_profit,
        )
        if size == 0.0:
            print(f"  ❌ Trade not viable — slippage exceeds edge at any size.\n")
            return
        print(f"  ✅ Optimal size: ${size:.2f}\n")
        viable, net = is_viable(sim, args.edge, args.min_profit)
        print(sim.summary())
        print(f"\n  Edge:           {args.edge*100:.2f}%")
        print(f"  Fees (est.):   -{FEE*100:.2f}%")
        print(f"  Slippage:      -{sim.slippage_pct:.2f}%")
        print(f"  ─────────────────────────")
        print(f"  Net profit:     {net*100:.2f}%")
        print(f"  Decision:       {'✅ TRADE' if viable else '❌ SKIP'}\n")
        if args.json:
            result = asdict(sim)
            result["optimal_size"] = size
            result["net_profit"]   = net
            print(json.dumps(result, indent=2))
        return

    print(f"\n  Simulating {args.side.upper()} ${args.size:.2f} on token {args.token_id[:20]}...")
    sim = simulate_order(client, args.token_id, args.side.upper(), args.size)
    viable, net = is_viable(sim, args.edge, args.min_profit)

    if args.json:
        result = asdict(sim)
        result["edge"]       = args.edge
        result["net_profit"] = net
        result["decision"]   = "TRADE" if viable else "SKIP"
        print(json.dumps(result, indent=2))
        return

    print(f"\n{'─'*50}")
    print(sim.summary())
    print(f"{'─'*50}")
    print(f"\n  Your edge:      {args.edge*100:.2f}%")
    print(f"  Fees (est.):   -{FEE*100:.2f}%")
    print(f"  Slippage:      -{sim.slippage_pct:.2f}%")
    print(f"  ─────────────────────────")
    print(f"  Net profit:     {net*100:.2f}%")
    print(f"\n  Decision:  {'✅ TRADE — edge > slippage + fees' if viable else '❌ SKIP — slippage erases edge'}\n")

    if fills := sim.fills:
        print(f"  Fill breakdown ({len(fills)} level(s)):")
        print(f"  {'PRICE':>8}  {'SHARES':>10}  {'USD':>10}  {'CUMUL USD':>12}")
        print(f"  {'─'*8}  {'─'*10}  {'─'*10}  {'─'*12}")
        for f in fills:
            print(f"  {f['price']:8.4f}  {f['shares']:10.4f}  ${f['size_usd']:9.2f}  ${f['cumulative']:11.2f}")
    print()


if __name__ == "__main__":
    main()
