#!/usr/bin/env python3
"""
notifier.py — Central trade-notification hub for OpenPoly auto bots.

Every time a bot opens or closes a trade it calls one of the two public
functions here.  The notifier:
  1. Appends a structured record to  logs/trade_notifications.json
     (readable by the OpenClaw agent and the 'poly notify' command)
  2. Fires a macOS desktop notification via osascript so the user sees
     a banner immediately without switching apps.
  3. Prints a compact one-line summary to stdout for log files.

Public API
----------
notify_trade_opened(
    bot          : str,          # "auto_arbitrage" | "news_trader" | etc.
    market       : str,          # question text (truncated internally)
    market_id    : str,
    direction    : str,          # "YES" | "NO" | "ARB" | "BUY" | "SELL"
    amount_usd   : float,        # total USDC deployed
    price        : float | None, # fill price (0‑1); None for multi-leg arb
    order_ids    : list[str],    # placed order IDs (may be empty for dry-run)
    extras       : dict | None,  # arbitrary bot-specific metadata
)

notify_trade_closed(
    bot          : str,
    market       : str,
    market_id    : str,
    direction    : str,
    amount_usd   : float,
    pnl_est      : float | None, # estimated P&L in USDC
    order_ids    : list[str],
    extras       : dict | None,
)

Usage (read notifications):
    python scripts/notifier.py                 # last 20
    python scripts/notifier.py --limit 50
    python scripts/notifier.py --since 2h
    python scripts/notifier.py --bot news_trader
    python scripts/notifier.py --clear
"""

from __future__ import annotations
import json, os, subprocess, sys, uuid
from datetime import datetime, timezone, timedelta
from pathlib import Path

# ── Paths ──────────────────────────────────────────────────────────────────────
SKILL_DIR      = Path(__file__).parent.parent
LOG_DIR        = SKILL_DIR / "logs"
LOG_DIR.mkdir(exist_ok=True)
NOTIF_FILE     = LOG_DIR / "trade_notifications.json"
MAX_NOTIFS     = 2000          # cap the JSON file size
_MACOS_NOTIF   = sys.platform == "darwin"  # only send desktop notification on macOS


# ── Internal helpers ───────────────────────────────────────────────────────────

def _load() -> list:
    try:
        if NOTIF_FILE.exists():
            return json.loads(NOTIF_FILE.read_text())
    except Exception:
        pass
    return []


def _save(records: list):
    records = records[-MAX_NOTIFS:]
    NOTIF_FILE.write_text(json.dumps(records, indent=2))


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _desktop(title: str, subtitle: str, body: str):
    """Send a macOS Notification Center banner (non-blocking)."""
    if not _MACOS_NOTIF:
        return
    # Escape any double-quotes in the strings
    for s in (title, subtitle, body):
        _s = s.replace('"', '\\"')
    script = (
        f'display notification "{body.replace(chr(34), chr(39))}" '
        f'with title "{title.replace(chr(34), chr(39))}" '
        f'subtitle "{subtitle.replace(chr(34), chr(39))}"'
    )
    try:
        subprocess.Popen(
            ["osascript", "-e", script],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    except Exception:
        pass  # never crash a trading bot over a notification


def _print(line: str):
    ts = datetime.now().strftime("%H:%M:%S")
    print(f"  [{ts}]  🔔  {line}", flush=True)


def _record(event: str, bot: str, market: str, market_id: str, direction: str,
            amount_usd: float, price: float | None, order_ids: list,
            extras: dict | None, pnl_est: float | None) -> dict:
    return {
        "id":         str(uuid.uuid4())[:12],
        "ts":         _now(),
        "event":      event,          # "trade_opened" | "trade_closed"
        "bot":        bot,
        "market":     market[:120],
        "market_id":  market_id,
        "direction":  direction,
        "amount_usd": round(amount_usd, 4),
        "price":      round(price, 4) if price is not None else None,
        "pnl_est":    round(pnl_est, 4) if pnl_est is not None else None,
        "order_ids":  [str(o) for o in order_ids],
        **(extras or {}),
    }


# ── Public API ─────────────────────────────────────────────────────────────────

def notify_trade_opened(
    bot: str,
    market: str,
    market_id: str = "",
    direction: str = "",
    amount_usd: float = 0.0,
    price: float | None = None,
    order_ids: list | None = None,
    extras: dict | None = None,
):
    """
    Call this immediately after a bot successfully places opening order(s).
    """
    order_ids = order_ids or []
    rec = _record(
        event="trade_opened", bot=bot, market=market, market_id=market_id,
        direction=direction, amount_usd=amount_usd, price=price,
        order_ids=order_ids, extras=extras, pnl_est=None,
    )

    # Persist
    records = _load()
    records.append(rec)
    _save(records)

    # Human-readable summary
    price_str = f" @ {price:.4f}" if price is not None else ""
    orders_str = f"  ids={','.join(o[:10] for o in order_ids[:3])}" if order_ids else ""
    summary = (
        f"OPENED {direction} | {bot} | ${amount_usd:.2f}{price_str} | "
        f"{market[:55]}{orders_str}"
    )
    _print(summary)

    # Desktop notification
    _desktop(
        title=f"OpenPoly — Trade Opened",
        subtitle=f"{bot}  •  {direction}  •  ${amount_usd:.2f}",
        body=market[:80],
    )


def notify_event(
    source: str,
    title: str,
    body: str,
    level: str = "info",   # "info" | "warning" | "error"
    extras: dict | None = None,
):
    """
    General-purpose lifecycle event notification (bot started, crashed, heartbeat…).
    Appended to the same trade_notifications.json under event="system_event".
    """
    rec = {
        "id":      str(uuid.uuid4())[:12],
        "ts":      _now(),
        "event":   "system_event",
        "level":   level,
        "source":  source,
        "title":   title,
        "body":    body[:200],
        **(extras or {}),
    }
    records = _load()
    records.append(rec)
    _save(records)

    icon = {"info": "ℹ️", "warning": "⚠️", "error": "🚨"}.get(level, "ℹ️")
    _print(f"{icon}  [{source}]  {title}  — {body[:80]}")

    _desktop(
        title=f"OpenPoly — {title}",
        subtitle=source,
        body=body[:80],
    )


def notify_trade_closed(
    bot: str,
    market: str,
    market_id: str = "",
    direction: str = "",
    amount_usd: float = 0.0,
    pnl_est: float | None = None,
    order_ids: list | None = None,
    extras: dict | None = None,
):
    """
    Call this when a bot closes/exits a position or cancels resting quotes.
    """
    order_ids = order_ids or []
    rec = _record(
        event="trade_closed", bot=bot, market=market, market_id=market_id,
        direction=direction, amount_usd=amount_usd, price=None,
        order_ids=order_ids, extras=extras, pnl_est=pnl_est,
    )

    records = _load()
    records.append(rec)
    _save(records)

    pnl_str = f"  P&L est ≈${pnl_est:+.4f}" if pnl_est is not None else ""
    orders_str = f"  ids={','.join(o[:10] for o in order_ids[:3])}" if order_ids else ""
    summary = (
        f"CLOSED {direction} | {bot} | ${amount_usd:.2f}{pnl_str} | "
        f"{market[:55]}{orders_str}"
    )
    _print(summary)

    pnl_label = f"P&L ≈${pnl_est:+.4f}" if pnl_est is not None else "closed"
    _desktop(
        title=f"OpenPoly — Trade Closed",
        subtitle=f"{bot}  •  {direction}  •  {pnl_label}",
        body=market[:80],
    )


# ── CLI reader ─────────────────────────────────────────────────────────────────

def _parse_since(s: str) -> datetime:
    """'2h' → datetime 2 hours ago."""
    s = s.strip().lower()
    if s.endswith("s"):
        return datetime.now(timezone.utc) - timedelta(seconds=int(s[:-1]))
    if s.endswith("m"):
        return datetime.now(timezone.utc) - timedelta(minutes=int(s[:-1]))
    if s.endswith("h"):
        return datetime.now(timezone.utc) - timedelta(hours=int(s[:-1]))
    if s.endswith("d"):
        return datetime.now(timezone.utc) - timedelta(days=int(s[:-1]))
    return datetime.min.replace(tzinfo=timezone.utc)


def _main():
    import argparse
    p = argparse.ArgumentParser(description="Read OpenPoly trade notifications")
    p.add_argument("--limit",  type=int,   default=20,  help="Number of notifications to show (default 20)")
    p.add_argument("--since",  default="",              help="Only show notifications within this window (e.g. 2h, 30m, 1d)")
    p.add_argument("--bot",    default="",              help="Filter by bot name")
    p.add_argument("--event",  default="",              help="Filter: trade_opened | trade_closed")
    p.add_argument("--clear",  action="store_true",     help="Delete all saved notifications")
    p.add_argument("--json",   action="store_true",     help="Print raw JSON")
    args = p.parse_args()

    if args.clear:
        _save([])
        print("  Notifications cleared.\n")
        return

    records = _load()

    # Apply filters
    if args.since:
        cutoff = _parse_since(args.since)
        records = [r for r in records
                   if datetime.fromisoformat(r["ts"]) >= cutoff]
    if args.bot:
        records = [r for r in records if r.get("bot","") == args.bot]
    if args.event:
        records = [r for r in records if r.get("event","") == args.event]

    records = records[-args.limit:]

    if not records:
        print("  No notifications found.\n")
        return

    if args.json:
        print(json.dumps(records, indent=2))
        return

    # Pretty table
    print(f"\n  OpenPoly Trade Notifications  ({len(records)} shown)\n")
    print(f"  {'TIME':>8}  {'EVENT':<14}  {'BOT':<20}  {'DIR':>4}  {'$USD':>8}  MARKET")
    print(f"  {'─'*8}  {'─'*14}  {'─'*20}  {'─'*4}  {'─'*8}  {'─'*55}")
    for r in records:
        try:
            ts_dt = datetime.fromisoformat(r["ts"])
            ts_str = ts_dt.strftime("%H:%M:%S")
        except Exception:
            ts_str = r.get("ts","?")[:8]
        event  = r.get("event","?")
        symbol = "▶" if event == "trade_opened" else "■"
        pnl    = f" (+${r['pnl_est']:.3f})" if r.get("pnl_est") is not None else ""
        print(
            f"  {ts_str:>8}  {symbol} {event:<13}  "
            f"{r.get('bot','?'):<20}  {r.get('direction','?'):>4}  "
            f"${r.get('amount_usd',0):>7.2f}  "
            f"{r.get('market','?')[:55]}{pnl}"
        )
    print()


if __name__ == "__main__":
    _main()
