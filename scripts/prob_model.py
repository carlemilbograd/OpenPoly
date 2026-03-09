#!/usr/bin/env python3
"""
prob_model.py — Calibrated probability estimation for Polymarket markets.

Converts available signals into a fair probability estimate using:

  1. Market price prior  — current consensus embedded in the orderbook
  2. Bayesian updates    — each signal shifts the prior up or down
  3. Source calibration  — sources with better historical accuracy get more weight
  4. Time decay          — old signals lose influence; recent ones count more
  5. Shrinkage           — with few signals, estimate stays close to market price

Output:
  {
    "fair_prob":      0.61,    # calibrated P(YES)
    "market_price":   0.52,    # raw market mid-price
    "edge":           0.09,    # fair_prob − market_price
    "direction":      "YES",   # BUY YES if positive edge
    "kelly_full":     0.18,    # Kelly fraction (uncapped)
    "kelly_quarter":  0.045,   # quarter-Kelly (recommended)
    "suggested_size": 11.25,   # USDC (quarter-Kelly × balance × cap)
    "confidence":     0.73,    # 0–1 confidence in estimate
    "n_signals":      3,       # number of signals used
    "factors":        {...},   # per-factor breakdown
  }

Usage:
  python scripts/prob_model.py --market-id MARKET_ID
  python scripts/prob_model.py --market-id MARKET_ID --balance 500
  python scripts/prob_model.py --market-id MARKET_ID --show-signals  # also list contributing signals
  python scripts/prob_model.py --market-id MARKET_ID --json

Importable API:
  from prob_model import estimate
  result = estimate(market_id="0xabc...", market_price=0.52, balance=500)
"""

import argparse, json, math, sys, time, urllib.request
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from _utils import GAMMA_API, SKILL_DIR, get_mid
try:
    from db import DB, DB_PATH
    _DB_AVAILABLE = DB_PATH.exists()
except ImportError:
    _DB_AVAILABLE = False

CLOB_API = "https://clob.polymarket.com"

# ── Calibration defaults ──────────────────────────────────────────────────────
# Hit rates when no historical data in DB yet.
# Derived from general literature on prediction market signal quality.
_DEFAULT_HIT_RATES = {
    "news": 0.54,   # slightly above coin flip — most news is already priced
    "ai":   0.56,   # momentum/mean-revert heuristics have modest edge
    "arb":  0.72,   # structural arb is more reliable (spread capture)
    "manual": 0.60,
}

# Maximum position as fraction of balance (quarter-Kelly default)
_MAX_POSITION_FRACTION = 0.25

# How strongly to shrink toward market price when signal evidence is thin
_SHRINKAGE_N = 4   # equivalent to having N virtual "neutral" observations


# ── Data helpers ──────────────────────────────────────────────────────────────

def _get(url: str) -> dict | list | None:
    try:
        with urllib.request.urlopen(url, timeout=15) as r:
            return json.loads(r.read())
    except Exception:
        return None


def _market_mid(market_id: str) -> tuple[float, str, str]:
    """
    Return (mid_price, yes_token_id, question) for a market.
    Tries Gamma API first, then CLOB midpoint endpoint.
    """
    # Try Gamma
    data = _get(f"{GAMMA_API}/markets/{market_id}")
    if not data:
        import urllib.parse
        qs   = urllib.parse.urlencode({"condition_id": market_id})
        data = _get(f"{GAMMA_API}/markets?{qs}")
        if isinstance(data, list) and data:
            data = data[0]

    if isinstance(data, dict):
        for tok in data.get("tokens", []):
            if tok.get("outcome", "").upper() == "YES":
                tid   = tok.get("token_id", "")
                price = float(tok.get("price", 0) or 0)
                q     = data.get("question", "")
                if price > 0:
                    return price, tid, q
                # fallback to CLOB
                mid = _clob_mid(tid)
                return mid, tid, q

    return 0.5, "", ""   # no data → use flat prior


def _clob_mid(token_id: str) -> float:
    data = _get(f"{CLOB_API}/midpoint?token_id={token_id}")
    if isinstance(data, dict):
        v = data.get("mid")
        if v is not None:
            return float(v)
    return 0.5


def _load_signals(market_id: str, max_age_hours: float = 48.0
                  ) -> list[dict]:
    """
    Load recent signals for a market from the DB (preferred) or JSON fallbacks.
    Each signal dict has: source, direction, confidence, edge_estimate, created_at
    """
    cutoff = time.time() - max_age_hours * 3600
    signals = []

    if _DB_AVAILABLE:
        try:
            with DB() as db:
                rows = db.recent_signals(limit=50, market_id=market_id)
                for r in rows:
                    if r["created_at"] >= cutoff:
                        signals.append(dict(r))
        except Exception:
            pass

    # JSON fallback: news_trader_state + ai_signals
    if not signals:
        signals += _json_signals_news(market_id, cutoff)
        signals += _json_signals_ai(market_id, cutoff)

    return signals


def _json_signals_news(market_id: str, cutoff: float) -> list[dict]:
    p = SKILL_DIR / "news_trader_state.json"
    if not p.exists():
        return []
    try:
        state = json.loads(p.read_text())
        result = []
        for entry in state.get("trade_log", []):
            if entry.get("market_id", "") != market_id:
                continue
            ts = entry.get("timestamp", 0)
            if ts < cutoff:
                continue
            d = (entry.get("side", entry.get("direction", "")) or "").upper()
            result.append({
                "source":        "news",
                "direction":     d,
                "confidence":    float(entry.get("impact", entry.get("edge", 0))),
                "edge_estimate": float(entry.get("edge", 0)),
                "created_at":    ts,
            })
        return result
    except Exception:
        return []


def _json_signals_ai(market_id: str, cutoff: float) -> list[dict]:
    p = SKILL_DIR / "ai_signals.json"
    if not p.exists():
        return []
    try:
        state = json.loads(p.read_text())
        raw   = state.get("history", state.get("signals", []))
        result = []
        for entry in (raw if isinstance(raw, list) else []):
            if entry.get("market_id", "") != market_id:
                continue
            ts = entry.get("timestamp", 0)
            if ts < cutoff:
                continue
            d = (entry.get("direction", entry.get("side", "")) or "").upper()
            if d == "BUY":   d = "YES"
            elif d == "SELL": d = "NO"
            result.append({
                "source":        "ai",
                "direction":     d,
                "confidence":    float(entry.get("confidence", entry.get("edge", 0))),
                "edge_estimate": float(entry.get("edge", 0)),
                "created_at":    ts,
            })
        return result
    except Exception:
        return []


def _calibration_weights() -> dict[str, float]:
    """
    Get per-source accuracy weights from DB, falling back to defaults.
    Converts hit_rate → weight using: w = hit_rate / (1 - hit_rate)
    (log-odds scaling — a 0.60 source gets 1.5× weight of a 50/50 source)
    """
    weights = {}
    if _DB_AVAILABLE:
        try:
            with DB() as db:
                stats = db.accuracy_by_source()
            for src, d in stats.items():
                hr = d.get("hit_rate")
                total = d.get("hit", 0) + d.get("miss", 0)
                if hr is not None and total >= 10:  # need 10+ scored signals
                    hr = max(0.40, min(0.80, hr))   # clip to sensible range
                    weights[src] = hr / (1 - hr)
        except Exception:
            pass

    # Fill in defaults for any missing source
    for src, hr in _DEFAULT_HIT_RATES.items():
        if src not in weights:
            weights[src] = hr / (1 - hr)

    return weights


# ── Core probability engine ───────────────────────────────────────────────────

def _bayesian_update(prior: float, signal_prob: float, weight: float) -> float:
    """
    Bayesian update with fractional weight.
    weight=1 → full update; weight=0.5 → half-strength.
    """
    # Interpolate signal_prob toward 0.5 by (1-weight) to modulate its strength
    effective = 0.5 + (signal_prob - 0.5) * weight
    effective = max(0.01, min(0.99, effective))

    # Bayes: P' = P(E|H) * P(H) / P(E)
    p_h  = prior
    p_nh = 1 - prior
    p_e_h  = effective
    p_e_nh = 1 - effective
    p_e    = p_e_h * p_h + p_e_nh * p_nh

    if p_e < 1e-9:
        return prior
    return (p_e_h * p_h) / p_e


def _time_weight(created_at: float, now: float, half_life_hours: float = 24.0) -> float:
    """Exponential decay: signal loses half its weight every half_life hours."""
    age_hours = max(0, (now - created_at) / 3600)
    return math.exp(-age_hours * math.log(2) / half_life_hours)


def estimate(
    market_id: str,
    market_price: float = 0.0,
    balance: float = 0.0,
    max_age_hours: float = 48.0,
    extra_signals: list[dict] | None = None,
) -> dict:
    """
    Produce a calibrated probability estimate for a market.

    Args:
        market_id       — Polymarket condition ID or slug
        market_price    — current YES mid-price (fetched automatically if 0)
        balance         — portfolio balance for Kelly sizing (0 = skip sizing)
        max_age_hours   — ignore signals older than this
        extra_signals   — additional signals to include (e.g. from news pipeline)

    Returns a dict with fair_prob, edge, direction, kelly fractions, factors.
    """
    now = time.time()

    # ── 1. Resolve market price ───────────────────────────────────────────────
    yes_token_id = ""
    question     = ""
    if market_price <= 0 or market_price >= 1:
        market_price, yes_token_id, question = _market_mid(market_id)

    prior = max(0.02, min(0.98, market_price))

    # ── 2. Load signals ───────────────────────────────────────────────────────
    signals = _load_signals(market_id, max_age_hours)
    if extra_signals:
        signals = signals + extra_signals

    # ── 3. Calibration weights ────────────────────────────────────────────────
    cal_weights = _calibration_weights()

    # ── 4. Apply Bayesian updates ─────────────────────────────────────────────
    updated    = prior
    n_applied  = 0
    factor_log = []

    for sig in signals:
        src       = sig.get("source", "unknown")
        direction = (sig.get("direction") or "").upper()
        conf      = float(sig.get("confidence", 0))
        created   = float(sig.get("created_at", now))

        if direction not in ("YES", "NO"):
            continue

        # Signal's implied probability (direction + confidence)
        # conf=0.0 → no information; conf=1.0 → certainty
        if direction == "YES":
            sig_prob = 0.5 + conf * 0.45   # max out at 0.95
        else:
            sig_prob = 0.5 - conf * 0.45   # min at 0.05

        # Effective weight = calibration_weight × time_decay
        cal_w  = cal_weights.get(src, 0.5)
        t_w    = _time_weight(created, now)
        weight = cal_w * t_w

        pre     = updated
        updated = _bayesian_update(updated, sig_prob, weight)
        n_applied += 1

        factor_log.append({
            "source":     src,
            "direction":  direction,
            "conf":       round(conf, 3),
            "sig_prob":   round(sig_prob, 3),
            "cal_weight": round(cal_w, 3),
            "time_weight": round(t_w, 3),
            "prior":      round(pre, 4),
            "posterior":  round(updated, 4),
        })

    # ── 5. Shrinkage toward market price ──────────────────────────────────────
    # With few signals, we don't want to stray far from the market consensus.
    # Equivalent to adding _SHRINKAGE_N neutral observations at prior.
    if n_applied > 0:
        shrink_w = _SHRINKAGE_N / (n_applied + _SHRINKAGE_N)
        fair_prob = prior * shrink_w + updated * (1 - shrink_w)
    else:
        fair_prob = prior   # no signals → return market price as fair estimate

    fair_prob = round(max(0.02, min(0.98, fair_prob)), 4)
    edge      = round(fair_prob - market_price, 4)

    # ── 6. Kelly sizing ───────────────────────────────────────────────────────
    # BUY YES: b = (1 - price) / price  (payout per $ risked)
    # f* = (p×b - q) / b  where p = fair_prob, q = 1-p
    kelly_full   = 0.0
    kelly_quarter = 0.0
    suggested_size = 0.0
    direction    = "YES" if edge >= 0 else "NO"

    if abs(edge) > 0.01:   # only size if edge is meaningful
        if direction == "YES":
            buy_price = market_price
        else:
            buy_price = 1 - market_price   # buying NO at complement price

        if 0.01 < buy_price < 0.99:
            b  = (1 - buy_price) / buy_price   # net payout per $ risked
            p  = fair_prob if direction == "YES" else (1 - fair_prob)
            q  = 1 - p
            kelly_full    = max(0.0, (p * b - q) / b)
            kelly_quarter = kelly_full * 0.25   # standard fractional Kelly

            if balance > 0:
                suggested_size = round(
                    min(kelly_quarter, _MAX_POSITION_FRACTION) * balance, 2
                )

    # ── 7. Confidence estimate ────────────────────────────────────────────────
    # How much should we trust this estimate?
    # More signals + high-weight sources → higher confidence (capped at 0.95).
    if n_applied == 0:
        confidence = 0.30   # just the market price
    else:
        avg_cal = sum(f["cal_weight"] for f in factor_log) / len(factor_log)
        confidence = 1 - math.exp(-n_applied * avg_cal / 3)
        confidence = round(min(0.95, confidence), 3)

    return {
        "fair_prob":      fair_prob,
        "market_price":   round(market_price, 4),
        "edge":           edge,
        "direction":      direction,
        "kelly_full":     round(kelly_full, 4),
        "kelly_quarter":  round(kelly_quarter, 4),
        "suggested_size": suggested_size,
        "confidence":     confidence,
        "n_signals":      n_applied,
        "yes_token_id":   yes_token_id,
        "question":       question,
        "factors":        factor_log,
    }


# ── CLI ───────────────────────────────────────────────────────────────────────

def _print_result(r: dict, show_signals: bool = False):
    edge_sign = "▲" if r["edge"] >= 0 else "▼"
    edge_abs  = abs(r["edge"])
    dir_arrow  = "↑ BUY YES" if r["direction"] == "YES" else "↓ BUY NO"

    print()
    print("═" * 60)
    if r.get("question"):
        print(f"  {r['question'][:56]}")
        print("─" * 60)
    print(f"  Market price        {r['market_price']:.3f}")
    print(f"  Fair probability    {r['fair_prob']:.3f}   ({confidence_bar(r['confidence'])})")
    print(f"  Edge                {edge_sign} {edge_abs:.3f}   {dir_arrow}")
    print()
    print(f"  Kelly (full)        {r['kelly_full']:.1%}")
    print(f"  Kelly (¼, recommended) {r['kelly_quarter']:.1%}")
    if r["suggested_size"]:
        print(f"  Suggested size      ${r['suggested_size']:.2f}")
    print(f"  Confidence          {r['confidence']:.0%}   ({r['n_signals']} signals)")

    if show_signals and r["factors"]:
        print()
        print("  Signals used:")
        print(f"    {'SRC':<8} {'DIR':<4} {'CONF':>5} → {'PRIOR':>6} {'POST':>6}")
        print("    " + "─" * 42)
        for f in r["factors"]:
            print(f"    {f['source']:<8} {f['direction']:<4} {f['conf']:>5.2f} → "
                  f"{f['prior']:>6.4f} {f['posterior']:>6.4f}")

    print("═" * 60)


def confidence_bar(c: float, width: int = 10) -> str:
    filled = round(c * width)
    return "█" * filled + "░" * (width - filled) + f" {c:.0%}"


def main():
    ap = argparse.ArgumentParser(
        description="Calibrated probability estimator for Polymarket markets")
    ap.add_argument("--market-id",     required=True,
                    help="Polymarket condition ID, slug, or Gamma market ID")
    ap.add_argument("--market-price",  type=float, default=0.0,
                    help="Override the live market mid-price")
    ap.add_argument("--balance",       type=float, default=0.0,
                    help="Portfolio balance (USDC) for Kelly sizing")
    ap.add_argument("--max-age",       type=float, default=48.0,
                    help="Max signal age in hours (default: 48)")
    ap.add_argument("--show-signals",  action="store_true",
                    help="Print per-signal factor breakdown")
    ap.add_argument("--json",          action="store_true",
                    help="Machine-readable JSON output")
    ap.add_argument("--save",          action="store_true",
                    help="Save the estimate to the DB signals table")
    args = ap.parse_args()

    result = estimate(
        market_id=args.market_id,
        market_price=args.market_price,
        balance=args.balance,
        max_age_hours=args.max_age,
    )

    if args.save and abs(result["edge"]) > 0.005:
        if _DB_AVAILABLE:
            with DB() as db:
                db.insert_signal(
                    source="prob_model",
                    market_id=args.market_id,
                    direction=result["direction"],
                    confidence=result["confidence"],
                    edge_estimate=result["edge"],
                    fair_prob=result["fair_prob"],
                    model_version="1",
                )
            print(f"  Signal saved to DB (edge {result['edge']:+.3f})")
        else:
            print("  DB not found — run  poly db migrate  first.")

    if args.json:
        print(json.dumps(result, indent=2))
    else:
        _print_result(result, show_signals=args.show_signals)


if __name__ == "__main__":
    main()
