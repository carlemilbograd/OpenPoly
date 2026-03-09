#!/usr/bin/env python3
"""
scheduler.py — OpenClaw automation scheduler daemon.

Manages a set of named jobs, each running a Polymarket script on a repeating
interval. Start it once; it runs in the background until stopped.

Configuration is stored in schedule.json (in the skill root).
Logs go to logs/scheduler_YYYY-MM-DD.log.

Usage:
    # Register jobs
    python scripts/scheduler.py add --name auto_arbitrage --script auto_arbitrage.py --args "--min-gap 0.005 --budget-pct 0.05 --once" --interval 15m
    python scripts/scheduler.py add --name monitor        --script auto_monitor.py   --args "--once"   --interval 1h
    python scripts/scheduler.py add --name exposure       --script exposure.py       --args ""           --interval 6h
    python scripts/scheduler.py add --name watchlist      --script watchlist.py      --args "check"      --interval 5m

    # Manage
    python scripts/scheduler.py list                       # show all jobs and next-run times
    python scripts/scheduler.py remove --name auto_arbitrage
    python scripts/scheduler.py enable  --name auto_arbitrage
    python scripts/scheduler.py disable --name auto_arbitrage

    # Run
    python scripts/scheduler.py start               # foreground (blocking) daemon
    python scripts/scheduler.py start --background  # detach, write PID file
    python scripts/scheduler.py stop                # stop background daemon
    python scripts/scheduler.py status              # show running jobs and last results

Interval format:  10s | 5m | 15m | 1h | 6h | 1d
"""
import sys, os, json, time, signal, logging, subprocess, shlex, argparse
from datetime import datetime, timezone, timedelta
from pathlib import Path

SKILL_DIR   = Path(__file__).parent.parent
CONFIG_FILE = SKILL_DIR / "schedule.json"
PID_FILE    = SKILL_DIR / "scheduler.pid"
LOG_DIR     = SKILL_DIR / "logs"
LOG_DIR.mkdir(exist_ok=True)
LOG_FILE    = LOG_DIR / f"scheduler_{datetime.now().strftime('%Y-%m-%d')}.log"

# ── Logging ───────────────────────────────────────────────────────────────────
logger = logging.getLogger("scheduler")
logger.setLevel(logging.DEBUG)
_fh = logging.FileHandler(LOG_FILE)
_fh.setFormatter(logging.Formatter("%(asctime)s  %(levelname)-7s  %(message)s"))
logger.addHandler(_fh)
_ch = logging.StreamHandler()
_ch.setFormatter(logging.Formatter("%(asctime)s  %(levelname)-7s  %(message)s"))
logger.addHandler(_ch)


# ── Interval parsing ──────────────────────────────────────────────────────────
def parse_interval(s: str) -> int:
    """'15m' → 900, '1h' → 3600, '30s' → 30, '1d' → 86400."""
    s = s.strip().lower()
    if s.endswith("s"): return int(s[:-1])
    if s.endswith("m"): return int(s[:-1]) * 60
    if s.endswith("h"): return int(s[:-1]) * 3600
    if s.endswith("d"): return int(s[:-1]) * 86400
    return int(s)


def fmt_interval(secs: int) -> str:
    if secs < 60:   return f"{secs}s"
    if secs < 3600: return f"{secs//60}m"
    if secs < 86400:return f"{secs//3600}h"
    return f"{secs//86400}d"


def next_run_in(last_run_ts: float | None, interval_secs: int) -> float:
    if last_run_ts is None:
        return 0  # run immediately
    return max(0, (last_run_ts + interval_secs) - time.time())


# ── Config ────────────────────────────────────────────────────────────────────
def load_config() -> list:
    if CONFIG_FILE.exists():
        try:
            data = json.loads(CONFIG_FILE.read_text())
            return data.get("jobs", [])
        except Exception:
            pass
    return []


def save_config(jobs: list):
    CONFIG_FILE.write_text(json.dumps({"jobs": jobs}, indent=2))


def find_job(jobs: list, name: str) -> dict | None:
    for j in jobs:
        if j["name"] == name:
            return j
    return None


# ── Exec ──────────────────────────────────────────────────────────────────────
def run_job(job: dict) -> dict:
    """
    Spawn the job script as a subprocess. Returns result info.
    """
    script_path = SKILL_DIR / "scripts" / job["script"]
    raw_args    = job.get("args", "").strip()
    cmd_parts   = [sys.executable, str(script_path)] + (
        shlex.split(raw_args) if raw_args else []
    )
    start   = time.time()
    ts      = datetime.now(timezone.utc).isoformat()
    job_log = LOG_DIR / f"job_{job['name']}_{datetime.now().strftime('%Y-%m-%d')}.log"

    logger.info(f"[{job['name']}] Starting  →  {' '.join(cmd_parts)}")

    with open(job_log, "a") as fh:
        fh.write(f"\n{'─'*60}\n{ts}\n{'─'*60}\n")
        try:
            proc = subprocess.run(
                cmd_parts,
                stdout=fh,
                stderr=fh,
                timeout=job.get("timeout", 300),   # default 5-min timeout
                cwd=str(SKILL_DIR),
            )
            exit_code = proc.returncode
        except subprocess.TimeoutExpired:
            exit_code = -1
            logger.warning(f"[{job['name']}] Timed out after "
                           f"{job.get('timeout', 300)}s")
            fh.write("\n[TIMEOUT]\n")
        except Exception as e:
            exit_code = -2
            logger.error(f"[{job['name']}] Exception: {e}")
            fh.write(f"\n[ERROR] {e}\n")

    elapsed = time.time() - start
    status  = "ok" if exit_code == 0 else f"exit({exit_code})"
    logger.info(f"[{job['name']}] Finished  status={status}  "
                f"elapsed={elapsed:.1f}s  log={job_log.name}")

    return {
        "ts":        ts,
        "status":    status,
        "exit_code": exit_code,
        "elapsed":   round(elapsed, 1),
    }


# ── Daemon loop ───────────────────────────────────────────────────────────────
def daemon_loop():
    logger.info(f"Scheduler daemon started (PID {os.getpid()})")
    logger.info(f"Config: {CONFIG_FILE}")
    logger.info(f"Log:    {LOG_FILE}")

    def _stop(sig, frame):
        logger.info("Scheduler stopping (signal received).")
        try:
            PID_FILE.unlink(missing_ok=True)
        except Exception:
            pass
        sys.exit(0)

    signal.signal(signal.SIGTERM, _stop)
    signal.signal(signal.SIGINT,  _stop)

    while True:
        jobs = load_config()
        now  = time.time()

        for job in jobs:
            if not job.get("enabled", True):
                continue

            interval_secs = parse_interval(job["interval"])
            last_ts       = job.get("last_run_ts")
            due_in        = next_run_in(last_ts, interval_secs)

            if due_in > 0:
                continue  # not yet time

            # ── Run ───────────────────────────────────────────────────────────
            result = run_job(job)

            # Update persisted state
            job["last_run_ts"]     = now
            job["last_run"]        = result["ts"]
            job["last_status"]     = result["status"]
            job["last_exit_code"]  = result["exit_code"]
            job["run_count"]       = job.get("run_count", 0) + 1
            save_config(jobs)

        time.sleep(2)  # check every 2 seconds


# ── CLI commands ──────────────────────────────────────────────────────────────
def cmd_add(args):
    jobs = load_config()
    if find_job(jobs, args.name):
        print(f"  Job '{args.name}' already exists. Remove it first.")
        sys.exit(1)

    # Validate script exists
    script_path = SKILL_DIR / "scripts" / args.script
    if not script_path.exists():
        print(f"  Warning: script not found at {script_path}")

    interval_secs = parse_interval(args.interval)

    job = {
        "name":      args.name,
        "script":    args.script,
        "args":      args.args,
        "interval":  args.interval,
        "timeout":   args.timeout,
        "enabled":   True,
        "created":   datetime.now(timezone.utc).isoformat(),
        "last_run":  None,
        "last_run_ts": None,
        "last_status": None,
        "run_count": 0,
    }
    jobs.append(job)
    save_config(jobs)

    print(f"\n  ✅  Job '{args.name}' added")
    print(f"      Script:   scripts/{args.script}")
    print(f"      Args:     {args.args or '(none)'}")
    print(f"      Interval: every {args.interval}")
    print(f"      First run: immediately when scheduler starts\n")


def cmd_remove(args):
    jobs = load_config()
    before = len(jobs)
    jobs   = [j for j in jobs if j["name"] != args.name]
    if len(jobs) == before:
        print(f"  Job '{args.name}' not found.")
        sys.exit(1)
    save_config(jobs)
    print(f"  Removed job '{args.name}'.")


def cmd_enable(args):
    jobs = load_config()
    job  = find_job(jobs, args.name)
    if not job:
        print(f"  Job '{args.name}' not found.")
        sys.exit(1)
    job["enabled"] = True
    save_config(jobs)
    print(f"  Job '{args.name}' enabled.")


def cmd_disable(args):
    jobs = load_config()
    job  = find_job(jobs, args.name)
    if not job:
        print(f"  Job '{args.name}' not found.")
        sys.exit(1)
    job["enabled"] = False
    save_config(jobs)
    print(f"  Job '{args.name}' disabled.")


def cmd_list(args):
    jobs = load_config()
    if not jobs:
        print(f"\n  No jobs configured. Use  python scripts/scheduler.py add  to register one.\n")
        return

    now = time.time()
    print(f"\n  {'NAME':<22} {'SCRIPT':<22} {'INTERVAL':<10} "
          f"{'STATUS':<10} {'NEXT RUN':<12}  RUNS")
    print(f"  {'─'*22} {'─'*22} {'─'*10} {'─'*10} {'─'*12}  {'─'*6}")

    for j in jobs:
        enabled = "" if j.get("enabled", True) else " [off]"
        interval_secs = parse_interval(j["interval"])
        due_secs = next_run_in(j.get("last_run_ts"), interval_secs)
        if due_secs <= 0:
            next_run = "now"
        elif due_secs < 60:
            next_run = f"{int(due_secs)}s"
        elif due_secs < 3600:
            next_run = f"{int(due_secs//60)}m"
        else:
            next_run = f"{int(due_secs//3600)}h {int((due_secs%3600)//60)}m"

        status = j.get("last_status") or "pending"
        runs   = j.get("run_count", 0)

        print(f"  {(j['name']+enabled):<22} {j['script']:<22} {j['interval']:<10} "
              f"{status:<10} {next_run:<12}  {runs}")

    print()


def cmd_status(args):
    jobs = load_config()

    # PID status
    if PID_FILE.exists():
        pid = PID_FILE.read_text().strip()
        try:
            os.kill(int(pid), 0)  # signal 0 = check if alive
            print(f"\n  Scheduler daemon:  RUNNING  (PID {pid})")
        except (ProcessLookupError, OSError):
            print(f"\n  Scheduler daemon:  NOT RUNNING  (stale PID {pid})")
    else:
        print(f"\n  Scheduler daemon:  NOT RUNNING")

    cmd_list(args)


def cmd_start(args):
    if args.background:
        # Spawn a detached child process running scheduler.py start --foreground
        argv = [a for a in sys.argv if a != "--background"]
        argv.append("--foreground")
        log_fd = open(LOG_FILE, "a")
        proc = subprocess.Popen(
            argv,
            stdout=log_fd,
            stderr=log_fd,
            start_new_session=True,
            cwd=str(SKILL_DIR),
        )
        PID_FILE.write_text(str(proc.pid))
        print(f"\n  Scheduler started in background (PID {proc.pid})")
        print(f"  Log:   {LOG_FILE}")
        print(f"  Stop:  python scripts/scheduler.py stop")
        print(f"  Jobs:  python scripts/scheduler.py list\n")
    else:
        daemon_loop()


def cmd_stop(args):
    if not PID_FILE.exists():
        print("  Scheduler is not running (no PID file found).")
        sys.exit(0)
    pid = int(PID_FILE.read_text().strip())
    try:
        os.kill(pid, signal.SIGTERM)
        PID_FILE.unlink(missing_ok=True)
        print(f"  Scheduler stopped (PID {pid}).")
    except ProcessLookupError:
        print(f"  Process {pid} not found (already stopped).")
        PID_FILE.unlink(missing_ok=True)
    except PermissionError:
        print(f"  Permission denied to stop PID {pid}.")
        sys.exit(1)


# ── Entry point ───────────────────────────────────────────────────────────────
def main():
    parser = argparse.ArgumentParser(
        description="OpenClaw automation scheduler"
    )
    sub = parser.add_subparsers(dest="command")

    # add
    p_add = sub.add_parser("add", help="Register a new scheduled job")
    p_add.add_argument("--name",     required=True, help="Unique job name")
    p_add.add_argument("--script",   required=True, help="Script filename under scripts/ (e.g. auto_arbitrage.py)")
    p_add.add_argument("--args",     default="",    help="Arguments to pass to the script (quoted string)")
    p_add.add_argument("--interval", default="15m", help="Run interval: 30s | 5m | 15m | 1h | 1d")
    p_add.add_argument("--timeout",  type=int, default=300, help="Max runtime per execution in seconds (default 300)")

    # remove / enable / disable
    for name, help_text in [("remove", "Remove a job"), ("enable", "Enable a job"), ("disable", "Disable a job")]:
        p = sub.add_parser(name, help=help_text)
        p.add_argument("--name", required=True)

    # list / status
    sub.add_parser("list",   help="List all scheduled jobs")
    sub.add_parser("status", help="Show daemon status + job list")

    # start / stop
    p_start = sub.add_parser("start", help="Start the scheduler daemon")
    p_start.add_argument("--background", action="store_true",
                         help="Detach and run in background")
    p_start.add_argument("--foreground", action="store_true",
                         help="Internal flag (used by --background)")
    sub.add_parser("stop", help="Stop the background daemon")

    args = parser.parse_args()

    dispatch = {
        "add":     cmd_add,
        "remove":  cmd_remove,
        "enable":  cmd_enable,
        "disable": cmd_disable,
        "list":    cmd_list,
        "status":  cmd_status,
        "start":   cmd_start,
        "stop":    cmd_stop,
    }

    if args.command not in dispatch:
        parser.print_help()
        sys.exit(0)

    dispatch[args.command](args)


if __name__ == "__main__":
    main()
