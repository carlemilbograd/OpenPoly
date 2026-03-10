#!/usr/bin/env python3
"""
time_decay.py — Resolution-edge strategy for Polymarket.

**The edge**: traders systematically underestimate time decay.  When a market
is close to its resolution deadline and the event hasn't happened yet, the true
probability collapses — but the posted price often lags behind.

Two sub-strategies are combined:

  FADE  — event hasn't happened, deadline approaching, YES still priced too high
          → buy NO (short YES)  ← most common and profitable case

  RUSH  — event is very likely given remaining time but market underprices it
          → buy YES             ← e.g. election called but price at 0.85

Scan logic:
  1. Fetch active markets that resolve within `days_to_deadline` days
  2. For each, compute a time-adjusted "fair NO premium":
       fair_no = P(event hasn't happened) × residual_prob_per_day^days_remaining
  3. Buy NO when live NO price < fair_no − fees − buffer
  4. Buy YES when live YES price < event_prior − fees − buffer

Usage:
  python scripts/time_decay.py --scan                          # find all opportunities
  python scripts/time_decay.py --scan --max-days 3             # only markets expiring in 3 days
  python scripts/time_decay.py --scan --execute --budget 50    # find + execute best
  python scripts/time_decay.py --once                          # scheduler-friendly
  python scripts/time_decay.py --status                        # P&L + history
  python scripts/time_decay.py --loop --interval 30m           # continuous
"""
from __future__ import annotations

import sys, json, time, argparse, requests, logging
from datetime import datetime, timezone, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from _client     import get_client, GAMMA_API
from _utils      import SKILL_DIR, LOG_DIR, FEE, load_json, save_json, get_mid, fetch_markets
from _guards     import check_min_order

# ── Constants ─────────────────────────────────────────────────────────────────
DEFAULT_MAX_DAYS    = 7        # look at markets resolving within 7 days
MIN_EDGE            = 0.04     # 4% minimum net edge after fees
DECAY_PER_DAY       = 0.30     # heuristic: uninitiated event loses ~30%/day of residual prob
MIN_VOLUME_24H      = 200      # skip illiquid markets
STATE_FILE          = SKILL_DIR / "time_decay_state.json"
LOG_FILE            = LOG_DIR  / f"time_decay_{datetime.now().strftime('%Y-%m-%d')}.log"

_DEFAULT_STATE: dict = {
    "runs": 0, "trades_executed": 0,
    "total_spent": 0.0, "total_profit_est": 0.0, "history": [],
}

# ── Logging ───────────────────────────────────────────────────────────────────
LOG_DIR.mkdir(exist_ok=True)
logging.basicConfig(level=logging.INFO,
    format="%(asctime)s  %(levelname)-7s  %(message)s",
    handlers=[logging.StreamHandler(), logging.FileHandler(LOG_FILE)],
)
log = logging.getLogger("time_decay")


# ── Helpers ───────────────────────────────────────────────────────────────────
def _parse_end_date(m: dict) -> datetime | None:
    """Return market end date as UTC datetime, or None."""
    for field in ("endDate", "end_date", "expirationDate", "gameStartTime"):
        raw = m.get(field)
        if raw:
            try:
                # ISO format with optional Z
                return datetime.fromisoformat(raw.replace("Z", "+00:00"))
            except Exception:
                pass
    return None


def days_remaining(m: dict) -> float | None:
    end = _parse_end_date(m)
    if not end:
        return None
    now = datetime.now(timezone.utc)
    delta = (end - now).total_seconds() / 86400
    return max(0.0, delta)


def _fair_no_price(yes_price: float, days: float) -> float:
    """
    Estimate fair NO price given current YES price and days remaining.

    Heuristic model:
      - If the event hasn't happened and days are ticking down, the true
        probability of YES decreases at rate DECAY_PER_DAY per day remaining.
      - fair_yes = yes_price * (1 - DECAY_PER_DAY) ^ days
      - fair_no  = 1 - fair_yes
    """
    if days <= 0:
        return 1.0   # expired market — NO should be 1.0
    decay_factor = (1 - DECAY_PER_DAY) ** days
    fair_yes = yes_price * decay_factor
    return round(1.0 - fair_yes, 4)


# ── Market scanner ────────────────────────────────────────────────────────────
def scan(
    client,
    max_days: float = DEFAULT_MAX_DAYS,
    min_edge: float = MIN_EDGE,
    limit: int = 300,
    tag: str = "",
    live_prices: bool = True,
) -> list[dict]:
    """Return list of time-decay opportunities sorted by edge descending."""
    log.info(f"Scanning (max_days={max_days}, limit={limit})…")
    markets = fetch_markets(limit=limit, tag=tag)
    opportunities = []

    for m in markets:
        days = days_remaining(m)
        if days is None or days > max_days or days < 0:
            continue

        vol = float(m.get("volume24hr") or 0)
        if vol < MIN_VOLUME_24H:
            continue

        tokens = m.get("tokens", []) or []
        if len(tokens) < 2:
            continue

        yes_token = tokens[0].get("token_id", "")
        no_token  = tokens[1].get("token_id", "")
        if not yes_token or not no_token:
            continue

        # Get live prices
        if live_prices and client:
            yes_price = get_mid(client, yes_token)
            no_price  = get_mid(client, no_token)
        else:
            try:
                yes_price = float(tokens[0].get("price") or 0)
                no_price  = float(tokens[1].get("price") or 0)
            except Exception:
                continue

        if yes_price is None or no_price is None:
            continue
        if yes_price <= 0.01 or yes_price >= 0.99:
            continue  # already near resolution, skip

        fair_no = _fair_no_price(yes_price, days)

        # FADE: NO is underpriced relative to time-adjusted fairness
        fade_edge = fair_no - no_price - FEE
        if fade_edge >= min_edge:
            opportunities.append({
                "type":        "FADE",
                "action":      "BUY_NO",
                "token_id":    no_token,
                "yes_token":   yes_token,
                "question":    m.get("question", ""),
                "market_id":   m.get("id", ""),
                "days":        round(days, 2),
                "yes_price":   round(yes_price, 4),
                "no_price":    round(no_price, 4),
                "fair_no":     fair_no,
                "edge":        round(fade_edge, 4),
                "volume_24h":  round(vol, 2),
            })

        # RUSH: YES is underpriced for something clearly happening
        # Only when days > 1 and yes is high-probability but discounted
        rush_edge = 0.0
        if days >= 1 and yes_price >= 0.70:
            rush_edge = yes_price - (1.0 - fair_no) - FEE - 0.02  # extra buffer
            if rush_edge >= min_edge:
                opportunities.append({
                    "type":        "RUSH",
                    "action":      "BUY_YES",
                    "token_id":    yes_token,
                    "yes_token":   yes_token,
                    "question":    m.get("question", ""),
                    "market_id":   m.get("id", ""),
                    "days":        round(days, 2),
                    "yes_price":   round(yes_price, 4),
                    "no_price":    round(no_price, 4),
                    "fair_no":     fair_no,
                    "edge":        round(rush_edge, 4),
                    "volume_24h":  round(vol, 2),
                })

    opportunities.sort(key=lambda x: x["edge"], reverse=True)
    log.info(f"Found {len(opportunities)} time-decay opportunities")
    return opportunities


# ── Execution ─────────────────────────────────────────────────────────────────
def execute_opportunity(opp: dict, budget: float, client, dry_run: bool, state: dict):
    token_id  = opp["token_id"]
    action    = opp["action"]
    question  = opp["question"][:65]
    days      = opp["days"]
    edge      = opp["edge"]
    price     = opp["no_price"] if action == "BUY_NO" else opp["yes_price"]
    direction = "NO" if action == "BUY_NO" else "YES"

    print(f"\n  TIME-DECAY [{opp['type']}]  {question}")
    print(f"    days_left={days:.1f}  yes={opp['yes_price']:.3f}  "
          f"no={opp['no_price']:.3f}  fair_no={opp['fair_no']:.3f}  edge={edge:.1%}")
    print(f"    Action: BUY {direction} @ {price:.4f}  ${budget:.2f}"
          + ("  [DRY-RUN]" if dry_run else ""))

    record = {
        "ts":        datetime.now(timezone.utc).isoformat(),
        "type":      opp["type"],
        "action":    action,
        "question":  question,
        "market_id": opp.get("market_id", ""),
        "days":      days,
        "edge":      edge,
        "direction": direction,
        "price":     price,
        "budget":    budget,
        "dry_run":   dry_run,
    }

    if dry_run:
        record["status"] = "dry_run"
        state["history"].append(record)
        return record

    try:
        from py_clob_client.clob_types import OrderArgs, OrderType
        from py_clob_client.order_builder.constants import BUY
        o_args = OrderArgs(token_id=token_id, price=round(price, 4),
                           size=round(budget, 2), side=BUY)
        signed = client.create_order(o_args)
        resp   = client.post_order(signed, OrderType.GTC)
        oid    = (resp or {}).get("orderID") or (resp or {}).get("id", "?")
        print(f"    OK  order {str(oid)[:20]}")
        record.update({"status": "placed", "order_id": str(oid)})
        state["trades_executed"] += 1
        state["total_spent"]     += budget
        state["total_profit_est"] += round(budget * edge, 4)
        try:
            from notifier import notify_trade_opened
            notify_trade_opened(
                bot="time_decay",
                market=question,
                market_id=opp.get("market_id", ""),
                direction=direction,
                amount_usd=round(budget, 2),
                price=price,
                order_ids=[str(oid)],
                extras={"type": opp["type"], "days_remaining": days, "edge": edge},
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
    p = argparse.ArgumentParser(description="Time-decay / resolution-edge strategy")
    p.add_argument("--scan",      action="store_true", help="Scan for opportunities")
    p.add_argument("--execute",   action="store_true", help="Execute best opportunity")
    p.add_argument("--once",      action="store_true", help="Single scan + optional execute, then exit")
    p.add_argument("--loop",      action="store_true", help="Run continuously")
    p.add_argument("--interval",  default="30m",       help="Loop interval (default 30m)")
    p.add_argument("--max-days",  type=float, default=DEFAULT_MAX_DAYS,
                   help=f"Max days to resolution (default {DEFAULT_MAX_DAYS})")
    p.add_argument("--min-edge",  type=float, default=MIN_EDGE,
                   help=f"Min net edge (default {MIN_EDGE})")
    p.add_argument("--budget",    type=float, default=1.0,
                   help="USDC per trade (default 1)")
    p.add_argument("--limit",     type=int,   default=300,
                   help="Markets to scan (default 300)")
    p.add_argument("--tag",       default="",  help="Filter by tag (politics, crypto…)")
    p.add_argument("--top",       type=int,   default=3,
                   help="Number of opportunities to show (default 3)")
    p.add_argument("--dry-run",   action="store_true", help="No real orders")
    p.add_argument("--json",      action="store_true", help="Output as JSON")
    p.add_argument("--status",    action="store_true", help="Show P&L and history")
    args = p.parse_args()

    # Guard
    if (args.execute or args.once or args.loop) and not args.dry_run:
        check_min_order(args.budget, flag="--budget", bot="time_decay",
                        exit_on_fail=True)

    state  = load_json(STATE_FILE, _DEFAULT_STATE)
    client = get_client(authenticated=bool(args.execute and not args.dry_run))

    if args.status:
        print(f"\n  Time-Decay Strategy Status\n  {'─'*40}")
        print(f"  Runs:          {state.get('runs', 0)}")
        print(f"  Trades placed: {state.get('trades_executed', 0)}")
        print(f"  USDC deployed: ${state.get('total_spent', 0):.2f}")
        print(f"  Est. profit:   +${state.get('total_profit_est', 0):.4f}")
        hist = state.get("history", [])[-10:]
        if hist:
            print(f"\n  Last {len(hist)} records:")
            for r in hist:
                tag = "DRY" if r.get("dry_run") else r.get("status","?").upper()
                print(f"  [{r['ts'][:19]}]  {tag:<8}  {r['type']:<5}  "
                      f"days={r.get('days',0):.1f}  edge={r.get('edge',0):.1%}  "
                      f"{r.get('question','')[:50]}")
        print()
        return

    def _run_once():
        state["runs"] = state.get("runs", 0) + 1
        opps = scan(client, max_days=args.max_days, min_edge=args.min_edge,
                    limit=args.limit, tag=args.tag)
        if not opps:
            print("  No time-decay opportunities found.")
            return
        display = opps[:args.top]
        if args.json:
            print(json.dumps(display, indent=2))
        else:
            print(f"\n  Time-decay opportunities ({len(opps)} found, "
                  f"showing top {len(display)}):\n")
            for o in display:
                print(f"  [{o['type']:<5}] {o['question'][:60]}")
                print(f"         days={o['days']:.1f}  yes={o['yes_price']:.3f}  "
                      f"no={o['no_price']:.3f}  fair_no={o['fair_no']:.3f}  "
                      f"edge={o['edge']:.1%}  vol24h=${o['volume_24h']:.0f}")
            print()
        if args.execute and opps:
            execute_opportunity(opps[0], args.budget, client, args.dry_run, state)
        save_json(STATE_FILE, state)

    if args.scan or args.once:
        _run_once()
        return

    if args.loop:
        from auto_arbitrage import parse_interval  # reuse interval parser
        secs = parse_interval(args.interval)
        try:
            while True:
                _run_once()
                print(f"  Sleeping {args.interval}…")
                time.sleep(secs)
        except KeyboardInterrupt:
            save_json(STATE_FILE, state)
            print("\n  Stopped.\n")
        return

    p.print_help()


if __name__ == "__main__":
    main()
