#!/usr/bin/env python3
"""
risk_guard.py — Daily loss limit, position caps, and kill switch.

Also importable as a module by other strategy scripts:

    from risk_guard import check_limits, is_killed

CLI usage:
    python scripts/risk_guard.py status                      # current risk state
    python scripts/risk_guard.py kill                        # activate kill switch
    python scripts/risk_guard.py reset                       # clear kill switch + start new day
    python scripts/risk_guard.py set --max-daily-loss 0.05  # configure
    python scripts/risk_guard.py set --max-position-pct 0.25
    python scripts/risk_guard.py set --max-open-orders 20
    python scripts/risk_guard.py record --pnl -12.50         # log a trade PnL
    python scripts/risk_guard.py history                     # daily PnL log

Config keys (stored in risk_state.json → "config"):
    max_daily_loss_pct   float  max loss as fraction of day-start balance (default 0.05 = 5%)
    max_position_pct     float  max single trade size as fraction of balance (default 0.20 = 20%)
    max_open_orders      int    max simultaneously open orders (default 50)
    enabled              bool   whether limits are enforced (default true)

State keys (stored in risk_state.json → "state"):
    kill_switch          bool   if true, all trading is halted
    day_start_date       str    ISO date of the current tracking day
    day_start_balance    float  balance at start of day (set via --reset or first record)
    daily_pnl            float  running sum of recorded PnL for today
    total_open_orders    int    tracked open order count
    history              list   [{date, pnl, kill_switch_fired}]
"""

import argparse, json, sys
from datetime import datetime, date, timezone
from pathlib import Path

# ── Paths ─────────────────────────────────────────────────────────────────────
_SCRIPTS_DIR  = Path(__file__).parent
_SKILL_DIR    = _SCRIPTS_DIR.parent
_STATE_FILE   = _SKILL_DIR / "risk_state.json"

_DEFAULT_CONFIG = {
    "max_daily_loss_pct": 0.05,   # 5 % of day-start balance
    "max_position_pct":   0.20,   # 20 % of balance per trade
    "max_open_orders":    50,
    "enabled":            True,
}

_DEFAULT_STATE = {
    "kill_switch":       False,
    "day_start_date":    "",
    "day_start_balance": 0.0,
    "daily_pnl":         0.0,
    "total_open_orders": 0,
    "history":           [],
}


# ── State I/O ─────────────────────────────────────────────────────────────────

def _load() -> dict:
    try:
        if _STATE_FILE.exists():
            return json.loads(_STATE_FILE.read_text())
    except Exception:
        pass
    return {"config": dict(_DEFAULT_CONFIG), "state": dict(_DEFAULT_STATE)}


def _save(data: dict):
    _STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    _STATE_FILE.write_text(json.dumps(data, indent=2))


def _today() -> str:
    return date.today().isoformat()


def _roll_day(data: dict):
    """If the stored day is not today, archive yesterday and reset counters."""
    state = data["state"]
    today = _today()
    if state.get("day_start_date") == today:
        return  # same day, nothing to do

    if state.get("day_start_date"):
        # Archive previous day
        state.setdefault("history", []).append({
            "date":             state["day_start_date"],
            "pnl":              state["daily_pnl"],
            "kill_switch_fired": state["kill_switch"],
        })

    # Reset for today
    state["day_start_date"]    = today
    state["daily_pnl"]         = 0.0
    # kill_switch intentionally NOT auto-cleared on day roll — require explicit reset
    _save(data)


# ── Public module API ─────────────────────────────────────────────────────────

def is_killed() -> bool:
    """Return True if the kill switch is active. Fast (single file read)."""
    try:
        data = json.loads(_STATE_FILE.read_text()) if _STATE_FILE.exists() else {}
        return bool(data.get("state", {}).get("kill_switch", False))
    except Exception:
        return False


def check_limits(trade_size_usd: float = 0.0,
                 current_balance: float = 0.0) -> tuple[bool, str]:
    """
    Check whether a proposed trade is within configured risk limits.

    Returns (allowed: bool, reason: str).
    allowed=True means the trade is safe to proceed.

    Args:
        trade_size_usd   — size of the proposed trade in USDC
        current_balance  — current portfolio balance (0 = skip position check)
    """
    data   = _load()
    config = {**_DEFAULT_CONFIG, **data.get("config", {})}
    state  = {**_DEFAULT_STATE,  **data.get("state",  {})}

    if not config.get("enabled", True):
        return True, "risk_guard disabled"

    # ── kill switch ────────────────────────────────────────────────────────
    if state.get("kill_switch"):
        return False, "Kill switch is active — run 'poly risk reset' to resume"

    # ── daily loss limit ───────────────────────────────────────────────────
    start_bal = state.get("day_start_balance", 0.0)
    if start_bal > 0:
        daily_pnl     = state.get("daily_pnl", 0.0)
        max_loss_usd  = start_bal * config["max_daily_loss_pct"]
        if daily_pnl < -max_loss_usd:
            # Auto-fire kill switch
            state["kill_switch"] = True
            data["state"] = state
            _save(data)
            pct = config["max_daily_loss_pct"] * 100
            return (False,
                    f"Daily loss limit reached ({pct:.0f}% of ${start_bal:.0f}). "
                    f"Kill switch activated — run 'poly risk reset' to resume.")

    # ── position size cap ──────────────────────────────────────────────────
    if trade_size_usd > 0 and current_balance > 0:
        max_pos_usd = current_balance * config["max_position_pct"]
        if trade_size_usd > max_pos_usd:
            return (False,
                    f"Trade size ${trade_size_usd:.0f} exceeds max position "
                    f"({config['max_position_pct']*100:.0f}% of "
                    f"${current_balance:.0f} = ${max_pos_usd:.0f})")

    # ── open order cap ─────────────────────────────────────────────────────
    max_orders = int(config.get("max_open_orders", 50))
    if state.get("total_open_orders", 0) >= max_orders:
        return (False,
                f"Open order limit reached ({max_orders}). "
                f"Cancel some orders before placing new ones.")

    return True, "ok"


def record_pnl(pnl: float, balance_now: float = 0.0):
    """
    Record a trade's realised PnL.
    Call this after each fill to keep daily totals accurate.
    Also sets day_start_balance the first time it's called each day.
    """
    data = _load()
    _roll_day(data)

    state = data.setdefault("state", dict(_DEFAULT_STATE))

    # Set start balance on first record of the day
    if state.get("day_start_balance", 0.0) == 0.0 and balance_now > 0:
        state["day_start_balance"] = balance_now

    state["daily_pnl"] = round(state.get("daily_pnl", 0.0) + pnl, 6)
    _save(data)


# ── CLI ───────────────────────────────────────────────────────────────────────

def _status(data: dict):
    config = {**_DEFAULT_CONFIG, **data.get("config", {})}
    state  = {**_DEFAULT_STATE,  **data.get("state",  {})}

    ks   = state.get("kill_switch", False)
    pnl  = state.get("daily_pnl", 0.0)
    sb   = state.get("day_start_balance", 0.0)
    pct  = (pnl / sb * 100) if sb else 0.0

    print()
    print("═" * 52)
    print("  Risk Guard — Status")
    print("═" * 52)
    print(f"  Kill switch        {'🔴 ACTIVE' if ks else '🟢 off'}")
    print(f"  Day date           {state.get('day_start_date', '–')}")
    print(f"  Day start balance  ${sb:,.2f}")
    print(f"  Today's PnL        {'–' if not sb else f'${pnl:+,.2f} ({pct:+.1f}%)'}")
    print(f"  Open orders        {state.get('total_open_orders', 0)}")
    print()
    print(f"  Limits:")
    print(f"    max daily loss   {config['max_daily_loss_pct']*100:.1f}% "
          f"(= ${sb * config['max_daily_loss_pct']:.2f} today)")
    print(f"    max position     {config['max_position_pct']*100:.1f}% of balance")
    print(f"    max open orders  {int(config['max_open_orders'])}")
    print(f"    enabled          {'yes' if config['enabled'] else 'no (bypassed)'}")

    hist = state.get("history", [])
    if hist:
        print()
        print(f"  Recent daily PnL (last {min(7, len(hist))} days):")
        for day in hist[-7:]:
            sign = "+" if day["pnl"] >= 0 else ""
            ks_  = " ← kill switch fired" if day.get("kill_switch_fired") else ""
            print(f"    {day['date']}  {sign}${day['pnl']:.2f}{ks_}")

    print("═" * 52)


def main():
    ap = argparse.ArgumentParser(description="Risk guard — daily loss limits and kill switch")
    sub = ap.add_subparsers(dest="cmd")

    sub.add_parser("status",  help="Show current risk state")
    sub.add_parser("kill",    help="Activate kill switch (halt all trading)")
    sub.add_parser("reset",   help="Clear kill switch and start a new day")
    sub.add_parser("history", help="Show daily PnL history")

    sp_set = sub.add_parser("set", help="Configure limits")
    sp_set.add_argument("--max-daily-loss",  type=float,
                        help="Max daily loss as fraction of balance (e.g. 0.05 = 5%%)")
    sp_set.add_argument("--max-position-pct", type=float,
                        help="Max single trade as fraction of balance (e.g. 0.20)")
    sp_set.add_argument("--max-open-orders",  type=int,
                        help="Max simultaneously open orders")
    sp_set.add_argument("--disable",  action="store_true",
                        help="Disable limits (bypass risk guard)")
    sp_set.add_argument("--enable",   action="store_true",
                        help="Re-enable limits")

    sp_rec = sub.add_parser("record", help="Log a trade PnL")
    sp_rec.add_argument("--pnl",     type=float, required=True,
                        help="Realised PnL in USDC (positive or negative)")
    sp_rec.add_argument("--balance", type=float, default=0.0,
                        help="Current portfolio balance in USDC")

    sp_check = sub.add_parser("check", help="Check whether a trade is allowed")
    sp_check.add_argument("--size",    type=float, default=0.0,
                          help="Proposed trade size in USDC")
    sp_check.add_argument("--balance", type=float, default=0.0)

    args = ap.parse_args()
    data = _load()

    if args.cmd in (None, "status"):
        _roll_day(data)
        _status(data)

    elif args.cmd == "kill":
        data.setdefault("state", dict(_DEFAULT_STATE))["kill_switch"] = True
        _save(data)
        print("🔴 Kill switch activated. All trading halted.")
        print("   Run  poly risk reset  to resume.")

    elif args.cmd == "reset":
        state = data.setdefault("state", dict(_DEFAULT_STATE))
        was_killed = state.get("kill_switch", False)
        state["kill_switch"]       = False
        state["day_start_date"]    = _today()
        state["daily_pnl"]         = 0.0
        state["day_start_balance"] = 0.0
        _save(data)
        msg = "Kill switch cleared. " if was_killed else ""
        print(f"🟢 {msg}New day started. Daily PnL counter reset.")

    elif args.cmd == "set":
        cfg = data.setdefault("config", dict(_DEFAULT_CONFIG))
        changed = []
        if args.max_daily_loss is not None:
            cfg["max_daily_loss_pct"] = args.max_daily_loss
            changed.append(f"max_daily_loss_pct = {args.max_daily_loss}")
        if args.max_position_pct is not None:
            cfg["max_position_pct"] = args.max_position_pct
            changed.append(f"max_position_pct = {args.max_position_pct}")
        if args.max_open_orders is not None:
            cfg["max_open_orders"] = args.max_open_orders
            changed.append(f"max_open_orders = {args.max_open_orders}")
        if args.disable:
            cfg["enabled"] = False
            changed.append("enabled = False (bypassed)")
        if args.enable:
            cfg["enabled"] = True
            changed.append("enabled = True")
        if not changed:
            print("Nothing changed. Use --max-daily-loss, --max-position-pct, etc.")
        else:
            _save(data)
            for c in changed:
                print(f"  ✓ {c}")

    elif args.cmd == "record":
        record_pnl(args.pnl, getattr(args, "balance", 0.0))
        state = data["state"]
        print(f"  PnL recorded: ${args.pnl:+.2f}  "
              f"Today's total: ${state['daily_pnl']:.2f}")

    elif args.cmd == "check":
        ok, reason = check_limits(
            trade_size_usd=args.size,
            current_balance=args.balance,
        )
        print(f"{'✓ ALLOWED' if ok else '✗ BLOCKED'}  {reason}")
        sys.exit(0 if ok else 1)

    elif args.cmd == "history":
        _roll_day(data)
        hist = data.get("state", {}).get("history", [])
        if not hist:
            print("No daily history yet.")
            return
        print(f"\n  {'DATE':<12} {'PnL':>10}  NOTES")
        print("  " + "─" * 40)
        for day in hist[-30:]:
            sign  = "+" if day["pnl"] >= 0 else ""
            note  = " [kill switch]" if day.get("kill_switch_fired") else ""
            print(f"  {day['date']:<12} {sign}${day['pnl']:>8.2f}{note}")


if __name__ == "__main__":
    main()
