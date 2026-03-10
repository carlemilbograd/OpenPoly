#!/usr/bin/env python3
"""
market_maker.py — Automated market-making for Polymarket.

Places a BID slightly below mid and an ASK slightly above mid, then earns
the spread every time both sides fill. Inventory control prevents over-exposure
to any single direction.

Strategy:
  mid = (best_bid + best_ask) / 2
  our_bid  = mid - spread/2   (we buy at a discount)
  our_ask  = mid + spread/2   (we sell at a premium)
  when BOTH fill → net profit ≈ spread - fees

Inventory control:
  Track net position (YES shares held) per market.
  When net_position > max_inventory → stop posting asks, post narrower bid
  When net_position < -max_inventory → stop posting bids, post narrower ask

Target markets: high-volume AND near-50/50 price (tightest natural spread).

Usage:
  python scripts/market_maker.py --scan-targets              # find best markets to make
  python scripts/market_maker.py --market-id TOKEN           # make a specific token
  python scripts/market_maker.py --market-id TOKEN --spread 0.02 --size 10
  python scripts/market_maker.py --once                      # single quote refresh (scheduler)
  python scripts/market_maker.py --loop --interval 30        # refresh every 30 seconds
  python scripts/market_maker.py --status                    # show inventory + open orders
  python scripts/market_maker.py --close --market-id TOKEN   # cancel all quotes and flatten
"""
import sys, json, time, argparse, requests
from pathlib import Path
from datetime import datetime, timezone

sys.path.insert(0, str(Path(__file__).parent))
from _client import GAMMA_API, get_client
from _utils import SKILL_DIR, LOG_DIR, FEE, load_json, save_json

STATE_FILE = SKILL_DIR / "market_maker_state.json"
LOG_FILE   = LOG_DIR / f"market_maker_{datetime.now().strftime('%Y-%m-%d')}.log"
MIN_MID         = 0.10    # don't make markets below 10¢ or above 90¢
MAX_MID         = 0.90
MIN_VOLUME_24H  = 1000    # minimum 24h volume for a market to be worth making
DEFAULT_SPREAD  = 0.02    # 2% spread default
DEFAULT_SIZE    = 10.0    # $10 per side default
DEFAULT_INV_MAX = 50.0    # max $50 net YES exposure per market


# ── State ─────────────────────────────────────────────────────────────────────
def load_state() -> dict:
    return load_json(STATE_FILE, {"inventory": {}, "order_log": [], "filled_log": [], "pnl": 0.0})


def save_state(state: dict):
    save_json(STATE_FILE, state)


def log(msg: str):
    ts = datetime.now().strftime("%H:%M:%S")
    line = f"[{ts}] {msg}"
    print(f"  {line}")
    try:
        with LOG_FILE.open("a") as f:
            f.write(line + "\n")
    except Exception:
        pass


# ── Market data ────────────────────────────────────────────────────────────────
def get_orderbook_summary(client, token_id: str) -> dict | None:
    """Return mid, best_bid, best_ask, spread from the live orderbook."""
    try:
        book = client.get_order_book(token_id)
        asks = sorted(book.asks or [], key=lambda x: float(x.price))
        bids = sorted(book.bids or [], key=lambda x: float(x.price), reverse=True)

        if not asks or not bids:
            return None

        best_ask = float(asks[0].price)
        best_bid = float(bids[0].price)
        mid      = (best_ask + best_bid) / 2
        spread   = best_ask - best_bid

        # Depth: total USD value within 2% of mid on each side
        bid_depth = sum(float(l.price) * float(l.size) for l in bids
                        if float(l.price) >= mid * 0.98)
        ask_depth = sum(float(l.price) * float(l.size) for l in asks
                        if float(l.price) <= mid * 1.02)

        return {
            "mid":       round(mid, 6),
            "best_bid":  round(best_bid, 6),
            "best_ask":  round(best_ask, 6),
            "spread":    round(spread, 6),
            "bid_depth": round(bid_depth, 2),
            "ask_depth": round(ask_depth, 2),
        }
    except Exception:
        return None


def scan_target_markets(limit: int) -> list:
    """Find markets closest to 50/50 with highest volume — ideal for market-making."""
    try:
        resp = requests.get(
            f"{GAMMA_API}/markets",
            params={"limit": limit, "active": "true", "order": "volume24hr", "ascending": "false"},
            timeout=20,
        )
        if not resp.ok:
            return []
        markets = resp.json()
    except Exception:
        return []

    candidates = []
    for m in markets:
        tokens = m.get("tokens", [])
        if not tokens:
            continue
        vol = float(m.get("volume24hr") or 0)
        if vol < MIN_VOLUME_24H:
            continue
        # Use token outcome_prices if available, else skip
        try:
            yes_price = float(tokens[0].get("price") or 0)
        except Exception:
            yes_price = 0
        if yes_price < MIN_MID or yes_price > MAX_MID:
            continue
        # Score: closer to 0.50, higher volume = better
        distance_from_50 = abs(yes_price - 0.50)
        score = vol / (1 + distance_from_50 * 10)
        candidates.append({
            "market_id":     m.get("id", ""),
            "question":      m.get("question", ""),
            "yes_token":     tokens[0].get("token_id", ""),
            "no_token":      tokens[1].get("token_id", "") if len(tokens) > 1 else "",
            "yes_price":     round(yes_price, 4),
            "volume_24h":    round(vol, 2),
            "score":         round(score, 2),
            "dist_from_50":  round(distance_from_50, 4),
        })

    candidates.sort(key=lambda x: x["score"], reverse=True)
    return candidates


# ── Order placement ────────────────────────────────────────────────────────────
def cancel_existing_quotes(client, token_id: str, state: dict):
    """Cancel any outstanding market-maker orders for this token."""
    inv = state["inventory"].get(token_id, {})
    orders_to_cancel = inv.get("active_order_ids", [])
    if not orders_to_cancel:
        return
    for oid in orders_to_cancel:
        try:
            client.cancel(order_id=oid)
        except Exception:
            pass
    inv["active_order_ids"] = []


def place_quote(client, token_id: str, side: str, price: float, size_usd: float,
                dry_run: bool) -> str | None:
    """Place a limit order. Returns order_id or None."""
    from py_clob_client.clob_types import OrderArgs, OrderType
    from py_clob_client.order_builder.constants import BUY, SELL

    poly_side = BUY if side == "BUY" else SELL
    try:
        if dry_run:
            return f"dry_{side}_{token_id[:8]}_{int(time.time())}"
        o_args = OrderArgs(
            token_id=token_id,
            price=round(price, 4),
            size=round(size_usd, 2),
            side=poly_side,
        )
        signed = client.create_order(o_args)
        resp   = client.post_order(signed, OrderType.GTC)
        return str((resp or {}).get("orderID") or (resp or {}).get("id") or "?")
    except Exception as e:
        log(f"Order error ({side} {token_id[:12]} @ {price:.4f}): {e}")
        return None


def refresh_quotes(client, token_id: str, market_q: str, spread: float,
                   size: float, max_inventory: float, state: dict, dry_run: bool):
    """Cancel and re-post quotes for a single token."""
    inv = state["inventory"].setdefault(token_id, {
        "token_id":        token_id,
        "question":        market_q,
        "net_yes":         0.0,
        "active_order_ids": [],
        "fills":           0,
        "pnl_est":         0.0,
    })

    cancel_existing_quotes(client, token_id, state)

    ob = get_orderbook_summary(client, token_id)
    if not ob:
        log(f"No orderbook data for {token_id[:16]}")
        return

    mid     = ob["mid"]
    net_yes = inv.get("net_yes", 0.0)

    if mid < MIN_MID or mid > MAX_MID:
        log(f"Skipping {token_id[:16]} — mid {mid:.3f} is outside [{MIN_MID}, {MAX_MID}]")
        return

    half_spread = spread / 2
    our_bid     = round(mid - half_spread, 4)
    our_ask     = round(mid + half_spread, 4)
    our_bid     = max(0.01, our_bid)
    our_ask     = min(0.99, our_ask)

    # Adjust size based on inventory skew
    bid_size = size
    ask_size = size

    if net_yes > 0:
        # Holding YES inventory — reduce bid size, increase ask size (unwind)
        skew_ratio = min(1.0, net_yes / max_inventory)
        bid_size  *= (1.0 - skew_ratio)
        ask_size  *= (1.0 + skew_ratio * 0.5)
    elif net_yes < 0:
        # Holding NO inventory — reduce ask size, increase bid size
        skew_ratio = min(1.0, abs(net_yes) / max_inventory)
        ask_size  *= (1.0 - skew_ratio)
        bid_size  *= (1.0 + skew_ratio * 0.5)

    bid_size = max(1.0, round(bid_size, 2))
    ask_size = max(1.0, round(ask_size, 2))

    log(f"Quoting {market_q[:40]}  mid={mid:.4f}  "
        f"bid={our_bid:.4f} (${bid_size:.2f})  ask={our_ask:.4f} (${ask_size:.2f})"
        + ("  [DRY-RUN]" if dry_run else ""))

    new_ids = []
    if max_inventory <= 0 or net_yes < max_inventory:  # only bid if not max long
        if bid_size >= 1.0:
            oid = place_quote(client, token_id, "BUY",  our_bid, bid_size, dry_run)
            if oid:
                new_ids.append(oid)
    if max_inventory <= 0 or net_yes > -max_inventory:  # only ask if not max short
        if ask_size >= 1.0:
            oid = place_quote(client, token_id, "SELL", our_ask, ask_size, dry_run)
            if oid:
                new_ids.append(oid)

    inv["active_order_ids"] = new_ids
    inv["last_quoted"]       = datetime.now(timezone.utc).isoformat()
    inv["last_mid"]          = mid


# ── Status display ─────────────────────────────────────────────────────────────
def show_status(state: dict):
    inv_map = state.get("inventory", {})
    print(f"\n  Market Maker Status\n  {'─'*70}")
    if not inv_map:
        print("  No active markets.\n")
        return
    print(f"  {'TOKEN':<18} {'QUESTION':<40} {'NET_YES':>8}  {'FILLS':>6}  {'P&L EST':>9}")
    print(f"  {'─'*18} {'─'*40} {'─'*8}  {'─'*6}  {'─'*9}")
    total_pnl = 0.0
    for token_id, inv in inv_map.items():
        q       = (inv.get("question") or "?")[:38]
        net_yes = inv.get("net_yes", 0.0)
        fills   = inv.get("fills", 0)
        pnl     = inv.get("pnl_est", 0.0)
        total_pnl += pnl
        print(f"  {token_id[:16]:<18} {q:<40} {net_yes:>8.2f}  {fills:>6}  ${pnl:>8.2f}")
    print(f"\n  Total P&L estimate: ${total_pnl:.2f}\n")


# ── Main ───────────────────────────────────────────────────────────────────────
def main():
    parser = argparse.ArgumentParser(description="Automated market maker for Polymarket")
    parser.add_argument("--market-id",    metavar="TOKEN",                     help="YES token to make a market in")
    parser.add_argument("--market-q",     default="",                          help="Question label (optional, for display)")
    parser.add_argument("--spread",       type=float, default=DEFAULT_SPREAD,  help=f"Total spread to post (default {DEFAULT_SPREAD})")
    parser.add_argument("--size",         type=float, default=DEFAULT_SIZE,    help=f"USDC per side (default {DEFAULT_SIZE})")
    parser.add_argument("--max-inventory",type=float, default=DEFAULT_INV_MAX, help=f"Max net YES exposure in USD (default {DEFAULT_INV_MAX})")
    parser.add_argument("--scan-targets", action="store_true",                 help="Find best markets to make")
    parser.add_argument("--scan-limit",   type=int,   default=200,             help="Markets to scan (default 200)")
    parser.add_argument("--loop",         action="store_true",                 help="Continuously refresh quotes")
    parser.add_argument("--interval",     type=float, default=30.0,            help="Seconds between quote refreshes (default 30)")
    parser.add_argument("--once",         action="store_true",                 help="Single quote refresh and exit")
    parser.add_argument("--dry-run",      action="store_true",                 help="Simulate without placing orders")
    parser.add_argument("--status",       action="store_true",                 help="Show inventory and open-order status")
    parser.add_argument("--close",        action="store_true",                 help="Cancel all quotes for --market-id")
    args = parser.parse_args()

    state  = load_state()
    client = get_client(authenticated=not args.dry_run)

    if args.status:
        show_status(state)
        return

    if args.scan_targets:
        print(f"\n  Scanning {args.scan_limit} markets for ideal market-making targets...\n")
        targets = scan_target_markets(args.scan_limit)
        if not targets:
            print("  No suitable targets found.\n")
            return
        print(f"  {'#':<3} {'SCORE':>7}  {'VOL 24H':>10}  {'DIST 50':>7}  {'YES':>6}  QUESTION")
        print(f"  {'─'*3} {'─'*7}  {'─'*10}  {'─'*7}  {'─'*6}  {'─'*50}")
        for i, t in enumerate(targets[:20], 1):
            print(f"  {i:<3} {t['score']:>7.0f}  ${t['volume_24h']:>9,.0f}  {t['dist_from_50']:>7.4f}  "
                  f"{t['yes_price']:>6.3f}  {t['question'][:50]}")
        print()
        return

    if args.close:
        if not args.market_id:
            print("  --close requires --market-id TOKEN\n")
            return
        cancel_existing_quotes(client, args.market_id, state)
        save_state(state)
        print(f"  ✅ Cancelled all quotes for {args.market_id[:20]}\n")
        return

    if not args.market_id and not args.scan_targets:
        # Auto-pick the best target if no market specified
        print("  No --market-id specified — scanning for best target...")
        targets = scan_target_markets(50)
        if not targets:
            print("  No suitable targets found. Specify --market-id manually.\n")
            return
        best     = targets[0]
        token_id = best["yes_token"]
        market_q = best["question"]
        print(f"  Auto-selected: {market_q[:60]}  (YES token: {token_id[:20]})\n")
    else:
        token_id = args.market_id
        market_q = args.market_q

    def do_refresh():
        refresh_quotes(
            client, token_id, market_q,
            args.spread, args.size, args.max_inventory,
            state, args.dry_run,
        )
        save_state(state)

    if args.once or args.loop:
        try:
            while True:
                do_refresh()
                if args.once:
                    break
                time.sleep(args.interval)
        except KeyboardInterrupt:
            # Cancel quotes on exit
            log("Shutting down — cancelling quotes...")
            cancel_existing_quotes(client, token_id, state)
            save_state(state)
            print("\n  Stopped.\n")
    else:
        do_refresh()


if __name__ == "__main__":
    main()
