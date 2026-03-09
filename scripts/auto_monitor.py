#!/usr/bin/env python3
"""
auto_monitor.py — Automated Polymarket market monitor.

Periodically scans markets and fires alerts for:
  1. Significant price moves  (default ≥5 percentage points since last check)
  2. Sudden volume spikes     (24h volume jumped >50% vs baseline)
  3. Arbitrage opportunities  (YES+NO gap above threshold)
  4. Near-50/50 markets       (high uncertainty = prime research candidates)
  5. Extreme pricing          (<4% or >96% — potential contrarian plays)

Alerts are appended to logs/monitor_alerts.json so the agent can read them.

Usage (standalone loop):
    python scripts/auto_monitor.py --loop --interval 1h
    python scripts/auto_monitor.py --loop --interval 30m --limit 200 --price-move 0.08

Usage (single-shot, called by scheduler.py):
    python scripts/auto_monitor.py --once

Usage (read recent alerts):
    python scripts/auto_monitor.py --alerts              # last 20 alerts
    python scripts/auto_monitor.py --alerts --since 2h   # last 2 hours

Interval format:  10s | 5m | 30m | 1h | 6h | 1d
"""
import sys, json, time, signal, logging, requests, argparse
from datetime import datetime, timezone, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from _client import GAMMA_API, get_client

# ── Config ────────────────────────────────────────────────────────────────────
SKILL_DIR    = Path(__file__).parent.parent
LOG_DIR      = SKILL_DIR / "logs"
STATE_FILE   = SKILL_DIR / "monitor_state.json"
ALERTS_FILE  = LOG_DIR   / "monitor_alerts.json"
LOG_DIR.mkdir(exist_ok=True)
LOG_FILE     = LOG_DIR / f"monitor_{datetime.now().strftime('%Y-%m-%d')}.log"
FEE_ESTIMATE = 0.02

# ── Logging ───────────────────────────────────────────────────────────────────
logger = logging.getLogger("monitor")
logger.setLevel(logging.DEBUG)
_fh = logging.FileHandler(LOG_FILE)
_fh.setFormatter(logging.Formatter("%(asctime)s  %(levelname)-7s  %(message)s"))
logger.addHandler(_fh)
_ch = logging.StreamHandler()
_ch.setFormatter(logging.Formatter("%(asctime)s  %(levelname)-7s  %(message)s"))
logger.addHandler(_ch)


# ── Helpers ───────────────────────────────────────────────────────────────────
def parse_interval(s: str) -> int:
    s = s.strip().lower()
    if s.endswith("s"): return int(s[:-1])
    if s.endswith("m"): return int(s[:-1]) * 60
    if s.endswith("h"): return int(s[:-1]) * 3600
    if s.endswith("d"): return int(s[:-1]) * 86400
    return int(s)


def parse_since(s: str) -> float:
    """'2h' → unix timestamp 2 hours ago."""
    secs = parse_interval(s)
    return time.time() - secs


def load_state() -> dict:
    if STATE_FILE.exists():
        try:
            return json.loads(STATE_FILE.read_text())
        except Exception:
            pass
    return {"prices": {}, "volumes": {}, "runs": 0, "last_run": None}


def save_state(state: dict):
    STATE_FILE.write_text(json.dumps(state, indent=2))


def load_alerts() -> list:
    if ALERTS_FILE.exists():
        try:
            return json.loads(ALERTS_FILE.read_text())
        except Exception:
            pass
    return []


def save_alerts(alerts: list):
    # Keep last 2000 alerts
    alerts = alerts[-2000:]
    ALERTS_FILE.write_text(json.dumps(alerts, indent=2))


def push_alert(alerts: list, kind: str, market_id: str, question: str,
               detail: str, token_id: str = "", price: float = 0.0):
    ts = datetime.now(timezone.utc).isoformat()
    alert = {
        "ts":        ts,
        "kind":      kind,
        "market_id": market_id,
        "token_id":  token_id,
        "question":  question[:80],
        "detail":    detail,
        "price":     price,
    }
    alerts.append(alert)
    logger.info(f"ALERT [{kind}]  {question[:50]}  —  {detail}")
    return alert


def get_live_prices(client, token_ids: list) -> dict:
    prices = {}
    for tid in token_ids:
        try:
            resp = client.get_midpoint(tid)
            v = resp.get("mid")
            prices[tid] = float(v) if v else None
        except Exception:
            prices[tid] = None
    return prices


# ── Scan ───────────────────────────────────────────────────────────────────────
def run_once(args, client, state: dict, alerts: list):
    now_str    = datetime.now(timezone.utc).isoformat()
    state["runs"]    += 1
    state["last_run"] = now_str
    new_alerts = []

    logger.info(f"Run #{state['runs']} — scanning {args.limit} markets")

    params = {
        "limit":     args.limit,
        "active":    "true",
        "order":     "volume24hr",
        "ascending": "false",
    }
    try:
        resp    = requests.get(f"{GAMMA_API}/markets", params=params, timeout=20)
        markets = resp.json() if resp.ok else []
    except Exception as e:
        logger.error(f"Gamma API error: {e}")
        save_state(state)
        return

    if not markets:
        logger.warning("No markets returned from API.")
        save_state(state)
        return

    logger.info(f"Fetched {len(markets)} markets. Checking conditions...")

    for market in markets:
        question  = market.get("question", "?")
        market_id = market.get("id", "")
        tokens    = market.get("tokens", [])
        if not tokens:
            continue

        vol_24h = float(market.get("volume24hr", 0) or 0)

        # Live prices from CLOB
        token_ids  = [t.get("token_id", "") for t in tokens if t.get("token_id")]
        live_px    = get_live_prices(client, token_ids)

        outcome_data = []
        for t in tokens:
            tid   = t.get("token_id", "")
            price = live_px.get(tid)
            if price is None:
                price = float(t.get("price", 0) or 0)
            if price > 0 and tid:
                outcome_data.append({
                    "outcome":  t.get("outcome", "?"),
                    "token_id": tid,
                    "price":    price,
                })

        if len(outcome_data) < 2:
            continue

        for od in outcome_data:
            tid   = od["token_id"]
            price = od["price"]
            prev  = state["prices"].get(tid)

            # ── 1. Price move alert ────────────────────────────────────────────
            if prev is not None:
                move = abs(price - prev)
                if move >= args.price_move:
                    direction = "▲" if price > prev else "▼"
                    detail = (
                        f"{direction} {od['outcome']} moved "
                        f"{move*100:.1f}pp  "
                        f"({prev*100:.0f}% → {price*100:.0f}%)"
                    )
                    a = push_alert(alerts, "PRICE_MOVE", market_id, question,
                                   detail, tid, price)
                    new_alerts.append(a)

            # ── 2. Extreme pricing ─────────────────────────────────────────────
            if price <= 0.04 and (prev is None or prev > 0.06):
                detail = (
                    f"{od['outcome']} at extreme low {price*100:.1f}% — "
                    f"potential contrarian YES play"
                )
                a = push_alert(alerts, "EXTREME_LOW", market_id, question,
                               detail, tid, price)
                new_alerts.append(a)

            elif price >= 0.96 and (prev is None or prev < 0.94):
                detail = (
                    f"{od['outcome']} at extreme high {price*100:.1f}% — "
                    f"potential contrarian NO play"
                )
                a = push_alert(alerts, "EXTREME_HIGH", market_id, question,
                               detail, tid, price)
                new_alerts.append(a)

            # Update price state
            state["prices"][tid] = price

        # ── 3. Near-50/50 (binary markets only) ───────────────────────────────
        if len(outcome_data) == 2:
            yes_price = outcome_data[0]["price"]
            no_price  = outcome_data[1]["price"]
            spread    = abs(yes_price - no_price)
            if spread <= 0.05:  # within 5pp of 50/50
                detail = (
                    f"Near 50/50: YES {yes_price*100:.1f}% / "
                    f"NO {no_price*100:.1f}% — "
                    f"high uncertainty, prime research candidate"
                )
                # Only alert if newly near-50 (avoid spamming)
                prev_yes = state["prices"].get(outcome_data[0]["token_id"])
                if prev_yes is None or abs(prev_yes - 0.5) > 0.07:
                    a = push_alert(alerts, "NEAR_5050", market_id, question,
                                   detail, outcome_data[0]["token_id"], yes_price)
                    new_alerts.append(a)

        # ── 4. Arbitrage gap ──────────────────────────────────────────────────
        total = sum(od["price"] for od in outcome_data)
        gap   = 1.0 - total
        net   = gap - FEE_ESTIMATE
        if gap >= args.min_arb_gap and net > 0:
            prices_str = ", ".join(
                f"{od['outcome']} {od['price']*100:.1f}%" for od in outcome_data
            )
            detail = (
                f"ARB GAP {gap*100:.2f}%  net ~{net*100:.2f}% after fees | "
                f"prices: {prices_str}"
            )
            a = push_alert(alerts, "ARB_GAP", market_id, question,
                           detail, token_id=market_id, price=gap)
            new_alerts.append(a)

        # ── 5. Volume spike ───────────────────────────────────────────────────
        prev_vol = state["volumes"].get(market_id)
        if prev_vol and prev_vol > 1000 and vol_24h > prev_vol * 1.5:
            detail = (
                f"Volume spike: ${vol_24h:,.0f} vs ${prev_vol:,.0f} "
                f"24h ago (+{(vol_24h/prev_vol-1)*100:.0f}%)"
            )
            a = push_alert(alerts, "VOLUME_SPIKE", market_id, question,
                           detail, price=vol_24h)
            new_alerts.append(a)
        state["volumes"][market_id] = vol_24h

    save_state(state)
    save_alerts(alerts)

    logger.info(
        f"Run #{state['runs']} complete — "
        f"markets checked: {len(markets)}  |  "
        f"alerts fired: {len(new_alerts)}"
    )

    # Print new alerts to stdout for OpenClaw to see
    if new_alerts:
        print(f"\n  ── {len(new_alerts)} new alert(s) ──────────────────────────")
        for a in new_alerts:
            print(f"  [{a['kind']}]  {a['question'][:55]}")
            print(f"           {a['detail']}")
            # Suggest an action
            if a["kind"] == "ARB_GAP":
                print(f"           → Run: python scripts/arb_execute.py "
                      f"--market-id {a['market_id']} --budget 50")
            elif a["kind"] in ("PRICE_MOVE", "NEAR_5050"):
                print(f"           → Run: python scripts/research_agent.py "
                      f"--market-id {a['market_id']}")
            elif a["kind"] == "EXTREME_LOW":
                print(f"           → Run: python scripts/orderbook.py "
                      f"--token-id {a['token_id']}")
            print()
    else:
        print(f"  No new alerts this round ({len(markets)} markets checked).")


# ── Print alerts ──────────────────────────────────────────────────────────────
def show_alerts(args):
    alerts = load_alerts()
    if not alerts:
        print("\n  No alerts recorded yet.\n")
        return

    since_ts = None
    if hasattr(args, "since") and args.since:
        since_ts = parse_since(args.since)

    filtered = [
        a for a in alerts
        if since_ts is None or
        datetime.fromisoformat(a["ts"]).timestamp() >= since_ts
    ]

    n = getattr(args, "n", 20)
    recent = filtered[-n:]

    print(f"\n  Last {len(recent)} alert(s)"
          + (f" (past {args.since})" if since_ts else "") + ":\n")
    print(f"  {'TIME':<22} {'KIND':<14} {'MARKET':.55}")
    print(f"  {'─'*22} {'─'*14} {'─'*55}")

    for a in recent:
        ts_short = a["ts"][:19].replace("T", " ")
        print(f"  {ts_short:<22} {a['kind']:<14} {a['question'][:55]}")
        print(f"  {'':22} {'':14} {a['detail'][:55]}")

    print()

    # Suggest arb execution for any unresolved arb gaps
    arb_alerts = [a for a in recent if a["kind"] == "ARB_GAP"]
    if arb_alerts:
        print(f"  💡 {len(arb_alerts)} arbitrage gap(s) detected. "
              f"Run: python scripts/auto_arb.py --once to capture them.\n")


# ── Main ───────────────────────────────────────────────────────────────────────
def main():
    parser = argparse.ArgumentParser(
        description="Automated Polymarket market monitor"
    )
    parser.add_argument("--interval", default="1h",
                        help="Run interval: 5m | 30m | 1h | 6h (default: 1h)")
    parser.add_argument("--limit", type=int, default=150,
                        help="Markets to scan per round (default 150)")
    parser.add_argument("--price-move", type=float, default=0.05,
                        help="Minimum price move (abs) to alert on (default 0.05 = 5pp)")
    parser.add_argument("--min-arb-gap", type=float, default=0.03,
                        help="Minimum arb gap to alert on (default 0.03 = 3%%)")
    parser.add_argument("--loop", action="store_true",
                        help="Run in continuous loop (standalone mode)")
    parser.add_argument("--once", action="store_true",
                        help="Run exactly one round and exit (for scheduler.py)")
    parser.add_argument("--alerts", action="store_true",
                        help="Print recent alerts and exit")
    parser.add_argument("--since", default="",
                        help="Filter alerts by time (e.g. 2h, 24h, 7d) — use with --alerts")
    parser.add_argument("--n", type=int, default=20,
                        help="Number of recent alerts to show (default 20)")
    args = parser.parse_args()

    # ── Print alert log ───────────────────────────────────────────────────────
    if args.alerts:
        show_alerts(args)
        return

    # ── Connect (unauthenticated is enough for price data) ────────────────────
    try:
        client = get_client(authenticated=False)
    except Exception as e:
        logger.error(f"Could not create client: {e}")
        sys.exit(1)

    state  = load_state()
    alerts = load_alerts()

    # ── Single-shot ───────────────────────────────────────────────────────────
    if args.once or not args.loop:
        run_once(args, client, state, alerts)
        return

    # ── Loop mode ─────────────────────────────────────────────────────────────
    interval_secs = parse_interval(args.interval)

    def _stop(sig, frame):
        logger.info("Monitor stopping.")
        sys.exit(0)

    signal.signal(signal.SIGTERM, _stop)
    signal.signal(signal.SIGINT,  _stop)

    logger.info(f"Monitor loop started — interval {args.interval}  "
                f"price_move_threshold {args.price_move*100:.0f}pp  "
                f"arb_gap {args.min_arb_gap*100:.0f}%")
    logger.info(f"Alerts: {ALERTS_FILE}")

    while True:
        try:
            run_once(args, client, state, alerts)
            state  = load_state()   # reload in case another process updated it
            alerts = load_alerts()
        except Exception as e:
            logger.error(f"Unhandled error: {e}", exc_info=True)
        logger.info(f"Sleeping {args.interval}...")
        time.sleep(interval_secs)


if __name__ == "__main__":
    main()
