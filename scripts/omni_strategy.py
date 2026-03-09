#!/usr/bin/env python3
"""
omni_strategy.py — All-in-one strategy orchestrator for OpenPoly.

Runs ALL strategies simultaneously in background subprocesses and reports
combined P&L, activity, and health across all running strategies.

Strategies orchestrated:
  • auto_arbitrage      — Same-market yes/no arbitrage
  • correlation_arbitrage — Cross-market correlated pair arbitrage
  • market_maker        — Bid/ask spread earning
  • news_trader         — News-driven momentum trades
  • ai_automation       — AI signal generation and execution

Usage:
  python scripts/omni_strategy.py --start                         # start all strategies
  python scripts/omni_strategy.py --start --dry-run               # dry-run all
  python scripts/omni_strategy.py --start --budget 1000           # allocate $1000 across strategies
  python scripts/omni_strategy.py --start --split arb:30,corr:30,mm:20,news:10,ai:10
  python scripts/omni_strategy.py --status                         # live status of all strategies
  python scripts/omni_strategy.py --stop                           # stop all strategies
  python scripts/omni_strategy.py --once                           # run one cycle of each, then exit
  python scripts/omni_strategy.py --pnl                            # show combined P&L report
"""
import sys, os, json, time, argparse, signal as _signal, subprocess
from pathlib import Path
from datetime import datetime, timezone

SKILL_DIR  = Path(__file__).parent.parent
SCRIPTS_DIR = Path(__file__).parent
LOG_DIR    = SKILL_DIR / "logs"
STATE_FILE = SKILL_DIR / "omni_state.json"
LOG_DIR.mkdir(exist_ok=True)

# Default budget allocation percentages
DEFAULT_SPLIT = {
    "auto_arbitrage":       30,
    "correlation_arbitrage": 25,
    "market_maker":         25,
    "news_trader":          10,
    "ai_automation":        10,
}

# Strategy configs: name → script name + default runtime flags for loop mode
STRATEGY_CONFIGS = {
    "auto_arbitrage": {
        "script":      "auto_arbitrage.py",
        "loop_flags":  ["--interval", "5"],
        "once_flags":  ["--once"],
        "budget_flag": "--max-budget",
    },
    "correlation_arbitrage": {
        "script":      "correlation_arbitrage.py",
        "loop_flags":  [],          # scan-only; execute separately
        "once_flags":  ["--once", "--scan"],
        "budget_flag": "--budget",
    },
    "market_maker": {
        "script":      "market_maker.py",
        "loop_flags":  ["--loop", "--interval", "30"],
        "once_flags":  ["--once"],
        "budget_flag": "--size",
    },
    "news_trader": {
        "script":      "news_trader.py",
        "loop_flags":  ["--loop", "--interval", "5"],
        "once_flags":  ["--once"],
        "budget_flag": "--budget",
    },
    "ai_automation": {
        "script":      "ai_automation.py",
        "loop_flags":  ["--loop", "--interval", "30"],
        "once_flags":  ["--once"],
        "budget_flag": "--budget",
    },
}


# ── State ─────────────────────────────────────────────────────────────────────
def load_state() -> dict:
    if STATE_FILE.exists():
        try:
            return json.loads(STATE_FILE.read_text())
        except Exception:
            pass
    return {"processes": {}, "started_at": None, "total_budget": 0}


def save_state(state: dict):
    STATE_FILE.write_text(json.dumps(state, indent=2))


# ── Budget splitting ───────────────────────────────────────────────────────────
def parse_split(split_str: str | None) -> dict:
    """Parse --split 'arb:30,corr:25,mm:25,news:10,ai:10' into name→pct dict."""
    aliases = {
        "arb":   "auto_arbitrage",
        "corr":  "correlation_arbitrage",
        "mm":    "market_maker",
        "news":  "news_trader",
        "ai":    "ai_automation",
    }
    if not split_str:
        return DEFAULT_SPLIT.copy()
    result = {}
    for part in split_str.split(","):
        if ":" not in part:
            continue
        name, pct = part.strip().split(":", 1)
        full_name = aliases.get(name.strip(), name.strip())
        result[full_name] = int(pct.strip())
    if not result:
        return DEFAULT_SPLIT.copy()
    # Normalize to percentages
    total = sum(result.values())
    if total != 100:
        for k in result:
            result[k] = round(result[k] / total * 100)
    return result


def budget_for(strategy: str, total_budget: float, split: dict) -> float:
    pct = split.get(strategy, 0)
    return round(total_budget * pct / 100, 2)


# ── Process management ─────────────────────────────────────────────────────────
def start_strategy(name: str, config: dict, budget: float, dry_run: bool,
                   once: bool, state: dict) -> subprocess.Popen | None:
    script = SCRIPTS_DIR / config["script"]
    if not script.exists():
        print(f"  ⚠️  {config['script']} not found — skipping {name}")
        return None

    flags = config.get("once_flags", ["--once"]) if once else config.get("loop_flags", [])
    cmd   = [sys.executable, str(script)] + list(flags)

    # Add budget
    budget_flag = config.get("budget_flag")
    if budget_flag and budget > 0:
        cmd += [budget_flag, str(budget)]

    if dry_run:
        cmd += ["--dry-run"]

    log_path = LOG_DIR / f"omni_{name}_{datetime.now().strftime('%Y-%m-%d')}.log"
    log_fh   = open(log_path, "a")

    try:
        proc = subprocess.Popen(
            cmd,
            stdout=log_fh,
            stderr=log_fh,
            start_new_session=True,
        )
        state["processes"][name] = {
            "pid":       proc.pid,
            "script":    config["script"],
            "budget":    budget,
            "dry_run":   dry_run,
            "once":      once,
            "started_at": datetime.now(timezone.utc).isoformat(),
            "log":       str(log_path),
        }
        print(f"  ✅ Started {name:<28} pid={proc.pid:<8} budget=${budget:.2f}  "
              f"log={log_path.name}")
        return proc
    except Exception as e:
        print(f"  ❌ Failed to start {name}: {e}")
        return None


def is_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
        return True
    except (ProcessLookupError, PermissionError):
        return False


def stop_strategy(name: str, state: dict):
    info = state["processes"].get(name)
    if not info:
        print(f"  {name}: not in state")
        return
    pid = info.get("pid")
    if pid and is_alive(pid):
        try:
            os.kill(pid, _signal.SIGTERM)
            print(f"  ✅ Stopped {name} (pid {pid})")
        except Exception as e:
            print(f"  ⚠️  Failed to stop {name} pid {pid}: {e}")
    else:
        print(f"  {name}: already stopped (pid {pid})")
    del state["processes"][name]


# ── Status ────────────────────────────────────────────────────────────────────
def show_status(state: dict):
    procs = state.get("processes", {})
    if not procs:
        print("\n  No strategies running.\n")
        return
    print(f"\n  {'STRATEGY':<28} {'PID':>7}  {'STATUS':>8}  {'BUDGET':>8}  STARTED")
    print(f"  {'─'*28} {'─'*7}  {'─'*8}  {'─'*8}  {'─'*24}")
    for name, info in procs.items():
        pid    = info.get("pid", 0)
        status = "RUNNING" if is_alive(pid) else "STOPPED"
        budget = info.get("budget", 0)
        since  = info.get("started_at", "?")[:19].replace("T", " ")
        dr     = "  [DRY]" if info.get("dry_run") else ""
        print(f"  {name:<28} {pid:>7}  {status:>8}  ${budget:>7.2f}  {since}{dr}")
    print()


def read_pnl() -> dict:
    """Aggregate P&L estimates from all strategy state files."""
    pnl = {}

    # auto_arbitrage
    f = SKILL_DIR / "auto_arbitrage_state.json"
    if f.exists():
        try:
            d = json.loads(f.read_text())
            pnl["auto_arbitrage"] = d.get("total_profit_est", 0.0)
        except Exception:
            pass

    # market_maker
    f = SKILL_DIR / "market_maker_state.json"
    if f.exists():
        try:
            d = json.loads(f.read_text())
            inv = d.get("inventory", {})
            pnl["market_maker"] = sum(v.get("pnl_est", 0) for v in inv.values())
        except Exception:
            pass

    # news_trader
    f = SKILL_DIR / "news_trader_state.json"
    if f.exists():
        try:
            d = json.loads(f.read_text())
            trades = d.get("trade_log", [])
            # Can't know P&L without resolution; count executed trades
            pnl["news_trader"] = f"{sum(1 for t in trades if t.get('status')=='placed')} trades placed"
        except Exception:
            pass

    # ai_automation signals
    f = SKILL_DIR / "ai_signals.json"
    if f.exists():
        try:
            sigs = json.loads(f.read_text())
            pnl["ai_automation"] = f"{sum(1 for s in sigs if s.get('execute'))} signals generated"
        except Exception:
            pass

    return pnl


def show_pnl():
    pnl = read_pnl()
    print(f"\n  Combined P&L Report\n  {'─'*50}")
    total = 0.0
    for name, val in pnl.items():
        if isinstance(val, float):
            print(f"  {name:<30} ${val:>8.2f}")
            total += val
        else:
            print(f"  {name:<30} {val}")
    print(f"\n  Total estimated profit:  ${total:.2f}\n")


# ── Main ───────────────────────────────────────────────────────────────────────
def main():
    parser = argparse.ArgumentParser(description="All-in-one Polymarket strategy runner")
    parser.add_argument("--start",    action="store_true", help="Start all strategies")
    parser.add_argument("--stop",     action="store_true", help="Stop all running strategies")
    parser.add_argument("--once",     action="store_true", help="Run one cycle of each strategy then exit")
    parser.add_argument("--status",   action="store_true", help="Show status of all running strategies")
    parser.add_argument("--pnl",      action="store_true", help="Show combined P&L from all strategies")
    parser.add_argument("--dry-run",  action="store_true", help="Pass --dry-run to all strategies")
    parser.add_argument("--budget",   type=float, default=0.0,  help="Total USDC to split across strategies")
    parser.add_argument("--split",    default=None,             help="Budget split e.g. 'arb:30,mm:25,corr:25,news:10,ai:10'")
    parser.add_argument("--only",     default=None,             help="Comma-separated subset: 'arb,mm'")
    args = parser.parse_args()

    state = load_state()

    if args.status:
        show_status(state)
        return

    if args.pnl:
        show_pnl()
        return

    if args.stop:
        print(f"\n  Stopping all strategies...")
        for name in list(state["processes"].keys()):
            stop_strategy(name, state)
        save_state(state)
        print()
        return

    if args.start or args.once:
        split      = parse_split(args.split)
        total_budget = args.budget
        once       = args.once

        # Filter to only subset if --only specified
        if args.only:
            aliases = {"arb": "auto_arbitrage", "corr": "correlation_arbitrage",
                       "mm": "market_maker", "news": "news_trader", "ai": "ai_automation"}
            only_set = set()
            for part in args.only.split(","):
                p = part.strip()
                only_set.add(aliases.get(p, p))
            strategies = {k: v for k, v in STRATEGY_CONFIGS.items() if k in only_set}
        else:
            strategies = STRATEGY_CONFIGS

        mode = "once-cycle" if once else "continuous loop"
        print(f"\n  Starting {len(strategies)} strategies ({mode}, "
              f"{'dry-run' if args.dry_run else 'LIVE'})...\n")

        if total_budget > 0:
            print(f"  Total budget: ${total_budget:.2f}")
            print(f"  Split: {split}\n")

        state["started_at"] = datetime.now(timezone.utc).isoformat()
        state["total_budget"] = total_budget

        procs = []
        for name, config in strategies.items():
            b = budget_for(name, total_budget, split) if total_budget > 0 else 0
            p = start_strategy(name, config, b, args.dry_run, once, state)
            if p:
                procs.append(p)

        save_state(state)

        if once:
            print(f"\n  Waiting for all strategies to complete...")
            for p in procs:
                try:
                    p.wait(timeout=300)
                except subprocess.TimeoutExpired:
                    print(f"  ⚠️  Process {p.pid} timed out.")
            print(f"\n  All once-cycles complete.\n")
            show_pnl()
        else:
            print(f"\n  All strategies started. Use --status to monitor.\n"
                  f"  Logs: {LOG_DIR}/omni_<strategy>_<date>.log\n"
                  f"  Stop with: python scripts/omni_strategy.py --stop\n")
        return

    parser.print_help()


if __name__ == "__main__":
    main()
