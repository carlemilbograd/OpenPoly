#!/usr/bin/env python3
"""
auto_arbitrage.py — Automated arbitrage bot for Polymarket.

Scans all markets at a configurable interval, executes arbitrage whenever a
gap exceeds the minimum threshold, risking a given percentage of available
account balance per round.

Can run as a self-contained loop OR as a single-shot script called by
scheduler.py.

Usage (standalone loop):
    python scripts/auto_arbitrage.py --interval 15m --min-gap 0.005 --budget-pct 0.10
    python scripts/auto_arbitrage.py --interval 1h  --min-gap 0.01  --budget-pct 0.05 --dry-run
    python scripts/auto_arbitrage.py --interval 30s --min-gap 0.003 --budget-pct 0.20 --max-budget 200

Usage (single-shot, called by scheduler.py):
    python scripts/auto_arbitrage.py --once --min-gap 0.005 --budget-pct 0.10

Interval format: 30s | 5m | 15m | 1h | 6h | 1d
"""
import sys, os, argparse, requests, json, time, signal, logging
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from _client import GAMMA_API, get_client

# ── Constants ─────────────────────────────────────────────────────────────────
FEE_ESTIMATE   = 0.02    # ~2% round-trip fee estimate
MIN_LIQUIDITY  = 5.0     # minimum USDC depth required per leg
SCAN_LIMIT     = 200     # markets to scan per round
SKILL_DIR      = Path(__file__).parent.parent
LOG_DIR        = SKILL_DIR / "logs"
STATE_FILE     = SKILL_DIR / "auto_arbitrage_state.json"

# ── Logging ───────────────────────────────────────────────────────────────────
LOG_DIR.mkdir(exist_ok=True)
log_path = LOG_DIR / f"auto_arbitrage_{datetime.now().strftime('%Y-%m-%d')}.log"

logger = logging.getLogger("auto_arbitrage")
logger.setLevel(logging.DEBUG)

_fh = logging.FileHandler(log_path)
_fh.setFormatter(logging.Formatter("%(asctime)s  %(levelname)-7s  %(message)s"))
logger.addHandler(_fh)

_ch = logging.StreamHandler()
_ch.setFormatter(logging.Formatter("%(asctime)s  %(levelname)-7s  %(message)s"))
logger.addHandler(_ch)

# ── Helpers ───────────────────────────────────────────────────────────────────
def parse_interval(s: str) -> int:
    """Convert '15m', '1h', '30s', '1d' → seconds."""
    s = s.strip().lower()
    if s.endswith("s"):
        return int(s[:-1])
    if s.endswith("m"):
        return int(s[:-1]) * 60
    if s.endswith("h"):
        return int(s[:-1]) * 3600
    if s.endswith("d"):
        return int(s[:-1]) * 86400
    return int(s)  # assume seconds if no unit


def get_balance(client) -> float:
    """Fetch current USDC balance."""
    try:
        from py_clob_client.clob_types import BalanceAllowanceParams, AssetType
        params = BalanceAllowanceParams(asset_type=AssetType.COLLATERAL)
        bal = client.get_balance_allowance(params=params)
        return float(bal.get("balance", 0)) / 1e6  # USDC has 6 decimals
    except Exception as e:
        logger.warning(f"Could not fetch balance: {e}")
        return 0.0


def get_live_price(client, token_id: str) -> float | None:
    try:
        resp = client.get_midpoint(token_id)
        v = resp.get("mid")
        return float(v) if v else None
    except Exception:
        return None


def get_depth(client, token_id: str, target_usdc: float) -> float:
    """Return USDC of liquidity available within 2% of mid on the ask side."""
    try:
        book  = client.get_order_book(token_id)
        mid_r = client.get_midpoint(token_id)
        mid   = float(mid_r.get("mid", 0.5))
        threshold = mid * 1.02
        total = 0.0
        for level in sorted(book.asks or [], key=lambda x: float(x.price)):
            if float(level.price) <= threshold:
                total += float(level.size) * float(level.price)
        return total
    except Exception:
        return 0.0


def scan_markets(client, min_gap: float, scan_limit: int, tag: str) -> list:
    """Return list of arb opportunities sorted by net profit pct."""
    params = {
        "limit": scan_limit,
        "active": "true",
        "order": "volume24hr",
        "ascending": "false",
    }
    if tag:
        params["tag"] = tag

    try:
        resp = requests.get(f"{GAMMA_API}/markets", params=params, timeout=20)
        markets = resp.json() if resp.ok else []
    except Exception as e:
        logger.error(f"Gamma API error: {e}")
        return []

    opportunities = []
    for market in markets:
        tokens = market.get("tokens", [])
        if len(tokens) < 2:
            continue

        token_ids = [t.get("token_id", "") for t in tokens if t.get("token_id")]
        outcome_prices = []
        for t in tokens:
            tid = t.get("token_id", "")
            price = get_live_price(client, tid)
            if price is None:
                price = float(t.get("price", 0) or 0)
            if price > 0:
                outcome_prices.append({
                    "outcome":  t.get("outcome", "?"),
                    "token_id": tid,
                    "price":    price,
                })

        if len(outcome_prices) < 2:
            continue

        total          = sum(o["price"] for o in outcome_prices)
        gap            = 1.0 - total
        net_profit_pct = gap - FEE_ESTIMATE

        if gap < min_gap or net_profit_pct <= 0:
            continue

        opportunities.append({
            "question":       market.get("question", "?"),
            "market_id":      market.get("id", ""),
            "outcomes":       outcome_prices,
            "total":          total,
            "gap":            gap,
            "net_profit_pct": net_profit_pct,
            "volume_24h":     float(market.get("volume24hr", 0) or 0),
        })

    opportunities.sort(key=lambda x: x["net_profit_pct"], reverse=True)
    return opportunities


# ── State ─────────────────────────────────────────────────────────────────────
def load_state() -> dict:
    if STATE_FILE.exists():
        try:
            return json.loads(STATE_FILE.read_text())
        except Exception:
            pass
    return {
        "runs":         0,
        "arbs_found":   0,
        "arbs_executed": 0,
        "total_spent":  0.0,
        "total_profit_est": 0.0,
        "last_run":     None,
        "history":      [],
    }


def save_state(state: dict):
    STATE_FILE.write_text(json.dumps(state, indent=2))


# ── Core execution ─────────────────────────────────────────────────────────────
def run_once(args, client, state: dict) -> dict:
    """
    One scan-and-execute round. Returns updated state.
    """
    now_str = datetime.now(timezone.utc).isoformat()
    state["runs"]    += 1
    state["last_run"]  = now_str

    logger.info(f"Run #{state['runs']} — scanning {SCAN_LIMIT} markets "
                f"(min gap {args.min_gap*100:.2f}%)")

    # ── Budget ────────────────────────────────────────────────────────────────
    balance = get_balance(client)
    if balance <= 0:
        logger.warning("Balance is 0 — skipping execution.")
        save_state(state)
        return state

    budget = balance * args.budget_pct
    if args.max_budget and budget > args.max_budget:
        budget = args.max_budget

    logger.info(f"Balance: ${balance:.2f} USDC | "
                f"Budget this round: ${budget:.2f} USDC "
                f"({args.budget_pct*100:.0f}%)")

    if budget < 1.0:
        logger.warning(f"Budget ${budget:.2f} is too small to trade.")
        save_state(state)
        return state

    # ── Scan ──────────────────────────────────────────────────────────────────
    opps = scan_markets(client, args.min_gap, SCAN_LIMIT, args.tag)
    state["arbs_found"] += len(opps)

    if not opps:
        logger.info(f"No arb opportunities above {args.min_gap*100:.2f}% gap.")
        save_state(state)
        return state

    best = opps[0]
    logger.info(
        f"Best opportunity: {best['question'][:60]} | "
        f"gap {best['gap']*100:.3f}% | "
        f"net {best['net_profit_pct']*100:.2f}%"
    )
    logger.info(f"Found {len(opps)} total opportunities this round.")

    # ── Size the trade ────────────────────────────────────────────────────────
    total_price = best["total"]
    shares      = budget / total_price
    profit_est  = shares - budget
    roi         = profit_est / budget * 100

    logger.info(
        f"Trade plan: budget ${budget:.2f} | shares {shares:.4f} | "
        f"est. profit ${profit_est:.4f} ({roi:.2f}% ROI)"
    )

    # ── Liquidity check ───────────────────────────────────────────────────────
    for outcome in best["outcomes"]:
        leg_cost = shares * outcome["price"]
        depth    = get_depth(client, outcome["token_id"], leg_cost)
        if depth < leg_cost * 0.8:
            logger.warning(
                f"Low liquidity for {outcome['outcome']}: "
                f"need ${leg_cost:.2f}, found ~${depth:.2f}. Skipping."
            )
            save_state(state)
            return state

    # ── Slippage simulation ───────────────────────────────────────────────────
    # Simulate each leg against the live orderbook. Only proceed if the
    # actual fill price still leaves a positive net profit after slippage.
    if not args.skip_slippage_check:
        try:
            from execution_simulator import simulate_order, is_viable
            total_slippage = 0.0
            viable = True
            for outcome in best["outcomes"]:
                leg_cost = shares * outcome["price"]
                sim = simulate_order(client, outcome["token_id"], "BUY", leg_cost)
                total_slippage += sim.slippage_pct
                ok, net = is_viable(sim, best["net_profit_pct"])
                if not ok:
                    logger.warning(
                        f"Slippage check FAILED for {outcome['outcome']}: "
                        f"slippage {sim.slippage_pct:.2f}%  net after slip: {net*100:.2f}%  "
                        f"(gap was {best['net_profit_pct']*100:.2f}%). Skipping."
                    )
                    viable = False
                    break
                if sim.depth_warning:
                    logger.warning(
                        f"Depth warning on {outcome['outcome']}: "
                        f"book may not fill ${leg_cost:.2f}"
                    )
            if not viable:
                save_state(state)
                return state
            logger.info(
                f"Slippage check PASSED: total slippage ≈ {total_slippage:.2f}%  "
                f"net still profitable."
            )
        except ImportError:
            logger.debug("execution_simulator not found — skipping slippage check.")

    if args.dry_run:
        logger.info("[DRY RUN] Would execute the following legs:")
        for o in best["outcomes"]:
            leg_cost = shares * o["price"]
            logger.info(
                f"  BUY {shares:.4f} shares of {o['outcome']} "
                f"@ {o['price']:.4f}  =  ${leg_cost:.2f}"
            )
        logger.info("[DRY RUN] No orders placed.")
        save_state(state)
        return state

    # ── Execute ───────────────────────────────────────────────────────────────
    logger.info(f"Executing {len(best['outcomes'])} arb legs...")
    from py_clob_client.clob_types import OrderArgs, OrderType
    from py_clob_client.order_builder.constants import BUY
    order_ids  = []
    failed_legs = 0

    for i, outcome in enumerate(best["outcomes"], 1):
        leg_cost = shares * outcome["price"]
        o_args   = OrderArgs(
            token_id=outcome["token_id"],
            price=round(outcome["price"], 4),
            size=round(leg_cost, 2),
            side=BUY,
        )
        try:
            signed = client.create_order(o_args)
            resp   = client.post_order(signed, OrderType.GTC)
            oid    = (resp or {}).get("orderID") or (resp or {}).get("id", "?")
            logger.info(f"  [{i}] OK  {outcome['outcome']}  "
                        f"order {str(oid)[:20]}")
            order_ids.append(str(oid))
        except Exception as e:
            logger.error(f"  [{i}] FAIL  {outcome['outcome']}:  {e}")
            failed_legs += 1

    ok_legs = len(order_ids) - failed_legs
    logger.info(f"Executed {ok_legs}/{len(best['outcomes'])} legs successfully.")

    if ok_legs > 0:
        state["arbs_executed"] += 1
        state["total_spent"]   += budget
        state["total_profit_est"] += profit_est
        state["history"].append({
            "ts":          now_str,
            "question":    best["question"][:80],
            "gap":         round(best["gap"], 4),
            "net_pct":     round(best["net_profit_pct"], 4),
            "budget":      round(budget, 2),
            "profit_est":  round(profit_est, 4),
            "order_ids":   order_ids,
        })
        # Keep last 500 history entries
        state["history"] = state["history"][-500:]

        # ── Notify OpenClaw ──────────────────────────────────────────────────
        try:
            from notifier import notify_trade_opened
            notify_trade_opened(
                bot="auto_arbitrage",
                market=best["question"],
                market_id=best["market_id"],
                direction="ARB",
                amount_usd=round(budget, 2),
                price=None,
                order_ids=order_ids,
                extras={
                    "legs":           len(best["outcomes"]),
                    "gap_pct":        round(best["gap"] * 100, 3),
                    "net_profit_pct": round(best["net_profit_pct"] * 100, 3),
                    "profit_est_usd": round(profit_est, 4),
                },
            )
        except Exception:
            pass

    save_state(state)
    return state


# ── Main ───────────────────────────────────────────────────────────────────────
def main():
    parser = argparse.ArgumentParser(
        description="Automated Polymarket arbitrage bot"
    )
    parser.add_argument("--interval", default="15m",
                        help="Run interval: 30s | 5m | 15m | 1h | 1d  (default: 15m)")
    parser.add_argument("--min-gap", type=float, default=0.005,
                        help="Minimum arb gap to execute (default 0.005 = 0.5%%)")
    parser.add_argument("--budget-pct", type=float, default=0.05,
                        help="Fraction of balance to risk per round (default 0.05 = 5%%)")
    parser.add_argument("--max-budget", type=float, default=1.0,
                        help="Hard cap on USDC per round (default 1; 0 = no cap)")
    parser.add_argument("--tag", default="",
                        help="Restrict scan to a market tag (e.g. politics, crypto)")
    parser.add_argument("--scan-limit", type=int, default=200,
                        help="Markets to scan per round (default 200)")
    parser.add_argument("--dry-run", action="store_true",
                        help="Simulate only — no orders placed")
    parser.add_argument("--skip-slippage-check", action="store_true",
                        help="Bypass execution_simulator slippage gate (faster, less safe)")
    parser.add_argument("--once", action="store_true",
                        help="Run exactly one round and exit (for use by scheduler.py)")
    parser.add_argument("--status", action="store_true",
                        help="Print bot statistics and exit")
    args = parser.parse_args()

    # ── Hard limits (cannot be overridden by user flags) ────────────────────
    if args.max_budget and args.max_budget > 0 and not args.dry_run:
        from _guards import check_min_order
        check_min_order(args.max_budget, flag="--max-budget", bot="auto_arbitrage",
                        exit_on_fail=True)

    global SCAN_LIMIT
    SCAN_LIMIT = args.scan_limit

    # ── Status report ─────────────────────────────────────────────────────────
    if args.status:
        state = load_state()
        print("\n  Auto-Arb Bot Status")
        print(f"  {'─'*40}")
        print(f"  Total runs:       {state['runs']}")
        print(f"  Arbs found:       {state['arbs_found']}")
        print(f"  Arbs executed:    {state['arbs_executed']}")
        print(f"  Total deployed:   ${state['total_spent']:.2f} USDC")
        print(f"  Est. profit:      +${state['total_profit_est']:.4f} USDC")
        print(f"  Last run:         {state['last_run'] or 'Never'}")
        if state["history"]:
            print(f"\n  Last execution:")
            h = state["history"][-1]
            print(f"    {h['question'][:60]}")
            print(f"    Gap: {h['gap']*100:.3f}%  |  "
                  f"Budget: ${h['budget']}  |  "
                  f"Est. profit: +${h['profit_est']}")
        print()
        return

    # ── Connect ───────────────────────────────────────────────────────────────
    # Kill switch check — abort if risk_guard says stop
    from risk_guard import is_killed
    if is_killed():
        print("⛔  Kill switch is active. Run: poly risk reset")
        sys.exit(0)

    mode = "DRY RUN" if args.dry_run else "LIVE"
    logger.info(
        f"Starting auto_arbitrage  [{mode}]  interval={args.interval}  "
        f"min_gap={args.min_gap*100:.2f}%  budget={args.budget_pct*100:.0f}%  "
        f"max_budget={'$'+str(args.max_budget) if args.max_budget else 'none'}"
    )

    try:
        client = get_client(authenticated=True)
    except Exception as e:
        logger.error(f"Could not authenticate: {e}")
        sys.exit(1)

    state          = load_state()
    interval_secs  = parse_interval(args.interval)

    # ── Single-shot mode ──────────────────────────────────────────────────────
    if args.once:
        run_once(args, client, state)
        return

    # ── Loop mode ─────────────────────────────────────────────────────────────
    def _handle_stop(sig, frame):
        logger.info("Received stop signal — shutting down.")
        sys.exit(0)

    signal.signal(signal.SIGTERM, _handle_stop)
    signal.signal(signal.SIGINT,  _handle_stop)

    logger.info(f"Loop mode: running every {args.interval} "
                f"({interval_secs}s). Press Ctrl+C to stop.")
    logger.info(f"Log file: {log_path}")
    logger.info(f"State file: {STATE_FILE}")

    while True:
        try:
            state = run_once(args, client, state)
        except Exception as e:
            logger.error(f"Unhandled error in run_once: {e}", exc_info=True)

        logger.info(f"Sleeping {args.interval} until next run...")
        time.sleep(interval_secs)


if __name__ == "__main__":
    main()
