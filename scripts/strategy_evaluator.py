#!/usr/bin/env python3
"""
strategy_evaluator.py — Per-strategy performance tracker with auto-disable.

Reads all strategy state files, computes ROI / win-rate / Sharpe / avg-edge
per strategy, and prints a ranked performance table.

With --auto-disable it writes a disabled list into master_state.json so that
master_bot skips underperforming strategies automatically.

Usage:
  python scripts/strategy_evaluator.py --report
  python scripts/strategy_evaluator.py --report --json
  python scripts/strategy_evaluator.py --auto-disable --min-trades 30
  python scripts/strategy_evaluator.py --recommend
  python scripts/strategy_evaluator.py --reset auto_arbitrage
  python scripts/strategy_evaluator.py --all           # report + recommend
"""
from __future__ import annotations

import sys, json, math, argparse
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from _utils import SKILL_DIR, load_json, save_json

# ── Strategy state file registry ──────────────────────────────────────────────
# Maps canonical strategy name → state file path (relative to SKILL_DIR)
STRATEGY_SOURCES: dict[str, Path] = {
    "auto_arbitrage":        SKILL_DIR / "auto_arbitrage_state.json",
    "news_trader":           SKILL_DIR / "news_trader_state.json",
    "market_maker":          SKILL_DIR / "market_maker_state.json",
    "ai_automation":         SKILL_DIR / "ai_signals.json",
    "correlation_arbitrage": SKILL_DIR / "correlation_arb_state.json",
    "time_decay":            SKILL_DIR / "time_decay_state.json",
    "logical_arb":           SKILL_DIR / "logical_arb_state.json",
    "resolution_arb":        SKILL_DIR / "resolution_arb_state.json",
    "news_latency":          SKILL_DIR / "news_latency_state.json",
}

MASTER_STATE_FILE = SKILL_DIR / "master_state.json"
EVAL_STATE_FILE   = SKILL_DIR / "evaluator_state.json"

_DEFAULT_MASTER: dict = {"disabled_strategies": [], "strategy_budgets": {}}


# ── Metrics extraction ─────────────────────────────────────────────────────────
def _extract_history(name: str, data: dict) -> list[dict]:
    """
    Normalise strategy state data to a flat list of trade dicts with keys:
      spent, profit_est, status, edge (all optional)
    """
    # Most state files store a "history" list
    history = data.get("history") or []
    if not isinstance(history, list):
        history = []

    # ai_signals.json uses a "signals" list
    if not history:
        history = data.get("signals") or []

    return history


def _compute_metrics(name: str, data: dict) -> dict:
    """
    Compute per-strategy metrics from raw state.
    Returns a dict usable for the report table.
    """
    history = _extract_history(name, data)
    trades_executed = int(data.get("trades_executed", 0) or 0)
    total_spent     = float(data.get("total_spent", 0.0) or 0.0)
    # Some bots store total_profit_est, some store total_pnl_est, fallback 0
    total_profit    = float(
        data.get("total_profit_est", 0.0)
        or data.get("total_pnl_est", 0.0)
        or 0.0
    )
    runs            = int(data.get("runs", 0) or 0)

    # ── Per-trade metrics from history ───────────────────────────────────────
    edges: list[float] = []
    wins = 0
    losses = 0
    daily_returns: list[float] = []

    for item in history:
        if not isinstance(item, dict):
            continue
        # Skip dry-run entries
        if item.get("dry_run") or item.get("status") == "dry_run":
            continue
        # Edge
        e = item.get("edge")
        if e is not None:
            try:
                edges.append(float(e))
            except Exception:
                pass
        # Win/loss from "outcome" or "profit" fields
        outcome = item.get("outcome")
        profit  = item.get("profit") or item.get("pnl") or item.get("profit_est")
        if outcome == "WIN" or (profit is not None and float(profit) > 0):
            wins += 1
        elif outcome == "LOSS" or (profit is not None and float(profit) < 0):
            losses += 1
        # Daily return proxy
        if profit is not None:
            try:
                daily_returns.append(float(profit))
            except Exception:
                pass

    total_trades = trades_executed or (wins + losses)
    win_rate = (wins / (wins + losses)) if (wins + losses) > 0 else None

    roi_pct = None
    if total_spent > 0:
        roi_pct = (total_profit / total_spent) * 100.0

    avg_edge = (sum(edges) / len(edges)) if edges else None

    # Simplified Sharpe: mean / std of daily returns (if we have enough data)
    sharpe = None
    if len(daily_returns) >= 5:
        mean_r = sum(daily_returns) / len(daily_returns)
        variance = sum((r - mean_r) ** 2 for r in daily_returns) / len(daily_returns)
        std_r = math.sqrt(variance) if variance > 0 else 0.0
        if std_r > 0:
            sharpe = round(mean_r / std_r, 3)

    return {
        "strategy":       name,
        "runs":           runs,
        "total_trades":   total_trades,
        "total_spent":    round(total_spent, 2),
        "total_profit":   round(total_profit, 4),
        "roi_pct":        round(roi_pct, 2) if roi_pct is not None else None,
        "win_rate":       round(win_rate * 100, 1) if win_rate is not None else None,
        "avg_edge":       round(avg_edge, 4) if avg_edge is not None else None,
        "sharpe":         sharpe,
    }


# ── Report ─────────────────────────────────────────────────────────────────────
def _load_all_metrics() -> list[dict]:
    metrics: list[dict] = []
    for name, path in STRATEGY_SOURCES.items():
        if not path.exists():
            metrics.append({
                "strategy": name, "runs": 0, "total_trades": 0,
                "total_spent": 0.0, "total_profit": 0.0,
                "roi_pct": None, "win_rate": None, "avg_edge": None, "sharpe": None,
            })
            continue
        data = load_json(path, {})
        metrics.append(_compute_metrics(name, data))

    # Sort: strategies with data first, ranked by ROI% desc, then alpha
    def _sort_key(m: dict) -> tuple:
        has_data  = 1 if (m["total_trades"] > 0 or m["runs"] > 0) else 0
        roi_val   = m["roi_pct"] if m["roi_pct"] is not None else -9999.0
        return (-has_data, -roi_val, m["strategy"])

    metrics.sort(key=_sort_key)
    return metrics


def print_report(metrics: list[dict], disabled: list[str]):
    header = (
        f"  {'Strategy':<25} {'Runs':>5} {'Trades':>7} "
        f"{'Spent $':>9} {'Profit $':>10} {'ROI%':>7} "
        f"{'Win%':>6} {'AvgEdge':>8} {'Sharpe':>7}  Status"
    )
    print(f"\n  Performance Report — {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}")
    print(f"  {'─'*len(header.rstrip())}")
    print(header)
    print(f"  {'─'*len(header.rstrip())}")

    for m in metrics:
        d          = m["strategy"] in disabled
        roi_str    = f"{m['roi_pct']:+.1f}%" if m["roi_pct"] is not None else "  —"
        win_str    = f"{m['win_rate']:.1f}%"  if m["win_rate"] is not None else "  —"
        edge_str   = f"{m['avg_edge']:.4f}"   if m["avg_edge"] is not None else "      —"
        sharpe_str = f"{m['sharpe']:.3f}"     if m["sharpe"]   is not None else "     —"
        status     = "DISABLED" if d else ("active" if m["total_trades"] > 0 else "no data")
        print(
            f"  {m['strategy']:<25} {m['runs']:>5} {m['total_trades']:>7} "
            f"${m['total_spent']:>8.2f} ${m['total_profit']:>9.4f} "
            f"{roi_str:>7} {win_str:>6} {edge_str:>8} {sharpe_str:>7}  {status}"
        )
    print()


# ── auto-disable ───────────────────────────────────────────────────────────────
def auto_disable(metrics: list[dict], min_trades: int, master: dict) -> list[str]:
    """
    Disable strategies with negative ROI after min_trades.
    Returns list of newly-disabled strategy names.
    """
    newly_disabled: list[str] = []
    disabled: set[str] = set(master.get("disabled_strategies") or [])

    for m in metrics:
        if m["total_trades"] < min_trades:
            continue
        if m["roi_pct"] is None or m["roi_pct"] >= 0:
            continue
        if m["strategy"] not in disabled:
            disabled.add(m["strategy"])
            newly_disabled.append(m["strategy"])
            print(f"  AUTO-DISABLE  {m['strategy']}  "
                  f"(ROI={m['roi_pct']:+.1f}% after {m['total_trades']} trades)")

    master["disabled_strategies"] = sorted(disabled)
    return newly_disabled


# ── recommend ──────────────────────────────────────────────────────────────────
def recommend(metrics: list[dict], disabled: list[str]):
    """Print budget-scaling recommendations."""
    print("  Recommendations\n  " + "─"*40)
    actives = [m for m in metrics if m["strategy"] not in disabled and m["total_trades"] > 0]
    if not actives:
        print("  No active strategies with trade data yet.\n")
        return

    top = actives[:3]
    bot_strats = actives[-2:] if len(actives) >= 4 else []

    for m in top:
        roi_s = f"ROI={m['roi_pct']:+.1f}%" if m["roi_pct"] is not None else "new"
        print(f"  ↑ SCALE UP   {m['strategy']:<25} {roi_s}")
    for m in bot_strats:
        roi_s = f"ROI={m['roi_pct']:+.1f}%" if m["roi_pct"] is not None else "0 trades"
        print(f"  ↓ REDUCE     {m['strategy']:<25} {roi_s}")
    print()

    no_data = [m["strategy"] for m in metrics
               if m["total_trades"] == 0 and m["strategy"] not in disabled]
    if no_data:
        print(f"  No data yet: {', '.join(no_data)}")
        print("  Run these for at least 30 trades before drawing conclusions.\n")


# ── reset ──────────────────────────────────────────────────────────────────────
def reset_strategy(name: str):
    """Zero out a strategy's state file after confirmation."""
    if name not in STRATEGY_SOURCES:
        print(f"  Unknown strategy: {name}")
        print(f"  Known: {', '.join(STRATEGY_SOURCES)}")
        return
    path = STRATEGY_SOURCES[name]
    if not path.exists():
        print(f"  No state file for {name}")
        return
    ans = input(f"  Really reset {name} state? [y/N] ").strip().lower()
    if ans != "y":
        print("  Aborted.")
        return
    path.unlink()
    print(f"  Reset {name} — state file removed.")


def re_enable_strategy(name: str, master: dict):
    """Remove strategy from disabled list."""
    disabled = set(master.get("disabled_strategies") or [])
    if name in disabled:
        disabled.discard(name)
        master["disabled_strategies"] = sorted(disabled)
        print(f"  Re-enabled {name}")
    else:
        print(f"  {name} was not disabled")


# ── Main ──────────────────────────────────────────────────────────────────────
def main():
    p = argparse.ArgumentParser(description="Strategy performance evaluator")
    p.add_argument("--report",        action="store_true",
                   help="Print performance report table")
    p.add_argument("--json",          action="store_true",
                   help="Output raw metrics as JSON")
    p.add_argument("--recommend",     action="store_true",
                   help="Print scale-up / scale-down recommendations")
    p.add_argument("--auto-disable",  action="store_true",
                   help="Auto-disable ROI<0 strategies in master_state.json")
    p.add_argument("--min-trades",    type=int, default=30,
                   help="Min trades before auto-disable (default 30)")
    p.add_argument("--reset",         metavar="STRATEGY",
                   help="Clear a strategy's state file")
    p.add_argument("--re-enable",     metavar="STRATEGY",
                   help="Remove strategy from disabled list")
    p.add_argument("--all",           action="store_true",
                   help="Run report + recommend (shortcut)")
    args = p.parse_args()

    master = load_json(MASTER_STATE_FILE, _DEFAULT_MASTER)
    disabled = master.get("disabled_strategies") or []

    if args.reset:
        reset_strategy(args.reset)
        return

    if args.re_enable:
        re_enable_strategy(args.re_enable, master)
        save_json(MASTER_STATE_FILE, master)
        return

    metrics = _load_all_metrics()

    if args.json:
        print(json.dumps(metrics, indent=2))
        return

    if args.report or args.all or not any([
        args.recommend, args.auto_disable, args.reset, args.re_enable,
    ]):
        print_report(metrics, disabled)

    if args.auto_disable:
        newly = auto_disable(metrics, args.min_trades, master)
        if newly:
            save_json(MASTER_STATE_FILE, master)
            print(f"  Saved {len(newly)} disable(s) to {MASTER_STATE_FILE}")
        else:
            print("  No strategies newly disabled.")

    if args.recommend or args.all:
        recommend(metrics, disabled)

    # Save evaluator snapshot
    snap = {
        "ts": datetime.now(timezone.utc).isoformat(),
        "metrics": metrics,
        "disabled": disabled,
    }
    save_json(EVAL_STATE_FILE, snap)


if __name__ == "__main__":
    main()
