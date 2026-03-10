#!/usr/bin/env python3
"""
resolution_arb.py — Near-settlement mispricing arbitrage for Polymarket.

**The edge**: near settlement (last 24–48 h), some markets still have YES + NO
prices that sum to > 1.0 — implying free money.  Because the market resolves
soon, you collect in hours not months, making the annualised return enormous.

Additionally scans for "settled but not resolved" markets where one side is
clearly 0.99+ and the other side is still 0.02–0.05 (should be 0.01 or less).

Two profit modes:

  BOTH_SIDES  — YES + NO > 1.0 + fees → buy both legs → guaranteed profit
  ONE_SIDE    — YES = 0.98, NO = 0.05 → total = 1.03 → sell NO (buy YES is ok
                at 0.98 but still earns the 0.03 premium via short NO)

Usage:
  python scripts/resolution_arb.py --scan
  python scripts/resolution_arb.py --scan --max-days 2    # within 48 hours only
  python scripts/resolution_arb.py --scan --execute --budget 100
  python scripts/resolution_arb.py --once
"""
from __future__ import annotations

import sys, json, time, argparse, logging
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from _client     import get_client
from _utils      import SKILL_DIR, LOG_DIR, FEE, load_json, save_json, get_mid, fetch_markets
from _guards     import check_min_order
from time_decay  import days_remaining   # reuse date parser

# ── Constants ─────────────────────────────────────────────────────────────────
DEFAULT_MAX_DAYS = 3       # primary focus: markets within 3 days
DEFAULT_MIN_EDGE = 0.01    # 1% edge — these are very safe, accept lower threshold
MIN_VOLUME_24H   = 100     # lower bar than other strategies
STATE_FILE       = SKILL_DIR / "resolution_arb_state.json"
LOG_FILE         = LOG_DIR   / f"resolution_arb_{datetime.now().strftime('%Y-%m-%d')}.log"

_DEFAULT_STATE: dict = {
    "runs": 0, "trades_executed": 0,
    "total_spent": 0.0, "total_profit_est": 0.0, "history": [],
}

LOG_DIR.mkdir(exist_ok=True)
logging.basicConfig(level=logging.INFO,
    format="%(asctime)s  %(levelname)-7s  %(message)s",
    handlers=[logging.StreamHandler(), logging.FileHandler(LOG_FILE)],
)
log = logging.getLogger("resolution_arb")


# ── Scanner ───────────────────────────────────────────────────────────────────
def scan(
    client,
    max_days: float  = DEFAULT_MAX_DAYS,
    min_edge: float  = DEFAULT_MIN_EDGE,
    limit: int       = 400,
    include_anytime: bool = False,
    live_prices: bool = True,
) -> list[dict]:
    """
    Scan for near-resolution mispricings.
    include_anytime: also check markets without end dates (some resolve on events).
    """
    markets = fetch_markets(limit=limit)
    opportunities: list[dict] = []

    for m in markets:
        days = days_remaining(m)
        if days is None:
            if not include_anytime:
                continue
            days = 999  # no known deadline — still scan

        if days > max_days and not include_anytime:
            continue

        vol = float(m.get("volume24hr") or 0)
        if vol < MIN_VOLUME_24H:
            continue

        tokens = m.get("tokens") or []
        if len(tokens) < 2:
            continue

        yes_tid = tokens[0].get("token_id", "")
        no_tid  = tokens[1].get("token_id", "")
        if not yes_tid or not no_tid:
            continue

        if live_prices and client:
            yes_p = get_mid(client, yes_tid)
            no_p  = get_mid(client, no_tid)
        else:
            try:
                yes_p = float(tokens[0].get("price") or 0) or None
                no_p  = float(tokens[1].get("price") or 0) or None
            except Exception:
                continue

        if yes_p is None or no_p is None:
            continue

        total = yes_p + no_p

        # ── BOTH_SIDES arb ───────────────────────────────────────────────────
        if total > 1.0 + FEE + min_edge:
            edge = total - 1.0 - FEE
            opportunities.append({
                "type":      "BOTH_SIDES",
                "question":  m.get("question", "")[:70],
                "market_id": m.get("id", ""),
                "yes_token": yes_tid,
                "no_token":  no_tid,
                "yes_price": round(yes_p, 4),
                "no_price":  round(no_p, 4),
                "total":     round(total, 4),
                "edge":      round(edge, 4),
                "days":      round(days, 2),
                # To trade: SHORT both — buy NO + buy... wait. YES + NO > 1 means
                # market is overpriced collectively. Short: sell YES + sell NO.
                # In CLOB terms we BUY NO (i.e. SELL YES).
                "action":    "SELL_YES_SELL_NO",
                "vol_24h":   round(vol, 2),
            })

        # ── ONE_SIDE arb: one outcome near 0, other near 1, but spread too wide ─
        elif yes_p >= 0.93 and no_p >= 0.04:
            # NO is priced too high relative to near-certain YES
            edge = no_p - FEE - min_edge
            if edge > 0:
                opportunities.append({
                    "type":      "EXCESS_NO",
                    "question":  m.get("question", "")[:70],
                    "market_id": m.get("id", ""),
                    "yes_token": yes_tid,
                    "no_token":  no_tid,
                    "yes_price": round(yes_p, 4),
                    "no_price":  round(no_p, 4),
                    "total":     round(total, 4),
                    "edge":      round(edge, 4),
                    "days":      round(days, 2),
                    "action":    "SELL_NO",      # buy YES (or short NO via buying at low price)
                    "vol_24h":   round(vol, 2),
                })

        elif no_p >= 0.93 and yes_p >= 0.04:
            # YES is priced too high relative to near-certain NO
            edge = yes_p - FEE - min_edge
            if edge > 0:
                opportunities.append({
                    "type":      "EXCESS_YES",
                    "question":  m.get("question", "")[:70],
                    "market_id": m.get("id", ""),
                    "yes_token": yes_tid,
                    "no_token":  no_tid,
                    "yes_price": round(yes_p, 4),
                    "no_price":  round(no_p, 4),
                    "total":     round(total, 4),
                    "edge":      round(edge, 4),
                    "days":      round(days, 2),
                    "action":    "SELL_YES",
                    "vol_24h":   round(vol, 2),
                })

    opportunities.sort(key=lambda x: x["edge"], reverse=True)
    log.info(f"Found {len(opportunities)} resolution-arb opportunities")
    return opportunities


# ── Execution ─────────────────────────────────────────────────────────────────
def execute_opportunity(opp: dict, budget: float, client, dry_run: bool, state: dict):
    """Execute a resolution-arb trade."""
    arb_type = opp["type"]
    question = opp["question"]
    edge     = opp["edge"]
    half     = round(budget / 2, 2)
    full     = round(budget, 2)

    print(f"\n  RESOLUTION-ARB [{arb_type}]  {question}")
    print(f"    yes={opp['yes_price']:.4f}  no={opp['no_price']:.4f}  "
          f"sum={opp['total']:.4f}  edge={edge:.1%}  days={opp['days']:.1f}"
          + ("  [DRY-RUN]" if dry_run else ""))

    record: dict = {
        "ts":        datetime.now(timezone.utc).isoformat(),
        "type":      arb_type,
        "question":  question,
        "market_id": opp.get("market_id", ""),
        "edge":      edge,
        "budget":    budget,
        "dry_run":   dry_run,
    }

    if dry_run:
        record["status"] = "dry_run"
        state["history"].append(record)
        return record

    order_ids = []
    try:
        from py_clob_client.clob_types import OrderArgs, OrderType
        from py_clob_client.order_builder.constants import BUY

        legs = []
        if arb_type == "BOTH_SIDES":
            # Sell YES = buy NO; sell NO = buy YES complement
            # Practically: buy NO at (1-yes_price) and buy YES at (1-no_price)
            # Both sides simultaneously compress the overpricing
            legs = [
                (opp["no_token"],  round(1.0 - opp["yes_price"], 4), half),
                (opp["yes_token"], round(1.0 - opp["no_price"],  4), half),
            ]
        elif arb_type == "EXCESS_NO":
            # Sell NO = buy at near zero / short; simplest: buy YES (cheap hedge)
            legs = [(opp["yes_token"], round(opp["yes_price"], 4), full)]
        elif arb_type == "EXCESS_YES":
            legs = [(opp["no_token"], round(opp["no_price"], 4), full)]

        for tid, price, size in legs:
            if not tid or size < 1.0:
                continue
            o_args = OrderArgs(token_id=tid, price=price, size=size, side=BUY)
            signed = client.create_order(o_args)
            resp   = client.post_order(signed, OrderType.GTC)
            oid    = (resp or {}).get("orderID") or (resp or {}).get("id", "?")
            order_ids.append(str(oid))
            print(f"    OK  order {str(oid)[:20]}  ${size:.2f}  @ {price:.4f}")

        record.update({"status": "placed", "order_ids": order_ids})
        state["trades_executed"] += 1
        state["total_spent"]     += budget
        state["total_profit_est"] += round(budget * edge, 4)
        try:
            from notifier import notify_trade_opened
            notify_trade_opened(
                bot="resolution_arb",
                market=question,
                direction=opp["action"],
                amount_usd=budget,
                order_ids=order_ids,
                extras={"type": arb_type, "edge": edge, "days": opp["days"]},
            )
        except Exception:
            pass
    except Exception as exc:
        print(f"    FAIL  {exc}")
        record.update({"status": "error", "error": str(exc)})

    state["history"].append(record)
    if len(state["history"]) > 400:
        state["history"] = state["history"][-400:]
    return record


# ── Main ──────────────────────────────────────────────────────────────────────
def main():
    p = argparse.ArgumentParser(description="Near-settlement mispricing arbitrage")
    p.add_argument("--scan",          action="store_true", help="Scan for opportunities")
    p.add_argument("--execute",       action="store_true", help="Execute best opportunity")
    p.add_argument("--once",          action="store_true", help="Single scan + execute")
    p.add_argument("--max-days",      type=float, default=DEFAULT_MAX_DAYS,
                   help=f"Max days to resolution (default {DEFAULT_MAX_DAYS})")
    p.add_argument("--min-edge",      type=float, default=DEFAULT_MIN_EDGE,
                   help=f"Minimum net edge (default {DEFAULT_MIN_EDGE})")
    p.add_argument("--budget",        type=float, default=1.0,
                   help="USDC per trade (default 1)")
    p.add_argument("--limit",         type=int,   default=400,
                   help="Markets to scan (default 400)")
    p.add_argument("--include-anytime", action="store_true",
                   help="Also check markets with no end date")
    p.add_argument("--top",           type=int,   default=5, help="Results to show")
    p.add_argument("--dry-run",       action="store_true")
    p.add_argument("--json",          action="store_true")
    p.add_argument("--status",        action="store_true")
    args = p.parse_args()

    if (args.execute or args.once) and not args.dry_run:
        check_min_order(args.budget, flag="--budget", bot="resolution_arb",
                        exit_on_fail=True)

    state  = load_json(STATE_FILE, _DEFAULT_STATE)
    client = get_client(authenticated=bool((args.execute or args.once) and not args.dry_run))

    if args.status:
        print(f"\n  Resolution Arb Status\n  {'─'*40}")
        print(f"  Runs:          {state.get('runs', 0)}")
        print(f"  Trades placed: {state.get('trades_executed', 0)}")
        print(f"  USDC deployed: ${state.get('total_spent', 0):.2f}")
        print(f"  Est. profit:   +${state.get('total_profit_est', 0):.4f}")
        for r in state.get("history", [])[-10:]:
            tag = "DRY" if r.get("dry_run") else r.get("status","?").upper()
            print(f"  [{r['ts'][:19]}]  {tag:<8}  {r['type']:<12}  "
                  f"edge={r.get('edge',0):.1%}  {r.get('question','')[:50]}")
        print()
        return

    if not (args.scan or args.once):
        p.print_help()
        return

    state["runs"] = state.get("runs", 0) + 1
    opps = scan(client, max_days=args.max_days, min_edge=args.min_edge,
                limit=args.limit, include_anytime=args.include_anytime)

    if not opps:
        print("  No resolution-arb opportunities found.")
        save_json(STATE_FILE, state)
        return

    display = opps[:args.top]
    if args.json:
        print(json.dumps(display, indent=2))
    else:
        print(f"\n  Resolution-arb opportunities ({len(opps)} found):\n")
        for o in display:
            print(f"  [{o['type']:<12}] edge={o['edge']:.1%}  "
                  f"sum={o['total']:.4f}  days={o['days']:.1f}")
            print(f"    {o['question']}")
        print()

    if (args.execute or args.once) and opps:
        execute_opportunity(opps[0], args.budget, client, args.dry_run, state)

    save_json(STATE_FILE, state)


if __name__ == "__main__":
    main()
