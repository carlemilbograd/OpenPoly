#!/usr/bin/env python3
"""
setup_all.py — One-command automated setup for OpenPoly.

Runs every setup step in order, skipping anything already done.
Safe to re-run at any time (fully idempotent).

Steps:
  1. Dependency check   — ensure required packages are installed
  2. .env file          — copy .env.example if .env doesn't exist
  3. Private key        — validate POLYMARKET_PRIVATE_KEY is set and non-placeholder
  4. API credentials    — derive API key/secret/passphrase via setup_credentials.py
  5. Risk guard         — set sensible default limits
  6. Scheduler jobs     — register the standard set of background jobs
  7. Database           — run db.py migrate to create/update SQLite schema
  8. Geo-block check    — warn if current IP is restricted
  9. Summary            — print setup status

Usage:
  python scripts/setup_all.py              # interactive (confirms each step)
  python scripts/setup_all.py --yes        # accept all defaults, no prompts
  python scripts/setup_all.py --skip-creds # skip credential derivation (already done)
  python scripts/setup_all.py --dry-run    # show what would be done, change nothing
"""
from __future__ import annotations
import sys, os, json, subprocess, argparse, re
from pathlib import Path

SKILL_DIR   = Path(__file__).parent.parent
SCRIPTS_DIR = Path(__file__).parent
ENV_FILE    = SKILL_DIR / ".env"
ENV_EXAMPLE = SKILL_DIR / ".env.example"
PY          = sys.executable

# Colours for terminal output
_G = "\033[32m"   # green
_Y = "\033[33m"   # yellow
_R = "\033[31m"   # red
_B = "\033[34m"   # blue
_N = "\033[0m"    # reset


def ok(msg):    print(f"  {_G}✔{_N}  {msg}")
def warn(msg):  print(f"  {_Y}⚠{_N}  {msg}")
def fail(msg):  print(f"  {_R}✘{_N}  {msg}")
def info(msg):  print(f"  {_B}→{_N}  {msg}")
def head(msg):  print(f"\n  {_B}{'─'*60}{_N}\n  {msg}\n  {_B}{'─'*60}{_N}")


def ask(prompt: str, default: str, yes: bool) -> str:
    """Prompt user with a default; return default immediately if --yes."""
    if yes:
        print(f"  {prompt} [{default}]  {_Y}(auto){_N}")
        return default
    ans = input(f"  {prompt} [{default}]: ").strip()
    return ans if ans else default


def confirm(prompt: str, yes: bool) -> bool:
    if yes:
        print(f"  {prompt}  {_Y}(auto-yes){_N}")
        return True
    ans = input(f"  {prompt} [Y/n]: ").strip().lower()
    return ans in ("", "y", "yes")


def run(cmd: list[str], capture: bool = False) -> tuple[int, str]:
    """Run a subprocess; return (returncode, stdout+stderr)."""
    result = subprocess.run(cmd, capture_output=capture, text=True)
    return result.returncode, (result.stdout or "") + (result.stderr or "")


# ── Step helpers ──────────────────────────────────────────────────────────────

def step_dependencies(dry: bool):
    head("Step 1 — Dependencies")
    packages = [
        ("py_clob_client", "py-clob-client"),
        ("requests",       "requests"),
        ("dotenv",         "python-dotenv"),
    ]
    missing = []
    for module, pkg in packages:
        try:
            __import__(module)
            ok(f"  {pkg}")
        except ImportError:
            warn(f"  {pkg}  not installed")
            missing.append(pkg)

    if missing and not dry:
        info(f"Installing: {' '.join(missing)}")
        rc, out = run([PY, "-m", "pip", "install"] + missing + ["--quiet", "--break-system-packages"])
        if rc == 0:
            ok("Packages installed successfully.")
        else:
            fail(f"pip install failed: {out[:200]}")
            sys.exit(1)
    elif missing and dry:
        warn(f"[DRY-RUN] Would install: {' '.join(missing)}")


def step_env_file(dry: bool, yes: bool) -> bool:
    """Returns True if .env is ready."""
    head("Step 2 — .env file")

    if ENV_FILE.exists():
        ok(f".env already exists at {ENV_FILE}")
        return True

    if not ENV_EXAMPLE.exists():
        fail(f".env.example not found at {ENV_EXAMPLE}")
        return False

    warn(".env does not exist")
    if dry:
        warn(f"[DRY-RUN] Would copy {ENV_EXAMPLE.name} → .env")
        return False

    if confirm("Create .env from .env.example?", yes):
        import shutil
        shutil.copy(ENV_EXAMPLE, ENV_FILE)
        ok(f"Created {ENV_FILE}")
        print(f"\n  {_Y}ACTION REQUIRED:{_N} Open .env and set POLYMARKET_PRIVATE_KEY=0xYOUR_KEY\n")
        return False  # can't continue without key
    return False


def _load_env_var(key: str) -> str:
    """Read a key from .env file or os.environ."""
    # Try os.environ first
    val = os.environ.get(key, "")
    if val:
        return val
    # Fall back to .env file
    if ENV_FILE.exists():
        for line in ENV_FILE.read_text().splitlines():
            line = line.strip()
            if line.startswith(f"{key}="):
                return line.split("=", 1)[1].strip().strip('"').strip("'")
    return ""


def step_private_key() -> bool:
    head("Step 3 — Private key validation")
    key = _load_env_var("POLYMARKET_PRIVATE_KEY")
    placeholders = {"", "0xYOUR_PRIVATE_KEY_HERE", "0xYOUR_KEY"}

    if key in placeholders:
        fail("POLYMARKET_PRIVATE_KEY is not set.")
        print(f"\n  Open {ENV_FILE} and fill in your private key, then re-run setup.\n")
        return False

    if len(key.replace("0x", "")) < 32:
        fail(f"Key looks too short — is it complete? ({len(key)} chars)")
        return False

    masked = key[:6] + "****" + key[-4:]
    ok(f"Private key found ({masked})")
    return True


def step_api_credentials(dry: bool, yes: bool, skip: bool) -> bool:
    head("Step 4 — API credentials")

    if skip:
        info("Skipping credential derivation (--skip-creds)")
        return True

    api_key = _load_env_var("POLYMARKET_API_KEY")
    if api_key and api_key not in ("", "your_api_key_here"):
        ok(f"API credentials already derived (key: {api_key[:12]}…)")
        return True

    warn("API key not yet derived")
    if dry:
        warn("[DRY-RUN] Would run setup_credentials.py")
        return True

    if confirm("Derive API key, secret, passphrase now?", yes):
        rc, out = run([PY, str(SCRIPTS_DIR / "setup_credentials.py")], capture=True)
        if rc == 0:
            ok("API credentials derived and saved to .env")
        else:
            fail(f"setup_credentials.py failed:\n{out[:300]}")
            return False
    return True


def step_risk_guard(dry: bool, yes: bool):
    head("Step 5 — Risk guard defaults")

    risk_file = SKILL_DIR / "risk_state.json"
    if risk_file.exists():
        try:
            data = json.loads(risk_file.read_text())
            cfg  = data.get("config", {})
            ok(f"risk_state.json exists "
               f"(daily_loss_cap={cfg.get('max_daily_loss_pct',0)*100:.0f}%  "
               f"max_position={cfg.get('max_position_pct',0)*100:.0f}%)")
            if not confirm("Reconfigure risk guard limits?", False if yes else True):
                return
        except Exception:
            pass

    max_loss = ask("Max daily loss % (of start-of-day balance)", "5", yes)
    max_pos  = ask("Max position size % (per trade)", "20", yes)

    if dry:
        warn(f"[DRY-RUN] Would set max_daily_loss={max_loss}%  max_position={max_pos}%")
        return

    rc1, _ = run([PY, str(SCRIPTS_DIR / "risk_guard.py"),
                  "set", "--max-daily-loss", str(float(max_loss) / 100)], capture=True)
    rc2, _ = run([PY, str(SCRIPTS_DIR / "risk_guard.py"),
                  "set", "--max-position-pct", str(float(max_pos) / 100)], capture=True)
    if rc1 == 0 and rc2 == 0:
        ok(f"Risk guard: max daily loss {max_loss}%  |  max position {max_pos}%")
    else:
        warn("risk_guard.py returned non-zero — check manually with: poly risk status")


def step_scheduler(dry: bool, yes: bool):
    head("Step 6 — Scheduler default jobs")

    config_file = SKILL_DIR / "schedule.json"
    existing_names: set[str] = set()
    if config_file.exists():
        try:
            jobs = json.loads(config_file.read_text()).get("jobs", [])
            existing_names = {j["name"] for j in jobs}
            if existing_names:
                ok(f"Scheduler already has jobs: {', '.join(sorted(existing_names))}")
                if not confirm("Register additional missing default jobs?", False if yes else True):
                    return
        except Exception:
            pass

    # Default jobs: name, script, args, interval
    default_jobs = [
        ("auto_arbitrage",       "auto_arbitrage.py",
         "--once --min-gap 0.005 --budget-pct 0.05", "15m"),
        ("auto_monitor",         "auto_monitor.py",
         "--once", "1h"),
        ("exposure_check",       "exposure.py",
         "", "6h"),
        ("watchlist_check",      "watchlist.py",
         "check", "5m"),
        ("news_trader",          "news_trader.py",
         "--once", "5m"),
        ("market_maker",         "market_maker.py",
         "--once", "30s"),
        ("ai_signals",           "ai_automation.py",
         "--once", "30m"),
        ("correlation_arbitrage","correlation_arbitrage.py",
         "--once --scan", "30m"),
    ]

    added = []
    for name, script, args, interval in default_jobs:
        if name in existing_names:
            info(f"  skip (exists): {name}")
            continue
        cmd = [
            PY, str(SCRIPTS_DIR / "scheduler.py"), "add",
            "--name", name,
            "--script", script,
            "--interval", interval,
        ]
        if args:
            cmd += ["--args", args]
        if dry:
            warn(f"[DRY-RUN] Would add job: {name}  every {interval}")
            continue
        rc, out = run(cmd, capture=True)
        if rc == 0:
            ok(f"  Added: {name}  every {interval}")
            added.append(name)
        else:
            warn(f"  Could not add {name}: {out[:80]}")

    if added:
        info(f"Start scheduler with:  poly schedule start --background")


def step_database(dry: bool, yes: bool):
    head("Step 7 — Database migration")

    db_file = SKILL_DIR / "openpoly.db"
    if db_file.exists():
        ok(f"openpoly.db exists ({db_file.stat().st_size // 1024} KB)")
        if not confirm("Run migrate to ensure schema is up-to-date?", yes):
            return
    else:
        info("openpoly.db does not exist — will be created")

    if dry:
        warn("[DRY-RUN] Would run: db.py migrate")
        return

    rc, out = run([PY, str(SCRIPTS_DIR / "db.py"), "migrate"], capture=True)
    if rc == 0:
        ok("Database migrated / created successfully.")
    else:
        warn(f"db.py migrate returned error (non-critical):\n{out[:200]}")


def step_geoblock():
    head("Step 8 — Geo-block check")
    try:
        rc, out = run([PY, str(SCRIPTS_DIR / "geoblock.py"), "--json"], capture=True)
        import json as _j
        data = _j.loads(out.strip())
        status = data.get("status", "?")
        country = data.get("country", "?")
        ip = data.get("ip", "?")
        if status == "ok":
            ok(f"Not blocked — {country} ({ip})")
        elif status == "close_only":
            warn(f"CLOSE-ONLY region — {country} ({ip}). You can close positions but not open new ones.")
        elif status == "blocked":
            fail(f"BLOCKED — {country} ({ip}). Trading is not permitted from this IP.")
        else:
            warn(f"Unknown status: {out[:100]}")
    except Exception as e:
        warn(f"Geoblock check failed (non-critical): {e}")


def step_summary(dry: bool):
    head("Setup Complete" if not dry else "Setup Dry-Run Summary")
    print(f"  {'─'*55}")
    print(f"  Next steps:")
    if not (SKILL_DIR / ".env").exists():
        print(f"  1. Fill in POLYMARKET_PRIVATE_KEY in .env")
        print(f"  2. Re-run: python scripts/setup_all.py")
    else:
        print(f"  • Talk to OpenClaw: 'Show my portfolio'")
        print(f"  • Start master bot: poly master --start --budget 500")
        print(f"  • Dry-run test:     poly master --start --dry-run")
        print(f"  • Check status:     poly master --status")
        print(f"  • Read bot trades:  poly notify")
    print(f"  {'─'*55}\n")


# ── Main ───────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="One-command OpenPoly setup")
    parser.add_argument("--yes",        action="store_true", help="Accept all defaults, no prompts")
    parser.add_argument("--dry-run",    action="store_true", help="Show what would happen, change nothing")
    parser.add_argument("--skip-creds", action="store_true", help="Skip API credential derivation")
    args = parser.parse_args()

    dry = args.dry_run
    yes = args.yes

    print(f"\n  {'═'*60}")
    print(f"  OpenPoly — Automated Setup{'  [DRY-RUN]' if dry else ''}")
    print(f"  {'═'*60}")

    step_dependencies(dry)

    env_ready = step_env_file(dry, yes)
    if not env_ready and not dry:
        step_summary(dry)
        return

    key_ok = step_private_key()
    if not key_ok and not dry:
        step_summary(dry)
        return

    step_api_credentials(dry, yes, args.skip_creds)
    step_risk_guard(dry, yes)
    step_scheduler(dry, yes)
    step_database(dry, yes)
    step_geoblock()
    step_summary(dry)


if __name__ == "__main__":
    main()
