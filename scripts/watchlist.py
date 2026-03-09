#!/usr/bin/env python3
"""
Watchlist: monitor specific markets for price alerts.

Stores a persistent watchlist (JSON) in the skill root directory.
The agent calls this to add/remove markets and to check for threshold breaches.

Usage:
  python watchlist.py add --token-id TOKEN_ID [--label "My market"] [--above 0.70] [--below 0.30]
  python watchlist.py remove --token-id TOKEN_ID
  python watchlist.py list                         # show watchlist
  python watchlist.py check                        # check all prices, report alerts
  python watchlist.py check --once                 # check once and exit (default)
  python watchlist.py check --loop --interval 60   # poll every 60s

Watchlist is saved to:  <skill_root>/watchlist.json
"""
import sys, json, time, argparse, requests
from pathlib import Path
from datetime import datetime, timezone

sys.path.insert(0, str(Path(__file__).parent))
from _client import get_client, GAMMA_API

WATCHLIST_FILE = Path(__file__).parent.parent / "watchlist.json"


# ── Persistence ───────────────────────────────────────────────────────────────

def load_watchlist() -> list:
    if WATCHLIST_FILE.exists():
        try:
            return json.loads(WATCHLIST_FILE.read_text())
        except Exception:
            pass
    return []


def save_watchlist(items: list) -> None:
    WATCHLIST_FILE.write_text(json.dumps(items, indent=2))


# ── Helpers ────────────────────────────────────────────────────────────────────

def get_mid(client, token_id: str) -> float | None:
    try:
        resp = client.get_midpoint(token_id)
        return float(resp.get("mid", 0))
    except Exception:
        return None


def resolve_label(token_id: str) -> str:
    """Try to get human-readable market name from token_id."""
    try:
        resp = requests.get(
            f"{GAMMA_API}/markets",
            params={"clob_token_ids": token_id},
            timeout=5,
        )
        if resp.ok:
            markets = resp.json()
            if markets:
                question = markets[0].get("question", "")
                # find the outcome
                for t in markets[0].get("tokens", []):
                    if t.get("token_id") == token_id:
                        return f"{question[:40]} [{t.get('outcome','?')}]"
                return question[:50]
    except Exception:
        pass
    return token_id[:30] + "..."


def check_alerts(items: list, client) -> list[dict]:
    """Check all watchlist items and return triggered alerts."""
    alerts = []
    for item in items:
        tid = item.get("token_id", "")
        if not tid:
            continue
        price = get_mid(client, tid)
        if price is None:
            continue

        item["last_price"] = price
        item["last_checked"] = datetime.now(timezone.utc).isoformat()

        triggered = []
        above = item.get("above")
        below = item.get("below")

        if above is not None and price >= above:
            triggered.append(f"price {price:.4f} ≥ above threshold {above:.4f}")
        if below is not None and price <= below:
            triggered.append(f"price {price:.4f} ≤ below threshold {below:.4f}")

        if triggered:
            alerts.append({
                "token_id": tid,
                "label": item.get("label", tid[:20]),
                "price": price,
                "triggers": triggered,
            })

    save_watchlist(items)   # persist updated last_price
    return alerts


# ── Commands ──────────────────────────────────────────────────────────────────

def cmd_add(args):
    items = load_watchlist()

    existing = [i for i in items if i.get("token_id") == args.token_id]
    if existing:
        print(f"  Token {args.token_id[:20]}... is already in the watchlist.")
        print(f"  Remove it first with: python scripts/watchlist.py remove "
              f"--token-id {args.token_id}")
        sys.exit(1)

    label = args.label or resolve_label(args.token_id)
    entry = {
        "token_id": args.token_id,
        "label": label,
        "added": datetime.now(timezone.utc).isoformat(),
        "last_price": None,
        "last_checked": None,
    }
    if args.above is not None:
        entry["above"] = args.above
    if args.below is not None:
        entry["below"] = args.below

    items.append(entry)
    save_watchlist(items)

    thresholds = []
    if args.above is not None:
        thresholds.append(f"alert above {args.above:.4f}")
    if args.below is not None:
        thresholds.append(f"alert below {args.below:.4f}")
    threshold_str = "  |  " + ", ".join(thresholds) if thresholds else ""

    print(f"\n  ✅ Added to watchlist: {label}{threshold_str}")
    print(f"  Check with: python scripts/watchlist.py check\n")


def cmd_remove(args):
    items = load_watchlist()
    before = len(items)
    items = [i for i in items if i.get("token_id") != args.token_id]
    if len(items) == before:
        print(f"  Token not found in watchlist: {args.token_id[:20]}...")
        sys.exit(1)
    save_watchlist(items)
    print(f"\n  ✅ Removed from watchlist: {args.token_id[:20]}...\n")


def cmd_list(items: list, client):
    if not items:
        print("\n  Watchlist is empty.")
        print("  Add: python scripts/watchlist.py add --token-id TOKEN_ID "
              "[--above 0.70] [--below 0.30]\n")
        return

    print(f"\n{'='*80}")
    print(f"  WATCHLIST  ({len(items)} items)")
    print(f"{'='*80}")
    print(f"  {'LABEL':<42} {'CURRENT':>8}  {'ABOVE':>8}  {'BELOW':>8}  "
          f"{'LAST CHECKED':<20}")
    print(f"  {'-'*42} {'-'*8}  {'-'*8}  {'-'*8}  {'-'*20}")

    for item in items:
        tid = item.get("token_id", "")
        label = item.get("label", tid[:20])[:41]
        last_price = item.get("last_price")
        above = item.get("above")
        below = item.get("below")
        last_checked = item.get("last_checked", "never")
        if last_checked and last_checked != "never":
            last_checked = last_checked[:16].replace("T", " ")

        # Try fresh price
        if tid:
            price_live = get_mid(client, tid)
        else:
            price_live = None

        p_str = f"{price_live:.4f}" if price_live else (
            f"{last_price:.4f}" if last_price else "N/A   ")
        above_str = f"{above:.4f}" if above is not None else "  —   "
        below_str = f"{below:.4f}" if below is not None else "  —   "

        # Flag if threshold breached
        alert = ""
        if price_live:
            if above is not None and price_live >= above:
                alert = " 🔔 ABOVE"
            elif below is not None and price_live <= below:
                alert = " 🔔 BELOW"

        print(f"  {label:<42} {p_str:>8}  {above_str:>8}  {below_str:>8}  "
              f"{last_checked:<20}{alert}")

    print(f"{'='*80}\n")


def cmd_check(args, items: list, client):
    print(f"\n  Checking {len(items)} watchlist item(s)...")
    alerts = check_alerts(items, client)

    if not alerts:
        print(f"  ✅ No thresholds breached.\n")
    else:
        print(f"\n{'='*65}")
        print(f"  🔔 WATCHLIST ALERTS  —  {len(alerts)} triggered")
        print(f"{'='*65}")
        for alert in alerts:
            print(f"\n  {alert['label']}")
            print(f"  Current price: {alert['price']:.4f}  "
                  f"({alert['price']*100:.1f}%)")
            for trigger in alert["triggers"]:
                print(f"  → {trigger}")
            print(f"  Token: {alert['token_id']}")
            print(f"  Research: python scripts/research_agent.py "
                  f"--token-id {alert['token_id']}")
            print(f"  Trade:    python scripts/trade.py "
                  f"--token-id {alert['token_id']} --side BUY --price "
                  f"{alert['price']:.4f} --size 10")
        print(f"\n{'='*65}\n")

    return alerts


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="command")

    # add
    p_add = subparsers.add_parser("add", help="Add a market to the watchlist")
    p_add.add_argument("--token-id", required=True)
    p_add.add_argument("--label", default="",
                       help="Human-readable name (auto-resolved if omitted)")
    p_add.add_argument("--above", type=float, default=None,
                       help="Alert when price rises above this")
    p_add.add_argument("--below", type=float, default=None,
                       help="Alert when price drops below this")

    # remove
    p_rm = subparsers.add_parser("remove", help="Remove from watchlist")
    p_rm.add_argument("--token-id", required=True)

    # list
    subparsers.add_parser("list", help="Show all watched markets")

    # check
    p_check = subparsers.add_parser("check", help="Check prices against thresholds")
    p_check.add_argument("--loop", action="store_true",
                         help="Keep polling until interrupted")
    p_check.add_argument("--interval", type=int, default=60,
                         help="Poll interval in seconds when --loop (default 60)")

    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        sys.exit(0)

    if args.command == "add":
        cmd_add(args)
        return

    if args.command == "remove":
        cmd_remove(args)
        return

    items = load_watchlist()
    client = get_client(authenticated=False)

    if args.command == "list":
        cmd_list(items, client)
        return

    if args.command == "check":
        if not items:
            print("\n  Watchlist is empty. Add markets with:")
            print("  python scripts/watchlist.py add --token-id TOKEN_ID "
                  "[--above 0.70] [--below 0.30]\n")
            return

        if getattr(args, "loop", False):
            print(f"  Polling every {args.interval}s — press Ctrl+C to stop.\n")
            try:
                while True:
                    items = load_watchlist()
                    cmd_check(args, items, client)
                    time.sleep(args.interval)
            except KeyboardInterrupt:
                print("\n  Stopped.\n")
        else:
            cmd_check(args, items, client)


if __name__ == "__main__":
    main()
