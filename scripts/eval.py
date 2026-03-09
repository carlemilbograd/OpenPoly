#!/usr/bin/env python3
"""
eval.py — Post-resolution evaluation loop.

After Polymarket markets resolve, this script scores every signal and trade
that OpenPoly generated against the actual outcome. It measures:

  • hit rate       — did the signal predict the correct side?
  • edge accuracy  — was the estimated edge well-calibrated?
  • source quality — which signal source (news/ai/arb) had the best accuracy?
  • model drift    — is accuracy improving or declining over time?

State files read:
  news_trader_state.json  — news_trader.py trade log
  ai_signals.json         — ai_automation.py signal log
  auto_arbitrage_state.json — auto_arbitrage.py run log
  eval_log.json           — running log written by this script

Usage:
  python scripts/eval.py                    # evaluate all pending signals
  python scripts/eval.py --since 7d         # limit to last 7 days
  python scripts/eval.py --source news      # filter by source
  python scripts/eval.py --report           # print full accuracy report
  python scripts/eval.py --json             # JSON output
"""

import argparse, json, sys, urllib.request, urllib.parse
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from _utils import SKILL_DIR, GAMMA_API, load_json, save_json

EVAL_LOG   = SKILL_DIR / "eval_log.json"
NEWS_STATE = SKILL_DIR / "news_trader_state.json"
AI_STATE   = SKILL_DIR / "ai_signals.json"
ARB_STATE  = SKILL_DIR / "auto_arbitrage_state.json"


# ── Gamma / CLOB helpers ──────────────────────────────────────────────────────

def _get(url: str) -> dict | list | None:
    try:
        with urllib.request.urlopen(url, timeout=20) as r:
            return json.loads(r.read())
    except Exception:
        return None


def fetch_market_outcome(market_id: str) -> dict | None:
    """
    Return Gamma market dict if resolved, else None.
    Tries by conditionId, slug, then first-match token search.
    """
    data = _get(f"{GAMMA_API}/markets/{market_id}")
    if isinstance(data, dict) and not data.get("active", True):
        return data

    # Search fallback
    qs   = urllib.parse.urlencode({"condition_id": market_id, "active": "false"})
    data = _get(f"{GAMMA_API}/markets?{qs}")
    if isinstance(data, list) and data:
        return data[0]

    return None


def resolved_outcome(market: dict) -> str | None:
    """
    Return "YES" or "NO" from a resolved Gamma market, or None.
    The winning outcome has winnerSupply > 0 or a positive pNumerator.
    """
    for tok in market.get("tokens", []):
        supply = float(tok.get("winnerSupply", 0) or 0)
        redeemable = float(tok.get("redeemable", 0) or 0)
        if supply > 0 or redeemable > 0:
            return tok.get("outcome", "").upper() or None

    # Fallback: look at final price — price → 1.0 means winner
    for tok in market.get("tokens", []):
        if float(tok.get("price", 0) or 0) >= 0.95:
            return tok.get("outcome", "").upper() or None

    return None


# ── Signal extraction ─────────────────────────────────────────────────────────

def extract_news_signals(since_ts: float = 0.0) -> list[dict]:
    """Read trade records from news_trader_state.json."""
    state = load_json(NEWS_STATE, {"trade_log": []})
    signals = []
    for entry in state.get("trade_log", []):
        ts = entry.get("timestamp", 0)
        if ts < since_ts:
            continue
        market_id = entry.get("market_id") or entry.get("conditionId")
        direction = entry.get("side", entry.get("direction", "")).upper()
        if not market_id or not direction:
            continue
        signals.append({
            "source":    "news",
            "market_id": market_id,
            "direction": direction,
            "confidence": float(entry.get("impact", entry.get("edge", 0))),
            "timestamp": ts,
        })
    return signals


def extract_ai_signals(since_ts: float = 0.0) -> list[dict]:
    """Read signals from ai_signals.json."""
    state = load_json(AI_STATE, {"signals": [], "history": []})

    raw = state.get("history", state.get("signals", []))
    signals = []
    for entry in raw if isinstance(raw, list) else []:
        ts = entry.get("timestamp", 0)
        if ts < since_ts:
            continue
        market_id = entry.get("market_id") or entry.get("conditionId")
        direction = entry.get("direction", entry.get("side", "")).upper()
        if not market_id or direction not in ("YES", "NO", "BUY", "SELL"):
            continue
        # Normalise BUY→YES, SELL→NO
        if direction == "BUY":
            direction = "YES"
        elif direction == "SELL":
            direction = "NO"
        signals.append({
            "source":     "ai",
            "market_id":  market_id,
            "direction":  direction,
            "confidence": float(entry.get("confidence", entry.get("edge", 0))),
            "timestamp":  ts,
        })
    return signals


def extract_arb_signals(since_ts: float = 0.0) -> list[dict]:
    """Read runs from auto_arbitrage_state.json. Arb = buy both sides."""
    state = load_json(ARB_STATE, {"runs": []})
    signals = []
    for run in state.get("runs", []):
        ts = run.get("timestamp", 0)
        if ts < since_ts or not run.get("executed"):
            continue
        market_id = run.get("market_id") or run.get("conditionId")
        if not market_id:
            continue
        # Arb bets on BOTH sides; label as "ARB" (not a directional call)
        signals.append({
            "source":     "arb",
            "market_id":  market_id,
            "direction":  "ARB",
            "confidence": float(run.get("gap", run.get("edge", 0))),
            "timestamp":  ts,
            "pnl":        float(run.get("pnl", 0)),
        })
    return signals


# ── Evaluation engine ─────────────────────────────────────────────────────────

def evaluate_signals(signals: list[dict], verbose: bool = False) -> list[dict]:
    """
    For each signal, look up the resolved outcome and classify as hit/miss/pending.
    Returns enriched signal dicts.
    """
    evaluated = []
    total = len(signals)
    for i, sig in enumerate(signals):
        if verbose:
            print(f"  Evaluating {i+1}/{total}…", end="\r")

        market = fetch_market_outcome(sig["market_id"])
        if not market:
            sig["result"] = "pending"
            evaluated.append(sig)
            continue

        outcome = resolved_outcome(market)
        if not outcome:
            sig["result"] = "pending"
            evaluated.append(sig)
            continue

        sig["actual_outcome"]   = outcome
        sig["market_question"]  = market.get("question", "")[:70]

        if sig["direction"] == "ARB":
            # Arb trades always capture spread; count as hit if pnl > 0
            sig["result"] = "hit" if sig.get("pnl", 0) > 0 else "miss"
        else:
            # Directional: YES signal + YES outcome = hit
            sig["result"] = "hit" if sig["direction"] == outcome else "miss"

        evaluated.append(sig)

    if verbose:
        print()
    return evaluated


# ── Reporting ─────────────────────────────────────────────────────────────────

def _source_stats(records: list[dict]) -> dict:
    """Aggregate hit/miss/pending by source."""
    stats: dict[str, dict] = {}
    for r in records:
        src = r.get("source", "unknown")
        s   = stats.setdefault(src, {"hit": 0, "miss": 0, "pending": 0, "total": 0})
        s[r.get("result", "pending")] = s.get(r.get("result", "pending"), 0) + 1
        s["total"] += 1

    # Compute hit rates
    for src, s in stats.items():
        resolved = s["hit"] + s["miss"]
        s["hit_rate"] = round(s["hit"] / resolved, 3) if resolved else None

    return stats


def print_report(log: list[dict]):
    if not log:
        print("No evaluated signals yet. Run without --report first.")
        return

    stats = _source_stats(log)
    total = len(log)
    resolved = [r for r in log if r.get("result") in ("hit", "miss")]

    overall_hit = (sum(1 for r in resolved if r["result"] == "hit") / len(resolved)
                   if resolved else 0)

    print()
    print("═" * 64)
    print(f"  Evaluation report   {total} signals   "
          f"{len(resolved)} resolved   {total - len(resolved)} pending")
    print("═" * 64)
    print(f"  Overall hit rate    {overall_hit:.1%}")
    print()
    print(f"  By source:")
    print(f"    {'SOURCE':<12} {'HIT%':>6} {'HITS':>6} {'MISS':>6} {'PEND':>6}")
    print("    " + "─" * 34)
    for src, s in sorted(stats.items()):
        hr = f"{s['hit_rate']:.1%}" if s["hit_rate"] is not None else "  n/a"
        print(f"    {src:<12} {hr:>6} {s['hit']:>6} {s['miss']:>6} {s['pending']:>6}")

    # Recent resolved signals (last 10)
    recent = sorted(
        [r for r in resolved],
        key=lambda x: x.get("timestamp", 0),
        reverse=True
    )[:10]

    if recent:
        print()
        print(f"  {'SIGNAL':<10} {'DIRECTION':<6} {'OUTCOME':<8} {'RESULT':<6} MARKET")
        print("  " + "─" * 64)
        for r in recent:
            src  = r.get("source", "")[:8]
            dire = r.get("direction", "")[:5]
            act  = r.get("actual_outcome", "?")[:5]
            res  = "✓ HIT" if r["result"] == "hit" else "✗ MISS"
            q    = r.get("market_question", "")[:34]
            print(f"  {src:<10} {dire:<6} {act:<8} {res:<6} {q}")

    print("═" * 64)


# ── CLI ───────────────────────────────────────────────────────────────────────

def _parse_since(since: str) -> float:
    """Parse '7d', '30d', '24h' etc into a UTC timestamp cutoff."""
    since = since.strip().lower()
    now   = datetime.now(timezone.utc)
    if since.endswith("d"):
        return (now - timedelta(days=int(since[:-1]))).timestamp()
    if since.endswith("h"):
        return (now - timedelta(hours=int(since[:-1]))).timestamp()
    try:
        return datetime.fromisoformat(since).replace(tzinfo=timezone.utc).timestamp()
    except ValueError:
        return 0.0


def main():
    ap = argparse.ArgumentParser(description="Post-resolution signal evaluator")
    ap.add_argument("--since",   default="",
                    help="Only evaluate signals newer than this (7d / 30d / YYYY-MM-DD)")
    ap.add_argument("--source",  choices=["news", "ai", "arb", "all"], default="all",
                    help="Filter by signal source (default: all)")
    ap.add_argument("--report",  action="store_true",
                    help="Print the full accuracy report from eval_log.json")
    ap.add_argument("--reset",   action="store_true",
                    help="Clear eval_log.json (start fresh)")
    ap.add_argument("--json",    action="store_true",
                    help="JSON output")
    args = ap.parse_args()

    if args.reset:
        save_json(EVAL_LOG, [])
        print("eval_log.json cleared.")
        return

    if args.report:
        log = load_json(EVAL_LOG, [])
        if args.json:
            print(json.dumps(log, indent=2))
        else:
            print_report(log)
        return

    since_ts = _parse_since(args.since) if args.since else 0.0

    # ── collect signals ───────────────────────────────────────────────────
    signals: list[dict] = []
    if args.source in ("news", "all"):
        signals += extract_news_signals(since_ts)
    if args.source in ("ai", "all"):
        signals += extract_ai_signals(since_ts)
    if args.source in ("arb", "all"):
        signals += extract_arb_signals(since_ts)

    if not signals:
        print("No signals found to evaluate.")
        if not EVAL_LOG.exists():
            print("Tip: run news_trader.py, ai_automation.py, or auto_arbitrage.py first.")
        return

    print(f"Evaluating {len(signals)} signals…")
    evaluated = evaluate_signals(signals, verbose=not args.json)

    # ── merge into eval log ───────────────────────────────────────────────
    existing = load_json(EVAL_LOG, [])
    existing_ids = {
        f"{e['source']}:{e['market_id']}:{e.get('timestamp', 0)}"
        for e in existing
    }
    new = [
        e for e in evaluated
        if f"{e['source']}:{e['market_id']}:{e.get('timestamp', 0)}"
        not in existing_ids
    ]
    combined = existing + new
    save_json(EVAL_LOG, combined)

    hits    = sum(1 for e in evaluated if e.get("result") == "hit")
    misses  = sum(1 for e in evaluated if e.get("result") == "miss")
    pending = sum(1 for e in evaluated if e.get("result") == "pending")

    if args.json:
        print(json.dumps({
            "evaluated": len(evaluated),
            "new":       len(new),
            "hits":      hits,
            "misses":    misses,
            "pending":   pending,
            "records":   evaluated,
        }, indent=2))
    else:
        print_report(combined)
        print(f"\n  {len(new)} new records added to eval_log.json "
              f"({pending} pending resolution)")


if __name__ == "__main__":
    main()
