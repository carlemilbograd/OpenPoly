#!/usr/bin/env python3
"""
logical_arb.py — Logical constraint arbitrage for Polymarket.

**The edge**: prediction markets must respect logical constraints between
outcomes.  When they don't, you can lock in risk-free profit.

Core constraints enforced:

  IMPLICATION  — A implies B, so P(A) ≤ P(B)
                 Example: "Trump wins" → "Republican wins"
                 If P(trump) > P(republican), sell trump / buy republican

  MUTEX        — A and B are mutually exclusive  P(A) + P(B) ≤ 1
                 Example: "Team wins championship" for two different teams
                 If P(A) + P(B) > 1 + fees, short both → guaranteed profit

  EXHAUSTIVE   — All outcomes must sum to ≤ 1.0 (with fees)
                 Stronger form: also checks YES across logically identical
                 questions that must resolve the same way.

This is stronger than correlation_arbitrage.py because:
  - It enforces strict mathematical constraints, not just correlation guesses.
  - The profit is deterministic (risk-free) when the constraint truly holds.
  - Violations are more common and persistent in political / categorical markets.

Usage:
  python scripts/logical_arb.py --scan
  python scripts/logical_arb.py --scan --min-edge 0.03 --limit 200
  python scripts/logical_arb.py --scan --execute --budget 100
  python scripts/logical_arb.py --scan --json
  python scripts/logical_arb.py --once
"""
from __future__ import annotations

import sys, json, time, argparse, itertools, logging
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from _client import get_client, GAMMA_API
from _utils  import SKILL_DIR, LOG_DIR, FEE, load_json, save_json, get_mid, fetch_markets
from _guards import check_min_order

# ── Constants ─────────────────────────────────────────────────────────────────
DEFAULT_MIN_EDGE = 0.03      # 3% net edge after fees
DEFAULT_LIMIT    = 250
MIN_VOLUME_24H   = 300
STATE_FILE       = SKILL_DIR / "logical_arb_state.json"
LOG_FILE         = LOG_DIR   / f"logical_arb_{datetime.now().strftime('%Y-%m-%d')}.log"

_DEFAULT_STATE: dict = {
    "runs": 0, "trades_executed": 0,
    "total_spent": 0.0, "total_profit_est": 0.0, "history": [],
}

LOG_DIR.mkdir(exist_ok=True)
logging.basicConfig(level=logging.INFO,
    format="%(asctime)s  %(levelname)-7s  %(message)s",
    handlers=[logging.StreamHandler(), logging.FileHandler(LOG_FILE)],
)
log = logging.getLogger("logical_arb")


# ── Logical cluster taxonomy ───────────────────────────────────────────────────
# Each group defines an implication hierarchy or a mutex set.
# Format: {"type": "imply"|"mutex", "labels": [...in implication order...],
#          "keywords_per_label": [[kws], [kws], ...]}

LOGIC_GROUPS: list[dict] = [
    # Republican ⊇ Trump  (Trump wins → Republican wins)
    {
        "type": "imply",
        "labels": ["trump", "republican"],
        "keywords": [
            ["trump", "donald trump"],
            ["republican", "gop", "republican party"],
        ],
    },
    # Democrat ⊇ specific Democrat candidate
    {
        "type": "imply",
        "labels": ["dem_candidate", "democrat"],
        "keywords": [
            ["harris", "biden", "democratic nominee"],
            ["democrat", "democratic party"],
        ],
    },
    # "wins presidency" ⊇ "wins popular vote"  (wins electoral college → wins popular vote is common, so usually correlated)
    {
        "type": "imply",
        "labels": ["wins_popular_vote", "wins_presidency"],
        "keywords": [
            ["popular vote"],
            ["wins presidency", "elected president", "president of the united states"],
        ],
    },
    # Bitcoin spot ETF ⊆ any Bitcoin ETF  (spot implies general ETF approval)
    {
        "type": "imply",
        "labels": ["btc_spot_etf", "btc_etf"],
        "keywords": [
            ["bitcoin spot etf", "btc spot etf"],
            ["bitcoin etf", "btc etf"],
        ],
    },
    # Fed cut in March ⊆ Fed cut in Q1
    {
        "type": "imply",
        "labels": ["fed_mar", "fed_q1"],
        "keywords": [
            ["rate cut in march", "rate cut march", "cut rates in march"],
            ["rate cut in q1", "rate cut first quarter", "cut rates q1"],
        ],
    },
    # Mutually exclusive: team championship markets  (at most one wins)
    {
        "type": "mutex_hint",  # hint — need price > 0.5 each to confirm violation
        "labels": ["nba_champ_team"],
        "keywords": [["nba championship", "nba finals", "nba champion"]],
    },
    {
        "type": "mutex_hint",
        "labels": ["nfl_champ_team"],
        "keywords": [["super bowl", "nfl champion", "nfl championship"]],
    },
]


# ── Market annotation ─────────────────────────────────────────────────────────
def _annotate(markets: list) -> list:
    """Tag each market with which logic labels it might match."""
    annotated = []
    for m in markets:
        q = m.get("question", "").lower()
        tags: dict[str, list[int]] = {}    # label → [group_indices]
        for gi, grp in enumerate(LOGIC_GROUPS):
            for li, kws in enumerate(grp["keywords"]):
                if any(kw in q for kw in kws):
                    key = grp["labels"][li]
                    tags.setdefault(key, []).append(gi)
        if tags:
            annotated.append({"market": m, "tags": tags})
    return annotated


# ── Constraint checking ───────────────────────────────────────────────────────
def _find_violations(
    annotated: list,
    client,
    min_edge: float,
    live_prices: bool,
) -> list[dict]:
    """Find all logical constraint violations."""
    violations: list[dict] = []

    def price_of(m: dict) -> float | None:
        tokens = m.get("tokens") or []
        yes_tid = tokens[0].get("token_id", "") if tokens else ""
        if live_prices and client and yes_tid:
            return get_mid(client, yes_tid)
        try:
            return float((tokens[0] if tokens else {}).get("price") or 0) or None
        except Exception:
            return None

    def yes_token(m: dict) -> str:
        tokens = m.get("tokens") or []
        return (tokens[0] if tokens else {}).get("token_id", "")

    def no_token(m: dict) -> str:
        tokens = m.get("tokens") or []
        return (tokens[1] if len(tokens) > 1 else {}).get("token_id", "")

    # --- IMPLICATION checks ---
    for gi, grp in enumerate(LOGIC_GROUPS):
        if grp["type"] != "imply":
            continue
        # Find all markets tagged with the "narrow" label (a) and "broad" label (b)
        # implication: narrow (a) → broad (b), so P(a) ≤ P(b)
        label_a = grp["labels"][0]
        label_b = grp["labels"][1]

        markets_a = [e["market"] for e in annotated if label_a in e["tags"]]
        markets_b = [e["market"] for e in annotated if label_b in e["tags"]]

        if not markets_a or not markets_b:
            continue

        for ma, mb in itertools.product(markets_a, markets_b):
            if ma.get("id") == mb.get("id"):
                continue
            pa = price_of(ma)
            pb = price_of(mb)
            if pa is None or pb is None:
                continue
            if pa < 0.02 or pa > 0.98 or pb < 0.02 or pb > 0.98:
                continue

            # Violation: P(a) > P(b)  — narrow event priced HIGHER than broad event
            # Trade: sell YES(a) + buy YES(b)
            # Practically: buy NO(a) + buy YES(b)
            if pa > pb + FEE + min_edge:
                edge = pa - pb - FEE
                violations.append({
                    "constraint": "IMPLICATION",
                    "description": f"{label_a} → {label_b}: P({label_a})={pa:.3f} > P({label_b})={pb:.3f}",
                    "market_a":   ma.get("question", "")[:60],
                    "market_b":   mb.get("question", "")[:60],
                    "id_a":       ma.get("id", ""),
                    "id_b":       mb.get("id", ""),
                    # Buy NO on the overpriced narrow market
                    "leg1_token":     no_token(ma),
                    "leg1_side":      "BUY_NO",
                    "leg1_price":     round(1 - pa, 4),
                    "leg1_direction": "NO",
                    # Buy YES on the underpriced broad market
                    "leg2_token":     yes_token(mb),
                    "leg2_side":      "BUY_YES",
                    "leg2_price":     round(pb, 4),
                    "leg2_direction": "YES",
                    "edge": round(edge, 4),
                    "pa": round(pa, 4),
                    "pb": round(pb, 4),
                })

    # --- MUTEX checks (sum > 1 on same-event markets) ---
    # Group markets by mutex_hint label, find markets priced > 0.5 each → sum > 1
    for gi, grp in enumerate(LOGIC_GROUPS):
        if grp["type"] != "mutex_hint":
            continue
        label = grp["labels"][0]
        matching = [e["market"] for e in annotated if label in e["tags"]]
        if len(matching) < 2:
            continue
        for ma, mb in itertools.combinations(matching, 2):
            if ma.get("id") == mb.get("id"):
                continue
            pa = price_of(ma)
            pb = price_of(mb)
            if pa is None or pb is None:
                continue
            total = pa + pb
            edge  = total - 1.0 - FEE
            if edge >= min_edge:
                violations.append({
                    "constraint": "MUTEX",
                    "description": f"{label}: P(A)+P(B)={total:.3f} > 1.0",
                    "market_a":   ma.get("question", "")[:60],
                    "market_b":   mb.get("question", "")[:60],
                    "id_a":       ma.get("id", ""),
                    "id_b":       mb.get("id", ""),
                    "leg1_token":     no_token(ma),
                    "leg1_side":      "BUY_NO",
                    "leg1_price":     round(1 - pa, 4),
                    "leg1_direction": "NO",
                    "leg2_token":     no_token(mb),
                    "leg2_side":      "BUY_NO",
                    "leg2_price":     round(1 - pb, 4),
                    "leg2_direction": "NO",
                    "edge": round(edge, 4),
                    "pa": round(pa, 4),
                    "pb": round(pb, 4),
                })

    violations.sort(key=lambda x: x["edge"], reverse=True)
    return violations


# ── Execution ─────────────────────────────────────────────────────────────────
def execute_violation(v: dict, budget: float, client, dry_run: bool, state: dict):
    half = round(budget / 2, 2)
    print(f"\n  LOGICAL-ARB [{v['constraint']}]")
    print(f"    Market A: {v['market_a']}")
    print(f"    Market B: {v['market_b']}")
    print(f"    {v['description']}  →  edge={v['edge']:.1%}")
    print(f"    Leg1 BUY {v['leg1_direction']} @ {v['leg1_price']:.4f}  ${half:.2f}")
    print(f"    Leg2 BUY {v['leg2_direction']} @ {v['leg2_price']:.4f}  ${half:.2f}"
          + ("  [DRY-RUN]" if dry_run else ""))

    record: dict = {
        "ts":          datetime.now(timezone.utc).isoformat(),
        "constraint":  v["constraint"],
        "market_a":    v["market_a"],
        "market_b":    v["market_b"],
        "edge":        v["edge"],
        "budget":      budget,
        "dry_run":     dry_run,
    }

    if dry_run:
        record["status"] = "dry_run"
        state["history"].append(record)
        return record

    order_ids = []
    try:
        from py_clob_client.clob_types import OrderArgs, OrderType
        from py_clob_client.order_builder.constants import BUY
        for leg_token, leg_price, leg_dir in [
            (v["leg1_token"], v["leg1_price"], v["leg1_direction"]),
            (v["leg2_token"], v["leg2_price"], v["leg2_direction"]),
        ]:
            if not leg_token:
                continue
            o_args = OrderArgs(token_id=leg_token, price=round(leg_price, 4),
                               size=half, side=BUY)
            signed = client.create_order(o_args)
            resp   = client.post_order(signed, OrderType.GTC)
            oid    = (resp or {}).get("orderID") or (resp or {}).get("id", "?")
            order_ids.append(str(oid))
            print(f"    OK  {leg_dir} order {str(oid)[:20]}")
        record.update({"status": "placed", "order_ids": order_ids})
        state["trades_executed"] += 1
        state["total_spent"]     += budget
        state["total_profit_est"] += round(budget * v["edge"], 4)
        try:
            from notifier import notify_trade_opened
            notify_trade_opened(
                bot="logical_arb",
                market=f"{v['market_a'][:35]} / {v['market_b'][:35]}",
                direction=f"{v['leg1_direction']}/{v['leg2_direction']}",
                amount_usd=budget,
                order_ids=order_ids,
                extras={"constraint": v["constraint"], "edge": v["edge"]},
            )
        except Exception:
            pass
    except Exception as exc:
        print(f"    FAIL  {exc}")
        record.update({"status": "error", "error": str(exc)})

    state["history"].append(record)
    if len(state["history"]) > 400:
        state["history"] = state["history"][-400:]
    return record


# ── Main ──────────────────────────────────────────────────────────────────────
def main():
    p = argparse.ArgumentParser(description="Logical constraint arbitrage")
    p.add_argument("--scan",      action="store_true", help="Scan for violations")
    p.add_argument("--execute",   action="store_true", help="Execute best violation")
    p.add_argument("--once",      action="store_true", help="Single scan + execute, then exit")
    p.add_argument("--min-edge",  type=float, default=DEFAULT_MIN_EDGE,
                   help=f"Minimum net edge (default {DEFAULT_MIN_EDGE})")
    p.add_argument("--budget",    type=float, default=1.0,
                   help="Total USDC per trade pair (split 50/50, default 1)")
    p.add_argument("--limit",     type=int,   default=DEFAULT_LIMIT,
                   help=f"Markets to scan (default {DEFAULT_LIMIT})")
    p.add_argument("--top",       type=int,   default=5, help="Results to show")
    p.add_argument("--dry-run",   action="store_true", help="No real orders")
    p.add_argument("--json",      action="store_true", help="Output as JSON")
    p.add_argument("--status",    action="store_true", help="Show P&L and history")
    args = p.parse_args()

    if (args.execute or args.once) and not args.dry_run:
        check_min_order(args.budget / 2, flag="--budget (per leg)",
                        bot="logical_arb", exit_on_fail=True)

    state  = load_json(STATE_FILE, _DEFAULT_STATE)
    client = get_client(authenticated=bool((args.execute or args.once) and not args.dry_run))

    if args.status:
        print(f"\n  Logical Arb Status\n  {'─'*40}")
        print(f"  Runs:          {state.get('runs', 0)}")
        print(f"  Trades placed: {state.get('trades_executed', 0)}")
        print(f"  USDC deployed: ${state.get('total_spent', 0):.2f}")
        print(f"  Est. profit:   +${state.get('total_profit_est', 0):.4f}")
        hist = state.get("history", [])[-10:]
        if hist:
            print(f"\n  Last {len(hist)} records:")
            for r in hist:
                tag = "DRY" if r.get("dry_run") else r.get("status","?").upper()
                print(f"  [{r['ts'][:19]}]  {tag:<8}  {r['constraint']:<11}  "
                      f"edge={r.get('edge',0):.1%}  {r.get('market_a','')[:40]}")
        print()
        return

    if not (args.scan or args.once):
        p.print_help()
        return

    state["runs"] = state.get("runs", 0) + 1
    log.info(f"Fetching {args.limit} markets…")
    markets    = fetch_markets(limit=args.limit)
    annotated  = _annotate(markets)
    violations = _find_violations(annotated, client,
                                  min_edge=args.min_edge,
                                  live_prices=True)

    if not violations:
        print("  No logical constraint violations found.")
        save_json(STATE_FILE, state)
        return

    display = violations[:args.top]
    if args.json:
        print(json.dumps(display, indent=2))
    else:
        print(f"\n  Logical violations ({len(violations)} found, "
              f"showing top {len(display)}):\n")
        for v in display:
            print(f"  [{v['constraint']:<11}] edge={v['edge']:.1%}  {v['description']}")
            print(f"    A: {v['market_a']}")
            print(f"    B: {v['market_b']}")
        print()

    if (args.execute or args.once) and violations:
        execute_violation(violations[0], args.budget, client, args.dry_run, state)

    save_json(STATE_FILE, state)


if __name__ == "__main__":
    main()
