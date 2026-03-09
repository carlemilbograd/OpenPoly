#!/usr/bin/env python3
"""
poly — unified OpenClaw-callable CLI for the polymarket_trader skill.

Usage:
  poly <command> [args...]
  /polymarket_trader <command> [args...]   ← via OpenClaw slash command

All commands map directly to scripts/ — no LLM round-trip needed.
Run  poly help  to list available commands.
"""

import os
import sys
import subprocess

SKILL_DIR = os.path.dirname(os.path.abspath(__file__))
SCRIPTS   = os.path.join(SKILL_DIR, "scripts")

# ── command → (script, description) ─────────────────────────────────────────
COMMANDS = {
    # Core
    "portfolio":    ("portfolio.py",             "Show balance and open positions"),
    "markets":      ("markets.py",               "Browse / search markets  [--query TEXT] [--limit N]"),
    "orderbook":    ("orderbook.py",             "View orderbook  --token-id ID  [--depth N]"),
    "open-orders":  ("open_orders.py",           "List unfilled orders  [--market-id ID] [--side BUY|SELL]"),
    "history":      ("history.py",               "Trade history  [--limit N]"),
    "price":        ("price_history.py",         "Price history  --token-id ID  [--interval 1h]"),
    "stats":        ("market_stats.py",          "Deep market stats  --market-id ID"),

    # Research
    "research":     ("research_agent.py",        "LLM research + recommendation  --market-id ID"),

    # Trading
    "trade":        ("trade.py",                 "Place order  --token-id ID --side BUY|SELL --size N [--price P]"),
    "cancel":       ("cancel.py",                "Cancel orders  --order-id ID | --all | --market-id ID"),
    "redeem":       ("redeem.py",                "Redeem resolved winnings  [--market-id ID] [--dry-run]"),

    # Analysis
    "arb":          ("arbitrage.py",             "Find arbitrage gaps  [--min-gap 0.03] [--limit 50]"),
    "arb-exec":     ("arbitrage_execute.py",     "Execute best arbitrage  [--scan] [--budget 100]"),
    "corr-arb":     ("correlation_arbitrage.py", "Cross-market correlated-pair arb  [--scan] [--execute]"),
    "simulate":     ("execution_simulator.py",   "Slippage / fill simulator  --token-id ID --size N --edge E"),
    "exposure":     ("exposure.py",              "Portfolio risk / concentration  [--warn-threshold 0.30]"),

    # Monitoring
    "watch":        ("watchlist.py",             "Watchlist alerts  add|list|check|remove  [--above P] [--below P]"),
    "monitor":      ("auto_monitor.py",          "Market monitor  [--once] [--loop --interval 1h]"),

    # Automation
    "auto-arb":     ("auto_arbitrage.py",        "Auto arb bot  [--once] [--interval 15m] [--min-gap 0.005]"),
    "schedule":     ("scheduler.py",             "Job scheduler  add|start|list|status|stop|remove"),
    "news":         ("news_trader.py",            "News-driven trading  [--once] [--loop --interval 5] [--dry-run]"),
    "mm":           ("market_maker.py",          "Market making / spread capture  [--market-id ID] [--spread 0.02]"),
    "signals":      ("ai_automation.py",         "AI signal generation  [--once] [--execute]"),
    "omni":         ("omni_strategy.py",         "Run ALL strategies  --start --budget 1000 | --status | --stop"),

    # Evaluation & safety
    "backtest":     ("backtest.py",              "Replay strategies on price history  [--strategy momentum|mean-revert]"),
    "eval":         ("eval.py",                  "Score signals vs resolved outcomes  [--since 7d] [--report]"),
    "risk":         ("risk_guard.py",            "Daily loss limits + kill switch  status|kill|reset|set"),
}

# ── aliases ───────────────────────────────────────────────────────────────────
ALIASES = {
    "pos":          "portfolio",
    "bal":          "portfolio",
    "book":         "orderbook",
    "ob":           "orderbook",
    "orders":       "open-orders",
    "buy":          "trade",
    "sell":         "trade",
    "prices":       "price",
    "arb-find":     "arb",
    "exec-arb":     "arb-exec",
    "risk":         "exposure",
    "alert":        "watch",
    "alerts":       "watch",
    "autoarb":      "auto-arb",
    "cron":         "schedule",
    "sched":        "schedule",
    "make":         "mm",
    "ai":           "signals",
    "all":          "omni",
    "run-all":      "omni",
    "bt":           "backtest",
    "evaluate":     "eval",
    "guard":        "risk",
    "kill":         "risk",
    "safety":       "risk",
}


def _print_help():
    width = 72
    print("=" * width)
    print("  poly — Polymarket CLI (polymarket_trader skill)")
    print("=" * width)
    print()
    print("  Usage:  poly <command> [args...]")
    print()
    print("  In OpenClaw:  /polymarket_trader <command> [args...]")
    print("  Or type naturally — the agent maps requests to commands.")
    print()
    print("─" * width)
    print(f"  {'COMMAND':<16} DESCRIPTION")
    print("─" * width)

    sections = [
        ("Core", ["portfolio", "markets", "orderbook", "open-orders", "history", "price", "stats"]),
        ("Research & Analysis", ["research", "arb", "arb-exec", "corr-arb", "simulate", "exposure"]),
        ("Trading", ["trade", "cancel", "redeem"]),
        ("Monitoring", ["watch", "monitor"]),
        ("Automation", ["auto-arb", "schedule", "news", "mm", "signals", "omni"]),
        ("Evaluation & Safety", ["backtest", "eval", "risk"]),
    ]

    for section, cmds in sections:
        print()
        print(f"  ── {section}")
        for c in cmds:
            _, desc = COMMANDS[c]
            # Truncate description at first  [
            short = desc.split("  ")[0] if "  " in desc else desc
            print(f"  {c:<16} {short}")


    print()
    print("─" * width)
    print("  Run  poly <command> --help  to see all args for a command.")
    print("=" * width)


def main():
    args = sys.argv[1:]

    # ── no args / help ────────────────────────────────────────────────────────
    if not args or args[0] in ("help", "--help", "-h"):
        _print_help()
        sys.exit(0)

    raw_cmd = args[0]

    # ── resolve alias ─────────────────────────────────────────────────────────
    cmd = ALIASES.get(raw_cmd, raw_cmd)

    if cmd not in COMMANDS:
        # Unknown — print help and suggest closest
        print(f"poly: unknown command '{raw_cmd}'", file=sys.stderr)
        print(f"Run  poly help  to list available commands.", file=sys.stderr)
        sys.exit(1)

    script, _ = COMMANDS[cmd]
    script_path = os.path.join(SCRIPTS, script)

    if not os.path.exists(script_path):
        print(f"poly: script not found: {script_path}", file=sys.stderr)
        sys.exit(1)

    # ── exec forwarding (replace process so signals pass through cleanly) ─────
    py = sys.executable
    os.execv(py, [py, script_path] + args[1:])


if __name__ == "__main__":
    main()
