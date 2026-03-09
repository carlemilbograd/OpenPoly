#!/usr/bin/env python3
"""
backtest.py — Replay trading signals against Polymarket price history.

Fetches OHLC price history for resolved (or active) markets and simulates
two simple strategies to measure expected performance before risking capital.

Strategies:
  momentum    — BUY when N-bar trend > threshold, SELL on reversal
  mean-revert — BUY when price falls > Z std below rolling mean, SELL on spike

Metrics reported: hit rate, total PnL, Sharpe ratio, max drawdown,
avg PnL/trade, and trades per market.

Usage:
  python scripts/backtest.py --strategy momentum --limit 25
  python scripts/backtest.py --strategy mean-revert --limit 25 --tag politics
  python scripts/backtest.py --token-id TOKEN_ID --strategy momentum
  python scripts/backtest.py --start 2024-06-01 --position-size 20
  python scripts/backtest.py --results          # show last saved run
  python scripts/backtest.py --results --json   # machine-readable
"""

import argparse, json, math, statistics, sys, urllib.request, urllib.parse
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from _utils import SKILL_DIR, GAMMA_API, load_json, save_json

CLOB_API     = "https://clob.polymarket.com"
RESULTS_FILE = SKILL_DIR / "backtest_results.json"


# ── Data fetching ─────────────────────────────────────────────────────────────

def _get(url: str, timeout: int = 20) -> dict | list | None:
    try:
        with urllib.request.urlopen(url, timeout=timeout) as r:
            return json.loads(r.read())
    except Exception:
        return None


def fetch_price_history(token_id: str, fidelity: int = 3600) -> list[dict]:
    """Fetch all available OHLC bars for a token (fidelity in seconds)."""
    url = f"{CLOB_API}/prices-history?market={token_id}&interval=max&fidelity={fidelity}"
    data = _get(url)
    return data.get("history", []) if isinstance(data, dict) else []


def fetch_resolved_markets(limit: int = 50, tag: str = "") -> list[dict]:
    """Fetch recently resolved Polymarket markets from Gamma API."""
    params: dict = {"active": "false", "closed": "true", "limit": str(limit),
                    "order": "volume", "ascending": "false"}
    if tag:
        params["tag"] = tag
    url = f"{GAMMA_API}/markets?" + urllib.parse.urlencode(params)
    result = _get(url)
    return result if isinstance(result, list) else []


def _yes_token(market: dict) -> str | None:
    for tok in market.get("tokens", []):
        if tok.get("outcome", "").upper() == "YES":
            return tok.get("token_id")
    return None


def _tokens_from_markets(markets: list[dict]) -> tuple[list[str], dict[str, str]]:
    token_ids, names = [], {}
    for m in markets:
        tid = _yes_token(m)
        if tid:
            token_ids.append(tid)
            names[tid] = m.get("question", tid)[:60]
    return token_ids, names


# ── Signal generators ─────────────────────────────────────────────────────────

def momentum_signals(prices: list[float], lookback: int = 6,
                     threshold: float = 0.04) -> list[int]:
    """
    +1 (BUY) when price has risen > threshold over lookback bars.
    -1 (SELL) when price has fallen > threshold.
    """
    sigs = [0] * len(prices)
    for i in range(lookback, len(prices)):
        delta = prices[i] - prices[i - lookback]
        if delta > threshold:
            sigs[i] = 1
        elif delta < -threshold:
            sigs[i] = -1
    return sigs


def mean_revert_signals(prices: list[float], window: int = 12,
                        z_thresh: float = 1.5) -> list[int]:
    """
    +1 (BUY) when price is z_thresh std below rolling mean (oversold).
    -1 (SELL) when z_thresh std above (overbought).
    """
    sigs = [0] * len(prices)
    for i in range(window, len(prices)):
        window_p = prices[i - window:i]
        if len(window_p) < 4:
            continue
        mean = statistics.mean(window_p)
        std  = statistics.stdev(window_p)
        if std < 1e-6:
            continue
        z = (prices[i] - mean) / std
        sigs[i] = 1 if z < -z_thresh else (-1 if z > z_thresh else 0)
    return sigs


# ── Simulation engine ─────────────────────────────────────────────────────────

def simulate(prices: list[float], signals: list[int],
             spread: float = 0.025, fee: float = 0.02,
             size_usd: float = 10.0) -> dict:
    """
    Walk through the price series applying signals.
    Opens on signal, closes on opposite signal or end of series.
    """
    position = 0    # +1 long YES, -1 long NO, 0 flat
    entry    = 0.0
    trades: list[dict] = []
    cash = 0.0

    for i, sig in enumerate(signals):
        p    = prices[i]
        buy  = min(p + spread / 2, 0.99)
        sell = max(p - spread / 2, 0.01)

        # Close on opposite signal or final bar
        if position != 0 and (sig == -position or i == len(signals) - 1):
            exit_p = sell if position > 0 else buy
            pnl    = (exit_p - entry - fee) * size_usd if position > 0 \
                     else (entry - exit_p - fee) * size_usd
            cash  += pnl
            trades.append({
                "side":  "BUY" if position > 0 else "SELL",
                "entry": round(entry, 4),
                "exit":  round(exit_p, 4),
                "pnl":   round(pnl, 4),
                "hit":   pnl > 0,
            })
            position = 0

        # Open new position
        if sig != 0 and position == 0:
            position = sig
            entry    = buy if sig > 0 else sell

    if not trades:
        return {"trades": 0, "pnl": 0.0, "hit_rate": 0.0,
                "sharpe": 0.0, "max_drawdown": 0.0, "avg_pnl": 0.0}

    pnls = [t["pnl"] for t in trades]
    wins = sum(1 for t in trades if t["hit"])

    # Sharpe — annualise assuming hourly bars (8760 h/yr)
    sharpe = 0.0
    if len(pnls) > 1:
        std = statistics.stdev(pnls)
        if std > 1e-9:
            sharpe = statistics.mean(pnls) / std * math.sqrt(8760)

    # Max drawdown on cumulative PnL curve
    running = max_dd = peak = 0.0
    for p in pnls:
        running += p
        peak     = max(peak, running)
        max_dd   = max(max_dd, peak - running)

    return {
        "trades":       len(trades),
        "pnl":          round(cash, 4),
        "hit_rate":     round(wins / len(trades), 3),
        "sharpe":       round(sharpe, 2),
        "max_drawdown": round(max_dd, 4),
        "avg_pnl":      round(statistics.mean(pnls), 4),
    }


# ── Backtest runner ───────────────────────────────────────────────────────────

def run_backtest(strategy: str, token_ids: list[str],
                 market_names: dict[str, str],
                 start_ts: float = 0.0, size_usd: float = 10.0,
                 fidelity: int = 3600) -> list[dict]:
    results = []
    for tid in token_ids:
        history = fetch_price_history(tid, fidelity)
        if start_ts:
            history = [h for h in history if float(h.get("t", 0)) >= start_ts]

        prices = [float(h["c"]) for h in history if "c" in h]
        if not prices:
            prices = [float(h["p"]) for h in history if "p" in h]
        prices = [p for p in prices if 0.005 < p < 0.995]

        if len(prices) < 24:   # need at least 24 bars
            continue

        sigs = momentum_signals(prices)    if strategy == "momentum" \
             else mean_revert_signals(prices)

        m = simulate(prices, sigs, size_usd=size_usd)
        if m["trades"] == 0:
            continue

        results.append({
            "token_id": tid,
            "market":   market_names.get(tid, tid[:20]),
            "bars":     len(prices),
            **m,
        })

    return results


# ── Formatting helpers ────────────────────────────────────────────────────────

def _print_summary(s: dict):
    sign = "▲" if s["total_pnl"] >= 0 else "▼"
    color_pnl = f"{sign} ${abs(s['total_pnl']):.2f}"
    print()
    print("═" * 64)
    print(f"  Backtest  {s['strategy']:>12}   "
          f"{s['markets_tested']} markets   {s['total_trades']} trades")
    print("═" * 64)
    print(f"  Total PnL           {color_pnl}")
    print(f"  Avg hit rate        {s['avg_hit_rate']:.1%}")
    print(f"  Avg Sharpe          {s['avg_sharpe']:.2f}")
    print(f"  Avg drawdown        ${s['avg_max_drawdown']:.2f}")
    print(f"  Simulated size      ${s['position_size_usd']:.0f} per trade")
    print("═" * 64)


def _print_table(rows: list[dict]):
    if not rows:
        return
    print(f"\n  {'MARKET':<38} {'TRADES':>6} {'PNL':>8} {'HIT%':>6} {'SHARPE':>7}")
    print("  " + "─" * 68)
    for r in sorted(rows, key=lambda x: x["pnl"], reverse=True)[:25]:
        name  = r["market"][:36]
        sign  = "+" if r["pnl"] >= 0 else ""
        print(f"  {name:<38} {r['trades']:>6} "
              f"{sign}{r['pnl']:>7.2f} {r['hit_rate']:>6.1%} {r['sharpe']:>7.2f}")
    if len(rows) > 25:
        print(f"\n  … {len(rows) - 25} more markets in backtest_results.json")


# ── CLI ───────────────────────────────────────────────────────────────────────

def main():
    ap = argparse.ArgumentParser(
        description="Backtest momentum / mean-reversion signals on Polymarket price history")
    ap.add_argument("--strategy",       choices=["momentum", "mean-revert"],
                    default="momentum", help="Signal strategy (default: momentum)")
    ap.add_argument("--token-id",       help="Single token to backtest")
    ap.add_argument("--limit",          type=int, default=25,
                    help="Number of resolved markets to test (default: 25)")
    ap.add_argument("--tag",            default="",
                    help="Filter markets by tag (politics, crypto, sports…)")
    ap.add_argument("--start",          default="",
                    help="Ignore price history before this date (YYYY-MM-DD)")
    ap.add_argument("--position-size",  type=float, default=10.0,
                    help="Simulated USD per trade (default: 10)")
    ap.add_argument("--fidelity",       type=int, default=3600,
                    help="Bar size in seconds (default: 3600 = 1 h)")
    ap.add_argument("--results",        action="store_true",
                    help="Print the last saved backtest results")
    ap.add_argument("--json",           action="store_true",
                    help="JSON output")
    args = ap.parse_args()

    # ── show saved results ──────────────────────────────────────────────────
    if args.results:
        if not RESULTS_FILE.exists():
            print("No saved results. Run a backtest first.")
            return
        data = load_json(RESULTS_FILE, {})
        if args.json:
            print(json.dumps(data, indent=2))
        else:
            _print_summary(data.get("summary", {}))
            _print_table(data.get("results", []))
        return

    # ── resolve token ids ───────────────────────────────────────────────────
    if args.token_id:
        token_ids = [args.token_id]
        names     = {args.token_id: args.token_id[:30]}
    else:
        print(f"Fetching {args.limit} recently resolved markets…")
        markets = fetch_resolved_markets(args.limit, args.tag)
        if not markets:
            print("No resolved markets found. "
                  "Try a different --tag or check network access.")
            sys.exit(1)
        token_ids, names = _tokens_from_markets(markets)
        if not token_ids:
            print("No YES tokens found in fetched markets.")
            sys.exit(1)

    # ── run ─────────────────────────────────────────────────────────────────
    start_ts = 0.0
    if args.start:
        try:
            start_ts = datetime.fromisoformat(args.start).replace(
                tzinfo=timezone.utc).timestamp()
        except ValueError:
            print(f"Invalid date: {args.start}. Use YYYY-MM-DD.", file=sys.stderr)
            sys.exit(1)

    print(f"Running {args.strategy} on {len(token_ids)} markets "
          f"(fidelity={args.fidelity}s, size=${args.position_size})…")

    results = run_backtest(
        args.strategy, token_ids, names,
        start_ts=start_ts, size_usd=args.position_size,
        fidelity=args.fidelity,
    )

    if not results:
        print("Not enough price history for the selected markets. "
              "Try --limit with a larger number or a different --tag.")
        sys.exit(1)

    # ── aggregate summary ───────────────────────────────────────────────────
    pnls    = [r["pnl"]          for r in results]
    sharpes = [r["sharpe"]       for r in results]
    hits    = [r["hit_rate"]     for r in results]
    dds     = [r["max_drawdown"] for r in results]

    summary = {
        "strategy":         args.strategy,
        "markets_tested":   len(results),
        "total_trades":     sum(r["trades"] for r in results),
        "total_pnl":        round(sum(pnls), 4),
        "avg_hit_rate":     round(statistics.mean(hits), 3),
        "avg_sharpe":       round(statistics.mean(sharpes), 2),
        "avg_max_drawdown": round(statistics.mean(dds), 4),
        "position_size_usd": args.position_size,
        "run_at":           datetime.now(timezone.utc).isoformat(),
    }

    output = {"summary": summary, "results": results}
    save_json(RESULTS_FILE, output)

    if args.json:
        print(json.dumps(output, indent=2))
    else:
        _print_summary(summary)
        _print_table(results)
        print(f"\n  Full results saved to backtest_results.json")


if __name__ == "__main__":
    main()
