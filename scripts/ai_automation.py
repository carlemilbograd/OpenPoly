#!/usr/bin/env python3
"""
ai_automation.py — AI-driven automated analysis and signal generation for Polymarket.

Runs systematic AI research across Polymarket's top markets using OpenClaw's
research capabilities. Produces structured buy/sell signals (ai_signals.json)
that other scripts consume to automate trading decisions.

Workflow:
  1. Fetch top markets by volume
  2. For each market, gather relevant context (current price, volume, news snippets)
  3. Produce a structured signal: { confidence, direction, edge_estimate, rationale }
  4. Save signals to ai_signals.json for consumption by auto_arbitrage, omni_strategy, etc.
  5. Optionally execute top signals immediately

Signal schema:
  {
    "market_id": "...",
    "question": "...",
    "yes_token": "...",
    "timestamp": "...",
    "direction": "YES" | "NO" | "PASS",
    "confidence": 0.0-1.0,
    "edge_estimate": 0.0-1.0,
    "current_price": 0.0-1.0,
    "implied_fair_value": 0.0-1.0,
    "rationale": "...",
    "execute": true | false
  }

Usage:
  python scripts/ai_automation.py --once                       # research + signals, single run
  python scripts/ai_automation.py --research-top 10            # research top 10 markets
  python scripts/ai_automation.py --signals                     # print saved signals
  python scripts/ai_automation.py --execute --min-confidence 0.7
  python scripts/ai_automation.py --loop --interval 30          # run every 30 min
"""
import sys, json, time, argparse, requests, textwrap
from pathlib import Path
from datetime import datetime, timezone

sys.path.insert(0, str(Path(__file__).parent))
from _client import GAMMA_API, get_client
from _utils import SKILL_DIR, LOG_DIR, FEE, load_json, save_json, get_mid, fetch_markets

SIGNALS_FILE = SKILL_DIR / "ai_signals.json"
LOG_FILE     = LOG_DIR / f"ai_automation_{datetime.now().strftime('%Y-%m-%d')}.log"

# ── Helpers ───────────────────────────────────────────────────────────────────
def log(msg: str):
    ts = datetime.now().strftime("%H:%M:%S")
    line = f"[{ts}] {msg}"
    print(f"  {line}")
    try:
        with LOG_FILE.open("a") as f:
            f.write(line + "\n")
    except Exception:
        pass


def load_signals() -> list:
    return load_json(SIGNALS_FILE, [])


def save_signals(signals: list):
    save_json(SIGNALS_FILE, signals)


def get_market_stats(market_id: str) -> dict:
    """Fetch enriched stats from Gamma API for a single market."""
    try:
        resp = requests.get(f"{GAMMA_API}/markets/{market_id}", timeout=10)
        if resp.ok:
            return resp.json()
    except Exception:
        pass
    return {}


def get_recent_trades(market_id: str) -> list:
    """Fetch recent trade history to gauge momentum."""
    try:
        resp = requests.get(
            f"{GAMMA_API}/trades",
            params={"market": market_id, "limit": 20},
            timeout=10,
        )
        if resp.ok:
            return resp.json() if isinstance(resp.json(), list) else []
    except Exception:
        pass
    return []


# ── AI Signal Generation ──────────────────────────────────────────────────────
# This section builds a structured prompt representing what an AI agent would
# see, then produces a signal by applying heuristic rules + simple momentum/
# mean-reversion analysis. In a live OpenClaw environment the {AI_PROMPT}
# block would be sent to the language model via the OpenClaw tool call pattern.

def build_context(market: dict, current_price: float | None, stats: dict,
                  trades: list) -> str:
    q        = market.get("question", "Unknown")
    vol_24h  = float(market.get("volume24hr") or 0)
    vol_all  = float(market.get("volume") or 0)
    end_date = market.get("endDate") or market.get("end_date") or "unknown"
    tags     = ", ".join(market.get("tags") or [])
    desc     = (market.get("description") or "")[:300]
    price_str = f"{current_price:.4f}" if current_price else "unavailable"

    # Compute recent price direction from trade history
    momentum = "unknown"
    if len(trades) >= 4:
        prices = []
        for t in trades[:10]:
            p = t.get("price") or t.get("outcome_price")
            if p:
                try:
                    prices.append(float(p))
                except Exception:
                    pass
        if len(prices) >= 4:
            recent   = sum(prices[:3]) / 3
            older    = sum(prices[-3:]) / 3
            momentum = "rising" if recent > older else "falling" if recent < older else "flat"

    return textwrap.dedent(f"""
        Market: {q}
        Current YES price: {price_str}  (implies P(YES)={price_str})
        24h Volume: ${vol_24h:,.0f}   Total Volume: ${vol_all:,.0f}
        Closes: {end_date}
        Tags: {tags}
        Recent momentum: {momentum}
        Description: {desc}
    """).strip()


def heuristic_signal(market: dict, current_price: float | None, stats: dict,
                     trades: list, min_edge: float) -> dict:
    """
    Apply logic-based heuristics to produce a signal.
    
    In production: replace this with a real LLM call via OpenClaw's AI pipeline.
    The structured output format is the same either way — the consumer doesn't care.
    
    Heuristics applied:
      1. Extreme pricing: prices < 5% or > 95% have high resolution risk → PASS
      2. Momentum continuation: strong recent trend → follow direction
      3. Mean reversion: near-50 with no trend → look for external catalyst indicators
      4. Volume surge: 24h vol >> typical suggests informed buying → follow
      5. Near-zero / near-one: likely close to resolving → small edge trades only
    """
    q         = market.get("question", "")
    vol_24h   = float(market.get("volume24hr") or 0)
    vol_total = float(market.get("volume") or 1)

    if current_price is None:
        return _build_signal(market, "PASS", 0.0, 0.0, current_price,
                              "No price data available.")

    # Rule 1: too extreme — too binary, skip
    if current_price < 0.04 or current_price > 0.96:
        return _build_signal(market, "PASS", 0.0, 0.0, current_price,
                              f"Price {current_price:.3f} is at an extreme — "
                              "resolution risk too high for automated trading.")

    # Compute momentum
    momentum_dir = 0  # -1 falling, +1 rising, 0 flat
    if len(trades) >= 6:
        prices = []
        for t in trades[:10]:
            p = t.get("price") or t.get("outcome_price")
            if p:
                try:
                    prices.append(float(p))
                except Exception:
                    pass
        if len(prices) >= 6:
            recent = sum(prices[:3]) / 3
            older  = sum(prices[-3:]) / 3
            diff   = recent - older
            if abs(diff) > 0.02:
                momentum_dir = 1 if diff > 0 else -1

    # Rule 2: Volume surge relative to typical
    vol_ratio = vol_24h / (vol_total / 30 + 1)  # rough daily avg over 30 days
    
    # Rule 3: distance from 50
    dist_50  = abs(current_price - 0.50)

    # Generate direction signal
    if momentum_dir == 1 and vol_ratio > 2.0:
        direction = "YES"
        confidence = min(0.75, 0.50 + dist_50)
        edge_est   = max(0.0, (1.0 - current_price) * 0.10)  # upside potential
        rationale  = (f"Strong upward momentum ({vol_ratio:.1f}x daily volume). "
                     f"Following trend toward resolution.")
    elif momentum_dir == -1 and vol_ratio > 2.0:
        direction = "NO"
        confidence = min(0.75, 0.50 + dist_50)
        edge_est   = max(0.0, current_price * 0.10)
        rationale  = (f"Strong downward momentum ({vol_ratio:.1f}x daily volume). "
                     f"Following trend toward NO.")
    elif 0.40 <= current_price <= 0.60 and dist_50 > 0.05:
        # Near-50 markets: mean-revert if no strong momentum
        direction  = "YES" if current_price < 0.50 else "NO"
        confidence = 0.45
        edge_est   = dist_50 * 0.15
        rationale  = (f"Near-50/50 market ({current_price:.3f}) with no strong momentum. "
                     f"{'Slight underpricing of YES' if direction == 'YES' else 'Slight overpricing of YES'}.")
    else:
        return _build_signal(market, "PASS", 0.0, 0.0, current_price,
                              "No strong signal detected — insufficient edge.")

    if edge_est < min_edge + FEE:
        return _build_signal(market, "PASS", confidence, edge_est, current_price,
                              f"{rationale}  Edge {edge_est:.1%} < threshold {min_edge:.1%}.")

    return _build_signal(market, direction, confidence, edge_est, current_price, rationale)


def _build_signal(market: dict, direction: str, confidence: float,
                  edge_est: float, current_price: float | None, rationale: str) -> dict:
    tokens    = market.get("tokens", [])
    yes_token = tokens[0].get("token_id", "") if tokens else ""
    no_token  = tokens[1].get("token_id", "") if len(tokens) > 1 else ""
    fair_val  = None
    if current_price is not None:
        if direction == "YES":
            fair_val = round(min(0.99, current_price + edge_est), 4)
        elif direction == "NO":
            fair_val = round(max(0.01, current_price - edge_est), 4)
        else:
            fair_val = round(current_price, 4)
    return {
        "market_id":          market.get("id", ""),
        "question":           market.get("question", ""),
        "yes_token":          yes_token,
        "no_token":           no_token,
        "timestamp":          datetime.now(timezone.utc).isoformat(),
        "direction":          direction,
        "confidence":         round(confidence, 4),
        "edge_estimate":      round(edge_est, 4),
        "current_price":      round(current_price, 4) if current_price else None,
        "implied_fair_value": fair_val,
        "rationale":          rationale,
        "execute":            (direction != "PASS" and confidence >= 0.60),
    }


# ── Execute signals ───────────────────────────────────────────────────────────
def execute_signal(signal: dict, budget: float, client, dry_run: bool):
    from py_clob_client.clob_types import OrderArgs, OrderType
    from py_clob_client.order_builder.constants import BUY

    direction = signal["direction"]
    token_id  = signal["yes_token"] if direction == "YES" else signal["no_token"]
    price     = signal["current_price"]
    if direction == "NO":
        price = 1.0 - price

    label = "YES" if direction == "YES" else "NO"
    log(f"{'[DRY-RUN] ' if dry_run else ''}Executing {label} signal: "
        f"{signal['question'][:50]}  @ {price:.4f}  conf {signal['confidence']:.0%}  "
        f"edge {signal['edge_estimate']:.1%}")

    if dry_run:
        return

    try:
        o_args = OrderArgs(token_id=token_id, price=round(price, 4),
                           size=round(budget, 2), side=BUY)
        signed = client.create_order(o_args)
        resp   = client.post_order(signed, OrderType.GTC)
        oid    = (resp or {}).get("orderID") or (resp or {}).get("id", "?")
        log(f"✅ Placed order {str(oid)[:20]}")
    except Exception as e:
        log(f"❌ Order failed: {e}")


# ── Main cycle ─────────────────────────────────────────────────────────────────
def run_cycle(args, client) -> list:
    n = args.research_top
    log(f"Fetching top {n} markets by volume...")
    markets = fetch_markets(n)
    if not markets:
        log("No markets returned.")
        return []

    signals  = []
    executed = 0

    for m in markets:
        tokens    = m.get("tokens", [])
        yes_token = tokens[0].get("token_id", "") if tokens else ""
        if not yes_token:
            continue

        current_price = get_mid(client, yes_token)
        stats         = {}  # get_market_stats(m.get("id",""))  # optional extra call
        trades        = get_recent_trades(m.get("id", ""))

        sig = heuristic_signal(m, current_price, stats, trades, args.min_edge)
        signals.append(sig)

        if sig["direction"] != "PASS":
            log(f"{sig['direction']:4} [{sig['confidence']:.0%}]  edge {sig['edge_estimate']:.1%}  "
                f"{sig['question'][:55]}")

        if args.execute and sig.get("execute") and sig["confidence"] >= args.min_confidence:
            execute_signal(sig, args.budget, client, args.dry_run)
            executed += 1

    log(f"Researched {len(markets)} markets — {sum(1 for s in signals if s['direction']!='PASS')} signals "
        f"({executed} executed)")

    save_signals(signals)
    return signals


# ── Main ───────────────────────────────────────────────────────────────────────
def main():
    parser = argparse.ArgumentParser(description="AI-driven Polymarket signal generator")
    parser.add_argument("--once",           action="store_true",  help="Single research + signal run")
    parser.add_argument("--loop",           action="store_true",  help="Run continuously")
    parser.add_argument("--interval",       type=float, default=30.0, help="Minutes between runs (default 30)")
    parser.add_argument("--research-top",   type=int,   default=20,   help="Number of top markets to research (default 20)")
    parser.add_argument("--min-edge",       type=float, default=0.03, help="Min edge to generate a signal (0.03=3%%)")
    parser.add_argument("--min-confidence", type=float, default=0.60, help="Min confidence to execute (0.60=60%%)")
    parser.add_argument("--execute",        action="store_true",  help="Execute signals meeting threshold")
    parser.add_argument("--dry-run",        action="store_true",  help="Simulate execution only")
    parser.add_argument("--budget",         type=float, default=20.0, help="USDC per signal (default 20)")
    parser.add_argument("--signals",        action="store_true",  help="Print currently saved signals")
    args = parser.parse_args()

    if args.signals:
        sigs = load_signals()
        if not sigs:
            print("  No signals saved yet. Run with --once to generate.\n")
            return
        actionable = [s for s in sigs if s["direction"] != "PASS"]
        print(f"\n  Saved signals — {len(sigs)} total, {len(actionable)} actionable:\n")
        print(f"  {'DIR':4} {'CONF':>6}  {'EDGE':>6}  {'PRICE':>7}  {'QUESTION'}")
        print(f"  {'─'*4} {'─'*6}  {'─'*6}  {'─'*7}  {'─'*55}")
        for s in sorted(actionable, key=lambda x: x["confidence"], reverse=True):
            print(f"  {s['direction']:<4} {s['confidence']:>5.0%}  "
                  f"{s['edge_estimate']:>5.1%}  "
                  f"{(s['current_price'] or 0):>7.4f}  {s['question'][:55]}")
        if not actionable:
            print("  (no actionable signals)")
        print()
        return

    authenticated = args.execute and not args.dry_run
    client = get_client(authenticated=authenticated)

    if args.once or args.loop:
        try:
            while True:
                run_cycle(args, client)
                if args.once:
                    break
                log(f"Sleeping {args.interval:.0f} min...")
                time.sleep(args.interval * 60)
        except KeyboardInterrupt:
            print("\n  Stopped.\n")
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
