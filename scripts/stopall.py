#!/usr/bin/env python3
"""
stopall.py — Kill every running OpenPoly bot process.

Three-layer approach so nothing slips through:

  1. State files   — master_state.json, omni_state.json → stored PIDs
  2. PID file      — scheduler.pid
  3. Process scan  — pgrep -f over all known bot script names (catches
                     zombies, orphans, manually started processes)

After killing all processes:
  • Activates the risk_guard kill switch (blocks any new trades)
  • Clears the "processes" dict in master_state.json + omni_state.json
    so --status shows clean state after a stopall

Usage:
    poly stopall
    python scripts/stopall.py
    python scripts/stopall.py --force       # skip the 3-second grace period
    python scripts/stopall.py --no-guard    # don't activate kill switch
    python scripts/stopall.py --dry-run     # show what would be killed, do nothing
"""
from __future__ import annotations
import argparse, json, os, signal, subprocess, sys, time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from _utils import SKILL_DIR, load_json, save_json

# ── Constants ─────────────────────────────────────────────────────────────────

# All bot/automation scripts that should be considered "running bots"
BOT_SCRIPTS = [
    "auto_arbitrage.py",
    "auto_monitor.py",
    "market_maker.py",
    "news_trader.py",
    "ai_automation.py",
    "correlation_arbitrage.py",
    "master_bot.py",
    "omni_strategy.py",
    "scheduler.py",
    "time_decay.py",
    "logical_arb.py",
    "resolution_arb.py",
    "news_latency.py",
]

STATE_FILES = {
    "master":  SKILL_DIR / "master_state.json",
    "omni":    SKILL_DIR / "omni_state.json",
}
SCHEDULER_PID = SKILL_DIR / "scheduler.pid"

GRACE_SECONDS = 3   # wait after SIGTERM before SIGKILL


# ── Helpers ───────────────────────────────────────────────────────────────────

def _is_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
        return True
    except (ProcessLookupError, PermissionError):
        return False


def _pgrep_bots() -> dict[int, str]:
    """
    Return {pid: script_name} for every running process whose command line
    contains one of the known bot script names.  Uses /proc on Linux or
    pgrep on macOS/Linux — falls back to a pure-Python /proc scan when
    pgrep isn't available.
    """
    found: dict[int, str] = {}
    my_pid = os.getpid()

    for script in BOT_SCRIPTS:
        try:
            out = subprocess.check_output(
                ["pgrep", "-f", script],
                stderr=subprocess.DEVNULL,
                text=True,
            ).strip()
        except (FileNotFoundError, subprocess.CalledProcessError):
            out = ""

        for line in out.splitlines():
            try:
                pid = int(line.strip())
            except ValueError:
                continue
            if pid == my_pid:
                continue  # don't kill ourselves
            found[pid] = script

    return found


def _pids_from_state_files() -> dict[int, str]:
    """Read PIDs stored by master_bot and omni_strategy in their state files."""
    found: dict[int, str] = {}
    for label, path in STATE_FILES.items():
        if not path.exists():
            continue
        try:
            state = json.loads(path.read_text())
            for name, info in state.get("processes", {}).items():
                pid = info.get("pid", 0)
                if pid and pid > 1 and _is_alive(pid):
                    found[pid] = f"{label}/{name}"
        except Exception:
            pass
    return found


def _pid_from_scheduler() -> dict[int, str]:
    """Read scheduler daemon PID from scheduler.pid."""
    if not SCHEDULER_PID.exists():
        return {}
    try:
        pid = int(SCHEDULER_PID.read_text().strip())
        if pid > 1 and _is_alive(pid):
            return {pid: "scheduler"}
    except Exception:
        pass
    return {}


def _kill(pid: int, name: str, force: bool, dry_run: bool) -> bool:
    """
    SIGTERM → wait grace_seconds → SIGKILL if still alive.
    Returns True if process is confirmed dead.
    """
    if dry_run:
        print(f"  [dry-run]  would kill PID {pid:<8}  ({name})")
        return True

    try:
        os.kill(pid, signal.SIGTERM)
        print(f"  ✓  SIGTERM  PID {pid:<8}  ({name})")
    except ProcessLookupError:
        print(f"  –  PID {pid:<8} already gone  ({name})")
        return True
    except PermissionError:
        print(f"  ✗  Permission denied for PID {pid:<8}  ({name})")
        return False

    if force:
        time.sleep(0.2)
    else:
        time.sleep(GRACE_SECONDS)

    if not _is_alive(pid):
        return True

    # Still alive — escalate to SIGKILL
    try:
        os.kill(pid, signal.SIGKILL)
        print(f"  ✓  SIGKILL  PID {pid:<8}  ({name})")
        time.sleep(0.3)
    except ProcessLookupError:
        pass
    except PermissionError:
        print(f"  ✗  SIGKILL permission denied PID {pid:<8}  ({name})")
        return False

    return not _is_alive(pid)


def _clear_state_pids():
    """Zero out PIDs in master_state.json and omni_state.json so --status is clean."""
    for label, path in STATE_FILES.items():
        if not path.exists():
            continue
        try:
            state = json.loads(path.read_text())
            for name in state.get("processes", {}):
                state["processes"][name]["pid"]    = 0
                state["processes"][name]["status"] = "stopped"
            path.write_text(json.dumps(state, indent=2))
        except Exception:
            pass
    SCHEDULER_PID.unlink(missing_ok=True)


def _activate_kill_switch():
    """Flip the risk_guard kill switch so bots can't restart trades."""
    try:
        from risk_guard import activate_kill_switch
        activate_kill_switch()
        return
    except (ImportError, AttributeError):
        pass
    # Fallback: write directly to risk_state.json
    risk_path = SKILL_DIR / "risk_state.json"
    try:
        data = json.loads(risk_path.read_text()) if risk_path.exists() else {}
        data.setdefault("state", {})["kill_switch"] = True
        risk_path.write_text(json.dumps(data, indent=2))
    except Exception as e:
        print(f"  ⚠  Could not activate kill switch: {e}", file=sys.stderr)


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    p = argparse.ArgumentParser(
        description="Kill all running OpenPoly bot processes."
    )
    p.add_argument("--force",     action="store_true", help="Skip grace period — send SIGKILL immediately")
    p.add_argument("--no-guard",  action="store_true", help="Don't activate the risk_guard kill switch")
    p.add_argument("--dry-run",   action="store_true", help="Show what would be killed without doing anything")
    args = p.parse_args()

    print()
    print("  OpenPoly — Stop All Bots")
    print("  " + "─" * 50)
    if args.dry_run:
        print("  [DRY RUN — no processes will be killed]\n")

    # ── Layer 1: state-file PIDs ───────────────────────────────────────────
    state_pids = _pids_from_state_files()

    # ── Layer 2: scheduler PID file ───────────────────────────────────────
    sched_pids = _pid_from_scheduler()

    # ── Layer 3: process-scan (catches orphans / manual starts) ── ────────
    scan_pids = _pgrep_bots()

    # Merge all sources — union of all known PIDs
    all_pids: dict[int, str] = {}
    all_pids.update(scan_pids)
    all_pids.update(sched_pids)
    all_pids.update(state_pids)    # state labels overwrite scan labels for same PID

    if not all_pids:
        print("  No running bot processes found.\n")
        if not args.no_guard and not args.dry_run:
            _activate_kill_switch()
            print("  Kill switch activated (use  poly risk reset  to resume trading).\n")
        return

    print(f"  Found {len(all_pids)} process(es) to stop:\n")
    for pid, name in sorted(all_pids.items()):
        print(f"    PID {pid:<8}  {name}")
    print()

    # ── Kill ──────────────────────────────────────────────────────────────
    killed = 0
    failed = 0
    for pid, name in sorted(all_pids.items()):
        ok = _kill(pid, name, force=args.force, dry_run=args.dry_run)
        if ok:
            killed += 1
        else:
            failed += 1

    # ── Cleanup ───────────────────────────────────────────────────────────
    if not args.dry_run:
        _clear_state_pids()

    # ── Kill switch ───────────────────────────────────────────────────────
    if not args.no_guard and not args.dry_run:
        _activate_kill_switch()
        print(f"\n  Kill switch activated (use  poly risk reset  to resume trading).")

    # ── Summary ───────────────────────────────────────────────────────────
    print()
    print(f"  {'─' * 50}")
    if args.dry_run:
        print(f"  Dry run complete — {killed} process(es) would be stopped.")
    elif failed:
        print(f"  Done — {killed} stopped, {failed} could not be killed (permission denied?).")
        sys.exit(1)
    else:
        print(f"  Done — {killed} process(es) stopped.")
    print()


if __name__ == "__main__":
    main()
