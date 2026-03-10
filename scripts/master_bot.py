#!/usr/bin/env python3
"""
master_bot.py — Master supervisor for all OpenPoly automated strategies.

Runs every active strategy as a supervised subprocess. If a strategy crashes
it is automatically restarted (up to MAX_RESTARTS times). A heartbeat report
is pushed to the notifier every HEARTBEAT_MIN minutes so OpenClaw / the user
always knows what's running.

This file is the *single source of truth* for which strategies exist.
When a new strategy script is added, register it in STRATEGY_REGISTRY below
and it will be picked up by master_bot automatically.

Usage:
  python scripts/master_bot.py --start --budget 1000        # start all
  python scripts/master_bot.py --start --budget 1000 --dry-run
  python scripts/master_bot.py --start --only arb,mm,news   # subset
  python scripts/master_bot.py --status                      # live status table
  python scripts/master_bot.py --stop                        # graceful shutdown
  python scripts/master_bot.py --once                        # single cycle each, then exit
  python scripts/master_bot.py --pnl                         # combined P&L report

Budget aliases for --only:
  arb    = auto_arbitrage
  corr   = correlation_arbitrage
  mm     = market_maker
  news   = news_trader
  ai     = ai_automation
  mon    = auto_monitor

Interval format: 30s | 5m | 15m | 1h | 1d
"""
from __future__ import annotations
import sys, os, json, time, signal, argparse, subprocess
from datetime import datetime, timezone
from pathlib import Path

SCRIPTS_DIR = Path(__file__).parent
sys.path.insert(0, str(SCRIPTS_DIR))
from _utils import SKILL_DIR, LOG_DIR, load_json, save_json
from _guards import check_min_order, MIN_ORDER_USD

STATE_FILE    = SKILL_DIR / "master_state.json"
HEARTBEAT_MIN = 30       # minutes between heartbeat notifications
MAX_RESTARTS  = 5        # per strategy per session before giving up
RESTART_DELAY = 10       # seconds before restarting a crashed strategy

# ══════════════════════════════════════════════════════════════════════════════
#  STRATEGY REGISTRY
#  ─────────────────
#  Add any new strategy here. master_bot will supervise it automatically.
#
#  Keys:
#    script           str   — filename inside scripts/
#    loop_flags       list  — flags used when running continuously
#    once_flags       list  — flags used for a single cycle (--once mode)
#    budget_flag      str   — CLI flag to pass the per-strategy USDC budget
#    budget_pct       int   — default share of total budget (%)
#    alias            list  — short names accepted by --only
#    description      str   — shown in --status table
#    respawn_interval int   — seconds between re-runs for scan-only (--once) scripts;
#                             absent for scripts that have their own --loop flag
# ══════════════════════════════════════════════════════════════════════════════
STRATEGY_REGISTRY: dict[str, dict] = {
    "auto_arbitrage": {
        "script":      "auto_arbitrage.py",
        "loop_flags":  ["--interval", "5m"],
        "once_flags":  ["--once"],
        "budget_flag": "--max-budget",
        "budget_pct":  25,
        "alias":       ["arb"],
        "description": "Same-market YES/NO arbitrage",
    },
    "correlation_arbitrage": {
        "script":           "correlation_arbitrage.py",
        "loop_flags":       ["--once", "--scan"],   # scan-only; master re-spawns
        "once_flags":       ["--once", "--scan"],
        "budget_flag":      "--budget",
        "budget_pct":       10,
        "respawn_interval": 30 * 60,   # re-run every 30 min
        "alias":            ["corr"],
        "description": "Cross-market correlated-pair arbitrage",
    },
    "market_maker": {
        "script":      "market_maker.py",
        "loop_flags":  ["--loop", "--interval", "30"],
        "once_flags":  ["--once"],
        "budget_flag": "--size",
        "budget_pct":  15,
        "alias":       ["mm"],
        "description": "Bid/ask spread capture",
    },
    "news_trader": {
        "script":      "news_trader.py",
        "loop_flags":  ["--loop", "--interval", "5"],
        "once_flags":  ["--once"],
        "budget_flag": "--budget",
        "budget_pct":  10,
        "alias":       ["news"],
        "description": "News-driven momentum trades",
    },
    "ai_automation": {
        "script":      "ai_automation.py",
        "loop_flags":  ["--loop", "--interval", "30"],
        "once_flags":  ["--once", "--execute"],
        "budget_flag": "--budget",
        "budget_pct":  5,
        "alias":       ["ai"],
        "description": "AI/heuristic signal trading",
    },
    "auto_monitor": {
        "script":      "auto_monitor.py",
        "loop_flags":  ["--loop", "--interval", "1h"],
        "once_flags":  ["--once"],
        "budget_flag": None,          # monitor only, no budget
        "budget_pct":  0,
        "alias":       ["mon", "monitor"],
        "description": "Market anomaly alerts (no trading)",
    },
    "time_decay": {
        "script":      "time_decay.py",
        "loop_flags":  ["--loop", "--interval", "300"],
        "once_flags":  ["--once"],
        "budget_flag": "--budget",
        "budget_pct":  15,
        "alias":       ["td", "decay"],
        "description": "Resolution-timing FADE/RUSH edge",
    },
    "logical_arb": {
        "script":           "logical_arb.py",
        "loop_flags":       ["--once"],   # scan-only; master re-spawns on interval
        "once_flags":       ["--once"],
        "budget_flag":      "--budget",
        "budget_pct":       10,
        "respawn_interval": 60 * 60,   # re-run every 1 h
        "alias":            ["la", "logic"],
        "description":      "Logical constraint violation arb",
    },
    "resolution_arb": {
        "script":           "resolution_arb.py",
        "loop_flags":       ["--once"],   # scan-only; master re-spawns on interval
        "once_flags":       ["--once"],
        "budget_flag":      "--budget",
        "budget_pct":       5,
        "respawn_interval": 60 * 60,   # re-run every 1 h
        "alias":            ["res", "resarb"],
        "description":      "Near-settlement YES+NO>1 arb",
    },
    "news_latency": {
        "script":      "news_latency.py",
        "loop_flags":  ["--loop", "--interval", "10"],
        "once_flags":  ["--once"],
        "budget_flag": "--budget",
        "budget_pct":  5,
        "alias":       ["nl", "fast-news"],
        "description": "Sub-10s RSS news trading",
    },
    # ── Add new strategies below this line ────────────────────────────────────
    # "my_strategy": {
    #     "script":      "my_strategy.py",
    #     "loop_flags":  ["--loop"],
    #     "once_flags":  ["--once"],
    #     "budget_flag": "--budget",
    #     "budget_pct":  5,
    #     "alias":       ["my"],
    #     "description": "Short description",
    # },
}

# ── State ─────────────────────────────────────────────────────────────────────
_DEFAULT_STATE = {
    "started_at":    None,
    "stopped_at":    None,
    "total_budget":  0.0,
    "dry_run":       False,
    "processes":     {},   # name → {pid, restarts, started_at, log, budget, status}
}


def load_state() -> dict:  return load_json(STATE_FILE, _DEFAULT_STATE)
def save_state(s: dict):   save_json(STATE_FILE, s)


# ── Helpers ───────────────────────────────────────────────────────────────────
def _now_str() -> str:
    return datetime.now(timezone.utc).isoformat()


def _resolve_names(only_str: str | None) -> list[str]:
    """Expand alias list to canonical strategy names."""
    alias_map: dict[str, str] = {}
    for name, cfg in STRATEGY_REGISTRY.items():
        alias_map[name] = name
        for a in cfg.get("alias", []):
            alias_map[a] = name
    if not only_str:
        return list(STRATEGY_REGISTRY.keys())
    result = []
    for token in only_str.split(","):
        t = token.strip()
        if t in alias_map:
            result.append(alias_map[t])
        else:
            print(f"  ⚠️  Unknown strategy '{t}' — ignored")
    return result


def _is_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
        return True
    except (ProcessLookupError, PermissionError):
        return False


def _budget_for(name: str, total: float) -> float:
    pct = STRATEGY_REGISTRY[name].get("budget_pct", 0)
    return round(total * pct / 100, 2)


def _open_log(name: str):
    log_path = LOG_DIR / f"master_{name}_{datetime.now().strftime('%Y-%m-%d')}.log"
    return open(log_path, "a"), log_path


# ── Subprocess management ─────────────────────────────────────────────────────
def _spawn(name: str, cfg: dict, budget: float, dry_run: bool,
           once: bool, state: dict) -> subprocess.Popen | None:
    script = SCRIPTS_DIR / cfg["script"]
    if not script.exists():
        print(f"  ⚠️  {cfg['script']} not found — skipping {name}")
        return None

    flags = cfg["once_flags"] if once else cfg["loop_flags"]
    cmd   = [sys.executable, str(script)] + list(flags)

    if cfg.get("budget_flag") and budget > 0:
        cmd += [cfg["budget_flag"], str(budget)]
    if dry_run:
        cmd += ["--dry-run"]

    log_fh, log_path = _open_log(name)

    try:
        proc = subprocess.Popen(cmd, stdout=log_fh, stderr=log_fh,
                                start_new_session=True)
        info = state["processes"].setdefault(name, {
            "pid": 0, "restarts": 0, "budget": budget,
            "started_at": _now_str(), "log": str(log_path),
        })
        info["pid"]        = proc.pid
        info["status"]     = "running"
        info["started_at"] = _now_str()
        info["log"]        = str(log_path)
        return proc
    except Exception as e:
        print(f"  ❌ Could not start {name}: {e}")
        return None


def _stop_one(name: str, state: dict, quiet: bool = False):
    info = state["processes"].get(name)
    if not info:
        return
    pid = info.get("pid", 0)
    if pid and _is_alive(pid):
        try:
            os.kill(pid, signal.SIGTERM)
            if not quiet:
                print(f"  ✅ Stopped {name} (pid {pid})")
        except Exception:
            pass
    info["status"] = "stopped"


# ── Heartbeat ─────────────────────────────────────────────────────────────────
def _heartbeat(state: dict, total_budget: float):
    procs = state.get("processes", {})
    running = [n for n, p in procs.items() if p.get("status") == "running"
               and _is_alive(p.get("pid", 0))]
    stopped = [n for n, p in procs.items() if n not in running]

    lines = []
    for n in running:
        p = procs[n]
        lines.append(f"  {n}: RUNNING  pid={p.get('pid')}  budget=${p.get('budget',0):.0f}")
    for n in stopped:
        lines.append(f"  {n}: STOPPED")

    pnl = _aggregate_pnl()
    pnl_str = f"  Est. P&L: ${pnl:+.4f}" if isinstance(pnl, float) else ""

    body = (
        f"{len(running)}/{len(procs)} strategies running.  "
        f"Budget: ${total_budget:.0f}.{pnl_str}"
    )

    try:
        from notifier import notify_event
        notify_event(
            source="master_bot",
            title="Heartbeat",
            body=body,
            level="info",
            extras={
                "running":  running,
                "stopped":  stopped,
                "pnl_est":  pnl,
                "budget":   total_budget,
            },
        )
    except Exception:
        pass


# ── P&L aggregation ───────────────────────────────────────────────────────────
def _aggregate_pnl() -> float | str:
    total = 0.0
    try:
        f = SKILL_DIR / "auto_arbitrage_state.json"
        if f.exists():
            total += json.loads(f.read_text()).get("total_profit_est", 0.0)
    except Exception:
        pass
    try:
        f = SKILL_DIR / "market_maker_state.json"
        if f.exists():
            inv = json.loads(f.read_text()).get("inventory", {})
            total += sum(v.get("pnl_est", 0) for v in inv.values())
    except Exception:
        pass
    return round(total, 4)


# ── Status display ────────────────────────────────────────────────────────────
def show_status(state: dict):
    procs = state.get("processes", {})
    started = (state.get("started_at") or "?")[:19].replace("T", " ")
    budget  = state.get("total_budget", 0)
    dr      = "  [DRY-RUN]" if state.get("dry_run") else ""

    print(f"\n  Master Bot Status  started={started}  budget=${budget:.0f}{dr}")
    print(f"  {'─'*72}")
    if not procs:
        print("  No strategies registered.\n")
        return

    print(f"  {'NAME':<28} {'STATUS':>8}  {'PID':>7}  {'RESTARTS':>8}  {'BUDGET':>8}  {'DESCRIPTION'}")
    print(f"  {'─'*28} {'─'*8}  {'─'*7}  {'─'*8}  {'─'*8}  {'─'*30}")

    for name, info in procs.items():
        pid      = info.get("pid", 0)
        status   = "RUNNING" if info.get("status") == "running" and _is_alive(pid) else "STOPPED"
        restarts = info.get("restarts", 0)
        bud      = info.get("budget", 0)
        desc     = STRATEGY_REGISTRY.get(name, {}).get("description", "")[:30]
        print(f"  {name:<28} {status:>8}  {pid:>7}  {restarts:>8}  ${bud:>7.2f}  {desc}")

    pnl = _aggregate_pnl()
    print(f"\n  Est. combined P&L:  ${pnl:+.4f}" if isinstance(pnl, float) else "")
    print()


def show_pnl():
    pnl = _aggregate_pnl()
    print(f"\n  Master Bot — Aggregate P&L\n  {'─'*40}")

    labels = {
        "auto_arbitrage_state.json": "auto_arbitrage",
        "market_maker_state.json":   "market_maker",
    }
    total = 0.0
    for fname, label in labels.items():
        try:
            f = SKILL_DIR / fname
            if not f.exists():
                continue
            if label == "auto_arbitrage":
                v = json.loads(f.read_text()).get("total_profit_est", 0.0)
            else:
                inv = json.loads(f.read_text()).get("inventory", {})
                v   = sum(x.get("pnl_est", 0) for x in inv.values())
            print(f"  {label:<30} ${v:>8.4f}")
            total += v
        except Exception:
            pass

    # news + AI: count placed trades
    for fname, label in [("news_trader_state.json", "news_trader"),
                          ("ai_signals.json",        "ai_automation")]:
        try:
            f = SKILL_DIR / fname
            if not f.exists():
                continue
            data = json.loads(f.read_text())
            if label == "news_trader":
                n = sum(1 for t in data.get("trade_log", []) if t.get("status") == "placed")
                print(f"  {label:<30} {n} trade(s) placed  (unresolved)")
            else:
                n = sum(1 for s in data if s.get("execute"))
                print(f"  {label:<30} {n} signal(s) executed  (unresolved)")
        except Exception:
            pass

    print(f"\n  Total estimated profit: ${total:+.4f}\n")


# ── Main supervisor loop ──────────────────────────────────────────────────────
def _supervisor_loop(strategies: list[str], total_budget: float,
                     dry_run: bool, once: bool, state: dict):
    """
    Spawn all strategies, then loop watching for crashes and heartbeating.
    In --once mode: wait for all processes to exit, print P&L, and return.
    """
    procs: dict[str, subprocess.Popen | None] = {}

    # Notify: master started
    try:
        from notifier import notify_event
        notify_event(
            source="master_bot",
            title="Master bot started",
            body=(f"{'DRY-RUN — ' if dry_run else ''}"
                  f"{len(strategies)} strategies  •  budget ${total_budget:.0f}  •  "
                  f"mode={'once' if once else 'loop'}"),
            level="info",
            extras={"strategies": strategies, "budget": total_budget, "dry_run": dry_run},
        )
    except Exception:
        pass

    print(f"\n  {'─'*65}")
    print(f"  Starting {len(strategies)} strategies  "
          f"({'once-cycle' if once else 'continuous'}, "
          f"{'DRY-RUN' if dry_run else 'LIVE'}, "
          f"budget=${total_budget:.0f})\n")

    for name in strategies:
        cfg    = STRATEGY_REGISTRY[name]

        # Skip strategies auto-disabled by strategy_evaluator
        _master_st = load_state()
        _disabled  = _master_st.get("disabled_strategies") or []
        if name in _disabled:
            print(f"  ↷  {name} is DISABLED by strategy_evaluator — skipping. "
                  f"(run --evaluate or --re-enable {name} to restore)")
            continue

        budget = _budget_for(name, total_budget) if total_budget > 0 else 0

        # Warn if per-strategy budget is below Polymarket minimum
        if cfg.get("budget_flag") and total_budget > 0 and budget < MIN_ORDER_USD and not dry_run:
            pct = cfg.get("budget_pct", 0)
            needed = round(MIN_ORDER_USD / (pct / 100), 2) if pct > 0 else 0
            print(
                f"  ⚠️  {name}: budget ${budget:.2f} is below the minimum "
                f"${MIN_ORDER_USD:.2f}.\n"
                f"      → Increase --budget to at least ${needed:.2f}  "
                f"(or exclude {name} with --only)",
            )
            try:
                from notifier import notify_event
                notify_event(
                    source="master_bot",
                    title=f"⚠️ {name}: budget below minimum",
                    body=(
                        f"Computed budget ${budget:.2f} ({pct}% of "
                        f"${total_budget:.0f}) is below the Polymarket minimum "
                        f"${MIN_ORDER_USD:.2f}. "
                        f"Increase --budget to at least ${needed:.2f}."
                    ),
                    level="warning",
                )
            except Exception:
                pass

        p      = _spawn(name, cfg, budget, dry_run, once, state)
        procs[name] = p
        if p:
            print(f"  ✅  {name:<28} pid={p.pid:<8}  budget=${budget:.2f}")
        save_state(state)

    print()

    if once:
        # Wait for all to finish
        for name, p in procs.items():
            if p:
                try:
                    p.wait(timeout=300)
                    state["processes"][name]["status"] = "stopped"
                except subprocess.TimeoutExpired:
                    print(f"  ⚠️  {name} timed out after 5 min")
        save_state(state)
        show_pnl()
        try:
            from notifier import notify_event
            notify_event(
                source="master_bot",
                title="Once-cycle complete",
                body=f"All {len(strategies)} strategy cycles finished.",
                level="info",
            )
        except Exception:
            pass
        return

    # ── Continuous supervisor loop ────────────────────────────────────────────
    last_heartbeat = time.time()
    restart_counts: dict[str, int] = {n: 0 for n in strategies}
    # Track last-run time for scan-only strategies (those with respawn_interval)
    respawn_last: dict[str, float] = {n: 0.0 for n in strategies}

    print(f"  Supervisor running. Press Ctrl+C to stop.\n"
          f"  Use:  poly master --status\n"
          f"  Stop: poly master --stop\n")

    def _handle_stop(sig, frame):
        print("\n  Received stop signal — shutting down all strategies...\n")
        for n in list(procs.keys()):
            _stop_one(n, state, quiet=False)
        save_state(state)
        try:
            from notifier import notify_event
            notify_event(
                source="master_bot",
                title="Master bot stopped",
                body=f"Received signal {sig}.",
                level="warning",
            )
        except Exception:
            pass
        sys.exit(0)

    signal.signal(signal.SIGTERM, _handle_stop)
    signal.signal(signal.SIGINT,  _handle_stop)

    while True:
        time.sleep(5)
        for name in strategies:
            p   = procs.get(name)
            cfg = STRATEGY_REGISTRY[name]
            pid = p.pid if p else 0

            # ── Scan-only strategies: re-spawn on a fixed interval ───────────
            # These exit normally after one scan; treat a stopped process as
            # "done for now" rather than a crash, and respawn after the interval.
            if cfg.get("respawn_interval"):
                alive = p and _is_alive(pid)
                elapsed = time.time() - respawn_last[name]
                if not alive and elapsed >= cfg["respawn_interval"]:
                    budget = _budget_for(name, total_budget) if total_budget > 0 else 0
                    p = _spawn(name, cfg, budget, dry_run, once=True, state=state)
                    procs[name] = p
                    respawn_last[name] = time.time()
                continue

            # ── All other strategies: restart on crash ────────────────────────
            if p and _is_alive(pid):
                state["processes"][name]["status"] = "running"
                continue

            # Strategy is dead
            state["processes"][name]["status"] = "stopped"
            already = restart_counts[name]
            if already >= MAX_RESTARTS:
                if state["processes"][name].get("give_up_notified"):
                    continue
                state["processes"][name]["give_up_notified"] = True
                msg = f"{name} crashed {MAX_RESTARTS}× — giving up."
                print(f"  🚨  {msg}")
                try:
                    from notifier import notify_event
                    notify_event(source="master_bot", title="Strategy gave up",
                                 body=msg, level="error",
                                 extras={"strategy": name, "restarts": already})
                except Exception:
                    pass
                save_state(state)
                continue

            # Restart
            time.sleep(RESTART_DELAY)
            restart_counts[name] += 1
            state["processes"][name]["restarts"] = restart_counts[name]
            budget = _budget_for(name, total_budget) if total_budget > 0 else 0
            p = _spawn(name, cfg, budget, dry_run, once=False, state=state)
            procs[name] = p
            msg = f"Restarted {name} (attempt {restart_counts[name]}/{MAX_RESTARTS})"
            print(f"  🔄  {msg}")
            try:
                from notifier import notify_event
                notify_event(source="master_bot", title="Strategy restarted",
                             body=msg, level="warning",
                             extras={"strategy": name, "restart_count": restart_counts[name]})
            except Exception:
                pass
            save_state(state)

        # ── Heartbeat ─────────────────────────────────────────────────────────
        if time.time() - last_heartbeat >= HEARTBEAT_MIN * 60:
            _heartbeat(state, total_budget)
            last_heartbeat = time.time()
            save_state(state)


# ── Main ───────────────────────────────────────────────────────────────────────
def main():
    global HEARTBEAT_MIN
    parser = argparse.ArgumentParser(description="Master supervisor for all OpenPoly strategies")
    parser.add_argument("--start",    action="store_true", help="Start all (or --only) strategies")
    parser.add_argument("--stop",     action="store_true", help="Stop all running strategies")
    parser.add_argument("--once",     action="store_true", help="Run one cycle of each strategy then exit")
    parser.add_argument("--status",   action="store_true", help="Show status of all strategies")
    parser.add_argument("--pnl",      action="store_true", help="Show combined P&L")
    parser.add_argument("--dry-run",  action="store_true", help="Pass --dry-run to all strategies (no real orders)")
    parser.add_argument("--budget",   type=float, default=0.0, help="Total USDC budget to split across strategies")
    parser.add_argument("--only",     default=None, help="Comma-separated subset: 'arb,mm,news'")
    parser.add_argument("--heartbeat",type=int,   default=HEARTBEAT_MIN,
                        help=f"Minutes between heartbeat notifications (default {HEARTBEAT_MIN})")
    parser.add_argument("--evaluate",  action="store_true",
                        help="Show per-strategy performance report (via strategy_evaluator)")
    parser.add_argument("--list-strategies", action="store_true",
                        help="List all registered strategies and exit")
    args = parser.parse_args()

    state = load_state()

    # ── Read-only commands ────────────────────────────────────────────────────
    if args.list_strategies:
        print(f"\n  Registered strategies ({len(STRATEGY_REGISTRY)}):\n")
        for name, cfg in STRATEGY_REGISTRY.items():
            aliases = ", ".join(cfg.get("alias", []))
            print(f"  {name:<28} {cfg['budget_pct']:>3}%  aliases=[{aliases}]  {cfg['description']}")
        print()
        return

    if args.status:
        show_status(state)
        return

    if args.evaluate:
        import subprocess, sys
        evaluator = Path(__file__).parent / "strategy_evaluator.py"
        subprocess.run([sys.executable, str(evaluator), "--report", "--recommend"], check=False)
        return

    if args.pnl:
        show_pnl()
        return

    # ── Stop ──────────────────────────────────────────────────────────────────
    if args.stop:
        print("\n  Stopping all strategies...")
        for name in list(state.get("processes", {}).keys()):
            _stop_one(name, state)
        state["stopped_at"] = _now_str()
        save_state(state)
        try:
            from notifier import notify_event
            notify_event(source="master_bot", title="Master bot stopped",
                         body="All strategies stopped via --stop.", level="warning")
        except Exception:
            pass
        print()
        return

    # ── Start / once ──────────────────────────────────────────────────────────
    if args.start or args.once:
        # Kill-switch check
        try:
            from risk_guard import is_killed
            if is_killed():
                print("⛔  Kill switch is active. Run: poly risk reset")
                sys.exit(0)
        except Exception:
            pass

        strategies = _resolve_names(args.only)
        if not strategies:
            print("  No valid strategies found. Use --list-strategies to see options.")
            sys.exit(1)

        HEARTBEAT_MIN = args.heartbeat

        state["started_at"]   = _now_str()
        state["stopped_at"]   = None
        state["total_budget"] = args.budget
        state["dry_run"]      = args.dry_run
        state["processes"]    = {}
        save_state(state)

        _supervisor_loop(
            strategies=strategies,
            total_budget=args.budget,
            dry_run=args.dry_run,
            once=args.once,
            state=state,
        )
        return

    parser.print_help()


if __name__ == "__main__":
    main()
